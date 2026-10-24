"""Tests for pipeline/tracts_towns.py on small synthetic geometries (Req 1.5, 3.4, 3.5)."""
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from pipeline.common import CAPE_TOWNS, PipelineError
from pipeline.tracts_towns import assign_towns, cape_towns, cape_tracts

CRS = 26986


def _cousub(names):
    rows = [{"STATEFP": "25", "COUNTYFP": "001", "COUSUBFP": f"{i + 1:05d}", "GEOID": f"25001{i + 1:05d}",
             "NAME": n, "geometry": box(i * 1000, 0, i * 1000 + 1000, 1000)} for i, n in enumerate(names)]
    rows.append({"STATEFP": "25", "COUNTYFP": "001", "COUSUBFP": "00000", "GEOID": "2500100000",
                 "NAME": "County subdivisions not defined", "geometry": box(0, -500, 1, -499)})
    rows.append({"STATEFP": "25", "COUNTYFP": "017", "COUSUBFP": "99999", "GEOID": "2501799999",
                 "NAME": "Boston", "geometry": box(0, 5000, 1, 5001)})
    return gpd.GeoDataFrame(rows, crs=CRS)


def _names():
    return ["Barnstable Town" if t == "Barnstable" else t for t in CAPE_TOWNS]


def test_cape_towns_strips_town_suffix_and_drops_non_towns():
    towns = cape_towns(_cousub(_names()))
    assert sorted(towns["town"]) == sorted(CAPE_TOWNS)
    assert towns.crs.to_epsg() == 4326 and list(towns.columns) == ["town", "GEOID", "geometry"]


def test_cape_towns_raises_on_wrong_names():
    with pytest.raises(PipelineError, match="Hyannis"):
        cape_towns(_cousub(_names()[:-1] + ["Hyannis"]))


def test_tracts_pop_filter_and_assignment():
    towns = cape_towns(_cousub(_names()))
    tracts = gpd.GeoDataFrame({
        "STATEFP": ["25"] * 4, "COUNTYFP": ["001"] * 3 + ["017"], "GEOID": ["a", "b", "c", "d"],
        "geometry": [box(100, 100, 200, 200),        # inside town 0
                     box(1100, 1100, 1200, 1200),    # centroid outside all towns, nearest town 1
                     box(300, 300, 400, 400),        # population 0
                     box(100, 100, 200, 200)]}, crs=CRS)
    pop = pd.DataFrame({"GEOID": ["a", "b", "c", "d"], "B01003_001E": [10, 5, 0, 7]})
    kept = cape_tracts(tracts, pop)
    assert list(kept["GEOID"]) == ["a", "b"] and list(kept["population"]) == [10, 5]
    got = assign_towns(kept, towns).set_index("GEOID")
    assert got.loc["a", "town"] == CAPE_TOWNS[0] and got.loc["a", "assign_method"] == "centroid"
    assert got.loc["b", "town"] == CAPE_TOWNS[1] and got.loc["b", "assign_method"] == "nearest"
