"""Live outage sources: MEMA's statewide town CSV and the Eversource and National Grid outage maps.

The endpoints are the files the public maps load. They are undocumented and can change, so every
snapshot archives the raw responses and the parsing here can be redone later (docs/live-data.md).

Each collect_* function fills a SourceResult as it goes, so a failure part-way still leaves the raw
files fetched so far for the archive. `fetch(url, missing=(404,))` is the only network boundary: it
returns the body, or None when the status is in `missing` (normal for empty map tiles), and raises
FetchError for anything else.
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from collector import geo
from pipeline.common import TZ

Fetch = Callable[..., bytes | None]


class FetchError(Exception):
    """A request failed with something other than 404 (network error, timeout, 5xx)."""


MEMA_CSV = "http://mema.mapsonline.net/power_outage_public.csv"  # MEMA serves it over HTTP only

EVERSOURCE = "https://outagemap.eversource.com/resources/data/external/interval_generation_data"
EVERSOURCE_REPORTS = ("report_east.json", "report_west.json")  # Eastern, Western MA (report_conn/_hampshire: CT, NH)

KUBRA = "https://kubra.io"
NATIONAL_GRID_MA = ("9cb2e5b7-d321-4575-a552-4ae7078cbc31", "ec79df5b-2c54-4fb9-a86a-b20775678236")  # instance, view

ROOT_ZOOM = 7          # 3 tiles cover Massachusetts
MAX_ZOOM = 16          # both maps stop splitting clusters by zoom 15 (checked 2026-10-26)
MAX_TILE_REQUESTS = 4000
WORKERS = 4

TOWN_FIELDS = ("source", "utility", "town", "county", "cust_served", "cust_out", "cust_out_masked",
               "source_updated")
OUTAGE_FIELDS = ("source", "outage_id", "lat", "lon", "cust_out", "cust_out_masked", "n_out", "cluster",
                 "zoom", "start", "etr", "cause", "crew_status")


@dataclass
class SourceResult:
    source: str
    raw: dict[str, bytes] = field(default_factory=dict)
    towns: list[dict[str, Any]] = field(default_factory=list)
    outages: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _required(fetch: Fetch, url: str) -> bytes:
    body = fetch(url)
    if body is None:
        raise FetchError(f"HTTP 404: {url}")
    return body


def _int(v: Any) -> int | None:
    if v in (None, ""):
        return None
    return int(float(str(v).replace(",", "")))


def _label(v: Any) -> str | None:
    """Kubra text fields are either a string or {"EN-US": ..., "orig": ...}."""
    if isinstance(v, dict):
        return v.get("EN-US") or v.get("orig")
    return v


def _masked(cust_a: dict) -> bool:
    # Eversource marks rounded small counts {"masked": true}; National Grid adds {"mask": 5}.
    return bool(cust_a.get("masked")) or "mask" in cust_a


# ---------------------------------------------------------------- MEMA


def parse_mema(body: bytes) -> list[dict[str, Any]]:
    """One row per town and utility. MEMA lists only towns that currently have outages."""
    rows = []
    for r in csv.DictReader(io.StringIO(body.decode("utf-8-sig"))):
        try:
            updated = datetime.strptime(r["Last Updated"].strip(), "%Y/%m/%d %I:%M %p").replace(tzinfo=TZ)
        except ValueError:
            updated = None
        rows.append({"source": "mema", "utility": r["Utility"].strip(), "town": r["Town"].strip(),
                     "county": r["County"].strip(), "cust_served": _int(r["Total Customers"]),
                     "cust_out": _int(r["Without Power"]), "cust_out_masked": False,
                     "source_updated": updated.isoformat() if updated else None})
    return rows


def collect_mema(fetch: Fetch, res: SourceResult) -> None:
    body = _required(fetch, MEMA_CSV)
    res.raw["power_outage_public.csv"] = body
    res.towns = parse_mema(body)


# ---------------------------------------------------------------- outage tiles (both utilities)


def outage_row(source: str, q: str, item: dict) -> dict[str, Any] | None:
    """One map-tile item -> outage row; None when it has no location."""
    d = item.get("desc") or {}
    geom = item.get("geom") or {}
    pts = [p for enc in geom.get("p") or [] for p in geo.decode_polyline(enc)]
    if not pts:  # an area outage drawn as a polygon: use the mean of its vertices
        pts = [p for enc in geom.get("a") or [] for p in geo.decode_polyline(enc)]
    if not pts:
        return None
    cust_a = d.get("cust_a") or {}
    return {"source": source, "outage_id": d.get("inc_id"),
            "lat": round(sum(p[0] for p in pts) / len(pts), 5),
            "lon": round(sum(p[1] for p in pts) / len(pts), 5),
            "cust_out": _int(cust_a.get("val")), "cust_out_masked": _masked(cust_a),
            "n_out": _int(d.get("n_out")), "cluster": bool(d.get("cluster")), "zoom": len(q),
            "start": d.get("start") or d.get("start_time"), "etr": d.get("etr"),
            "cause": _label(d.get("cause")), "crew_status": _label(d.get("crew_status"))}


def _tile_items(body: bytes) -> list[dict]:
    return json.loads(body).get("file_data") or []


def crawl(tile_url: Callable[[str], str], fetch: Fetch, source: str, roots: Iterable[str],
          max_zoom: int = MAX_ZOOM, max_requests: int = MAX_TILE_REQUESTS, workers: int = WORKERS):
    """Fetch outage tiles top-down, splitting only tiles that still contain clusters.

    Returns (tiles, outages, stats). `tiles` maps quadkey -> raw body for the archive. `outages` has
    one row per outage, from the deepest zoom it was seen at. A cluster row is kept only when its tile
    was not split (max zoom, request cap, or no child tile came back), so customers are neither
    counted twice nor dropped.
    """
    tiles: dict[str, bytes] = {}
    errors: list[str] = []
    lock = threading.Lock()

    def get(q: str) -> bytes | None:
        try:
            return fetch(tile_url(q))
        except FetchError as e:
            with lock:
                errors.append(str(e))
            return None

    level, requests, truncated = list(roots), 0, False
    with ThreadPoolExecutor(workers) as pool:
        while level:
            if requests + len(level) > max_requests:
                level, truncated = level[: max_requests - requests], True
            bodies = list(pool.map(get, level))
            requests += len(level)
            nxt = []
            for q, body in zip(level, bodies, strict=True):
                if body is None:
                    continue
                tiles[q] = body
                if len(q) < max_zoom and any((it.get("desc") or {}).get("cluster") for it in _tile_items(body)):
                    nxt.extend(geo.children(q))
            level = [] if truncated else nxt

    outages: dict[str, dict] = {}
    for q, body in tiles.items():
        split = any(c in tiles for c in geo.children(q))
        for i, item in enumerate(_tile_items(body)):
            row = outage_row(source, q, item)
            if row is None or (row["cluster"] and split):
                continue
            if row["cluster"]:
                key = f"cluster:{q}:{i}"
            else:
                key = row["outage_id"] or f"{row['lat']:.5f},{row['lon']:.5f},{row['start']}"
            if key not in outages or row["zoom"] > outages[key]["zoom"]:
                outages[key] = row
    stats = {"tile_requests": requests, "tiles": len(tiles), "tile_errors": len(errors),
             "truncated": truncated, "deepest_zoom": max(map(len, tiles), default=None)}
    return tiles, list(outages.values()), stats


def _tiles_jsonl(tiles: dict[str, bytes]) -> bytes:
    return b"\n".join(json.dumps({"q": q, "data": json.loads(b)}).encode() for q, b in sorted(tiles.items()))


def _crawl_into(res: SourceResult, tile_url: Callable[[str], str], fetch: Fetch) -> None:
    tiles, outages, stats = crawl(tile_url, fetch, res.source, geo.bbox_quadkeys(geo.MA_BBOX, ROOT_ZOOM))
    res.raw["tiles.jsonl"] = _tiles_jsonl(tiles)
    res.outages = outages
    res.meta.update(stats)


# ---------------------------------------------------------------- Eversource (Kubra Storm Center, iFactor)


def parse_eversource_report(body: bytes) -> list[dict[str, Any]]:
    """report_east/west.json: EVERSOURCE > MA > EMA|WMA > towns."""
    rows: list[dict[str, Any]] = []

    def walk(area: dict, path: tuple[str, ...]) -> None:
        if area.get("areas"):
            for child in area["areas"]:
                walk(child, path + (area["area_name"],))
            return
        cust_a = area.get("cust_a") or {}
        rows.append({"source": "eversource", "utility": f"Eversource {path[-1]}" if path else "Eversource",
                     "town": area["area_name"], "county": None, "cust_served": _int(area.get("cust_s")),
                     "cust_out": _int(cust_a.get("val")), "cust_out_masked": _masked(cust_a),
                     "source_updated": None})

    for area in json.loads(body)["file_data"]["areas"]:
        walk(area, ())
    return rows


def collect_eversource(fetch: Fetch, res: SourceResult) -> None:
    meta = _required(fetch, f"{EVERSOURCE}/metadata.json")
    res.raw["metadata.json"] = meta
    base = f"{EVERSOURCE}/{json.loads(meta)['directory']}"
    summary = _required(fetch, f"{base}/data.json")
    res.raw["data.json"] = summary
    s = json.loads(summary)["summaryFileData"]
    res.meta.update(generated_at=s.get("date_generated"), page_mode=(s.get("page_mode") or {}).get("mode"),
                    pause_publish=(s.get("page_mode") or {}).get("pausePublish"))
    for name in EVERSOURCE_REPORTS:
        body = _required(fetch, f"{base}/{name}")
        res.raw[name] = body
        res.towns.extend(parse_eversource_report(body))
    for row in res.towns:
        row["source_updated"] = res.meta["generated_at"]
    # Eversource's file host answers 403, not 404, for tiles with no outages.
    _crawl_into(res, lambda q: f"{base}/outages/{q}.json", lambda url: fetch(url, (403, 404)))


# ---------------------------------------------------------------- National Grid (Kubra Storm Center)


def kubra_layers(config_text: str) -> tuple[list[str], str, str]:
    """(report files, summary file, cluster tile pattern) named in a Storm Center configuration."""
    reports = sorted(set(re.findall(r"public/reports/[A-Za-z0-9-]+_report\.json", config_text)))
    summary = re.findall(r"public/summary-\d+/data\.json", config_text)
    clusters = re.findall(r"public/cluster-\d+/\{q\}\.json", config_text)
    if not reports or not summary or not clusters:
        raise ValueError("Storm Center configuration has no report, summary or cluster layer")
    return reports, summary[0], clusters[0]


def parse_kubra_report(body: bytes) -> list[dict[str, Any]]:
    """Town ("ctv") rows from a Storm Center report; county reports nest the same towns."""
    rows: list[dict[str, Any]] = []

    def walk(area: dict) -> None:
        for child in area.get("areas") or []:
            walk(child)
        if area.get("key") == "ctv":
            cust_a = area.get("cust_a") or {}
            rows.append({"source": "national_grid", "utility": "National Grid", "town": area["name"],
                         "county": area.get("county"), "cust_served": _int(area.get("cust_s")),
                         "cust_out": _int(cust_a.get("val")), "cust_out_masked": _masked(cust_a),
                         "source_updated": None, "_id": area.get("areaId") or area["name"]})

    for area in json.loads(body)["file_data"]["areas"]:
        walk(area)
    return rows


def collect_national_grid(fetch: Fetch, res: SourceResult, ids: tuple[str, str] = NATIONAL_GRID_MA) -> None:
    api = f"{KUBRA}/stormcenter/api/v1/stormcenters/{ids[0]}/views/{ids[1]}"
    state_body = _required(fetch, f"{api}/currentState?preview=false")
    res.raw["currentState.json"] = state_body
    state = json.loads(state_body)
    data_path = state["data"]["interval_generation_data"]
    cluster_path = state["data"]["cluster_interval_generation_data"]
    config = _required(fetch, f"{api}/configuration/{state['stormcenterDeploymentId']}?preview=false")
    res.raw["configuration.json"] = config
    reports, summary_file, cluster_layer = kubra_layers(config.decode())

    summary = _required(fetch, f"{KUBRA}/{data_path}/{summary_file}")
    res.raw["summary.json"] = summary
    s = json.loads(summary)["summaryFileData"]
    res.meta.update(generated_at=s.get("date_generated"), page_mode=(s.get("page_mode") or {}).get("mode"),
                    pause_publish=(s.get("page_mode") or {}).get("pausePublish"))

    towns: dict[str, dict] = {}
    for path in reports:
        body = _required(fetch, f"{KUBRA}/{data_path}/{path}")
        res.raw[path.rsplit("/", 1)[-1]] = body
        for row in parse_kubra_report(body):
            towns.setdefault(row.pop("_id"), row)
    res.towns = list(towns.values())
    for row in res.towns:
        row["source_updated"] = res.meta["generated_at"]

    def tile_url(q: str) -> str:
        # Kubra shards cluster tiles by the last three quadkey digits, reversed.
        return f"{KUBRA}/{cluster_path.replace('{qkh}', q[-3:][::-1])}/{cluster_layer.replace('{q}', q)}"

    _crawl_into(res, tile_url, fetch)
