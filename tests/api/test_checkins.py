"""Tests for the check-in endpoints in api/main.py (task 13.3).

Req 15.6, 18.1, 18.5, 18.9, 19.8, 20.3, 21.1, 26.4. A fake clock is injected through `create_app`'s
`checkins_factory`, so the reply timeout is driven without sleeping.
"""
from __future__ import annotations

import logging
import re

import pytest
from fastapi.testclient import TestClient

from api.data import load_store
from api.main import create_app
from api.sms import SendResult, SimulatorSender
from api.state import CheckInState
from pipeline.privacy_guard import PHONE

HOUR = "2026-02-24T09:00"
SMS_TRACT = "25001015300"        # Barnstable, sms at HOUR, 8 households, #1 is the pt operator household
DOOR_TRACT = "25001014800"       # Falmouth, door_knock at HOUR
EMPTY_TRACT = "25001011002"      # sms at HOUR, no synthetic households
TIMEOUT = 30.0
TEST_NUMBERS = ("+1 617 555 0101", "+1 617 555 0102")   # reserved fictional numbers (Req 26.6)


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture(scope="module")
def data():
    return load_store()


@pytest.fixture(scope="module")
def clock():
    return FakeClock()


@pytest.fixture(scope="module")
def client(data, clock):
    app = create_app(lambda: data, lambda: CheckInState(clock=clock, sender_factory=SimulatorSender,
                                                        timeout_s=TIMEOUT, phones=()))
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client, clock):
    clock.t = 1000.0
    assert client.post("/api/demo/reset").status_code == 200
    yield


def _send(client, geoid=SMS_TRACT, hour=HOUR):
    return client.post("/api/checkins/send", json={"geoid": geoid, "hour": hour})


def _operator(run) -> dict:
    return next(h for h in run["households"] if h["is_operator"])


def _reply(client, run_id, household_id, body):
    return client.post("/api/simulator/reply", json={"run_id": run_id, "household_id": household_id,
                                                     "body": body})


# ---------------------------------------------------------------- send


def test_send_creates_then_returns_existing_run(client, data):
    r = _send(client)
    assert r.status_code == 201
    run = r.json()
    assert run["geoid"] == SMS_TRACT and run["hour"] == HOUR and run["telecom"] == 0
    assert run["synthetic"] is True and run["status"] == "active" and run["escalations"] == []
    hhs = data.households_for(SMS_TRACT)
    assert [h["id"] for h in run["households"]] == [h.id for h in sorted(hhs, key=lambda h: h.number)]
    assert all(h["status"] == "sent" and h["messages"][0]["kind"] == "checkin" for h in run["households"])
    assert run["counters"] == {"sent": 8, "ok": 0, "need_help": 0, "silent": 0}

    again = _send(client)
    assert again.status_code == 200 and again.json()["id"] == run["id"]
    assert len(client.app.state.checkins.store.runs) == 1


def test_door_knock_send_is_rejected_with_no_run(client):
    r = _send(client, DOOR_TRACT)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "phones_degraded" and r.json()["detail"]["message"]
    store = client.app.state.checkins.store
    assert store.runs == {} and store.sender.sent == ()


def test_send_without_households_is_409(client):
    r = _send(client, EMPTY_TRACT)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_households"


def test_send_unknown_tract_or_hour_is_404_and_bad_body_is_422(client):
    assert _send(client, "25001999999").status_code == 404
    assert _send(client, SMS_TRACT, "2026-03-01T00:00").status_code == 404
    assert client.post("/api/checkins/send", json={"geoid": SMS_TRACT}).status_code == 422


# ---------------------------------------------------------------- replies


def test_operator_help_reply_escalates_with_confirmation(client, data):
    run = _send(client).json()
    op = _operator(run)
    assert op["lang"] == "pt"
    r = _reply(client, run["id"], op["id"], "Ajuda")
    assert r.status_code == 200
    out = r.json()
    hh = _operator(out)
    assert hh["status"] == "escalated"
    (esc,) = [e for e in out["escalations"] if e["household_id"] == op["id"]]
    assert esc["id"] == hh["escalation_id"] and esc["synthetic"] is True
    assert esc["household_label"].startswith("Simulated household #") and esc["lang"] == "pt"
    assert "(Simulated)" in esc["responder_label"]
    confirm = [m for m in hh["messages"] if m["kind"] == "confirm"]
    assert len(confirm) == 1 and "911" in confirm[0]["text"]
    assert confirm[0]["text"] == data.content.sms["Barnstable"]["pt"]["confirm"].text
    assert out["counters"]["need_help"] >= 1


def test_reply_validation_and_unknown_ids(client):
    run = _send(client).json()
    op = _operator(run)["id"]
    assert _reply(client, run["id"], op, "").status_code == 422
    assert _reply(client, run["id"], op, "x" * 161).status_code == 422
    assert client.post("/api/simulator/reply", json={"run_id": run["id"], "household_id": op}).status_code == 422
    assert _reply(client, "run-999", op, "1").status_code == 404
    assert _reply(client, run["id"], "nope", "1").status_code == 404


def test_reply_logs_class_not_body(client, caplog):
    run = _send(client).json()
    with caplog.at_level(logging.INFO, logger="lifeline.api"):
        _reply(client, run["id"], _operator(run)["id"], "Ajuda")
    assert "class=help" in caplog.text and "Ajuda" not in caplog.text


# ---------------------------------------------------------------- advance, timeout, detail


def test_get_advances_to_silent_after_timeout(client, clock):
    run = _send(client).json()
    op = _operator(run)["id"]
    assert client.get(f"/api/checkins/{run['id']}").json()["counters"]["sent"] == 8
    clock.t += TIMEOUT + 1
    r = client.get(f"/api/checkins/{run['id']}")
    assert r.status_code == 200
    out = r.json()
    hh = next(h for h in out["households"] if h["id"] == op)
    assert hh["status"] == "silent" and hh["silent_reason"] == "no_reply"
    assert out["status"] == "complete" and out["counters"]["sent"] == 0
    assert sum(out["counters"].values()) == 8
    # Generated replies arrived and are labeled Simulated; the operator household got none
    gen = [m for h in out["households"] for m in h["messages"] if m["direction"] == "in"]
    assert gen and all(m["generated"] and m["label"] == "Simulated" for m in gen)
    assert not [m for m in hh["messages"] if m["direction"] == "in"]


def test_get_unknown_run_is_404(client):
    assert client.get("/api/checkins/run-999").status_code == 404


def test_tract_detail_includes_run_and_statuses(client, clock):
    d = client.get(f"/api/tracts/{SMS_TRACT}", params={"hour": HOUR}).json()
    assert d["run"] is None and d["escalations"] == []
    assert {h["status"] for h in d["households"]} == {"not_contacted"}

    run = _send(client).json()
    _reply(client, run["id"], _operator(run)["id"], "2")
    clock.t += TIMEOUT + 1
    d = client.get(f"/api/tracts/{SMS_TRACT}", params={"hour": HOUR}).json()
    assert d["run"]["id"] == run["id"] and d["run"]["status"] == "complete"
    by_id = {h["id"]: h["status"] for h in d["run"]["households"]}
    assert {h["id"]: h["status"] for h in d["households"]} == by_id
    assert by_id[_operator(run)["id"]] == "escalated"
    assert set(by_id.values()) <= {"ok", "escalated", "silent"}
    assert d["escalations"] == d["run"]["escalations"] and d["escalations"]

    # A door_knock tract-hour never has a run and stays awaiting door knock (Req 20.2)
    d = client.get(f"/api/tracts/{DOOR_TRACT}", params={"hour": HOUR}).json()
    assert d["run"] is None and {h["status"] for h in d["households"]} == {"awaiting_door_knock"}


def test_reset_clears_runs(client):
    run = _send(client).json()
    assert client.post("/api/demo/reset").json() == {"ok": True}
    assert client.get(f"/api/checkins/{run['id']}").status_code == 404
    assert client.get(f"/api/tracts/{SMS_TRACT}", params={"hour": HOUR}).json()["run"] is None
    again = _send(client)
    assert again.status_code == 201 and again.json()["id"] == "run-1"


# ---------------------------------------------------------------- startup and privacy


def test_startup_warns_when_reply_delay_reaches_timeout(data, caplog):
    app = create_app(lambda: data, lambda: CheckInState(clock=FakeClock(), sender_factory=SimulatorSender,
                                                        timeout_s=5, phones=()))
    with caplog.at_level(logging.WARNING, logger="lifeline.api"):
        with TestClient(app):
            pass
    (rec,) = [r for r in caplog.records if "reply_delay_s" in r.getMessage()]
    assert rec.levelno == logging.WARNING and "[3, 20]" in rec.getMessage() and "4.5" in rec.getMessage()


def test_startup_does_not_warn_below_timeout(client, data, caplog):
    app = create_app(lambda: data, lambda: CheckInState(clock=FakeClock(), sender_factory=SimulatorSender,
                                                        timeout_s=TIMEOUT, phones=()))
    with caplog.at_level(logging.WARNING, logger="lifeline.api"):
        with TestClient(app):
            pass
    assert not [r for r in caplog.records if "reply_delay_s" in r.getMessage()]


class _TwilioLikeSender(SimulatorSender):
    """A Sender that reports channel "twilio", so the store maps households to demo numbers."""

    channel = "twilio"

    def send(self, to):
        super().send(to)
        return SendResult(channel="twilio", ok=True)


def test_no_raw_phone_number_in_any_response_or_log(data, caplog):
    clock = FakeClock()
    app = create_app(lambda: data, lambda: CheckInState(clock=clock, sender_factory=_TwilioLikeSender,
                                                        timeout_s=TIMEOUT, phones=TEST_NUMBERS))
    texts: list[str] = []
    with caplog.at_level(logging.INFO), TestClient(app) as c:
        r = c.post("/api/checkins/send", json={"geoid": SMS_TRACT, "hour": HOUR})
        run = r.json()
        texts.append(r.text)
        assert run["households"][0]["phone"] == "+1 *** *** 0101"
        texts.append(_reply(c, run["id"], run["households"][0]["id"], "SIM").text)
        clock.t += TIMEOUT + 1
        texts.append(c.get(f"/api/checkins/{run['id']}").text)
        texts.append(c.get(f"/api/tracts/{SMS_TRACT}", params={"hour": HOUR}).text)
        # The raw number reached only the Sender
        assert c.app.state.checkins.store.sender.sent[0].phone == TEST_NUMBERS[0]
    texts.append(caplog.text)
    for text in texts:
        assert not re.search(PHONE, text)
        assert "555 0101" not in text and "5550101" not in text
