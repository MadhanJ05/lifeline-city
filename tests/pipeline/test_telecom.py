"""Unit tests for pipeline/telecom.py: modeled rule, event parsing, Active_Event, matrix and pins."""
import numpy as np
import pandas as pd

from pipeline.common import HOURS, PROVENANCE
from pipeline.telecom import (CAPE_WIDE_MARKER, EVENTS_CSV, export_event, is_active, modeled, parse_events,
                              telecom_matrix)

COLS = ["start_local", "end_local", "town_or_area", "system", "status", "affects", "drives_reach_flag",
        "source_name", "source_url", "note"]


def _events(*rows, default_hours=12):
    """rows: (start_local, end_local, town_or_area, drives_reach_flag)."""
    df = pd.DataFrame([dict(zip(COLS, (s, e, a, "x", "x", "x", f, "src", "https://example.invalid", "")))
                       for s, e, a, f in rows])
    return parse_events(df, default_hours)


def test_modeled_needs_k_in_window_hours_at_or_above_threshold():
    x = np.array([0.8] * 7 + [0.9, 0.79999, 0.8])
    assert modeled(x, 0.8, 8).tolist() == [False] * 7 + [True, False, False]
    assert not modeled(np.full(7, 1.0), 0.8, 8).any()  # never counts hours before the window


def test_split_whole_name_match_and_default_end():
    a, b = _events(("2026-02-23T04:42", "", "brewster ; Orleans;Outer Cape", "true"),
                   ("2026-02-23T05:45", "2026-02-23T06:25", "Barnstable County MACC", "false"))
    assert a.areas == ("brewster", "Orleans", "Outer Cape") and a.matched == ("Brewster", "Orleans")
    assert a.end_assumed and (a.end - a.start).total_seconds() == 12 * 3600
    assert b.matched == () and not b.end_assumed
    assert is_active(b, "2026-02-23T05:00") and is_active(b, "2026-02-23T06:00")
    assert not is_active(b, "2026-02-23T04:00") and not is_active(b, "2026-02-23T07:00")


def test_matrix_rules_and_cape_wide_context():
    hours = HOURS[:12]
    out = pd.DataFrame({"Brewster": [0.9] * 12, "Orleans": [0.0] * 12}, index=hours)
    evs = _events(("2026-02-23T01:00", "2026-02-23T03:00", "Orleans;Brewster", "true"),
                  ("2026-02-23T01:00", "2026-02-23T02:00", "Cape-wide", "true"),
                  ("2026-02-23T08:00", "2026-02-23T09:00", "Brewster", "false"))
    tel, rule, active = telecom_matrix(out, evs, 0.8, 8)
    assert rule["Orleans"].tolist() == ["observed"] * 2 + ["none"] * 10  # Cape-wide never flips a town
    assert rule["Brewster"].tolist() == ["observed"] * 2 + ["none"] * 5 + ["modeled"] * 5
    assert tel["Brewster"].tolist() == [1, 1] + [0] * 5 + [1] * 5
    assert active[(hours[0], "Orleans")] == ["tel_01", "tel_02"]
    assert active[(hours[7], "Brewster")] == ["tel_03"] and active[(hours[7], "Orleans")] == []
    # Same event marked both when the modeled rule also holds
    tel2, rule2, _ = telecom_matrix(out, _events(("2026-02-23T08:00", "", "Brewster", "true")), 0.8, 8)
    assert rule2.loc[hours[7], "Brewster"] == "both"


def test_pins_and_export_keep_every_curated_event():
    evs = parse_events(EVENTS_CSV, 12)
    assert not any(e.drives_reach_flag for e in evs)
    lp = {t: (-70.0, 41.7) for e in evs for t in e.matched}
    rec = [export_event(e, lp) for e in evs]
    assert len(rec) == len(pd.read_csv(EVENTS_CSV))
    cape = [r for r in rec if not r["matched_towns"]]
    assert cape and all(len(r["pins"]) == 1 and r["pins"][0]["kind"] == "cape_wide"
                        and (r["pins"][0]["lon"], r["pins"][0]["lat"]) == CAPE_WIDE_MARKER
                        and r["town_or_area"] in r["pins"][0]["caption"] for r in cape)
    bo = next(r for r in rec if r["town_or_area"] == "Brewster;Orleans")
    assert [p["town"] for p in bo["pins"]] == ["Brewster", "Orleans"]
    assert bo["end_assumed"] and bo["end_label"] == PROVENANCE["observed_default"] and bo["end_local"] is None
