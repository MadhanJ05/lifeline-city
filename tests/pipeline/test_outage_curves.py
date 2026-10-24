"""Unit tests for the Tab 3 curve, Anchors and town customer counts (task 3.3)."""
from __future__ import annotations

import pandas as pd
import pytest

from pipeline import outage_curves as oc
from pipeline.common import CAPE_TOWNS, HOURS, PROVENANCE, PipelineError

DUMMY_ACS = {t: 10_000 for t in CAPE_TOWNS}


def test_time_labels():
    assert [oc.parse_time_label(x) for x in ("12AM", "1AM", "11AM", "12PM", "1PM", "11PM")] == [0, 1, 11, 12, 13, 23]
    with pytest.raises(PipelineError):
        oc.parse_time_label("13PM")


@pytest.mark.skipif(not oc.WORKBOOK.exists(), reason="Eversource_Workbook not present")
def test_tab3_curve_peak_and_grid():
    curve = oc.tab3_curve(oc.open_workbook())
    assert list(curve.index) == HOURS
    assert curve.max() == 269_063 and curve.idxmax() == "2026-02-23T08:00"
    assert curve.notna().all()


class _FakeWS:
    def __init__(self, rows):
        self.rows = rows

    def iter_rows(self, min_row=1, max_row=None, max_col=None, values_only=True):
        return iter(self.rows[min_row - 1:max_row])


class _FakeWB:
    sheetnames = ["Tab 3"]

    def __init__(self, rows):
        self._ws = _FakeWS(rows)

    def __getitem__(self, name):
        return self._ws


def test_tab3_wrong_peak_reports_max_and_hour():
    from datetime import datetime
    d = datetime(2026, 2, 23)
    rows = [(None,)] * 3 + [oc.TAB3_HEADER, (d, "1AM", 100, 0), (d, "2AM", 50, 0), (d, "3AM", 0, 20)]
    with pytest.raises(PipelineError, match=r"150 at 2026-02-23T02:00"):
        oc.tab3_curve(_FakeWB(rows))


def test_anchors_keep_only_cape_and_record_exclusions():
    excluded: list[oc.Exclusion] = []
    rows = oc.read_anchor_rows(oc.ANCHORS_CSV, excluded)
    assert set(rows["town"]) <= set(CAPE_TOWNS)
    assert not {"Plymouth", "Scituate", "Nantucket", "Oak Bluffs", "Edgartown"} & set(rows["town"])
    assert len([e for e in excluded if e.reason == oc.NOT_CAPE_REASON]) == 5
    N = oc.town_customers(rows, DUMMY_ACS)
    anchors = oc.load_anchors(oc.ANCHORS_CSV, N)
    assert anchors and all(a.town in CAPE_TOWNS and 0 <= a.pct <= 1 for a in anchors)
    assert "Chatham" not in {a.town for a in anchors}
    # Sandwich 4,200 homes with blank pct_out -> customers_out / N (4.13)
    sandwich = [a for a in anchors if a.town == "Sandwich" and a.hour == "2026-02-23T14:00"]
    assert sandwich[0].pct == pytest.approx(4200 / 10_000)


def test_town_customers_mema_and_acs_fallback():
    rows = oc.read_anchor_rows(oc.ANCHORS_CSV)
    N = oc.town_customers(rows, DUMMY_ACS)
    assert set(N) == set(CAPE_TOWNS)
    assert N["Falmouth"].count == pytest.approx(22885 / 0.90) and N["Falmouth"].label is None
    for t in ("Sandwich", "Chatham"):
        assert N[t].count == 10_000 and N[t].label == PROVENANCE["acs_customers"]


def test_sitrep_009_excluded_without_value():
    df = pd.DataFrame([
        {"town": "Barnstable", "county": "Barnstable", "datetime_local": "2026-02-26T10:00",
         "customers_out": 133000, "pct_out": None, "pct_is_lower_bound": False, "time_is_approx": False,
         "source_name": "Barnstable County Situation Report #009", "source_url": "x", "note": ""},
    ])
    excluded: list[oc.Exclusion] = []
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "a.csv"
        df.to_csv(p, index=False)
        assert oc.read_anchor_rows(p, excluded).empty
    assert excluded == [oc.Exclusion(file="a.csv", row=2, reason=oc.SITREP_009_REASON)]
    assert "133" not in repr(excluded)


# ---------------------------------------------------------------- shaping and scaling (task 3.4)

from hypothesis import given, settings, strategies as st  # noqa: E402

H6 = [f"2026-02-23T0{i}:00" for i in range(1, 7)]


def test_ratio_shape_knots_and_constant_ratio_outside():
    base = pd.Series([10.0, 20, 40, 40, 20, 10], index=H6)
    out = oc.ratio_shape(base, [(H6[1], 10.0), (H6[3], 40.0)])
    assert out[H6[1]] == 10 and out[H6[3]] == 40
    assert out[H6[0]] == pytest.approx(5)          # ratio 0.5 held before
    assert out[H6[2]] == pytest.approx(40 * 0.75)  # ratio midway 0.5 -> 1.0
    assert out[H6[5]] == pytest.approx(10)         # ratio 1.0 held after


def test_ratio_shape_zero_base_interpolates_values():
    base = pd.Series([0.0, 0, 0, 10, 10, 10], index=H6)
    out = oc.ratio_shape(base, [(H6[0], 2.0), (H6[2], 6.0)])
    assert list(out[:3]) == pytest.approx([2, 4, 6])


@pytest.mark.skipif(not oc.WORKBOOK.exists(), reason="Eversource_Workbook not present")
def test_cape_total_through_cape_rows():
    knots = oc.read_cape_rows()
    assert len(knots) == 20 and ("2026-02-24T08:00", 158_803) in knots
    C = oc.cape_total(oc.tab3_curve(oc.open_workbook()), knots)
    assert list(C.index) == HOURS and (C >= 0).all()
    assert all(C[h] == pytest.approx(v) for h, v in knots)
    assert C.max() == pytest.approx(158_803) and C.idxmax() == "2026-02-24T08:00"


def test_unscaled_no_anchor_is_share_and_one_anchor_scales():
    share = pd.Series([0.1, 0.2, 0.4, 0.2, 0.1, 0.05], index=H6)
    assert oc.unscaled("Chatham", [], share).equals(share)
    from datetime import datetime
    a = oc.Anchor("Truro", datetime(2026, 2, 23, 3, 30, tzinfo=oc.TZ), H6[2], 0.8, False, False, "s", "u", 2)
    u = oc.unscaled("Truro", [a], share)
    assert list(u) == pytest.approx([min(0.8 * s / 0.4, 1) for s in share])


def test_scale_hour_unmatched_when_pins_exceed_total():
    N = {"A": 100.0, "B": 100.0}
    out, um = oc.scale_hour("h", {"A": 0.5, "B": 0.5}, N, {"A": 1.0}, {}, {"h": 50.0})
    assert out == {"A": 1.0, "B": 0.0} and um == pytest.approx(-50)
    out, um = oc.scale_hour("h", {"A": 0.5, "B": 0.5}, N, {}, {}, {"h": 250.0})
    assert out == {"A": 1.0, "B": 1.0} and um == pytest.approx(50)


towns = [f"T{i}" for i in range(6)]


@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(100, 30_000), min_size=6, max_size=6),
       st.lists(st.floats(0, 1), min_size=6, max_size=6),
       st.lists(st.sampled_from(["free", "pin", "lb"]), min_size=6, max_size=6),
       st.lists(st.floats(0, 1), min_size=6, max_size=6),
       st.floats(0, 1.2))
def test_property_8_scale_keeps_pins_bounds_and_total(ns, us, kinds, vs, frac):
    """Property 8: pins kept, bounds respected, total matched or recorded.

    **Validates: Requirements 4.1, 4.5, 4.6, 4.11, 4.12**
    """
    N = dict(zip(towns, map(float, ns)))
    u = dict(zip(towns, us))
    pinned = {t: v for t, k, v in zip(towns, kinds, vs) if k == "pin"}
    lb = {t: v for t, k, v in zip(towns, kinds, vs) if k == "lb"}
    C = {"h": frac * sum(N.values())}
    out, um = oc.scale_hour("h", u, N, pinned, lb, C)
    assert set(out) == set(towns)
    assert all(out[t] == pinned[t] for t in pinned)
    assert all(0 <= v <= 1 for v in out.values())
    assert all(out[t] >= lb[t] - 1e-12 for t in lb)
    total = sum(out[t] * N[t] for t in towns)
    assert abs(C["h"] - total - um) <= 1
    if um == 0:
        assert abs(total - C["h"]) <= 1
