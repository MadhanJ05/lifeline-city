"""Telecom flag: modeled tower-backup rule plus observed events from the curated CSV (Req 6, 8.4).

Rules: .kiro/steering/scoring.md. Only events with drives_reach_flag = true may set telecom (none do in the
curated data), so the modeled rule drives the channel; every event is kept as a map pin and briefing context.

Step outputs in ctx:
  telecom                int DataFrame, index HOURS, columns CAPE_TOWNS, 0/1 (observed | modeled)
  telecom_rule           str DataFrame like telecom: "none" | "observed" | "modeled" | "both"
  telecom_active_events  {(hour, town): [event id, ...]}: events active at the hour for the town, plus events
                         that match no town (Cape-wide context, shown for every town)
  telecom_events         list of dicts for telecom_events.json, one per CSV row
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pipeline.common import (CAPE_TOWNS, HOURS, PROVENANCE, RAW, TZ, PipelineError, hour_end, hour_start,
                             match_town)

EVENTS_CSV = RAW / "curated" / "cape_telecom_events.csv"
# Labeled marker for events that match no Cape town ("Cape-wide", "Outer Cape", county centers).
# Placed in Cape Cod Bay so it never reads as a town pin. (lon, lat), EPSG:4326.
CAPE_WIDE_MARKER = (-70.25, 41.85)
CAPE_WIDE_LABEL = "Cape-wide"
_FMT = "%Y-%m-%dT%H:%M"
_REQUIRED = ("start_local", "end_local", "town_or_area", "system", "status", "affects", "drives_reach_flag",
             "source_name", "source_url", "note")


@dataclass(frozen=True)
class TelecomEvent:
    id: str
    start: datetime
    end: datetime
    end_assumed: bool
    areas: tuple[str, ...]    # trimmed ";" parts of town_or_area
    matched: tuple[str, ...]  # parts that equal a Cape town name as a whole string (Req 6.5, 6.6)
    drives_reach_flag: bool
    row: dict[str, str]       # raw CSV fields, for export


def modeled(out_pct_T: np.ndarray, thr: float = 0.8, k: int = 8) -> np.ndarray:
    """m[i] = i >= k-1 and every out_pct in the k Hours ending at i is >= thr (in-window Hours only, Req 6.2)."""
    run = 0
    m = np.zeros(len(out_pct_T), dtype=bool)
    for i, v in enumerate(np.asarray(out_pct_T, dtype=float) >= thr):  # exact >=, no tolerance
        run = run + 1 if v else 0
        m[i] = run >= k
    return m


def _ts(s: str, field: str, row: int) -> datetime:
    try:
        return datetime.strptime(s.strip(), _FMT).replace(tzinfo=TZ)
    except ValueError as e:
        raise PipelineError(f"{EVENTS_CSV.name} row {row}: bad {field} {s!r}") from e


def _flag(s: str, row: int) -> bool:
    v = s.strip().casefold()
    if v not in ("true", "false"):
        raise PipelineError(f"{EVENTS_CSV.name} row {row}: drives_reach_flag must be true or false, got {s!r}")
    return v == "true"


def parse_events(csv: Path | pd.DataFrame, default_hours: int) -> list[TelecomEvent]:
    """One TelecomEvent per row. A blank end_local ends the event default_hours after start (Req 6.7)."""
    df = csv if isinstance(csv, pd.DataFrame) else pd.read_csv(csv, dtype=str, keep_default_na=False)
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise PipelineError(f"{EVENTS_CSV.name}: missing columns {missing}")
    events = []
    for i, r in enumerate(df.fillna("").astype(str).to_dict("records"), start=1):
        start = _ts(r["start_local"], "start_local", i)
        blank_end = not r["end_local"].strip()
        end = start + timedelta(hours=default_hours) if blank_end else _ts(r["end_local"], "end_local", i)
        areas = tuple(p.strip() for p in r["town_or_area"].split(";") if p.strip())
        matched = tuple(dict.fromkeys(t for t in map(match_town, areas) if t))
        events.append(TelecomEvent(f"tel_{i:02d}", start, end, blank_end, areas, matched,
                                   _flag(r["drives_reach_flag"], i), r))
    return events


def is_active(ev: TelecomEvent, h: str) -> bool:
    """Active_Event: starts before the end of Hour h and ends after its start."""
    return ev.start < hour_end(h) and ev.end > hour_start(h)


def telecom_matrix(out_pct: pd.DataFrame, events: list[TelecomEvent], thr: float = 0.8, k: int = 8
                   ) -> tuple[pd.DataFrame, pd.DataFrame, dict[tuple[str, str], list[str]]]:
    """telecom = observed | modeled, the rule that held, and active event ids per (hour, town) (Req 6.1 to 6.4)."""
    hours, towns = list(out_pct.index), list(out_pct.columns)
    mod = pd.DataFrame({t: modeled(out_pct[t].to_numpy(), thr, k) for t in towns}, index=hours)
    obs = pd.DataFrame(False, index=hours, columns=towns)
    active: dict[tuple[str, str], list[str]] = {(h, t): [] for h in hours for t in towns}
    for ev in events:
        for h in hours:
            if not is_active(ev, h):
                continue
            for t in ev.matched or towns:  # no matched town: Cape-wide context for every town, never a flag
                active[(h, t)].append(ev.id)
            if ev.drives_reach_flag:
                for t in ev.matched:
                    obs.loc[h, t] = True
    rule = pd.DataFrame(np.select([obs & mod, obs, mod], ["both", "observed", "modeled"], "none"),
                        index=hours, columns=towns)
    return (obs | mod).astype(int), rule, active


def pins(ev: TelecomEvent, label_points: dict[str, tuple[float, float]]) -> list[dict[str, Any]]:
    """One pin per matched town at its label point, else one labeled Cape-wide marker (Req 8.4)."""
    if ev.matched:
        return [{"kind": "town", "town": t, "caption": t, "lon": label_points[t][0], "lat": label_points[t][1]}
                for t in ev.matched]
    return [{"kind": "cape_wide", "town": None, "caption": ev.row["town_or_area"].strip(),
             "marker_label": CAPE_WIDE_LABEL, "lon": CAPE_WIDE_MARKER[0], "lat": CAPE_WIDE_MARKER[1]}]


def export_event(ev: TelecomEvent, label_points: dict[str, tuple[float, float]]) -> dict[str, Any]:
    """telecom_events.json record; every event is kept regardless of drives_reach_flag (Req 6.9)."""
    r = ev.row
    return {"id": ev.id, "system": r["system"], "status": r["status"], "affects": r["affects"],
            "start_local": r["start_local"].strip(), "end_local": r["end_local"].strip() or None,
            "end_effective": ev.end.strftime(_FMT), "end_assumed": ev.end_assumed,
            "end_label": PROVENANCE["observed_default"] if ev.end_assumed else None,
            "drives_reach_flag": ev.drives_reach_flag, "town_or_area": r["town_or_area"],
            "areas": list(ev.areas), "matched_towns": list(ev.matched),
            "source_name": r["source_name"], "source_url": r["source_url"], "note": r["note"] or None,
            "pins": pins(ev, label_points)}


def label_points(towns_gdf) -> dict[str, tuple[float, float]]:
    """Town polygon representative point (EPSG:4326), rounded to 4 dp."""
    g = towns_gdf.to_crs(4326)
    return {t: (round(p.x, 4), round(p.y, 4)) for t, p in zip(g["town"], g.geometry.representative_point())}


def step(ctx) -> None:
    s = ctx.scoring
    events = parse_events(EVENTS_CSV, s.telecom_observed_default_hours)
    out_pct = ctx["out_pct"].reindex(index=HOURS, columns=list(CAPE_TOWNS))
    tel, rule, active = telecom_matrix(out_pct, events, s.telecom_model.out_pct_threshold,
                                       s.telecom_model.consecutive_hours)
    lp = label_points(ctx["cape_towns"])
    ctx["telecom"] = tel
    ctx["telecom_rule"] = rule
    ctx["telecom_active_events"] = active
    ctx["telecom_events"] = [export_event(ev, lp) for ev in events]
    ctx["provenance_telecom_modeled"] = PROVENANCE["modeled_telecom"]
    on = tel.sum()
    matched = sorted({t for ev in events for t in ev.matched})
    print(f"       telecom: {len(events)} events ({sum(ev.drives_reach_flag for ev in events)} drive reach), "
          f"matched towns {matched}; telecom=1 town-hours {int(on.sum())}: "
          + (", ".join(f"{t} {int(n)}" for t, n in on.items() if n) or "none"))
