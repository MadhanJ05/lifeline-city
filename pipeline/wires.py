"""Downed wires: Tab 5 urgent wire calls -> town-hour counts, rate per 1,000 customers, percentile (Req 5).

Step outputs in ctx (town-hour arrays only, no call rows or street text, Req 5.7):
  wires_counts  int DataFrame, index HOURS, columns CAPE_TOWNS: calls received in that Hour
  wires_raw     float DataFrame like wires_counts: calls received before hour_end(h) per 1,000 customers
  wires         float DataFrame like wires_counts: pct_rank of wires_raw across the 15 towns, in (0, 1]
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

import numpy as np
import pandas as pd

from pipeline.common import CAPE_TOWNS, HOURS, TZ, PipelineError, hour_end, hour_key, match_town, pct_rank
from pipeline.outage_curves import open_workbook

TAB5_SHEET = "Tab 5"
TAB5_FIRST_ROW = 5          # header is row 4
EXPECTED_CAPE_CALLS = 1_082  # sanity check, logged only
# Columns read (1-based): C town, D priority, E received, H repaired. G (a formula string) and the rest are not read.
_COLS = {"town": 3, "priority": 4, "received": 5, "repaired": 8}


@dataclass
class WiresResult:
    counts: pd.DataFrame
    raw: pd.DataFrame
    pct: pd.DataFrame
    cape_calls: int
    unmatched: Counter = field(default_factory=Counter)  # non-Cape town name -> call count
    blank_received: int = 0                               # Cape calls with no received time


def _ts(v: Any) -> datetime | None:
    """Received/repair cell -> tz-aware local datetime, or None when blank. Naive values are local."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if not isinstance(v, datetime):
        try:
            v = pd.Timestamp(v).to_pydatetime()
        except (TypeError, ValueError) as e:
            raise PipelineError(f"Tab 5: unparseable timestamp {v!r}") from e
    return v.replace(tzinfo=TZ) if v.tzinfo is None else v.astimezone(TZ)


def tab5_calls(wb) -> pd.DataFrame:
    """One row per Tab_5_Call from row 5 on, columns town, priority, received, repaired. Blank rows skipped."""
    if TAB5_SHEET not in wb.sheetnames:
        raise PipelineError(f"Eversource_Workbook has no sheet {TAB5_SHEET!r}")
    rows = []
    for r in wb[TAB5_SHEET].iter_rows(min_row=TAB5_FIRST_ROW, max_col=max(_COLS.values()), values_only=True):
        cells = {k: r[i - 1] if len(r) >= i else None for k, i in _COLS.items()}
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in cells.values()):
            continue
        cells["received"], cells["repaired"] = _ts(cells["received"]), _ts(cells["repaired"])
        rows.append(cells)
    return pd.DataFrame(rows, columns=list(_COLS))


def _count(n: Any) -> float:
    """Customers record or plain number -> customer count."""
    return float(getattr(n, "count", n))


def aggregate(calls: pd.DataFrame, N: Mapping[str, Any]) -> WiresResult:
    """Town-hour counts, cumulative rate per 1,000 customers and per-hour percentile rank (Req 5.1 to 5.6)."""
    unmatched: Counter = Counter()
    received: dict[str, list[datetime]] = {t: [] for t in CAPE_TOWNS}
    blank = 0
    for town, ts in zip(calls["town"], calls["received"]):
        t = match_town(town)
        if t is None:
            unmatched[str(town).strip() if town is not None else "(blank)"] += 1
        elif ts is None or pd.isna(ts):
            blank += 1
        else:
            received[t].append(ts)

    ends = np.array([hour_end(h).timestamp() for h in HOURS])
    counts = pd.DataFrame(0, index=HOURS, columns=list(CAPE_TOWNS), dtype=int)
    cum = pd.DataFrame(0, index=HOURS, columns=list(CAPE_TOWNS), dtype=int)
    for t, tss in received.items():
        for k, n in Counter(hour_key(ts) for ts in tss).items():
            if k in counts.index:
                counts.loc[k, t] = n
        secs = np.sort([ts.timestamp() for ts in tss])
        cum[t] = np.searchsorted(secs, ends, side="left")  # received < hour_end(h); earlier calls included

    for t in CAPE_TOWNS:
        if not _count(N[t]) > 0:
            raise PipelineError(f"wires: town {t} has no customer count")
    raw = cum.astype(float) * 1000.0 / pd.Series({t: _count(N[t]) for t in CAPE_TOWNS})
    pct = raw.apply(pct_rank, axis=1)  # across the 15 towns at each Hour (Req 5.6)
    return WiresResult(counts, raw, pct, sum(len(v) for v in received.values()) + blank, unmatched, blank)


def step(ctx) -> None:
    res = aggregate(tab5_calls(open_workbook()), ctx["customers"])
    ctx["wires_counts"] = res.counts
    ctx["wires_raw"] = res.raw
    ctx["wires"] = res.pct
    for name, n in sorted(res.unmatched.items(), key=lambda kv: (-kv[1], kv[0])):
        ctx.source("wires_unmatched", town=name, calls=n, reason="Not a Cape town (Req 5.3)")
    if res.blank_received:
        ctx.source("wires_unmatched", town=None, calls=res.blank_received, reason="Cape call with blank received time")
    top = res.raw.iloc[-1].sort_values(ascending=False).head(3)
    print(f"       wires: {res.cape_calls:,} Cape calls (expected about {EXPECTED_CAPE_CALLS:,}); "
          f"{sum(res.unmatched.values()):,} non-Cape calls in {len(res.unmatched)} towns; "
          f"blank received {res.blank_received}; top per 1k: "
          + ", ".join(f"{t} {v:.1f}" for t, v in top.items()))
