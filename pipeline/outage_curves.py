"""Town outage curves: Tab 3 curve, Anchors, town customer counts, shaping and scaling (Req 3.1 to 3.3, 4).

Step outputs in ctx:
  customers         {town: Customers}
  cape_total        Series on HOURS (Cape_Total_Curve, customers out)
  out_pct           DataFrame, index HOURS, columns CAPE_TOWNS, values in [0, 1]
  pinned            bool DataFrame like out_pct (Pinned_Town_Hours)
  lower_bound       float DataFrame like out_pct (lower-bound pct, NaN where none)
  unmatched_hours   {hour: unmatched customers}
  provenance_out_pct  PROVENANCE["reconstructed"], for out_pct and hours_dark (Req 4.16)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import openpyxl
import pandas as pd

from pipeline.common import (CAPE_TOWNS, HOURS, PROVENANCE, RAW, ROOT, TZ, PipelineError, hour_key,
                             match_town, normalize)

WORKBOOK = RAW / "eversource_dpu_25-ERP-10" / "eversource_final_event_report_tabs.xlsx"
ANCHORS_CSV = RAW / "curated" / "cape_town_outage_anchors.csv"
TIMELINE_CSV = RAW / "curated" / "cape_total_outage_timeline.csv"

TAB3_SHEET = "Tab 3"
TAB3_HEADER = ("Date", "Time", "Customers Outages", "Customers Restored")
TAB3_PEAK = 269_063
TAB3_PEAK_HOUR = "2026-02-23T08:00"

CUSTOMER_ANCHOR_TIME = "2026-02-23T12:30"
CUSTOMER_ANCHOR_SOURCE = "MEMA via Patch"
ACS_SOURCE = "ACS B25001 housing units (county subdivision)"

SITREP_009_REASON = "County situation report #009 (2026-02-26) customers-out figure excluded (Req 4.15)"
NOT_CAPE_REASON = "Not a Barnstable County town (Req 3.1)"
NO_VALUE_REASON = "Anchor has neither customers_out nor pct_out"


# ---------------------------------------------------------------- records


@dataclass(frozen=True)
class Exclusion:
    """One input row left out of every computation. Never carries the excluded value."""
    file: str
    row: int
    reason: str


@dataclass(frozen=True)
class Customers:
    count: float
    source: str
    label: str | None  # PROVENANCE["acs_customers"] for the ACS fallback, else None


@dataclass(frozen=True)
class Anchor:
    town: str
    ts: datetime          # local timestamp of the report
    hour: str             # Hour key containing ts
    pct: float            # out share in [0, 1]
    lower_bound: bool     # pct_is_lower_bound
    time_is_approx: bool
    source_name: str
    source_url: str
    row: int              # line number in the CSV (header is line 1)


# ---------------------------------------------------------------- Tab 3 (Req 1.9, 4.2, 4.3)


def open_workbook(path: Path = WORKBOOK):
    """Open the Eversource_Workbook read-only with cached values (never written, Req 1.9)."""
    try:
        return openpyxl.load_workbook(Path(path), read_only=True, data_only=True)
    except (OSError, KeyError, ValueError) as e:
        raise PipelineError(f"cannot open Eversource_Workbook {path}: {e}") from e


_LABEL = re.compile(r"^\s*(\d{1,2})\s*(AM|PM)\s*$", re.IGNORECASE)


def parse_time_label(label: str) -> int:
    """'12AM' -> 0, '1AM'..'11AM' -> 1..11, '12PM' -> 12, '1PM'..'11PM' -> 13..23."""
    m = _LABEL.match(str(label))
    if not m or not 1 <= int(m.group(1)) <= 12:
        raise PipelineError(f"Tab 3: unrecognised Time label {label!r}")
    h = int(m.group(1)) % 12
    return h + (12 if m.group(2).upper() == "PM" else 0)


def _num(v: Any) -> float:
    if v is None or (isinstance(v, str) and not v.strip()):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError) as e:
        raise PipelineError(f"Tab 3: non-numeric value {v!r}") from e


def tab3_raw(wb) -> pd.Series:
    """Tab_3_Curve on the Tab 3 Hours: running sum of (outages - restored), indexed by Hour key."""
    if TAB3_SHEET not in wb.sheetnames:
        raise PipelineError(f"Eversource_Workbook has no sheet {TAB3_SHEET!r} (sheets: {wb.sheetnames})")
    ws = wb[TAB3_SHEET]
    header = next(ws.iter_rows(min_row=4, max_row=4, values_only=True), ())
    if tuple(str(c).strip() if c is not None else None for c in header[:4]) != TAB3_HEADER:
        raise PipelineError(f"Tab 3 row 4 header is {header[:4]}, expected {TAB3_HEADER}")
    keys: list[str] = []
    net: list[float] = []
    for r in ws.iter_rows(min_row=5, max_col=4, values_only=True):
        date, label, outages, restored = (tuple(r) + (None,) * 4)[:4]
        if date is None or label is None:  # blank rows and the unlabeled totals row
            continue
        if not isinstance(date, datetime):
            raise PipelineError(f"Tab 3: Date {date!r} is not a date")
        ts = datetime(date.year, date.month, date.day, parse_time_label(label), tzinfo=TZ)
        keys.append(hour_key(ts))
        net.append(_num(outages) - _num(restored))
    if not keys:
        raise PipelineError("Tab 3 has no data rows")
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise PipelineError("Tab 3 Hours are duplicated or out of order")
    return pd.Series(net, index=keys, dtype=float).cumsum()


def tab3_curve(wb) -> pd.Series:
    """Tab_3_Curve on the HOURS grid; stops unless the peak is 269,063 at 2026-02-23T08:00 (Req 4.3)."""
    raw = tab3_raw(wb)
    peak, peak_hour = float(raw.max()), str(raw.idxmax())
    if peak != TAB3_PEAK or peak_hour != TAB3_PEAK_HOUR:
        raise PipelineError(f"Tab 3 peak is {peak:,.0f} at {peak_hour}; expected {TAB3_PEAK:,} at {TAB3_PEAK_HOUR}")
    first, last = raw.index[0], raw.index[-1]
    out = raw.reindex(HOURS)
    out[[h < first for h in HOURS]] = 0.0               # before the first Tab 3 Hour
    out[[h > last for h in HOURS]] = float(raw.iloc[-1])  # after the last: hold the last value
    return out.ffill().astype(float)


# ---------------------------------------------------------------- Anchors (Req 3.1, 4.13 to 4.15)

_SITREP_009 = re.compile(r"(situation report|sitrep)\s*(no\.?|#)?\s*0*9\b")


def is_sitrep_009(row: Mapping[str, Any]) -> bool:
    """True for the county situation report #009 (2026-02-26) customers-out figure (Req 4.15).

    Matched by source (name or note) so the value itself is never needed downstream.
    """
    text = normalize(f"{row.get('source_name', '') or ''} {row.get('note', '') or ''}")
    if _SITREP_009.search(text):
        return True
    co = row.get("customers_out")
    day = str(row.get("datetime_local", ""))[:10]
    return day == "2026-02-26" and _is_num(co) and float(co) == 133_000


def _is_num(v: Any) -> bool:
    if v is None or isinstance(v, bool):
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _truthy(v: Any) -> bool:
    return str(v).strip().casefold() in ("true", "1", "yes", "y")


def read_anchor_rows(csv: Path = ANCHORS_CSV, excluded: list[Exclusion] | None = None) -> pd.DataFrame:
    """Barnstable County Cape-town Anchor rows, sitrep #009 removed. Adds `row` (CSV line) and canonical `town`."""
    csv = Path(csv)
    try:
        df = pd.read_csv(csv, dtype={"datetime_local": str, "town": str, "county": str})
    except (OSError, pd.errors.ParserError) as e:
        raise PipelineError(f"cannot read {csv}: {e}") from e
    need = {"town", "county", "datetime_local", "customers_out", "pct_out", "pct_is_lower_bound",
            "time_is_approx", "source_name", "source_url"}
    if need - set(df.columns):
        raise PipelineError(f"{csv.name} is missing columns {sorted(need - set(df.columns))}")
    df = df.assign(row=df.index + 2)
    keep = []
    for i, r in df.iterrows():
        town = match_town(r["town"])
        if normalize(r["county"]) != "barnstable" or town is None:
            _note(excluded, csv, int(r["row"]), NOT_CAPE_REASON)
        elif is_sitrep_009(r):
            _note(excluded, csv, int(r["row"]), SITREP_009_REASON)
        else:
            df.at[i, "town"] = town
            keep.append(i)
    return df.loc[keep].reset_index(drop=True)


def _note(excluded: list[Exclusion] | None, csv: Path, row: int, reason: str) -> None:
    if excluded is not None:
        excluded.append(Exclusion(file=_rel(csv), row=row, reason=reason))


def _rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return Path(path).name


def _parse_ts(s: str, csv: Path, row: int) -> datetime:
    try:
        return datetime.fromisoformat(str(s).strip()).replace(tzinfo=TZ)
    except ValueError as e:
        raise PipelineError(f"{csv.name} row {row}: bad datetime_local {s!r}") from e


def load_anchors(csv: Path, N: Mapping[str, Customers | float],
                 excluded: list[Exclusion] | None = None) -> list[Anchor]:
    """Anchors for the 15 Cape_Towns with pct in [0, 1].

    pct = pct_out / 100 when present (4.14), else customers_out / N[T] (4.13).
    """
    csv = Path(csv)
    out: list[Anchor] = []
    for _, r in read_anchor_rows(csv, excluded).iterrows():
        town, row = r["town"], int(r["row"])
        if _is_num(r["pct_out"]):
            pct = float(r["pct_out"]) / 100
        elif _is_num(r["customers_out"]):
            n = N[town].count if isinstance(N[town], Customers) else float(N[town])
            if not n > 0:
                raise PipelineError(f"{town}: customer count must be positive to convert row {row}")
            pct = float(r["customers_out"]) / n
        else:
            _note(excluded, csv, row, NO_VALUE_REASON)
            continue
        ts = _parse_ts(r["datetime_local"], csv, row)
        out.append(Anchor(town=town, ts=ts, hour=hour_key(ts), pct=min(max(pct, 0.0), 1.0),
                          lower_bound=_truthy(r["pct_is_lower_bound"]),
                          time_is_approx=_truthy(r["time_is_approx"]),
                          source_name=str(r["source_name"]), source_url=str(r["source_url"]), row=row))
    return out


# ---------------------------------------------------------------- customers (Req 3.2, 3.3)


def town_customers(anchors_raw: pd.DataFrame, acs_housing: Mapping[str, float]) -> dict[str, Customers]:
    """Customer count per Cape_Town.

    `anchors_raw` is `read_anchor_rows(...)`; `acs_housing` maps town -> ACS B25001 housing units.
    Prefer the 2026-02-23T12:30 "MEMA via Patch" row: customers_out / (pct_out / 100) (3.2).
    Else the first Anchor with both fields; else ACS housing units, labeled acs_customers (3.3).
    """
    both = anchors_raw[anchors_raw["customers_out"].map(_is_num) & anchors_raw["pct_out"].map(_is_num)]
    both = both[both["pct_out"].astype(float) > 0]
    out: dict[str, Customers] = {}
    for town in CAPE_TOWNS:
        rows = both[both["town"] == town]
        mema = rows[(rows["datetime_local"].str.strip() == CUSTOMER_ANCHOR_TIME)
                    & (rows["source_name"].str.strip() == CUSTOMER_ANCHOR_SOURCE)]
        pick = mema if len(mema) else rows.sort_values(["datetime_local", "row"])
        if len(pick):
            r = pick.iloc[0]
            count = float(r["customers_out"]) / (float(r["pct_out"]) / 100)
            out[town] = Customers(count=count, label=None,
                                  source=f"{r['source_name']} {r['datetime_local']} (anchors row {int(r['row'])})")
            continue
        units = acs_housing.get(town)
        if not _is_num(units) or float(units) <= 0:
            raise PipelineError(f"{town}: no Anchor with customers_out and pct_out, and no ACS housing units")
        out[town] = Customers(count=float(units), source=ACS_SOURCE, label=PROVENANCE["acs_customers"])
    return out


# ---------------------------------------------------------------- shaping (Req 4.4, 4.7 to 4.10)


def ratio_shape(base: pd.Series, knots: list[tuple[str, float]]) -> pd.Series:
    """Curve through every knot that follows `base` between and beyond the knots.

    rho_i = v_i / base(h_i); rho is piecewise-linear (in hours) between consecutive knots and constant
    before the first and after the last; result = base * rho. In a segment where base is 0 at a knot,
    v is interpolated linearly instead (and held constant beyond such an end knot).
    Knots at the same hour: the last one in the list wins. `base` is indexed by Hour keys.
    """
    if not knots:
        raise ValueError("ratio_shape needs at least one knot")
    pos = {h: i for i, h in enumerate(base.index)}
    by_pos: dict[int, float] = {}
    for h, v in knots:
        if h not in pos:
            raise PipelineError(f"knot hour {h} is outside the Demo_Window")
        by_pos[pos[h]] = float(v)
    ks = sorted(by_pos)
    b = base.to_numpy(dtype=float)
    out = np.empty_like(b)
    idx = np.arange(len(b))

    def rho(k: int) -> float | None:
        return by_pos[k] / b[k] if b[k] > 0 else None

    first, last = ks[0], ks[-1]
    r0, rn = rho(first), rho(last)
    out[:first + 1] = b[:first + 1] * r0 if r0 is not None else by_pos[first]
    out[last:] = b[last:] * rn if rn is not None else by_pos[last]
    for a, c in zip(ks, ks[1:]):
        seg = idx[a:c + 1]
        t = (seg - a) / (c - a)
        ra, rc = rho(a), rho(c)
        if ra is None or rc is None:
            out[a:c + 1] = by_pos[a] + t * (by_pos[c] - by_pos[a])
        else:
            out[a:c + 1] = b[a:c + 1] * (ra + t * (rc - ra))
    for k in ks:  # exact at every knot
        out[k] = by_pos[k]
    return pd.Series(out, index=base.index, dtype=float)


def read_cape_rows(csv: Path = TIMELINE_CSV, excluded: list[Exclusion] | None = None) -> list[tuple[str, float]]:
    """(Hour key, customers_out) knots from scope == "cape_eversource" rows; sitrep #009 dropped (4.4, 4.15).

    A timestamp inside an Hour (e.g. 16:15) is a knot at that Hour key; a later row in the same Hour wins.
    """
    csv = Path(csv)
    try:
        df = pd.read_csv(csv, dtype={"datetime_local": str, "scope": str})
    except (OSError, pd.errors.ParserError) as e:
        raise PipelineError(f"cannot read {csv}: {e}") from e
    if {"datetime_local", "customers_out", "scope"} - set(df.columns):
        raise PipelineError(f"{csv.name} needs datetime_local, customers_out and scope columns")
    df = df.assign(row=df.index + 2)
    rows = []
    for _, r in df[df["scope"].str.strip() == "cape_eversource"].iterrows():
        if is_sitrep_009(r):
            _note(excluded, csv, int(r["row"]), SITREP_009_REASON)
            continue
        if not _is_num(r["customers_out"]):
            raise PipelineError(f"{csv.name} row {int(r['row'])}: customers_out is not a number")
        ts = _parse_ts(r["datetime_local"], csv, int(r["row"]))
        rows.append((ts, hour_key(ts), float(r["customers_out"])))
    if not rows:
        raise PipelineError(f"{csv.name} has no cape_eversource rows")
    return [(h, v) for _, h, v in sorted(rows)]


def cape_total(tab3: pd.Series, rows: list[tuple[str, float]]) -> pd.Series:
    """Cape_Total_Curve: the cape_eversource knots shaped by the Tab_3_Curve (Req 4.4)."""
    return ratio_shape(tab3, rows).clip(lower=0.0)


def town_knots(town: str, anchors: list[Anchor]) -> list[tuple[str, float]]:
    """One knot per Hour from the town's Anchors: exact beats lower-bound, then the latest timestamp."""
    best: dict[str, Anchor] = {}
    for a in anchors:
        if a.town != town:
            continue
        cur = best.get(a.hour)
        if cur is None or (not a.lower_bound, a.ts) > (not cur.lower_bound, cur.ts):
            best[a.hour] = a
    return [(h, best[h].pct) for h in sorted(best)]


def unscaled(town: str, anchors: list[Anchor], share: pd.Series) -> pd.Series:
    """Unscaled out_pct for one town. `share` = Cape_Total_Curve / total Cape customers.

    No Anchors (Chatham): the Cape-wide share (4.10). Otherwise the share shaped through every Anchor
    (4.7, 4.8); one Anchor gives a * C(h) / C(h_a) (4.9). Clipped to [0, 1].
    """
    knots = town_knots(town, anchors)
    curve = ratio_shape(share, knots) if knots else share
    return curve.clip(0.0, 1.0)


# ---------------------------------------------------------------- scaling (Req 4.5, 4.6, 4.11, 4.12)

MATCH_TOL = 0.5  # customers; an hour within this of the Cape total counts as matched


def scale_hour(h: str, u: Mapping[str, float], N: Mapping[str, float], pinned: Mapping[str, float],
               lb: Mapping[str, float], C: Mapping[str, float] | pd.Series) -> tuple[dict[str, float], float]:
    """out_pct at Hour h for every town in N, and the unmatched customers (0 when matched).

    Pinned towns keep their Anchor pct (4.5). Free towns' customers out y = u*N are scaled by one factor s,
    each clipped to [lb*N, N] (4.6, 4.11); s is bisected so the town sum equals C[h]. When that is
    impossible, s goes to the nearest end and unmatched = C[h] - sum (4.12).
    """
    R = float(C[h]) - sum(pinned[t] * N[t] for t in pinned)
    free = [t for t in N if t not in pinned]
    y = np.array([max(float(u[t]), 0.0) * N[t] for t in free])
    hi = np.array([float(N[t]) for t in free])
    lo = np.array([min(max(float(lb.get(t, 0.0) or 0.0), 0.0), 1.0) * N[t] for t in free])

    def g(s: float) -> float:
        return float(np.clip(s * y, lo, hi).sum())

    y[y < 1e-9] = 0.0  # sub-customer amounts: avoid overflow in hi / y
    pos = y > 0
    s_max = float((hi[pos] / y[pos]).max()) if pos.any() else 0.0
    g0, ginf = g(0.0), g(s_max)
    if R < g0 - MATCH_TOL:
        s = 0.0
    elif R > ginf + MATCH_TOL:
        s = s_max
    else:
        a, b = 0.0, s_max
        for _ in range(60):
            m = (a + b) / 2
            a, b = (m, b) if g(m) < R else (a, m)
        s = (a + b) / 2
    vals = np.clip(s * y, lo, hi)
    out = {t: float(pinned[t]) for t in pinned}
    out.update({t: float(v / N[t]) for t, v in zip(free, vals)})
    total = sum(out[t] * N[t] for t in N)
    unmatched = float(C[h]) - total
    return out, (unmatched if abs(unmatched) > MATCH_TOL else 0.0)


def pins_and_bounds(anchors: list[Anchor]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pinned pct (exact Anchors, latest in the Hour wins) and lower-bound pct (highest in the Hour), NaN elsewhere."""
    pin = pd.DataFrame(np.nan, index=HOURS, columns=list(CAPE_TOWNS))
    lb = pin.copy()
    latest: dict[tuple[str, str], datetime] = {}
    for a in sorted(anchors, key=lambda a: a.ts):
        if a.hour not in pin.index:
            continue
        if a.lower_bound:
            prev = lb.at[a.hour, a.town]
            lb.at[a.hour, a.town] = a.pct if pd.isna(prev) else max(prev, a.pct)
        elif (a.town, a.hour) not in latest or a.ts >= latest[(a.town, a.hour)]:
            latest[(a.town, a.hour)] = a.ts
            pin.at[a.hour, a.town] = a.pct
    return pin, lb


def step(ctx) -> None:
    excluded: list[Exclusion] = []
    raw = read_anchor_rows(ANCHORS_CSV, excluded)
    N = town_customers(raw, ctx["town_housing_units"])
    anchors = load_anchors(ANCHORS_CSV, N, [])  # exclusions already recorded by read_anchor_rows above
    knots = read_cape_rows(TIMELINE_CSV, excluded)
    C = cape_total(tab3_curve(open_workbook()), knots)

    n = {t: N[t].count for t in CAPE_TOWNS}
    share = C / sum(n.values())
    U = pd.DataFrame({t: unscaled(t, anchors, share) for t in CAPE_TOWNS}, index=HOURS)
    pin, lb = pins_and_bounds(anchors)

    out = pd.DataFrame(np.nan, index=HOURS, columns=list(CAPE_TOWNS))
    unmatched: dict[str, float] = {}
    for h in HOURS:
        p = {t: v for t, v in pin.loc[h].items() if pd.notna(v)}
        b = {t: v for t, v in lb.loc[h].items() if pd.notna(v)}
        vals, um = scale_hour(h, U.loc[h].to_dict(), n, p, b, C)
        out.loc[h] = pd.Series(vals)
        if um:
            unmatched[h] = um

    ctx["customers"] = N
    ctx["anchors"] = anchors
    ctx["cape_total"] = C
    ctx["out_pct"] = out.astype(float)
    ctx["pinned"] = pin.notna()
    ctx["lower_bound"] = lb
    ctx["unmatched_hours"] = unmatched
    ctx["provenance_out_pct"] = PROVENANCE["reconstructed"]

    for e in excluded:
        ctx.source("exclusions", file=e.file, row=e.row, reason=e.reason)
    for t in CAPE_TOWNS:
        c = N[t]
        ctx.source("town_customers", town=t, count=round(c.count), source=c.source, label=c.label)
        if not any(a.town == t for a in anchors):
            ctx.source("towns_without_anchors", town=t,
                       note="No Anchors: unscaled out_pct is the Cape-wide share (Req 4.10)")
    for h, um in unmatched.items():
        ctx.source("unmatched_hours", hour=h, unmatched_customers=round(um))
    ctx.source("provenance", fields=["out_pct", "hours_dark"], label=PROVENANCE["reconstructed"])

    print(f"       outage_curves: Cape peak {C.max():,.0f} at {C.idxmax()}; {len(anchors)} anchors, "
          f"{int(pin.notna().sum().sum())} pinned town-hours; unmatched hours {len(unmatched)}")
