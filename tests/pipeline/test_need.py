"""Unit tests for pipeline/need.py on small synthetic inputs (Req 2.1 to 2.6)."""
import math

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from pipeline import fetch
from pipeline.common import PipelineError
from pipeline.need import (INDICATORS, NEED_ACS_VARS, allocate_zip_counts, check_acs_vars, indicator_values,
                           need_scores)

CRS = 26986


def _acs(**overrides):
    base = {v: 100.0 for v in NEED_ACS_VARS}
    base.update({"B11010_005E": 10, "B11010_012E": 20, "S1810_C03_001E": 12.5, "C16002_004E": 1,
                 "C16002_007E": 2, "C16002_010E": 3, "C16002_013E": 4, "B25044_003E": 5, "B25044_010E": 15,
                 "B25003_003E": 40})
    base.update(overrides)
    return pd.DataFrame([base], index=pd.Index(["t1"], name="GEOID"))


def test_pinned_vars_are_fetched_and_checked():
    assert set(NEED_ACS_VARS) <= set(fetch.ACS_TRACT_VARS)
    check_acs_vars({v: "label" for v in NEED_ACS_VARS})
    with pytest.raises(PipelineError, match="B25003_003E"):
        check_acs_vars({v: "label" for v in NEED_ACS_VARS if v != "B25003_003E"})


def test_indicator_values_formulas():
    got = indicator_values(_acs(), pd.Series({"t1": 7.5})).loc["t1"]
    assert got.to_dict() == pytest.approx({"seniors_alone": 0.3, "disability": 0.125, "limited_english": 0.1,
                                           "no_vehicle": 0.2, "renter": 0.4, "elec_dependent": 7.5})


def test_sentinel_and_zero_denominator_become_nan():
    got = indicator_values(_acs(S1810_C03_001E=-666666666, B25003_001E=0, B25044_003E=-999999999),
                           pd.Series(dtype=float)).loc["t1"]
    assert math.isnan(got["disability"]) and math.isnan(got["renter"]) and math.isnan(got["no_vehicle"])
    assert math.isnan(got["elec_dependent"]) and got["seniors_alone"] == pytest.approx(0.3)


def test_allocate_by_zip_area_share_and_mask_11():
    tracts = gpd.GeoDataFrame({"GEOID": ["a", "b"], "geometry": [box(0, 0, 10, 10), box(10, 0, 20, 10)]},
                              crs=CRS)
    zips = gpd.GeoDataFrame({
        "Zip_Code": ["z1", "z2"],
        "Power_Dependent_Devices_DME": ["100", 11],    # strings are coerced; 11 kept as reported
        "Medicare_Benes": [400, None],
        # z1 spans both tracts and a neighbor county (x 20..40); z2 lies inside tract b
        "geometry": [box(0, 0, 40, 10), box(12, 2, 14, 4)]}, crs=CRS).to_crs(4326)
    got = allocate_zip_counts(zips, tracts.to_crs(4326))
    assert got.loc["a", "Power_Dependent_Devices_DME"] == pytest.approx(25, rel=1e-3)
    assert got.loc["b", "Power_Dependent_Devices_DME"] == pytest.approx(25 + 11, rel=1e-3)
    assert got.loc["a", "Medicare_Benes"] == pytest.approx(100, rel=1e-3)
    assert got.loc["b", "Medicare_Benes"] == pytest.approx(100, rel=1e-3)  # null ZIP contributes nothing
    assert list(got["Power_Dependent_Devices_DME_masked"]) == [False, True]
    assert not got["Medicare_Benes_masked"].any()


def test_need_scores_mean_of_available_ranks_and_missing_list():
    raw = pd.DataFrame({k: [0.1, 0.2, 0.3] for k in INDICATORS}, index=["x", "y", "z"])
    raw.loc["z", "renter"] = float("nan")
    got = need_scores(raw)
    assert list(got["pct_seniors_alone"]) == pytest.approx([1 / 3, 2 / 3, 1])
    assert list(got["pct_renter"][:2]) == pytest.approx([0.5, 1]) and math.isnan(got.loc["z", "pct_renter"])
    assert got.loc["z", "need_t"] == pytest.approx(1.0)
    assert got.loc["x", "need_t"] == pytest.approx((5 / 3 + 0.5) / 6)
    assert got.loc["z", "need_missing"] == ["renter"] and got.loc["x", "need_missing"] == []
