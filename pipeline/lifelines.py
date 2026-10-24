"""Step 7 `lifelines`: hours_dark, lifelines, priority_Cape, Reach_Channel, Priority_Queue and Why_Chips.

Formulas: .kiro/steering/scoring.md (do not change them here; weights and thresholds come from scoring.yaml).
  hours_dark(T,h) = h - first Hour with out_pct >= dark_threshold, 0 whenever out_pct(T,h) < dark_threshold, capped
  lifelines(T,h)  = w.out_pct*out_pct + w.hours_dark*min(hours_dark/cap,1) + w.wires*wires + w.telecom*telecom
  priority(t,h)   = need_t * lifelines(town(t), h)
  channel(t,h)    = "door_knock" if telecom(town(t), h) == 1 else "sms"

Step outputs in ctx:
  hours_dark    int DataFrame, index HOURS, columns CAPE_TOWNS
  lifelines     float DataFrame like hours_dark, in [0, 1]
  contrib       {component: float DataFrame like hours_dark}: weighted terms, sum = lifelines
  priority      float DataFrame, index HOURS, columns GEOIDs, in [0, 1]
  channel       str DataFrame like priority: "sms" | "door_knock"
  queue         {hour: [QueueRow dict: rank, geoid, town, priority, need_t, channel, why_chips]}
  flat_metrics  callable (geoid, hour) -> {field: number}; the single source for Why_Chips and briefing claims

Step 10 `key_hour_report` (key_hour_step) stores:
  key_hour_report  {"hours": {hour: {sms: {count, towns}, door_knock: {count, towns}}}, "has_mixed_hour": bool}
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import pandas as pd

from pipeline.common import CAPE_TOWNS, HOURS, ConfigError, PipelineError
from pipeline.need import INDICATORS

COMPONENTS = ("out_pct", "hours_dark", "wires", "telecom")
NEED_LABELS = {
    "seniors_alone": "Seniors living alone",
    "disability": "Disability",
    "limited_english": "Limited-English households",
    "no_vehicle": "No-vehicle households",
    "renter": "Renter share",
    "elec_dependent": "Electricity-dependent Medicare beneficiaries",
}


def hours_dark(out_T, thr: float, cap: float) -> np.ndarray:
    """Literal reading: hd[i] = min(i - first, cap) if out_T[i] >= thr else 0; first = first i with out_T >= thr."""
    on = np.asarray(out_T, dtype=float) >= thr
    hd = np.zeros(len(on), dtype=int)
    if on.any():
        first = int(np.argmax(on))
        hd = np.where(on, np.minimum(np.arange(len(on)) - first, cap), 0).astype(int)
    return hd


def lifelines(out, hd, wires, tel, w: Mapping[str, float], cap: float):
    """(lifelines, contrib): elementwise on arrays or aligned DataFrames; lifelines = sum of the contributions."""
    contrib = {
        "out_pct": w["out_pct"] * out,
        "hours_dark": w["hours_dark"] * np.minimum(hd / cap, 1),
        "wires": w["wires"] * wires,
        "telecom": w["telecom"] * tel,
    }
    total = contrib["out_pct"] + contrib["hours_dark"] + contrib["wires"] + contrib["telecom"]
    return total, contrib


def priority(need_t: pd.Series, town_of: pd.Series, lifelines_T: pd.DataFrame) -> pd.DataFrame:
    """priority[h, t] = need_t[t] * lifelines[h, town(t)]; columns follow need_t's index (GEOIDs)."""
    lt = lifelines_T[town_of.reindex(need_t.index).to_numpy()].to_numpy()
    return pd.DataFrame(lt * need_t.to_numpy(), index=lifelines_T.index, columns=need_t.index)


def channel(tel_T) -> np.ndarray:
    """Req 12.1, 12.2."""
    return np.where(np.asarray(tel_T) == 1, "door_knock", "sms")


def build_queue(priority_h, need_t, geoids, n: int) -> list[dict[str, Any]]:
    """Top n by (-priority, -need_t, geoid), rank 1..n (Req 7.7). Rows carry rank, geoid, priority, need_t."""
    p, nt, g = np.asarray(priority_h, float), np.asarray(need_t, float), np.asarray(geoids, str)
    order = np.lexsort((g, -nt, -p))[:n]  # last key is primary
    return [{"rank": r, "geoid": str(g[i]), "priority": float(p[i]), "need_t": float(nt[i])}
            for r, i in enumerate(order, start=1)]


def _ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _chip(text: str, field: str, metrics: Mapping[str, float]) -> dict[str, Any]:
    return {"text": text, "field": field, "value": metrics[field]}


def why_chips(metrics: Mapping[str, float], telecom_rule: str = "modeled") -> list[dict[str, Any]]:
    """Exactly 2 chips, each {text, field, value} with value == metrics[field] (Req 9.3). Descriptive only.
    Chip 1: Need indicator with the highest pct (ties: INDICATORS order).
    Chip 2: largest lifelines contribution (ties: COMPONENTS order)."""
    pcts = [(metrics[f"need.{k}.pct"], -i, k) for i, k in enumerate(INDICATORS) if f"need.{k}.pct" in metrics]
    if not pcts:
        raise PipelineError(f"why_chips: no Need indicator pct for tract {metrics.get('geoid')!r}")
    k = max(pcts)[2]
    f1 = f"need.{k}.pct"
    chip1 = _chip(f"{NEED_LABELS[k]}, {_ordinal(round(metrics[f1] * 100))} percentile", f1, metrics)

    c = max(COMPONENTS, key=lambda c: (metrics[f"contrib.{c}"], -COMPONENTS.index(c)))
    if c == "out_pct":
        text = f"{round(metrics['out_pct'] * 100)}% without power"
    elif c == "hours_dark":
        n = int(metrics["hours_dark"])
        text = f"Dark {n} hour{'' if n == 1 else 's'}"
    elif c == "wires":
        text = f"Downed wires, {_ordinal(round(metrics['wires'] * 100))} percentile"
    else:
        label = "Modeled" if telecom_rule in ("modeled", "none") else "Observed"
        text = f"Phones likely degraded ({label})"
    return [chip1, _chip(text, c, metrics)]


def make_flat_metrics(need: pd.DataFrame, town_of: pd.Series, population: pd.Series,
                      customers: Mapping[str, float], town_frames: Mapping[str, pd.DataFrame],
                      contrib: Mapping[str, pd.DataFrame], weights: Mapping[str, float],
                      prio: pd.DataFrame, ranks: Mapping[tuple[str, str], int]
                      ) -> Callable[[str, str], dict[str, float]]:
    """flat_metrics(geoid, h): need_t, need.<k>.raw / .pct (non-null only), out_pct, hours_dark, wires, wires_raw,
    telecom, contrib.<c>, weight.<c>, lifelines, priority, rank (if queued), customers, population."""
    static: dict[str, dict[str, float]] = {}
    for g, row in need.iterrows():
        d = {"need_t": float(row["need_t"])}
        for k in INDICATORS:
            if pd.notna(row[k]):
                d[f"need.{k}.raw"] = float(row[k])
            if pd.notna(row[f"pct_{k}"]):
                d[f"need.{k}.pct"] = float(row[f"pct_{k}"])
        d["customers"] = float(customers[town_of[g]])
        d["population"] = float(population[g])
        static[str(g)] = d
    wts = {f"weight.{c}": float(weights[c]) for c in COMPONENTS}

    def flat_metrics(geoid: str, h: str) -> dict[str, float]:
        T = town_of[geoid]
        m = dict(static[geoid])
        for f, df in town_frames.items():
            m[f] = float(df.at[h, T])
        for c in COMPONENTS:
            m[f"contrib.{c}"] = float(contrib[c].at[h, T])
        m.update(wts)
        m["priority"] = float(prio.at[h, geoid])
        if (h, geoid) in ranks:
            m["rank"] = float(ranks[(h, geoid)])
        return m

    return flat_metrics


def step(ctx) -> None:
    s = ctx.scoring
    w, cap, thr = s.lifelines_weights, float(s.hours_dark_cap), float(s.dark_threshold)
    towns = list(CAPE_TOWNS)
    grid = lambda key: ctx[key].reindex(index=HOURS, columns=towns)  # noqa: E731
    out, wr, wraw, tel, rule = grid("out_pct"), grid("wires"), grid("wires_raw"), grid("telecom"), grid("telecom_rule")

    hd = pd.DataFrame({T: hours_dark(out[T].to_numpy(), thr, cap) for T in towns}, index=HOURS)
    life, contrib = lifelines(out, hd, wr, tel, w, cap)
    if life.isna().any().any():
        raise PipelineError("lifelines has missing town-hours: " +
                            str([T for T in towns if life[T].isna().any()]))

    tracts = ctx["cape_tracts"].set_index("GEOID")
    need = ctx["need"].reindex(tracts.index)
    if need["need_t"].isna().any():
        raise PipelineError(f"need_t missing for tracts {list(need.index[need['need_t'].isna()])}")
    town_of = tracts["town"]
    prio = priority(need["need_t"], town_of, life)
    tel_t = tel[town_of.to_numpy()].to_numpy()
    chan = pd.DataFrame(channel(tel_t), index=HOURS, columns=need.index)
    rule_t = pd.DataFrame(rule[town_of.to_numpy()].to_numpy(), index=HOURS, columns=need.index)

    geoids = need.index.to_numpy()
    queue = {h: build_queue(prio.loc[h].to_numpy(), need["need_t"].to_numpy(), geoids, s.queue_size) for h in HOURS}
    ranks = {(h, r["geoid"]): r["rank"] for h, rows in queue.items() for r in rows}
    customers = {T: float(getattr(n, "count", n)) for T, n in ctx["customers"].items()}
    fm = make_flat_metrics(need, town_of, tracts["population"].astype(float), customers,
                           {"out_pct": out, "hours_dark": hd, "wires": wr, "wires_raw": wraw,
                            "telecom": tel, "lifelines": life}, contrib, w, prio, ranks)
    for h, rows in queue.items():
        for r in rows:
            g = r["geoid"]
            r["town"] = town_of[g]
            r["channel"] = chan.at[h, g]
            r["why_chips"] = why_chips(fm(g, h), rule_t.at[h, g])
        queue[h] = [{k: r[k] for k in ("rank", "geoid", "town", "priority", "need_t", "channel", "why_chips")}
                    for r in rows]

    ctx["hours_dark"] = hd
    ctx["lifelines"] = life
    ctx["contrib"] = contrib
    ctx["priority"] = prio
    ctx["channel"] = chan
    ctx["queue"] = queue
    ctx["flat_metrics"] = fm
    print(f"       lifelines: {life.min().min():.3f}..{life.max().max():.3f}; priority "
          f"{prio.min().min():.3f}..{prio.max().max():.3f}; door_knock tract-hours {int((chan == 'door_knock').sum().sum())}")


# ---- Step 10: key-hour channel report (Req 11.16, 11.17, 11.19) ----

CHANNELS = ("sms", "door_knock")
MIXED_OK = "ok: at least one key hour shows both channels"
MIXED_ADJUST = ("No key_demo_hours queue has both sms and door_knock tracts: "
                "adjust key_demo_hours in config/scoring.yaml.")


def key_hour_report(queue: Mapping[str, list[Mapping[str, Any]]], channel: pd.DataFrame,
                    key_demo_hours: list[str]) -> dict[str, Any]:
    """{"hours": {h: {sms: {count, towns}, door_knock: {count, towns}}}, "has_mixed_hour": bool}.
    Counts the queued tracts at each Key_Demo_Hour by channel[h, geoid]; towns are sorted and unique.
    has_mixed_hour: some key hour has both counts > 0. A key hour outside the Demo_Window raises ConfigError."""
    bad = [h for h in key_demo_hours if h not in HOURS]
    if bad:
        raise ConfigError(f"key_demo_hours outside the Demo_Window: {bad}")
    hours: dict[str, dict[str, dict[str, Any]]] = {}
    for h in key_demo_hours:
        towns: dict[str, set[str]] = {c: set() for c in CHANNELS}
        counts = dict.fromkeys(CHANNELS, 0)
        for r in queue.get(h, []):
            c = str(channel.at[h, r["geoid"]])
            counts[c] += 1
            towns[c].add(str(r["town"]))
        hours[h] = {c: {"count": counts[c], "towns": sorted(towns[c])} for c in CHANNELS}
    mixed = any(all(v[c]["count"] > 0 for c in CHANNELS) for v in hours.values())
    return {"hours": hours, "has_mixed_hour": mixed}


def format_key_hour_report(report: Mapping[str, Any]) -> str:
    """The printed report (design.md "Pipeline step order"), ending with the ok or adjust line."""
    def part(c: str, v: Mapping[str, Any]) -> str:
        return f"{c} {v['count']}" + (f" ({', '.join(v['towns'])})" if v["count"] else "")

    rows = [(h, part("sms", v["sms"]), part("door_knock", v["door_knock"])) for h, v in report["hours"].items()]
    width = max((len(s) for _, s, _ in rows), default=0)
    lines = ["Key-hour channels"] + [f"  {h}  {s:<{width}}  {d}" for h, s, d in rows]
    lines.append("  " + (MIXED_OK if report["has_mixed_hour"] else MIXED_ADJUST))
    return "\n".join(lines)


def key_hour_step(ctx) -> None:
    """Runs on every run, including --no-llm. verifier copies ctx["key_hour_report"]["hours"] to key_hour_channels."""
    report = key_hour_report(ctx["queue"], ctx["channel"], list(ctx.scoring.key_demo_hours))
    ctx["key_hour_report"] = report
    print(format_key_hour_report(report))
