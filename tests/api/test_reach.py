"""Tests for api/reach.py over the real data/processed/ files (Req 15.1, 15.2, 15.3, 15.5, 17.9)."""
from __future__ import annotations

import dataclasses
import re
from types import MappingProxyType

import pytest

from api.data import NotFound, load_store
from api.reach import (ACCESS_HAZARD_NOTE, ChannelMismatch, ReachError, access_hazard, channel,
                       door_knock_list, town_responders, why_chips_for)
from pipeline.privacy_guard import ADDRESS, PHONE

HOUR = "2026-02-24T09:00"
DK_TRACT = "25001014800"    # Falmouth, rank 1, door_knock (modeled), wires 0.4
SMS_TRACT = "25001015300"   # Barnstable, rank 7, sms


@pytest.fixture(scope="module")
def store():
    return load_store()


def _with(store, **changes):
    return dataclasses.replace(store, **{k: MappingProxyType(v) for k, v in changes.items()})


def _find(store, *, queued: bool, hazard: bool | None = None):
    """First door_knock tract-hour with households matching the filters."""
    threshold = store.scoring["access_hazard_wires_pct"]
    for g in store.geoids:
        if not store.households_for(g):
            continue
        t = store.timeline.tracts[g]
        w = store.timeline.towns[t.town].wires
        for i, h in enumerate(store.hours):
            if t.channel[i] != "door_knock" or (t.rank[i] is not None) != queued:
                continue
            if hazard is None or (w[i] >= threshold) == hazard:
                return g, h
    pytest.skip("no matching tract-hour in the processed data")


# ---------------------------------------------------------------- channel


def test_channel_door_knock_is_modeled_with_label(store):
    ch = channel(store, DK_TRACT, HOUR)
    assert (ch.channel, ch.telecom, ch.telecom_rule) == ("door_knock", 1, "modeled")
    assert ch.label == "Modeled: assumes tower backup lasts about 8 hours"
    assert ch.citations == []  # no curated event has drives_reach_flag = true


def test_channel_sms_has_no_rule_label(store):
    ch = channel(store, SMS_TRACT, HOUR)
    assert (ch.channel, ch.telecom, ch.telecom_rule, ch.label) == ("sms", 0, "none", None)


def test_channel_unknown_tract_or_hour(store):
    with pytest.raises(NotFound):
        channel(store, "25001999999", HOUR)
    with pytest.raises(NotFound):
        channel(store, DK_TRACT, "2026-03-01T00:00")


# ---------------------------------------------------------------- door-knock list


def test_door_knock_list_entries(store):
    entries = door_knock_list(store, DK_TRACT, HOUR)
    households = store.households_for(DK_TRACT)
    assert len(entries) == len(households) > 0                                    # 15.1
    queue_chips = next(r.why_chips for r in store.queue(HOUR) if r.geoid == DK_TRACT)
    allowed = {r.label for r in store.responders_for("Falmouth")
               if r.role in store.responders_config["towns"]["Falmouth"]}
    for e, hh in zip(entries, households):
        assert e.household_label == f"Simulated household #{hh.number}"           # 15.2
        assert e.lang == hh.lang
        assert e.why_chips == queue_chips and len(e.why_chips) == 2
        assert e.responder_label in allowed and "(Simulated)" in e.responder_label  # 15.5
        assert e.doorstep_script == store.content.doorstep["Falmouth"][hh.lang]
        assert e.access_hazard is None                                             # wires 0.4 < 0.8
        assert e.synthetic is True                                                 # 17.9


def test_door_knock_entries_have_no_phone_or_address(store):
    for e in door_knock_list(store, DK_TRACT, HOUR):
        d = e.model_dump()
        assert not {"phone", "address", "lon", "lat"} & set(d)
        text = str(d)
        assert not re.search(PHONE, text) and not re.search(ADDRESS, text)


def test_door_knock_list_rejects_sms_tract_hour(store):
    with pytest.raises(ChannelMismatch, match="sms"):
        door_knock_list(store, SMS_TRACT, HOUR)


def test_responders_round_robin_by_household_number(store):
    entries = door_knock_list(store, DK_TRACT, HOUR)
    roles = town_responders(store, "Falmouth")
    for e, hh in zip(entries, store.households_for(DK_TRACT)):
        assert e.responder_label == roles[(hh.number - 1) % len(roles)].label
    assert door_knock_list(store, DK_TRACT, HOUR) == entries  # deterministic


def test_only_roles_listed_for_the_town(store):
    cfg = {**store.responders_config, "towns": {**store.responders_config["towns"],
                                                "Falmouth": ["coa_driver", "meals_on_wheels"]}}
    entries = door_knock_list(_with(store, responders_config=cfg), DK_TRACT, HOUR)
    assert {e.responder_label for e in entries} == {"Falmouth COA driver (Simulated)",
                                                    "Falmouth Meals on Wheels driver (Simulated)"}

    cfg["towns"]["Falmouth"] = []
    with pytest.raises(ReachError, match="Falmouth"):
        door_knock_list(_with(store, responders_config=cfg), DK_TRACT, HOUR)


# ---------------------------------------------------------------- access hazard


def test_access_hazard_note_when_wires_at_threshold(store):
    geoid, hour = _find(store, queued=True, hazard=True)
    assert access_hazard(store, geoid, hour)
    entries = door_knock_list(store, geoid, hour)
    assert entries and all(e.access_hazard == ACCESS_HAZARD_NOTE for e in entries)       # 15.3
    assert ACCESS_HAZARD_NOTE == "Downed wires reported nearby. Treat every wire as live."


def test_access_hazard_boundary_is_inclusive(store):
    wires = store.tract_hour(DK_TRACT, HOUR)["wires"]
    assert not access_hazard(store, DK_TRACT, HOUR)
    at = _with(store, scoring={**store.scoring, "access_hazard_wires_pct": wires})
    assert access_hazard(at, DK_TRACT, HOUR)
    assert all(e.access_hazard == ACCESS_HAZARD_NOTE for e in door_knock_list(at, DK_TRACT, HOUR))


# ---------------------------------------------------------------- why chips outside the queue


def test_unqueued_tract_hour_has_no_chips(store):
    geoid, hour = _find(store, queued=False)
    assert why_chips_for(store, geoid, hour) == []
    entries = door_knock_list(store, geoid, hour)
    assert entries and all(e.why_chips == [] for e in entries)
