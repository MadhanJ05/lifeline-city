"""Tests for pipeline/locate.py on a two-town toy geography in EPSG:26986: nearest-first spreading,
reconciliation to town totals, the year-round conversion and the summary."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from shapely.geometry import Point, box

from pipeline import locate
from pipeline.tracts_towns import METRIC

# Barnstable: x 0..1000, Bourne: x 1000..2000 (metres); both y 0..1000.
TOWNS = gpd.GeoDataFrame({"town": ["Barnstable", "Bourne"]},
                         geometry=[box(0, 0, 1000, 1000), box(1000, 0, 2000, 1000)], crs=METRIC)


def blocks_frame(rows):
    """rows: (GEOID, town, x, y, homes, year_round); tract = first 11 GEOID characters."""
    b = pd.DataFrame(rows, columns=["GEOID", "town", "x", "y", "homes", "year_round"])
    b["tract"] = b["GEOID"].str[:11]
    return b[["GEOID", "tract", "town", "x", "y", "homes", "year_round"]]


BLOCKS = blocks_frame([
    ("250010001001001", "Barnstable", 100, 100, 10, 5),
    ("250010001001002", "Barnstable", 300, 100, 10, 10),
    ("250010002001001", "Barnstable", 900, 900, 20, 2),
    ("250010003001001", "Bourne", 1500, 500, 50, 25),
])


def pts(rows):
    """rows: (x, y, cust_out) in metres -> outage rows with lat/lon."""
    g = gpd.GeoSeries([Point(x, y) for x, y, _ in rows], crs=METRIC).to_crs(4326)
    return pd.DataFrame({"lat": g.y, "lon": g.x, "cust_out": [c for _, _, c in rows]})


def placed(rows):
    return locate.place(pts(rows), TOWNS)


# ---------------------------------------------------------------- place


def test_place_inside_near_and_outside():
    p = placed([(500, 500, 1), (500, -800, 1), (500, -5000, 1), (1999, 10, 1)])
    assert p["town"].isna().tolist() == [False, False, True, False]  # 0.8 km offshore snaps; 5 km drops
    assert p["town"][~p["town"].isna()].tolist() == ["Barnstable", "Barnstable", "Bourne"]
    assert p["x"].iloc[0] == pytest.approx(500, abs=0.01)


# ---------------------------------------------------------------- spread


def test_spread_fills_nearest_homes_first():
    out, unplaced = locate.spread(placed([(100, 100, 15)]), BLOCKS)
    assert out.tolist() == [10, 5, 0, 0] and unplaced == 0


def test_spread_places_larger_outages_first_and_never_overfills():
    out, _ = locate.spread(placed([(300, 100, 4), (100, 100, 18)]), BLOCKS)
    assert out.tolist() == [10, 10, 2, 0]  # the 18 takes both near blocks, the 4 moves on to the far one
    assert (out <= BLOCKS["homes"].to_numpy()).all()


def test_spread_reports_customers_without_room():
    out, unplaced = locate.spread(placed([(1500, 500, 60)]), BLOCKS)
    assert out.tolist() == [0, 0, 0, 50] and unplaced == 10


# ---------------------------------------------------------------- reconcile


def test_reconcile_scales_down_to_the_town_total():
    out, method, checks = locate.reconcile(np.array([10, 5, 0, 0.0]), BLOCKS, {"Barnstable": 9, "Bourne": 0})
    assert out.tolist() == pytest.approx([6, 3, 0, 0])
    assert checks["Barnstable"] == {"reported": 9, "from_points": 15.0, "estimated": 9.0, "homes": 40,
                                    "method": "points, scaled to town total"}
    assert checks["Bourne"]["method"] == "town reports 0" and method[0] == locate.LABEL_POINTS


def test_reconcile_scales_up_with_clipping():
    out, _, checks = locate.reconcile(np.array([10, 0, 0, 0.0]), BLOCKS, {"Barnstable": 16})
    assert out.tolist() == pytest.approx([10, 2, 4, 0])  # 6 over block 1's homes, moved by room (10:20)
    assert checks["Barnstable"]["estimated"] == 16


def test_reconcile_town_total_without_points_and_no_report():
    out, method, checks = locate.reconcile(np.array([0, 0, 0, 7.0]), BLOCKS, {"Barnstable": 20})
    assert out.tolist() == pytest.approx([5, 5, 10, 7])  # Barnstable by homes; Bourne has no report: kept
    assert checks["Barnstable"]["method"] == "town total only (no outage locations)"
    assert checks["Bourne"]["method"] == "points, no town report"
    assert method[0] == locate.LABEL_TOWN and method[3] == locate.LABEL_POINTS


@given(st.lists(st.integers(1, 40), min_size=1, max_size=8),
       st.lists(st.tuples(st.integers(0, 999), st.integers(0, 999), st.integers(0, 60)), max_size=6),
       st.one_of(st.none(), st.integers(0, 400)))
def test_reconciled_blocks_stay_within_homes_and_match_the_report(homes, outages, reported):
    rows = [(f"25001000100{i:04d}", "Barnstable", 123 * i % 1000, 457 * i % 1000, h, h) for i, h in enumerate(homes)]
    b = blocks_frame(rows)
    spread_out, _ = locate.spread(placed(outages) if outages else placed([(0, 0, 0)]), b)
    totals = {} if reported is None else {"Barnstable": reported}
    out, _, _ = locate.reconcile(spread_out, b, totals)
    assert (out >= -1e-9).all() and (out <= b["homes"].to_numpy() + 1e-9).all()
    if reported is not None:
        assert out.sum() == pytest.approx(min(reported, sum(homes)))
    else:
        assert out.sum() == pytest.approx(spread_out.sum())


# ---------------------------------------------------------------- year-round and tracts


def test_by_tract_counts_year_round_homes_only():
    out, method, _ = locate.reconcile(np.array([10, 0, 0, 0.0]), BLOCKS, {"Barnstable": 10})
    t = locate.by_tract(BLOCKS, out, method).set_index("tract")
    first = t.loc["25001000100"]
    assert (first["homes"], first["year_round_homes"], first["customers_out"]) == (20, 15, 10)
    assert first["year_round_out"] == 5  # block 1: 10 customers out, half its homes year-round
    assert first["pct_year_round_out"] == pytest.approx(5 / 15, abs=1e-4)
    assert first["label"] == locate.LABEL_POINTS and t.loc["25001000300", "label"] == locate.LABEL_NONE


def test_prepare_blocks_scales_occupied_homes_to_acs_households():
    g = gpd.GeoSeries([Point(100, 100), Point(300, 100), Point(1500, 500), Point(1600, 500)], crs=METRIC).to_crs(4326)
    raw = pd.DataFrame({"GEOID": ["250010001001001", "250010001001002", "250010003001001", "250010003001002"],
                        "homes": [10, 10, 50, 0], "occupied": [4, 6, 20, 0], "lat": g.y, "lon": g.x})
    acs = pd.DataFrame({"GEOID": ["25001000100", "25001000300"], "B11001_001E": [15, 60]})
    b = locate.prepare_blocks(raw, acs, TOWNS)
    assert list(b["GEOID"]) == ["250010001001001", "250010001001002", "250010003001001"]  # 0 homes dropped
    assert b["year_round"].tolist() == pytest.approx([6, 9, 50])  # x1.5; Bourne x3 capped at its 50 homes
    assert list(b["town"]) == ["Barnstable", "Barnstable", "Bourne"]


# ---------------------------------------------------------------- town totals and the whole snapshot


def town_rows(rows):
    return pd.DataFrame(rows, columns=["source", "town", "cust_out"])


def test_town_totals_prefer_utility_reports():
    totals, source = locate.town_totals(town_rows([("eversource", "BARNSTABLE", 30), ("national_grid", "BARNSTABLE", 2),
                                                   ("eversource", "BOSTON", 9), ("mema", "BARNSTABLE", 99)]))
    assert source == "utility reports" and totals == {"Barnstable": 32}


def test_town_totals_fall_back_to_mema_with_unlisted_towns_at_zero():
    totals, source = locate.town_totals(town_rows([("mema", "BOURNE", 12), ("mema", "WARE", 3)]))
    assert source == "mema" and totals["Bourne"] == 12 and totals["Barnstable"] == 0 and len(totals) == 15


def test_locate_one_snapshot():
    tracts, summary = locate.locate(pts([(100, 100, 12), (1500, 500, 4), (500, -9000, 30)]),
                                    town_rows([("eversource", "BARNSTABLE", 12), ("eversource", "BOURNE", 4)]),
                                    BLOCKS, TOWNS)
    assert summary["points"] == {"total": 3, "in_county": 2, "outside_county": 1, "customers_without_room": 0.0}
    assert summary["county"]["customers_out"] == 16
    assert summary["county"]["year_round_out"] == pytest.approx(5 + 2 + 2, abs=0.1)  # 10x0.5 + 2x1 + 4x0.5
    assert tracts.set_index("tract").loc["25001000300", "customers_out"] == 4
