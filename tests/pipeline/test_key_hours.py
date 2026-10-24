"""Key-hour channel report (step 10): Req 11.16, 11.17, 11.19."""
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pipeline.common import HOURS, ConfigError
from pipeline.lifelines import MIXED_ADJUST, MIXED_OK, format_key_hour_report, key_hour_report

GEOIDS = [f"25001{i:06d}" for i in range(6)]
TOWNS = ["Barnstable", "Chatham", "Falmouth"]


def _frame(chans):
    """channel DataFrame (HOURS x GEOIDS) with every hour set to the given per-geoid channels."""
    return pd.DataFrame([chans] * len(HOURS), index=HOURS, columns=GEOIDS)


def _queue(hours, geoids, towns):
    return {h: [{"rank": i + 1, "geoid": g, "town": t} for i, (g, t) in enumerate(zip(geoids, towns))]
            for h in hours}


def test_counts_towns_and_mixed_flag():
    h = HOURS[10]
    chan = _frame(["sms", "door_knock", "sms", "door_knock", "sms", "sms"])
    q = _queue([h], GEOIDS[:4], ["Falmouth", "Chatham", "Barnstable", "Chatham"])
    rep = key_hour_report(q, chan, [h])
    assert rep["hours"][h] == {"sms": {"count": 2, "towns": ["Barnstable", "Falmouth"]},
                               "door_knock": {"count": 2, "towns": ["Chatham"]}}
    assert rep["has_mixed_hour"] is True
    text = format_key_hour_report(rep)
    assert text.splitlines()[0] == "Key-hour channels"
    assert text.endswith(MIXED_OK)


def test_no_mixed_hour_prints_adjust():
    h = HOURS[0]
    rep = key_hour_report(_queue([h], GEOIDS[:2], TOWNS[:2]), _frame(["sms"] * 6), [h])
    assert rep["has_mixed_hour"] is False
    assert rep["hours"][h]["door_knock"] == {"count": 0, "towns": []}
    assert format_key_hour_report(rep).endswith(MIXED_ADJUST)


def test_key_hour_outside_demo_window_raises():
    with pytest.raises(ConfigError):
        key_hour_report({}, _frame(["sms"] * 6), ["2026-03-01T09:00"])


@settings(max_examples=100, deadline=None)
@given(data=st.data())
def test_report_matches_naive_recount(data):
    """Property 27 (report part): counts and town sets equal a naive recount; has_mixed_hour iff both > 0.
    **Validates: Requirements 11.16, 11.17, 11.19**"""
    keys = data.draw(st.lists(st.sampled_from(HOURS), min_size=1, max_size=5, unique=True))
    chan = pd.DataFrame(data.draw(st.lists(st.lists(st.sampled_from(["sms", "door_knock"]), min_size=6, max_size=6),
                                           min_size=len(HOURS), max_size=len(HOURS))), index=HOURS, columns=GEOIDS)
    queue = {}
    for h in keys:
        gs = data.draw(st.lists(st.sampled_from(GEOIDS), max_size=6, unique=True))
        queue[h] = [{"geoid": g, "town": data.draw(st.sampled_from(TOWNS))} for g in gs]
    rep = key_hour_report(queue, chan, keys)
    mixed = False
    for h in keys:
        for c in ("sms", "door_knock"):
            rows = [r for r in queue[h] if chan.at[h, r["geoid"]] == c]
            assert rep["hours"][h][c] == {"count": len(rows), "towns": sorted({r["town"] for r in rows})}
        mixed |= rep["hours"][h]["sms"]["count"] > 0 and rep["hours"][h]["door_knock"]["count"] > 0
    assert rep["has_mixed_hour"] == mixed
