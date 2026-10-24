"""Tests for api/state.py and POST /api/demo/reset (Req 21.1)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import ALLOWED_ORIGINS, create_app
from api.state import CheckInState, CheckInStore

EMPTY = {"runs": {}, "run_ids": {}, "escalations": {}, "counters": {"run": 0, "escalation": 0},
         "pending": {}}


def _dirty(store: CheckInStore) -> None:
    """Put something in every part of the store, as a check-in run would."""
    with store.lock:
        store.runs["run-1"] = {"id": "run-1", "synthetic": True}
        store.run_ids[("25001014800", "2026-02-24T09:00")] = "run-1"
        store.escalations["esc-1"] = {"id": "esc-1", "synthetic": True}
        store.counters["run"] = 1
        store.counters["escalation"] = 1


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def test_new_store_is_empty_and_uses_injected_clock():
    store = CheckInStore(clock=lambda: 42.0)
    assert store.snapshot() == EMPTY
    assert store.now() == 42.0


def test_reset_swaps_in_fresh_empty_store_with_same_clock():
    state = CheckInState(clock=lambda: 7.5)
    old = state.store
    _dirty(old)
    assert old.snapshot() != EMPTY

    fresh = state.reset()
    assert fresh is state.store and fresh is not old
    assert fresh.snapshot() == EMPTY
    assert fresh.now() == 7.5
    assert state.reset().snapshot() == fresh.snapshot()   # resetting twice equals resetting once


def test_startup_puts_empty_checkins_on_app_state(client):
    assert isinstance(client.app.state.checkins, CheckInState)


def test_reset_endpoint_returns_ok_and_clears_state(client):
    checkins: CheckInState = client.app.state.checkins
    _dirty(checkins.store)
    before = checkins.store

    r = client.post("/api/demo/reset")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert checkins.store is not before
    assert checkins.store.snapshot() == EMPTY
    assert client.app.state.store is not None    # read-only processed data is untouched


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_reset_cors_preflight_from_vite_origin(client, origin):
    pre = client.options("/api/demo/reset", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                                     "Access-Control-Request-Headers": "Content-Type"})
    assert pre.status_code == 200
    assert pre.headers.get("access-control-allow-origin") == origin
    assert "POST" in pre.headers.get("access-control-allow-methods", "")
    r = client.post("/api/demo/reset", headers={"Origin": origin})
    assert r.headers.get("access-control-allow-origin") == origin


def test_reset_cors_rejects_other_origin(client):
    pre = client.options("/api/demo/reset", headers={"Origin": "http://evil.example",
                                                     "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in pre.headers


# ---------------------------------------------------------------- check-in state machine (task 13.2)

from api.data import NotFound, load_store  # noqa: E402
from api.reach import town_responders  # noqa: E402
from api.sms import SimulatorSender  # noqa: E402
from api.state import Rejected, effective_delays, seeded_schedule  # noqa: E402

HOUR = "2026-02-24T09:00"
SMS_TRACT = "25001015300"        # Barnstable, sms at HOUR
DOOR_TRACT = "25001014800"       # Falmouth, door_knock at HOUR
TIMEOUT = 30.0


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture(scope="module")
def data():
    return load_store()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sender():
    return SimulatorSender()


@pytest.fixture
def checkins(clock, sender):
    return CheckInStore(clock, sender=sender, timeout_s=TIMEOUT, phones=())


def _operator_id(run) -> str:
    return next(h["id"] for h in run["households"].values() if h["is_operator"])


def _kinds(hh, direction="out"):
    return [m["kind"] for m in hh["messages"] if m["direction"] == direction]


def _assert_synthetic(store: CheckInStore, run) -> None:
    assert run["synthetic"] is True
    for hh in run["households"].values():
        assert hh["synthetic"] is True
        assert all(m["synthetic"] is True for m in hh["messages"])
    assert all(e["synthetic"] is True for e in store.escalations.values())


def test_send_creates_run_in_each_household_language(data, checkins, sender):
    run, created = checkins.send(data, SMS_TRACT, HOUR)
    assert created is True
    households = data.households_for(SMS_TRACT)
    assert len(run["households"]) == len(households) == 8
    assert run["telecom"] == 0 and run["town"] == "Barnstable"
    for hh in households:
        rec = run["households"][hh.id]
        assert rec["lang"] == hh.lang and rec["status"] == "sent" and rec["phone"] is None
        (msg,) = rec["messages"]
        assert msg["kind"] == "checkin" and msg["text"] == data.content.sms["Barnstable"][hh.lang]["checkin"].text
    assert run["households"][f"{SMS_TRACT}-1"]["lang"] == "pt"       # operator household
    assert run["counters"] == {"sent": 8, "ok": 0, "need_help": 0, "silent": 0}
    assert len(sender.sent) == 8 and all(m.phone is None for m in sender.sent)
    _assert_synthetic(checkins, run)


def test_repeated_send_returns_same_run(data, checkins, sender):
    run, _ = checkins.send(data, SMS_TRACT, HOUR)
    again, created = checkins.send(data, SMS_TRACT, HOUR)
    assert created is False and again["id"] == run["id"]
    assert len(sender.sent) == 8 and len(checkins.runs) == 1


def test_door_knock_send_is_rejected_without_messages(data, checkins, sender):
    with pytest.raises(Rejected) as e:
        checkins.send(data, DOOR_TRACT, HOUR)
    assert e.value.code == "phones_degraded"
    assert checkins.runs == {} and sender.sent == ()


def test_send_without_households_or_unknown_ids(data, checkins):
    with_hh = {h.geoid for h in data.households.households}
    geoid, hour = next((g, data.hours[i]) for g in data.geoids if g not in with_hh
                       for i, ch in enumerate(data.timeline.tracts[g].channel) if ch == "sms")
    with pytest.raises(Rejected) as e:
        checkins.send(data, geoid, hour)
    assert e.value.code == "no_households"
    with pytest.raises(NotFound):
        checkins.send(data, "25999999999", HOUR)
    with pytest.raises(NotFound):
        checkins.get_run("run-404")


def test_generated_replies_are_simulated_and_skip_operator(data, checkins, clock):
    run, _ = checkins.send(data, SMS_TRACT, HOUR)
    clock.t += TIMEOUT - 1           # every generated reply (delays 3..20 s) is due, timeout not yet
    run = checkins.get_run(run["id"])
    op = _operator_id(run)
    assert _kinds(run["households"][op], "in") == []
    replies = [m for h in run["households"].values() for m in h["messages"] if m["direction"] == "in"]
    assert replies and all(m["simulated"] and m["generated"] and m["label"] == "Simulated" for m in replies)
    assert all(0 < m["at"] < TIMEOUT for m in replies)
    assert run["households"][op]["status"] == "sent"
    # Deterministic: a fresh store with the same seed replays the same replies.
    other = CheckInStore(FakeClock(5.0), timeout_s=TIMEOUT, phones=())
    run2, _ = other.send(data, SMS_TRACT, HOUR)
    other.clock.t += TIMEOUT - 1
    run2 = other.get_run(run2["id"])
    assert {k: h["status"] for k, h in run2["households"].items()} == \
           {k: h["status"] for k, h in run["households"].items()}


def test_help_creates_one_escalation_and_confirmation(data, checkins):
    run, _ = checkins.send(data, SMS_TRACT, HOUR)
    op = _operator_id(run)
    run = checkins.process_reply(data, run["id"], op, " Ajuda ")
    hh = run["households"][op]
    assert hh["status"] == "escalated" and run["counters"]["need_help"] >= 1
    escs = [e for e in checkins.escalations.values() if e["household_id"] == op]
    assert len(escs) == 1
    esc = escs[0]
    assert esc["responder_label"] in [r.label for r in town_responders(data, "Barnstable")]
    assert esc["lang"] == "pt" and esc["status"] == "assigned" and esc["household_label"] == hh["label"]
    confirm = [m for m in hh["messages"] if m["kind"] == "confirm"]
    assert len(confirm) == 1 and "911" in confirm[0]["text"]
    run = checkins.process_reply(data, run["id"], op, "2")         # second help: no new escalation
    assert len([e for e in checkins.escalations.values() if e["household_id"] == op]) == 1
    assert _kinds(run["households"][op]).count("confirm") == 1


def test_escalations_round_robin_over_town_responders(data, checkins):
    run, _ = checkins.send(data, SMS_TRACT, HOUR)
    for hid in run["households"]:
        checkins.process_reply(data, run["id"], hid, "2")
    labels = [r.label for r in town_responders(data, "Barnstable")]
    got = [e["responder_label"] for e in checkins.escalations.values()]
    assert got == [labels[i % len(labels)] for i in range(len(got))]


def test_unclear_reply_gets_exactly_one_reprompt(data, checkins):
    run, _ = checkins.send(data, SMS_TRACT, HOUR)
    op = _operator_id(run)
    checkins.process_reply(data, run["id"], op, "oi?")
    run = checkins.process_reply(data, run["id"], op, "12")
    hh = run["households"][op]
    assert _kinds(hh).count("reprompt") == 1 and _kinds(hh, "in") == ["reply", "reply"]
    assert hh["status"] == "sent" and hh["unrecognized"] == 2
    assert not [e for e in checkins.escalations.values() if e["household_id"] == op]


def test_operator_household_silent_after_timeout_then_late_ok(data, checkins, clock):
    run, _ = checkins.send(data, SMS_TRACT, HOUR)
    op = _operator_id(run)
    clock.t += TIMEOUT
    run = checkins.get_run(run["id"])
    assert run["households"][op]["status"] == "silent"
    assert run["households"][op]["silent_reason"] == "no_reply"
    assert run["complete"] is True and run["status"] == "complete"
    silent_before = run["counters"]["silent"]
    run = checkins.process_reply(data, run["id"], op, "1")
    assert run["households"][op]["status"] == "ok" and run["households"][op]["silent_reason"] is None
    assert run["counters"]["silent"] == silent_before - 1
    assert sum(run["counters"].values()) == 8
    _assert_synthetic(checkins, run)


def test_ok_then_help_escalates_and_escalated_stays(data, checkins):
    run, _ = checkins.send(data, SMS_TRACT, HOUR)
    op = _operator_id(run)
    assert checkins.process_reply(data, run["id"], op, "sim")["households"][op]["status"] == "ok"
    assert checkins.process_reply(data, run["id"], op, "HELP")["households"][op]["status"] == "escalated"
    assert checkins.process_reply(data, run["id"], op, "1")["households"][op]["status"] == "escalated"


def test_counters_sum_and_complete_status(data, checkins, clock):
    run, _ = checkins.send(data, SMS_TRACT, HOUR)
    for dt in (0, 5, 15, TIMEOUT - 1, TIMEOUT, TIMEOUT + 10):
        clock.t = run["created_at"] + dt
        run = checkins.get_run(run["id"])
        c = run["counters"]
        assert sum(c.values()) == 8
        statuses = [h["status"] for h in run["households"].values()]
        assert c == {"sent": statuses.count("sent"), "ok": statuses.count("ok"),
                     "need_help": statuses.count("escalated"), "silent": statuses.count("silent")}
        assert run["complete"] == (c["sent"] == 0)
    assert run["complete"] is True
    assert c["need_help"] == len(checkins.escalations)


def test_reset_clears_runs(data, clock):
    state = CheckInState(clock=clock, sender_factory=SimulatorSender, timeout_s=TIMEOUT, phones=())
    run, _ = state.store.send(data, SMS_TRACT, HOUR)
    state.store.process_reply(data, run["id"], _operator_id(run), "2")
    assert state.store.snapshot() != EMPTY
    fresh = state.reset()
    assert fresh.snapshot() == EMPTY and fresh.run_for(SMS_TRACT, HOUR) is None
    rerun, created = fresh.send(data, SMS_TRACT, HOUR)
    assert created is True and rerun["id"] == "run-1"


def test_phones_are_masked_and_only_used_with_twilio_sender(data, clock):
    class TwilioLike(SimulatorSender):
        channel = "twilio"

    tw = TwilioLike()
    store = CheckInStore(clock, sender=tw, timeout_s=TIMEOUT, phones=("+1 617 555 0101",))
    run, _ = store.send(data, SMS_TRACT, HOUR)
    first = run["households"][f"{SMS_TRACT}-1"]
    assert first["phone"] == "+1 *** *** 0101"
    assert all(h["phone"] is None for k, h in run["households"].items() if k != f"{SMS_TRACT}-1")
    assert "555 0101" not in repr(store.snapshot())
    assert [m.phone for m in tw.sent if m.household_id == f"{SMS_TRACT}-1"] == ["+1 617 555 0101"]


def test_effective_delays_clamps_below_timeout():
    assert effective_delays([3, 20], 30) == (3.0, 20.0, False)
    lo, hi, clamped = effective_delays([3, 40], 30)
    assert clamped and hi < 30 and lo == 3.0
    lo, hi, clamped = effective_delays([25, 40], 10)
    assert clamped and lo <= hi < 10


def test_seeded_schedule_skips_operator_and_unclear_bodies_do_not_classify(data):
    demo = data.scoring["demo"]
    kw = data.languages["reply_keywords"]
    hhs = data.households_for(SMS_TRACT)
    sched = seeded_schedule(demo["seed"], SMS_TRACT, HOUR, hhs, {"unclear": 1.0}, (3, 20), kw,
                            demo["operator_household"])
    assert [s.household_id for s in sched] == [h.id for h in hhs if not h.is_operator]
    from api.sms import classify
    assert all(s.kind == "unclear" and classify(s.body, kw) is None for s in sched)
    assert sched == seeded_schedule(demo["seed"], SMS_TRACT, HOUR, hhs, {"unclear": 1.0}, (3, 20), kw,
                                    demo["operator_household"])
