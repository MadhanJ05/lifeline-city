"""Unit tests for pipeline/synthetic.py (Req 17)."""
from __future__ import annotations

import geopandas as gpd
import shapely
from shapely.geometry import Polygon

from pipeline.common import LanguageMix, load_languages
from pipeline.synthetic import households, load_responders, responders

# A small L-shaped tract near Hyannis, so rejection sampling actually rejects.
POLY = Polygon([(-70.30, 41.64), (-70.26, 41.64), (-70.26, 41.66), (-70.28, 41.66),
                (-70.28, 41.68), (-70.30, 41.68)])
MIX = load_languages().household_language_mix


def _tracts(town: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"GEOID": ["25001012600"], "town": [town]}, geometry=[POLY], crs=4326)


def test_households_valid_and_deterministic():
    a = households(["25001012600"], _tracts("Falmouth"), MIX, 8, 20260223)
    b = households(["25001012600"], _tracts("Falmouth"), MIX, 8, 20260223)
    assert a == b
    assert [h["label"] for h in a] == [f"Simulated household #{i}" for i in range(1, 9)]
    for h in a:
        assert h["synthetic"] is True and "address" not in h and "phone" not in h
        assert h["lang"] in ("en", "pt", "es")
        assert shapely.contains_xy(POLY, h["lon"], h["lat"])
        assert round(h["lon"], 4) == h["lon"] and round(h["lat"], 4) == h["lat"]
    assert [h["is_operator"] for h in a] == [True] + [False] * 7


def test_pt_first_only_changes_household_one():
    all_en = LanguageMix(label="x", default={"en": 1.0}, by_town={"Barnstable": {"en": 1.0}})
    forced = households(["25001012600"], _tracts("Barnstable"), all_en, 8, 7)
    plain = households(["25001012600"], _tracts("Barnstable"), all_en, 8, 7, pt_first_towns=())
    assert forced[0]["lang"] == "pt" and plain[0]["lang"] == "en"
    assert forced[1:] == plain[1:]
    assert {k: v for k, v in forced[0].items() if k != "lang"} == {k: v for k, v in plain[0].items() if k != "lang"}


def test_responders_one_per_town_role():
    cfg = load_responders()
    rs = responders(cfg)
    assert len(rs) == sum(len(v) for v in cfg["towns"].values())
    assert {"Falmouth COA driver (Simulated)", "Yarmouth police wellness check (Simulated)"} <= {r["label"] for r in rs}
    assert all(r["synthetic"] is True and r["label"].endswith("(Simulated)") for r in rs)
    assert len({r["id"] for r in rs}) == len(rs)
