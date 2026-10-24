"""Unit tests for pipeline/scale_catalog.py (Req 23.12, 24.1, 24.2, 24.5, 24.6)."""
import pytest
from pipeline.common import ConfigError
from pipeline.scale_catalog import PREVIEW_LABEL, catalog, load_hazards
CFG = load_hazards()
SCORE_KEYS = {"data_endpoint", "scores", "need", "priority", "lifelines"}
def by_id(entries):
    return {e["id"]: e for e in entries}
def test_six_entries_with_tiers():
    cat = by_id(catalog(CFG, boston_built=False))
    assert list(cat) == ["cape_blizzard", "boston_blizzard", "plymouth_noreaster", "worcester_ice_storm",
                         "lowell_flood", "springfield_heat"]
    assert {k: e["tier"] for k, e in cat.items() if e["tier"] == 2} == {"boston_blizzard": 2}
def test_only_cape_is_live_without_boston():
    cat = by_id(catalog(CFG, boston_built=False))
    assert cat["cape_blizzard"]["mode"] == "live" and cat["cape_blizzard"]["data_endpoint"] == "/api/tracts"
    for eid, e in cat.items():
        if eid != "cape_blizzard":
            assert e["mode"] == "preview" and e["label"] == PREVIEW_LABEL
            assert not SCORE_KEYS & set(e), eid
def test_boston_live_when_built():
    cat = by_id(catalog(CFG, boston_built=True))
    assert [k for k, e in cat.items() if e["mode"] == "live"] == ["cape_blizzard", "boston_blizzard"]
    assert cat["boston_blizzard"]["data_endpoint"] == "/api/boston/voice"
def test_lost_lifelines_inputs_per_hazard():
    cat = by_id(catalog(CFG, boston_built=False))
    assert cat["plymouth_noreaster"]["lost_lifelines_inputs"] == ["power", "phones", "blocked roads"]
    assert cat["worcester_ice_storm"]["lost_lifelines_inputs"] == ["power", "phones", "blocked roads"]
    assert cat["lowell_flood"]["lost_lifelines_inputs"] == ["flood zones", "river gauges", "road closures"]
    assert cat["springfield_heat"]["lost_lifelines_inputs"] == ["power", "heat index"]
    assert all(len(e["need_inputs"]) == 6 for e in cat.values())
def test_unknown_hazard_rejected():
    bad = {**CFG, "entries": [{"id": "x", "place": "Salem", "hazard": "tornado", "mode": "preview"}]}
    with pytest.raises(ConfigError):
        catalog(bad, boston_built=False)
