"""Design step 15 `export`: write every processed output directly to data/processed/ (Req 1.1, 1.10).

No staging directory. Files are written with `common.write_json` (sorted keys, floats and coordinates
rounded to 6 dp), in FILES order, then `sources.json` last. `llm_cache/` is written by the LLM step.

Every file carries `"tz": "America/New_York"` at the top level (a foreign member for the GeoJSON files),
so list-shaped outputs are wrapped: telecom_events.json {tz, events}, households.json {tz, households},
responders.json {tz, responders}, scale_catalog.json {tz, entries}. Shapes: design.md "Data Models".

Privacy (steering privacy.md, Req 5.7, 25.1, 26.7): real data leaves only as tract-level ACS/emPOWER
aggregates and town-hour outage and downed-wire values. No Tab 5 call rows or street text, no phone
numbers, no addresses. Households and responders keep only their synthetic fields. Exclusions are
recorded without their values (the sitrep #009 figure never appears, Req 4.15).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import shapely
from shapely.geometry import mapping

from pipeline.common import CAPE_TOWNS, HOURS, PROCESSED, PROVENANCE, ROOT, PipelineError, write_json
from pipeline.lifelines import COMPONENTS
from pipeline.need import INDICATORS, MASKED_VALUE
from pipeline.outage_curves import (ANCHORS_CSV, NO_VALUE_REASON, TIMELINE_CSV, WORKBOOK, is_sitrep_009)
from pipeline.telecom import EVENTS_CSV
from pipeline.wires import TAB5_SHEET

TZ_NAME = "America/New_York"
GRID = 1e-6  # coordinate precision (6 dp); set_precision keeps polygons valid on this grid
FILES = ("cape_tracts.geojson", "cape_towns.geojson", "cape_timeline.json", "telecom_events.json",
         "content.json", "households.json", "responders.json", "scale_catalog.json", "verifier_log.json")
SOURCES = "sources.json"  # always written last
UNITS = {k: ("per_1000" if k == "elec_dependent" else "share") for k in INDICATORS}

HOUSEHOLD_KEYS = ("id", "geoid", "town", "number", "label", "lang", "lon", "lat", "is_operator", "synthetic")
RESPONDER_KEYS = ("id", "town", "role", "label", "synthetic")

EVERSOURCE_NAME = "Eversource final event report (DPU 25-ERP-10)"
EVERSOURCE_URL = "https://eeaonline.eea.state.ma.us/DPU/Fileroom/dockets/bynumber/25-ERP-10"
SCOPE_REASON = "Scope {scope!r} is not cape_eversource: not used (Req 4.4)"
_ANCHOR_ROW = re.compile(r"anchors row (\d+)")


def _rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return Path(path).name


def _geometry(geom) -> dict[str, Any]:
    """GeoJSON geometry on the 6 dp grid, valid after snapping."""
    g = shapely.set_precision(geom, GRID)
    if not g.is_valid:
        g = shapely.make_valid(g)
    return mapping(g)


def _count(c: Any) -> float:
    return float(getattr(c, "count", c))


# ---------------------------------------------------------------- GeoJSON


def tracts_geojson(ctx) -> dict[str, Any]:
    """cape_tracts.geojson: tract geometry with town, Need and the town's customer count (Req 1.5, 25.1)."""
    tracts = ctx["cape_tracts"].to_crs(4326).sort_values("GEOID")
    need = ctx["need"]
    names = ctx["tiger_tract"].set_index("GEOID")["NAMELSAD"]
    hh_n = Counter(h["geoid"] for h in ctx["households"])
    customers = ctx["customers"]
    features = []
    for _, r in tracts.iterrows():
        g, town = str(r["GEOID"]), str(r["town"])
        n = need.loc[g]
        c = customers[town]
        props = {
            "geoid": g,
            "name": str(names.get(g, f"Census Tract {g[5:]}")),
            "town": town,
            "town_assignment": str(r["assign_method"]),
            "population": int(r["population"]),
            "need_t": float(n["need_t"]),
            "need": {k: {"raw": n[k], "pct": n[f"pct_{k}"], "unit": UNITS[k]} for k in INDICATORS},
            "need_missing": list(n["need_missing"]),
            "empower_masked": bool(n["empower_masked"]),
            "empower": {"dme_allocated": n["dme_allocated"], "medicare_benes_allocated": n["medicare_benes_allocated"]},
            "households_n": int(hh_n.get(g, 0)),
            "customers": _count(c),
            "customers_label": c.label,
        }
        features.append({"type": "Feature", "id": g, "properties": props, "geometry": _geometry(r.geometry)})
    return {"type": "FeatureCollection", "tz": TZ_NAME, "features": features}


def label_points(towns) -> dict[str, list[float]]:
    pts = towns.to_crs(4326).geometry.representative_point()
    return {str(t): [round(p.x, 4), round(p.y, 4)] for t, p in zip(towns["town"], pts)}


def towns_geojson(ctx) -> dict[str, Any]:
    """cape_towns.geojson: the 15 Cape_Town_Boundaries with customer counts and Anchor counts."""
    towns = ctx["cape_towns"].to_crs(4326).sort_values("town")
    lp = label_points(towns)
    anchors = Counter(a.town for a in ctx["anchors"])
    features = []
    for _, r in towns.iterrows():
        t = str(r["town"])
        c = ctx["customers"][t]
        # The 10-digit cousub GEOID is not exported: it has the shape of a NANP phone number (privacy guard).
        props = {"name": t, "customers": _count(c), "customers_source": c.source,
                 "customers_label": c.label, "anchor_count": int(anchors.get(t, 0)), "label_point": lp[t]}
        features.append({"type": "Feature", "id": t, "properties": props, "geometry": _geometry(r.geometry)})
    return {"type": "FeatureCollection", "tz": TZ_NAME, "features": features}


# ---------------------------------------------------------------- timeline


def timeline(ctx) -> dict[str, Any]:
    """cape_timeline.json: town-hour components plus tract-hour priority, channel and rank (Req 7.8).

    Every array is aligned with `hours`. The API expands tract-hours from the tract's town (Req 7.4).
    """
    s = ctx.scoring
    towns = list(CAPE_TOWNS)

    def grid(df: pd.DataFrame) -> pd.DataFrame:
        return df.reindex(index=HOURS, columns=towns)

    out, hd, wraw, wr = grid(ctx["out_pct"]), grid(ctx["hours_dark"]), grid(ctx["wires_raw"]), grid(ctx["wires"])
    tel, rule, life = grid(ctx["telecom"]), grid(ctx["telecom_rule"]), grid(ctx["lifelines"])
    pinned, lb = grid(ctx["pinned"]).fillna(False), grid(ctx["lower_bound"])
    contrib = {c: grid(ctx["contrib"][c]) for c in COMPONENTS}
    active = ctx["telecom_active_events"]
    if out.isna().any().any() or life.isna().any().any():
        raise PipelineError("export", "cape_timeline has missing town-hours")

    town_rows = {}
    for T in towns:
        town_rows[T] = {
            "out_pct": out[T].to_numpy(float),
            "hours_dark": hd[T].to_numpy(int),
            "wires_raw": wraw[T].to_numpy(float),
            "wires": wr[T].to_numpy(float),
            "telecom": tel[T].to_numpy(int),
            "telecom_rule": [str(v) for v in rule[T]],
            "telecom_event_ids": [list(active.get((h, T), [])) for h in HOURS],
            "contrib": {c: contrib[c][T].to_numpy(float) for c in COMPONENTS},
            "lifelines": life[T].to_numpy(float),
            "pinned": pinned[T].to_numpy(bool),
            "lower_bound": [None if pd.isna(v) else float(v) for v in lb[T]],
            "customers_label": ctx["customers"][T].label,
        }

    prio, chan = ctx["priority"].reindex(index=HOURS), ctx["channel"].reindex(index=HOURS)
    town_of = ctx["cape_tracts"].set_index("GEOID")["town"]
    queue = ctx["queue"]
    ranks = {(h, r["geoid"]): r["rank"] for h, rows in queue.items() for r in rows}
    tract_rows = {}
    for g in sorted(map(str, prio.columns)):
        tract_rows[g] = {
            "town": str(town_of[g]),
            "priority": prio[g].to_numpy(float),
            "channel": [str(v) for v in chan[g]],
            "rank": [ranks.get((h, g)) for h in HOURS],
        }

    return {
        "tz": TZ_NAME,
        "hours": list(HOURS),
        "key_demo_hours": list(s.key_demo_hours),
        "weights": {c: float(s.lifelines_weights[c]) for c in COMPONENTS},
        "hours_dark_cap": float(s.hours_dark_cap),
        "dark_threshold": float(s.dark_threshold),
        "telecom_model": {"out_pct_threshold": float(s.telecom_model.out_pct_threshold),
                          "consecutive_hours": int(s.telecom_model.consecutive_hours)},
        "labels": {"reconstructed": PROVENANCE["reconstructed"], "modeled_telecom": PROVENANCE["modeled_telecom"],
                   "acs_customers": PROVENANCE["acs_customers"]},
        "provenance": {"out_pct": ctx["provenance_out_pct"], "hours_dark": ctx["provenance_out_pct"]},  # Req 4.16
        "cape_total": ctx["cape_total"].reindex(HOURS).to_numpy(float),  # Cape_Total_Curve, customers out
        "towns": town_rows,
        "tracts": tract_rows,
        "queue": {h: queue[h] for h in HOURS},
    }


# ---------------------------------------------------------------- synthetic records


def households(ctx) -> dict[str, Any]:
    rows = []
    for h in ctx["households"]:
        if h.get("synthetic") is not True:
            raise PipelineError("export", f"household {h.get('id')!r} is not marked synthetic")
        rows.append({k: h[k] for k in HOUSEHOLD_KEYS if k in h})
    return {"tz": TZ_NAME, "households": rows}


def responders(ctx) -> dict[str, Any]:
    rows = []
    for r in ctx["responders"]:
        if r.get("synthetic") is not True:
            raise PipelineError("export", f"responder {r.get('id')!r} is not marked synthetic")
        rows.append({k: r[k] for k in RESPONDER_KEYS})
    return {"tz": TZ_NAME, "responders": rows}


# ---------------------------------------------------------------- sources.json


def _read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return df.assign(row=range(2, len(df) + 2))  # CSV line numbers; header is line 1


def curated_inputs(ctx) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(inputs, extra exclusions): source name and URL of every curated row used (Req 25.2).

    Rows that are not used and were not already excluded by an earlier step are added as exclusions,
    so every curated row is accounted for. No row values are copied.
    """
    excluded = {(e["file"], int(e["row"])) for e in ctx.sources.get("exclusions", [])}
    inputs: list[dict[str, Any]] = []
    extra: list[dict[str, Any]] = []

    def add(file: str, r: pd.Series, used_in: list[str]) -> None:
        inputs.append({"file": file, "row": int(r["row"]), "source_name": r["source_name"].strip(),
                       "source_url": r["source_url"].strip(), "used_in": used_in})

    f = _rel(ANCHORS_CSV)
    used = {a.row for a in ctx["anchors"]}
    cust = {int(m.group(1)) for c in ctx["customers"].values() if (m := _ANCHOR_ROW.search(c.source or ""))}
    for _, r in _read_csv(ANCHORS_CSV).iterrows():
        row = int(r["row"])
        if (f, row) in excluded:
            continue
        if row in used or row in cust:
            add(f, r, (["out_pct"] if row in used else []) + (["customers"] if row in cust else []))
        else:
            extra.append({"file": f, "row": row, "reason": NO_VALUE_REASON})

    f = _rel(TIMELINE_CSV)
    for _, r in _read_csv(TIMELINE_CSV).iterrows():
        row = int(r["row"])
        if (f, row) in excluded:
            continue
        if is_sitrep_009(r):  # never cited, never used (Req 4.15)
            extra.append({"file": f, "row": row, "reason": "County situation report #009 figure excluded (Req 4.15)"})
        elif r["scope"].strip() == "cape_eversource":
            add(f, r, ["cape_total"])
        else:
            extra.append({"file": f, "row": row, "reason": SCOPE_REASON.format(scope=r["scope"].strip())})

    f = _rel(EVENTS_CSV)
    for _, r in _read_csv(EVENTS_CSV).iterrows():
        drives = r["drives_reach_flag"].strip().casefold() == "true"
        add(f, r, ["telecom_events"] + (["telecom"] if drives else []))
    return inputs, extra


def _mix(m: dict[str, float]) -> str:
    return ", ".join(f"{lang} {v:g}" for lang, v in m.items())


def assumptions(ctx) -> list[dict[str, Any]]:
    s, langs = ctx.scoring, ctx.languages
    mix = langs.household_language_mix
    acs_towns = [t for t in CAPE_TOWNS if ctx["customers"][t].label]
    no_anchor = [e["town"] for e in ctx.sources.get("towns_without_anchors", [])]
    out: list[dict[str, Any]] = [
        {"key": "telecom_model",
         "value": f"out_pct >= {s.telecom_model.out_pct_threshold:g} for {s.telecom_model.consecutive_hours} "
                  "consecutive Hours",
         "label": PROVENANCE["modeled_telecom"]},
        {"key": "telecom_observed_default_hours", "value": int(s.telecom_observed_default_hours),
         "label": PROVENANCE["observed_default"]},
        {"key": "acs_customers", "value": ", ".join(acs_towns), "label": PROVENANCE["acs_customers"]},
        {"key": "household_language_mix.default", "value": _mix(mix.default), "label": mix.label},
        *({"key": f"household_language_mix.{t}", "value": _mix(m), "label": mix.label}
          for t, m in sorted(mix.by_town.items())),
        {"key": "operator_household", "value": int(s.demo.get("operator_household", 1)),
         "label": "Simulated household #1 is the presenter's household; in Barnstable and Yarmouth tracts "
                  "its language is always pt"},
        {"key": "towns_without_anchors", "value": ", ".join(no_anchor),
         "label": "No Anchors: unscaled out_pct is the Cape-wide share (Cape_Total_Curve / total Cape customers)"},
        {"key": "empower_zip_to_tract", "value": "area(ZIP ∩ tract) / area(ZIP), EPSG:26986",
         "label": "emPOWER ZIP counts are allocated to tracts by area weight (assumes an even spread in each ZIP)"},
        {"key": "empower_masking", "value": MASKED_VALUE,
         "label": "emPOWER reports counts of 1 to 10 as 11; 11 is used as reported and the ZIP is marked masked"},
        {"key": "tract_town_assignment", "value": "centroid in EPSG:26986, else nearest boundary",
         "label": "Each tract takes the town that contains its centroid"},
    ]
    for region in ("cape", "boston"):
        if region in langs.help_line:
            out.append({"key": f"help_line.{region}", "value": langs.help_line[region].number,
                        "label": langs.help_line[region].sentence["en"].full})
    return out


def sources(ctx) -> dict[str, Any]:
    """sources.json (design.md "Data Models", Req 4.10, 4.12, 4.15, 5.3, 25.2)."""
    src = ctx.sources
    inputs, extra = curated_inputs(ctx)
    excl = {(e["file"], int(e["row"])): {"file": e["file"], "row": int(e["row"]), "reason": e["reason"]}
            for e in [*src.get("exclusions", []), *extra]}
    wires = src.get("wires_unmatched", [])
    return {
        "tz": TZ_NAME,
        "provenance_labels": dict(PROVENANCE),
        "inputs": inputs,
        "workbook_inputs": [
            {"file": _rel(WORKBOOK), "sheet": "Tab 3", "source_name": EVERSOURCE_NAME, "source_url": EVERSOURCE_URL,
             "used_in": ["cape_total"]},
            {"file": _rel(WORKBOOK), "sheet": TAB5_SHEET, "source_name": EVERSOURCE_NAME,
             "source_url": EVERSOURCE_URL, "used_in": ["wires"],
             "note": "Town-hour aggregates only; no call rows or street text are exported"},
        ],
        "excluded": [excl[k] for k in sorted(excl)],
        "tab5_unmatched_towns": [{"town": e["town"], "calls": int(e["calls"])} for e in wires if e["town"]],
        "tab5_blank_received_calls": sum(int(e["calls"]) for e in wires if not e["town"]),
        "unmatched_hours": sorted(({"hour": e["hour"], "unmatched_customers": e["unmatched_customers"]}
                                   for e in src.get("unmatched_hours", [])), key=lambda e: e["hour"]),
        "towns_without_anchors": [e["town"] for e in src.get("towns_without_anchors", [])],
        "customer_count_sources": {e["town"]: e["source"] for e in src.get("town_customers", [])},
        "tract_town_nearest": [{"geoid": e["GEOID"], "town": e["town"]} for e in src.get("tract_town_nearest", [])],
        "empower_masked_zips": sorted({e["Zip_Code"] for e in src.get("empower_masked_zips", [])}),
        "assumptions": assumptions(ctx),
        "fetches": [{k: e[k] for k in ("name", "url", "vintage") if k in e} for e in src.get("fetches", [])],
        "acs_vintage": {"tract": ctx["acs_tract_vintage"], "cousub": ctx["acs_cousub_vintage"]},
        "acs_variables": [{k: e[k] for k in ("geo", "id", "label", "vintage")} for e in src.get("acs_variables", [])],
    }


# ---------------------------------------------------------------- export


def build(ctx) -> dict[str, Any]:
    """Every processed file's content, keyed by file name, in write order (sources.json last)."""
    content = dict(ctx["content"])
    content["tz"] = TZ_NAME
    files = {
        "cape_tracts.geojson": tracts_geojson(ctx),
        "cape_towns.geojson": towns_geojson(ctx),
        "cape_timeline.json": timeline(ctx),
        "telecom_events.json": {"tz": TZ_NAME, "events": list(ctx["telecom_events"])},
        "content.json": content,
        "households.json": households(ctx),
        "responders.json": responders(ctx),
        "scale_catalog.json": {"tz": TZ_NAME, "entries": list(ctx["scale_catalog"])},
        "verifier_log.json": {**ctx["verifier_log"], "tz": TZ_NAME},
    }
    assert tuple(files) == FILES
    files[SOURCES] = sources(ctx)
    return files


def export(ctx, out_dir: Path = PROCESSED) -> dict[str, Path]:
    """Write every file directly to `out_dir` (no staging, Req 1.10); sources.json is written last."""
    out_dir = Path(out_dir)
    paths: dict[str, Path] = {}
    for name, obj in build(ctx).items():
        paths[name] = out_dir / name
        write_json(paths[name], obj)
    return paths


def step(ctx) -> None:
    paths = export(ctx)
    ctx["export_paths"] = paths
    sizes = ", ".join(f"{n} {p.stat().st_size / 1e6:.2f} MB" for n, p in paths.items())
    print(f"       export: {len(paths)} files -> {_rel(PROCESSED)}: {sizes}")
