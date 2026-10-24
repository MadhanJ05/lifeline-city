"""Tests for api/data.py: the startup Store over the real data/processed/ files (Req 11.10, 28.1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.data import (CONFIG, NO_TOWN_REPORTS_LABEL, PROCESSED, PROCESSED_FILES, RUN_PIPELINE, NotFound,
                      StoreError, load_store)

HOUR = "2026-02-24T09:00"


@pytest.fixture(scope="module")
def store():
    return load_store()


def _linked_copy(tmp_path: Path, skip: str | None = None) -> Path:
    """A processed dir that symlinks the real files, optionally leaving one out."""
    out = tmp_path / "processed"
    out.mkdir()
    for name in PROCESSED_FILES:
        if name != skip:
            (out / name).symlink_to(PROCESSED / name)
    return out


def test_loads_every_file_and_indexes(store):
    assert len(store.hours) == 119
    assert store.hours[0] == "2026-02-23T01:00" and store.hours[-1] == "2026-02-27T23:00"
    assert store.hour_index(HOUR) == store.hours.index(HOUR)
    assert len(store.town_names) == 15
    assert set(store.geoids) == {f.properties.geoid for f in store.tracts.features}
    assert set(store.raw) == set(PROCESSED_FILES)  # boston_voice.geojson is absent in this build
    assert store.boston_voice is None
    assert store.scoring["queue_size"] == 10 and "reply_keywords" in store.languages


def test_tract_hour_matches_timeline_and_queue(store):
    for row in store.queue(HOUR):
        th = store.tract_hour(row.geoid, HOUR)
        assert th["town"] == row.town == store.tract_town(row.geoid)
        assert th["rank"] == row.rank
        assert th["channel"] == row.channel
        assert th["priority"] == pytest.approx(row.priority, abs=1e-6)
        assert th["priority"] == pytest.approx(th["need_t"] * th["lifelines"], abs=1e-5)
        town = store.town_hour(row.town, HOUR)
        assert {k: th[k] for k in town} == town
        assert set(town["contrib"]) == {"out_pct", "hours_dark", "wires", "telecom"}


def test_households_and_responders_are_indexed_and_synthetic(store):
    geoid = store.geoids[0]
    hh = store.households_for(geoid)
    assert hh and all(h.geoid == geoid and h.synthetic is True for h in hh)
    assert [h.number for h in hh] == sorted(h.number for h in hh)
    assert len(hh) == store.tract_props(geoid).households_n
    rs = store.responders_for("Falmouth")
    assert rs and all(r.town == "Falmouth" and r.synthetic is True for r in rs)


def test_unknown_keys_raise_not_found(store):
    with pytest.raises(NotFound):
        store.tract_town("00000000000")
    with pytest.raises(NotFound):
        store.hour_index("2026-03-01T00:00")
    with pytest.raises(NotFound):
        store.town_hour("Nantucket", HOUR)
    with pytest.raises(NotFound):
        store.households_for("bogus")
    with pytest.raises(NotFound):
        store.responders_for("Boston")


def test_chatham_out_pct_label(store):
    assert "Chatham" in store.sources.towns_without_anchors
    assert store.out_pct_label("Chatham") == NO_TOWN_REPORTS_LABEL
    assert store.town_hour("Chatham", HOUR)["out_pct_label"] == NO_TOWN_REPORTS_LABEL
    reconstructed = store.timeline.provenance["out_pct"]
    for town in store.town_names:
        if town not in store.sources.towns_without_anchors:
            assert store.out_pct_label(town) == reconstructed


def test_store_is_read_only(store):
    with pytest.raises(Exception):
        store.timeline = None  # type: ignore[misc]
    with pytest.raises(TypeError):
        store.raw["content.json"] = b""  # type: ignore[index]


@pytest.mark.parametrize("name", ["cape_timeline.json", "content.json"])
def test_missing_required_file_stops_startup(tmp_path, name):
    with pytest.raises(StoreError) as e:
        load_store(_linked_copy(tmp_path, skip=name), CONFIG)
    assert name in str(e.value) and RUN_PIPELINE in str(e.value)


def test_boston_voice_is_optional_and_loaded_when_present(tmp_path):
    d = _linked_copy(tmp_path)
    assert load_store(d, CONFIG).boston_voice is None
    (d / "boston_voice.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "tz": "America/New_York", "features": [], "metadata": {"k": 7}}))
    s = load_store(d, CONFIG)
    assert s.boston_voice is not None and s.boston_voice.metadata == {"k": 7}
    assert "boston_voice.geojson" in s.raw


def test_invalid_file_names_file_and_pipeline(tmp_path):
    d = _linked_copy(tmp_path, skip="households.json")
    (d / "households.json").write_text(json.dumps(
        {"tz": "America/New_York", "households": [{"id": "x", "synthetic": False}]}))
    with pytest.raises(StoreError) as e:
        load_store(d, CONFIG)
    assert "households.json" in str(e.value) and RUN_PIPELINE in str(e.value)
