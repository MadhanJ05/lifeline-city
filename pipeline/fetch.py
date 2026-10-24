"""Step 1 `fetch`: ACS, TIGER 2020 and HHS emPOWER, cached under data/raw/cache/ (Req 1.1, 1.3, 1.7).

Every network response is written to data/raw/cache/<name>.<ext> once and re-read from there on later
runs with no network call. This module is the only writer under data/raw/ (design.md, step order).
"""
from __future__ import annotations

import io
import json
import os
from collections.abc import Iterable
from typing import Any, Literal

import geopandas as gpd
import pandas as pd
import requests

from pipeline import common
from pipeline.common import PipelineError

STATE, COUNTY = "25", "001"  # Massachusetts, Barnstable County
ACS_VINTAGES = (2025, 2024)  # newest first; fall back one year (Req 1.7)

# ACS variable IDs, checked against each table's groups/<TABLE>.json for the vintage used.
# seniors_alone uses B11010 (label "...Living alone:!!Householder 65 years and over", male + female)
# over B11001_001E total households; B11007_003E ("households with 65+ : 1-person") was not used.
ACS_TRACT_VARS: tuple[str, ...] = (
    "B01003_001E",                                              # population
    "B11001_001E", "B11010_005E", "B11010_012E",                # seniors_alone
    "S1810_C03_001E",                                           # disability (percent)
    "C16002_001E", "C16002_004E", "C16002_007E", "C16002_010E", "C16002_013E",  # limited_english
    "B25044_001E", "B25044_003E", "B25044_010E",                # no_vehicle
    "B25003_001E", "B25003_003E",                               # renter
)
ACS_COUSUB_VARS: tuple[str, ...] = ("B25001_001E",)            # housing units (Req 3.3)

TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2020/{kind_u}/tl_2020_25_{kind}.zip"
EMPOWER_URL = ("https://services2.arcgis.com/ZQ4jTQn6k7VPXEwO/arcgis/rest/services/"
               "HHS_emPOWER_REST_Service_Public/FeatureServer/1/query")
EMPOWER_FIELDS = "Zip_Code,COUNTY,Power_Dependent_Devices_DME,Medicare_Benes"
EMPOWER_PAGE = 500

# Fetch log for sources.json: {"name", "url", "vintage"?, "cached"}. Drained by the step function.
LOG: list[dict[str, Any]] = []


# ---------------------------------------------------------------- cache


def cache_path(name: str, ext: str = "json"):
    return common.CACHE / f"{name}.{ext}"


def _public_url(url: str, params: dict | None) -> str:
    """URL with query string, without the Census key (secrets never reach sources.json)."""
    shown = {k: v for k, v in (params or {}).items() if k != "key"}
    return requests.Request("GET", url, params=shown).prepare().url or url


def cached_get(name: str, url: str, params: dict | None = None, ext: str = "json",
               vintage: int | None = None) -> bytes:
    """Return data/raw/cache/<name>.<ext>; fetch and store it only when the cache file is missing.

    A failed fetch (network error, HTTP error, or invalid JSON for ext="json") raises
    PipelineError(source, url) and writes nothing.
    """
    path = cache_path(name, ext)
    shown = _public_url(url, params)
    entry = {"name": name, "url": shown, **({"vintage": vintage} if vintage is not None else {})}
    if path.exists():
        LOG.append({**entry, "cached": True})
        return path.read_bytes()
    try:
        r = requests.get(url, params=params, timeout=120, headers={"User-Agent": "lifeline-city-pipeline"})
        r.raise_for_status()
        if "missing_key" in r.url or "invalid_key" in r.url or r.headers.get("X-DataWebAPI-KeyError"):
            raise ValueError("Census API rejected the request: set a valid CENSUS_API_KEY in .env")
        body = r.content
        if ext in ("json", "geojson"):
            data = json.loads(body)
            if isinstance(data, dict) and "error" in data:  # ArcGIS reports errors with HTTP 200
                raise ValueError(data["error"])
    except (requests.RequestException, ValueError) as e:
        raise PipelineError(name, shown, f"{type(e).__name__}: {e}") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(body)
    tmp.replace(path)  # no half-written cache file after a crash
    LOG.append({**entry, "cached": False})
    return body


# ---------------------------------------------------------------- ACS


def _acs_key() -> dict[str, str]:
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    return {"key": key} if key else {}


def _acs_base(vintage: int, subject: bool) -> str:
    return f"https://api.census.gov/data/{vintage}/acs/acs5" + ("/subject" if subject else "")


def _geo_params(geo: Literal["tract", "cousub"], county: str) -> dict[str, str]:
    level = "tract" if geo == "tract" else "county subdivision"
    return {"for": f"{level}:*", "in": f"state:{STATE} county:{county}"}


def _acs_requests(variables: Iterable[str], geo: Literal["tract", "cousub"], county: str, vintage: int):
    """(cache name, url, params) for each table-group check and each data call of one vintage."""
    variables = list(variables)
    tables = sorted({v.split("_")[0] for v in variables})
    for t in tables:
        yield (f"acs{vintage}_groups_{t}", f"{_acs_base(vintage, t.startswith('S'))}/groups/{t}.json", None)
    for subject in (False, True):
        vs = [v for v in variables if v.startswith("S") == subject]
        if vs:
            kind = "subject" if subject else "detail"
            yield (f"acs{vintage}_{geo}_{county}_{kind}", _acs_base(vintage, subject),
                   {"get": ",".join(["NAME", *vs]), **_geo_params(geo, county), **_acs_key()})


def _acs_vintage(variables, geo, county, vintage: int) -> tuple[pd.DataFrame, dict[str, str]]:
    labels: dict[str, str] = {}
    frame: pd.DataFrame | None = None
    geo_cols = ["state", "county", "tract"] if geo == "tract" else ["state", "county", "county subdivision"]
    for name, url, params in _acs_requests(variables, geo, county, vintage):
        body = json.loads(cached_get(name, url, params, vintage=vintage))
        if params is None:  # groups/<TABLE>.json
            group = body.get("variables", {})
            for v in variables:
                if v.split("_")[0] == name.rsplit("_", 1)[1]:
                    if v not in group:
                        raise PipelineError(name, url, f"variable {v} is not in the {vintage} table")
                    labels[v] = group[v]["label"]
            continue
        part = pd.DataFrame(body[1:], columns=body[0])
        frame = part if frame is None else frame.merge(part.drop(columns="NAME"), on=geo_cols, how="outer",
                                                       validate="one_to_one")
    assert frame is not None
    for v in variables:
        frame[v] = pd.to_numeric(frame[v], errors="coerce")  # sentinel negatives are handled in need.py
    frame["GEOID"] = frame[geo_cols].astype(str).agg("".join, axis=1)
    return frame.sort_values("GEOID").reset_index(drop=True), labels


def acs(variables: Iterable[str], geo: Literal["tract", "cousub"], county: str = COUNTY,
        vintages: tuple[int, ...] = ACS_VINTAGES) -> tuple[pd.DataFrame, int, dict[str, str]]:
    """ACS 5-year values for `variables` at tract or county-subdivision level in one county.

    Uses the newest vintage that responds and falls back one year (Req 1.7). A vintage whose files are
    all cached wins first, so a re-run makes no network call. Returns (frame, vintage, {var: label}).
    """
    variables = list(variables)
    for v in vintages:  # cache-only pass
        if all(cache_path(n).exists() for n, _, _ in _acs_requests(variables, geo, county, v)):
            frame, labels = _acs_vintage(variables, geo, county, v)
            return frame, v, labels
    errors = []
    for v in vintages:
        try:
            frame, labels = _acs_vintage(variables, geo, county, v)
            return frame, v, labels
        except PipelineError as e:
            errors.append(f"{v}: {' '.join(map(str, e.args))}")
    raise PipelineError("acs", "; ".join(errors))


# ---------------------------------------------------------------- TIGER and emPOWER


def tiger(kind: Literal["tract", "cousub"]) -> gpd.GeoDataFrame:
    """TIGER 2020 Massachusetts tracts or county subdivisions, in EPSG:4326."""
    url = TIGER_URL.format(kind=kind, kind_u=kind.upper())
    cached_get(f"tl_2020_25_{kind}", url, ext="zip")
    gdf = gpd.read_file(cache_path(f"tl_2020_25_{kind}", "zip"))
    return gdf.to_crs(4326)


def empower_zips(bbox_4326: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """emPOWER ZIP polygons (layer 1) intersecting the envelope, paged by resultOffset, in EPSG:4326."""
    xmin, ymin, xmax, ymax = (round(float(c), 4) for c in bbox_4326)
    frames, offset, page = [], 0, 0
    while True:
        params = {"where": "1=1", "geometry": f"{xmin},{ymin},{xmax},{ymax}",
                  "geometryType": "esriGeometryEnvelope", "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
                  "outFields": EMPOWER_FIELDS, "returnGeometry": "true", "outSR": "4326", "f": "geojson",
                  "orderByFields": "OBJECTID", "resultOffset": str(offset), "resultRecordCount": str(EMPOWER_PAGE)}
        body = cached_get(f"empower_zips_p{page}", EMPOWER_URL, params, ext="geojson")
        data = json.loads(body)
        feats = data.get("features", [])
        if feats:
            frames.append(gpd.read_file(io.BytesIO(body)))
        more = data.get("exceededTransferLimit") or data.get("properties", {}).get("exceededTransferLimit")
        if not feats or (len(feats) < EMPOWER_PAGE and not more):
            break
        offset += len(feats)
        page += 1
    if not frames:
        raise PipelineError("empower_zips", EMPOWER_URL, "no ZIP features in the Barnstable envelope")
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs).to_crs(4326)
    gdf["Zip_Code"] = gdf["Zip_Code"].astype(str).str.zfill(5)
    return gdf.drop_duplicates("Zip_Code").sort_values("Zip_Code").reset_index(drop=True)


# ---------------------------------------------------------------- step


def step(ctx) -> None:
    LOG.clear()
    ctx["tiger_tract"] = tiger("tract")
    ctx["tiger_cousub"] = cousub = tiger("cousub")
    cape = cousub[cousub["COUNTYFP"] == COUNTY]
    ctx["empower_zips"] = empower_zips(tuple(cape.total_bounds))

    for key, variables, geo in (("acs_tract", ACS_TRACT_VARS, "tract"), ("acs_cousub", ACS_COUSUB_VARS, "cousub")):
        frame, vintage, labels = acs(variables, geo)
        ctx[key] = frame
        ctx[f"{key}_vintage"] = vintage
        for var, label in labels.items():
            ctx.source("acs_variables", geo=geo, id=var, label=label, vintage=vintage)

    for entry in LOG:
        ctx.source("fetches", **{k: v for k, v in entry.items() if k != "cached"})
    net = sum(not e["cached"] for e in LOG)
    print(f"       fetch: {net} network, {len(LOG) - net} cached; "
          f"ACS {ctx['acs_tract_vintage']}; tracts {len(ctx['tiger_tract'])}, cousub {len(cousub)}, "
          f"ZIPs {len(ctx['empower_zips'])}, acs_tract {len(ctx['acs_tract'])}, acs_cousub {len(ctx['acs_cousub'])}")
