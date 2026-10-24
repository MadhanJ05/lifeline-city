"""Unit tests for pipeline/lifelines.py: hours_dark, lifelines, channel, queue order and Why_Chips."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import given, strategies as st

from pipeline.lifelines import build_queue, channel, hours_dark, lifelines, priority, why_chips

W = {"out_pct": 0.4, "hours_dark": 0.3, "wires": 0.1, "telecom": 0.2}


def test_hours_dark_literal_reading_and_cap():
    out = np.array([0.1, 0.5, 0.7, 0.4, 0.6] + [0.9] * 80)
    hd = hours_dark(out, 0.5, 72)
    assert hd[:5].tolist() == [0, 0, 1, 0, 3]  # counted from the first Hour at or above 0.5; 0 when below
    assert hd.max() == 72 and hours_dark(np.zeros(4), 0.5, 72).tolist() == [0, 0, 0, 0]


def test_lifelines_weighted_sum_and_contributions():
    total, c = lifelines(np.array([0.5]), np.array([144]), np.array([0.25]), np.array([1]), W, 72)
    assert np.isclose(total[0], 0.4 * 0.5 + 0.3 * 1 + 0.1 * 0.25 + 0.2)
    assert np.isclose(sum(v[0] for v in c.values()), total[0])


def test_channel():
    assert channel([0, 1, 0]).tolist() == ["sms", "door_knock", "sms"]


def test_build_queue_ties_by_need_then_geoid():
    q = build_queue([0.5, 0.5, 0.5, 0.9], [0.6, 0.7, 0.7, 0.1], ["003", "002", "001", "004"], 3)
    assert [r["geoid"] for r in q] == ["004", "001", "002"] and [r["rank"] for r in q] == [1, 2, 3]


def test_why_chips_values_come_from_metrics():
    m = {"need.seniors_alone.pct": 0.92, "need.renter.pct": 0.5, "out_pct": 0.82, "hours_dark": 40.0,
         "wires": 0.85, "telecom": 1.0, "contrib.out_pct": 0.328, "contrib.hours_dark": 0.1667,
         "contrib.wires": 0.085, "contrib.telecom": 0.2}
    a, b = why_chips(m)
    assert a == {"text": "Seniors living alone, 92nd percentile", "field": "need.seniors_alone.pct", "value": 0.92}
    assert b == {"text": "82% without power", "field": "out_pct", "value": 0.82}
    m["contrib.hours_dark"] = 0.5
    assert why_chips(m)[1]["text"] == "Dark 40 hours"
    m["contrib.telecom"] = 0.6
    assert why_chips(m, "modeled")[1] == {"text": "Phones likely degraded (Modeled)", "field": "telecom", "value": 1.0}


# Feature: lifeline-city, Property 1: Lifelines and priority stay in [0, 1]
EPS = 1e-12
unit = st.floats(0, 1, allow_nan=False)


@st.composite
def lifelines_case(draw):
    raw = draw(st.lists(unit, min_size=4, max_size=4).filter(lambda r: sum(r) > 0))
    w = dict(zip(("out_pct", "hours_dark", "wires", "telecom"), (x / sum(raw) for x in raw)))
    cap = draw(st.floats(1e-3, 200, allow_nan=False))
    n_h, towns = draw(st.integers(1, 30)), [f"T{i}" for i in range(draw(st.integers(1, 4)))]
    col = lambda s: draw(st.lists(s, min_size=n_h, max_size=n_h))  # noqa: E731
    out = pd.DataFrame({T: col(unit) for T in towns})
    if draw(st.booleans()):  # derived from the out_pct series, like the step
        thr = draw(unit)
        hd = pd.DataFrame({T: hours_dark(out[T].to_numpy(), thr, cap) for T in towns})
    else:  # any hours_dark >= 0, including values far above cap
        hd = pd.DataFrame({T: col(st.integers(0, 1000)) for T in towns})
    wires = pd.DataFrame({T: col(unit) for T in towns})
    tel = pd.DataFrame({T: col(st.integers(0, 1)) for T in towns})
    geoids = [f"G{i:03d}" for i in range(draw(st.integers(1, 6)))]
    need_t = pd.Series([draw(unit) for _ in geoids], index=geoids)
    town_of = pd.Series([draw(st.sampled_from(towns)) for _ in geoids], index=geoids)
    return w, cap, out, hd, wires, tel, need_t, town_of


@pytest.mark.required_pbt
@given(lifelines_case())
def test_property_1_lifelines_and_priority_in_unit_interval(case):
    """**Validates: Requirements 7.3, 7.4, 7.5, 30.1**"""
    w, cap, out, hd, wires, tel, need_t, town_of = case
    total, contrib = lifelines(out, hd, wires, tel, w, cap)

    expected = (w["out_pct"] * out + w["hours_dark"] * np.minimum(hd / cap, 1)
                + w["wires"] * wires + w["telecom"] * tel)
    assert np.allclose(total.to_numpy(), expected.to_numpy(), rtol=0, atol=EPS)
    assert np.allclose(total.to_numpy(), sum(c.to_numpy() for c in contrib.values()), rtol=0, atol=EPS)
    assert (total.to_numpy() >= -EPS).all() and (total.to_numpy() <= 1 + EPS).all()

    prio = priority(need_t, town_of, total)
    assert list(prio.columns) == list(need_t.index)
    for g in need_t.index:
        assert np.allclose(prio[g].to_numpy(), need_t[g] * total[town_of[g]].to_numpy(), rtol=0, atol=EPS)
    assert (prio.to_numpy() >= -EPS).all() and (prio.to_numpy() <= 1 + EPS).all()
