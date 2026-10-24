"""Tests for api/main.py read and content endpoints over the real data/processed/ files.

Req 8.2, 8.4, 9.1, 9.2, 10.1 to 10.5, 11.10, 12.4, 12.7, 15.1, 20.2, 24.1, 28.1, 28.2.
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from api.data import NO_TOWN_REPORTS_LABEL, StoreError
from api.main import ALLOWED_ORIGINS, create_app
from pipeline.privacy_guard import ADDRESS, PHONE

HOUR = "2026-02-24T09:00"
DK_TRACT = "25001014800"     # Falmouth, rank 1, door_knock (modeled)
SMS_TRACT = "25001015300"    # Barnstable, sms
CHATHAM_TRACT = "25001010600"
MODELED = "Modeled: assumes tower backup lasts about 8 hours"


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="module")
def store(client):
    return client.app.state.store


# ---------------------------------------------------------------- startup, health, CORS


def test_store_error_stops_startup():
    def broken():
        raise StoreError("Missing required file(s); run python -m pipeline.run")

    with pytest.raises(StoreError, match="run python -m pipeline.run"):
        with TestClient(create_app(broken)):
            pass


@pytest.mark.parametrize("env,expected", [(None, "simulator"), ("twilio", "twilio"),
                                          ("Twilio", "simulator"), ("simulator", "simulator")])
def test_health(client, monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("SMS_MODE", raising=False)
    else:
        monkeypatch.setenv("SMS_MODE", env)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret-token-value")
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "boston_voice": client.app.state.store.boston_voice is not None,
                    "sms_mode": expected}
    assert "secret-token-value" not in r.text


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_cors_allows_local_vite_origin(client, origin):
    r = client.get("/api/health", headers={"Origin": origin})
    assert r.headers.get("access-control-allow-origin") == origin
    pre = client.options("/api/queue", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    assert pre.status_code == 200 and pre.headers.get("access-control-allow-origin") == origin


def test_cors_rejects_other_origin(client):
    r = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    pre = client.options("/api/queue", headers={"Origin": "http://localhost:3000",
                                                "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in pre.headers


# ---------------------------------------------------------------- static endpoints


def test_hours(client, store):
    body = client.get("/api/hours").json()
    assert body["tz"] == "America/New_York"
    assert len(body["hours"]) == 119
    assert body["hours"][0] == "2026-02-23T01:00" and body["hours"][-1] == "2026-02-27T23:00"
    assert body["key_demo_hours"] == store.timeline.key_demo_hours


@pytest.mark.parametrize("path,name,media", [
    ("/api/towns", "cape_towns.geojson", "application/geo+json"),
    ("/api/tracts", "cape_tracts.geojson", "application/geo+json"),
    ("/api/timeline", "cape_timeline.json", "application/json"),
    ("/api/telecom-events", "telecom_events.json", "application/json"),
    ("/api/sources", "sources.json", "application/json"),
    ("/api/scale-catalog", "scale_catalog.json", "application/json"),
])
def test_pass_through_endpoints(client, store, path, name, media):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(media)
    assert r.content == store.raw[name]
    json.loads(r.content)


def test_scale_catalog_has_six_static_entries(client):
    assert len(client.get("/api/scale-catalog").json()["entries"]) >= 6


# ---------------------------------------------------------------- queue


def test_queue(client, store):
    rows = client.get("/api/queue", params={"hour": HOUR}).json()
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0]["geoid"] == DK_TRACT and rows[0]["channel"] == "door_knock"
    assert all(len(r["why_chips"]) == 2 for r in rows)
    assert rows == [r.model_dump(mode="json") for r in store.queue(HOUR)]


def test_queue_unknown_and_missing_hour(client):
    assert client.get("/api/queue", params={"hour": "2026-03-01T00:00"}).status_code == 404
    assert client.get("/api/queue").status_code == 422


# ---------------------------------------------------------------- tract detail


def test_detail_door_knock_tract(client, store):
    r = client.get(f"/api/tracts/{DK_TRACT}", params={"hour": HOUR})
    assert r.status_code == 200
    d = r.json()
    assert (d["geoid"], d["town"], d["hour"], d["rank"], d["channel"]) == (DK_TRACT, "Falmouth", HOUR, 1,
                                                                             "door_knock")
    assert d["telecom_rule"] == "modeled" and d["telecom_label"] == MODELED
    assert d["components"]["telecom"] == 1
    # Door-knock list: one Simulated entry per synthetic household (Req 15.1)
    n = len(store.households_for(DK_TRACT))
    assert n > 0 and len(d["door_knock"]) == n
    assert all(e["synthetic"] is True and e["household_label"].startswith("Simulated household #")
               for e in d["door_knock"])
    # Households are awaiting a door knock, never silent (Req 20.2)
    assert len(d["households"]) == n
    assert {h["status"] for h in d["households"]} == {"awaiting_door_knock"}
    assert all(h["synthetic"] is True for h in d["households"])
    assert d["why_chips"] == store.queue(HOUR)[0].model_dump(mode="json")["why_chips"]
    assert d["run"] is None


def test_detail_sms_tract(client):
    d = client.get(f"/api/tracts/{SMS_TRACT}", params={"hour": HOUR}).json()
    assert d["channel"] == "sms" and d["door_knock"] is None
    assert d["telecom_rule"] == "none" and d["telecom_label"] is None
    assert d["households"] and {h["status"] for h in d["households"]} == {"not_contacted"}


def test_detail_why_flagged_numbers_are_consistent(client, store):
    """Every component, weight, contribution, lifelines and priority (Req 10.1, 10.2)."""
    d = client.get(f"/api/tracts/{DK_TRACT}", params={"hour": HOUR}).json()
    th = store.tract_hour(DK_TRACT, HOUR)
    assert set(d["need"]) == {"seniors_alone", "disability", "limited_english", "no_vehicle", "renter",
                              "elec_dependent"}
    assert set(d["weights"]) == set(d["contributions"]) == {"out_pct", "hours_dark", "wires", "telecom"}
    assert d["lifelines"] == pytest.approx(sum(d["contributions"].values()), abs=1e-6)
    assert d["priority"] == pytest.approx(d["need_t"] * d["lifelines"], abs=1e-6)
    assert d["components"]["out_pct"] == th["out_pct"] and d["components"]["hours_dark"] == th["hours_dark"]
    m = d["metrics"]
    assert m["priority"] == d["priority"] and m["rank"] == 1.0
    assert m["weight.out_pct"] == d["weights"]["out_pct"]
    # Briefing claim fields resolve against the detail metrics with matching values
    briefing = store.content.briefings[HOUR][DK_TRACT]
    for c in briefing.claims:
        assert m[c.field] == pytest.approx(c.value, abs=1e-6)


def test_detail_active_events_with_citations(client, store):
    d = client.get(f"/api/tracts/{DK_TRACT}", params={"hour": HOUR}).json()
    expected = set(store.tract_hour(DK_TRACT, HOUR)["telecom_event_ids"])
    assert {e["id"] for e in d["active_events"]} == expected
    for e in d["active_events"]:
        assert e["source_name"] and e["source_url"] and e["system"] and e["start_local"]
        assert "end_local" in e and "end_assumed" in e


def test_detail_chatham_label(client):
    d = client.get(f"/api/tracts/{CHATHAM_TRACT}", params={"hour": HOUR}).json()
    assert d["town"] == "Chatham"
    assert d["out_pct_label"] == NO_TOWN_REPORTS_LABEL == "Estimated from the Cape-wide share (no town reports)"


def test_detail_other_town_label(client, store):
    d = client.get(f"/api/tracts/{DK_TRACT}", params={"hour": HOUR}).json()
    assert d["out_pct_label"] == store.timeline.labels["reconstructed"]


def test_detail_404_and_422(client):
    assert client.get("/api/tracts/25001999999", params={"hour": HOUR}).status_code == 404
    assert client.get(f"/api/tracts/{DK_TRACT}", params={"hour": "2026-02-23T00:00"}).status_code == 404
    assert client.get(f"/api/tracts/{DK_TRACT}").status_code == 422


def test_detail_has_no_phone_or_address(client):
    for g in (DK_TRACT, SMS_TRACT):
        text = client.get(f"/api/tracts/{g}", params={"hour": HOUR}).text
        assert not re.search(PHONE, text) and not re.search(ADDRESS, text)


# ---------------------------------------------------------------- content


def test_content_door_knock_key_hour(client, store):
    r = client.get(f"/api/content/{DK_TRACT}", params={"hour": HOUR})
    assert r.status_code == 200
    c = r.json()
    assert c["briefing"]["kind"] == "verified"
    assert c["briefing"] == store.content.briefings[HOUR][DK_TRACT].model_dump(mode="json")
    reach = c["reach"]
    assert (reach["channel"], reach["rule"], reach["label"]) == ("door_knock", "modeled", MODELED)
    assert reach["sms"] is None
    assert set(reach["doorstep"]) == {"en", "pt", "es"}
    assert set(reach["radio"]) == {"en", "pt", "es"}
    assert reach["radio"]["en"] == store.content.radio[HOUR]["Falmouth"]["en"].model_dump(mode="json")
    assert c["help_line"]["sentence"]["en"]


def test_content_sms_tract(client, store):
    c = client.get(f"/api/content/{SMS_TRACT}", params={"hour": HOUR}).json()
    reach = c["reach"]
    assert reach["channel"] == "sms" and reach["label"] is None
    assert set(reach["sms"]) == {"en", "pt", "es"}
    for lang, msg in reach["sms"].items():
        assert msg == store.content.sms["Barnstable"][lang]["checkin"].model_dump(mode="json")
        assert msg["segments"] <= 2
    assert set(reach["doorstep"]) == {"en", "pt", "es"}


def test_content_radio_null_when_town_not_cached(client, store):
    """A town absent from the radio cache at the hour gets radio: null, never generated text."""
    for g in store.geoids:
        town = store.tract_town(g)
        if town not in store.content.radio.get(HOUR, {}):
            c = client.get(f"/api/content/{g}", params={"hour": HOUR}).json()
            assert c["reach"]["radio"] is None
            return
    pytest.skip("every town has a radio script at this hour")


def test_content_404_and_422(client):
    assert client.get("/api/content/25001999999", params={"hour": HOUR}).status_code == 404
    assert client.get(f"/api/content/{DK_TRACT}", params={"hour": "2026-02-28T00:00"}).status_code == 404
    assert client.get(f"/api/content/{DK_TRACT}").status_code == 422
