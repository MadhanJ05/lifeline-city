"""Step 8 `synthetic`: Synthetic_Households and Synthetic_Responders (Req 17; privacy.md "Synthetic records").

Every record carries `synthetic: true`. Households are generated points inside a tract polygon, labeled
"Simulated household #N", with no street address and no phone number. Responders are role labels only,
"<Town> <role> (Simulated)", never real people.

  households(queued, tracts, mix, n, seed)
    rng = np.random.default_rng([seed, int(geoid)])  -> each tract's records depend only on (seed, GEOID)
    points: rejection-sampled in the polygon in EPSG:26986, moved to EPSG:4326, rounded to 4 dp, re-checked
    lang:   drawn for all n households from mix.by_town[town], else mix.default (17.3, 17.4)
    then household #1 in PT_FIRST_TOWNS is set to "pt" after drawing, so the rng sequence and
    households #2..N are unchanged (17.5). Household #1 is demo.operator_household.

Step outputs in ctx:
  households  [Household dict: id, geoid, town, number, label, lang, lon, lat, is_operator, synthetic]
  responders  [Responder dict: id, town, role, label, synthetic]
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import shapely
from pyproj import Transformer

from pipeline.common import CAPE_TOWNS, CONFIG, ConfigError, LanguageMix, PipelineError, _load_yaml

PT_FIRST_TOWNS = ("Barnstable", "Yarmouth")
METRIC = 26986           # NAD83 / Massachusetts Mainland, metres
DP = 4                   # lon/lat decimals
BATCH = 64               # candidate points drawn per rejection round
MAX_ROUNDS = 1000        # a tract that never yields a point is a data error

_TO_4326 = Transformer.from_crs(METRIC, 4326, always_xy=True)


def _points(rng: np.random.Generator, poly_m, poly_ll, n: int) -> list[tuple[float, float]]:
    """n (lon, lat) points, rounded to DP, each inside both the metric and the lon/lat polygon."""
    minx, miny, maxx, maxy = poly_m.bounds
    shapely.prepare(poly_m)
    shapely.prepare(poly_ll)
    out: list[tuple[float, float]] = []
    for _ in range(MAX_ROUNDS):
        x = rng.uniform(minx, maxx, BATCH)
        y = rng.uniform(miny, maxy, BATCH)
        keep = shapely.contains_xy(poly_m, x, y)
        lon, lat = _TO_4326.transform(x[keep], y[keep])
        lon, lat = np.round(lon, DP), np.round(lat, DP)
        ok = shapely.contains_xy(poly_ll, lon, lat)
        for a, b in zip(lon[ok], lat[ok]):
            out.append((float(a), float(b)))
            if len(out) == n:
                return out
    raise PipelineError(f"could not place {n} points inside the tract polygon after {MAX_ROUNDS * BATCH} draws")


def tract_households(geoid: str, town: str, poly_ll, mix: LanguageMix, n: int, seed: int,
                     operator: int = 1, pt_first_towns: Iterable[str] = PT_FIRST_TOWNS) -> list[dict[str, Any]]:
    """The n Synthetic_Households of one tract. Deterministic in (seed, geoid)."""
    rng = np.random.default_rng([seed, int(geoid)])
    poly_m = gpd.GeoSeries([poly_ll], crs=4326).to_crs(METRIC).iloc[0]
    pts = _points(rng, poly_m, poly_ll, n)
    town_mix = mix.by_town.get(town, mix.default)
    codes = list(town_mix)
    p = np.array([town_mix[c] for c in codes], dtype=float)
    langs = [str(codes[k]) for k in rng.choice(len(codes), size=n, p=p / p.sum())]
    if town in tuple(pt_first_towns) and n >= 1:
        langs[0] = "pt"  # after drawing: rng sequence and households #2..N unchanged (17.5)
    return [{
        "id": f"{geoid}-{i}",
        "geoid": geoid,
        "town": town,
        "number": i,
        "label": f"Simulated household #{i}",
        "lang": langs[i - 1],
        "lon": lon,
        "lat": lat,
        "is_operator": i == operator,
        "synthetic": True,
    } for i, (lon, lat) in enumerate(pts, start=1)]


def households(queued_geoids: Iterable[str], tracts: gpd.GeoDataFrame, mix: LanguageMix, n: int, seed: int,
               operator: int = 1, pt_first_towns: Iterable[str] = PT_FIRST_TOWNS) -> list[dict[str, Any]]:
    """n households for each queued tract, in GEOID order (17.1, 17.2, 17.3, 17.5, 17.6, 17.8)."""
    by_geoid = tracts.set_index("GEOID")
    wanted = sorted(set(queued_geoids))
    missing = [g for g in wanted if g not in by_geoid.index]
    if missing:
        raise PipelineError(f"queued tracts not in cape_tracts: {missing[:5]}")
    out: list[dict[str, Any]] = []
    for g in wanted:
        row = by_geoid.loc[g]
        out += tract_households(g, row["town"], row.geometry, mix, n, seed, operator, pt_first_towns)
    return out


def load_responders(path: Path = CONFIG / "responders.yaml") -> dict[str, Any]:
    """responders.yaml: roles {key: label}, towns {town: [role key, ...]}; towns must be Cape towns."""
    cfg = _load_yaml(Path(path))
    roles, towns = cfg.get("roles"), cfg.get("towns")
    if not isinstance(roles, dict) or not roles or not isinstance(towns, dict) or not towns:
        raise ConfigError(f"{Path(path).name}: needs non-empty 'roles' and 'towns' mappings")
    bad_towns = [t for t in towns if t not in CAPE_TOWNS]
    if bad_towns:
        raise ConfigError(f"{Path(path).name}: towns not on the Cape: {bad_towns}")
    for town, keys in towns.items():
        unknown = [k for k in (keys or []) if k not in roles]
        if unknown:
            raise ConfigError(f"{Path(path).name}: {town} lists unknown roles {unknown}")
    return cfg


def responders(cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One Synthetic_Responder per (town, role) in responders.yaml (17.7, 17.8)."""
    roles = cfg["roles"]
    return [{
        "id": f"{town.lower().replace(' ', '_')}-{role}",
        "town": town,
        "role": role,
        "label": f"{town} {roles[role]} (Simulated)",
        "synthetic": True,
    } for town in sorted(cfg["towns"]) for role in dict.fromkeys(cfg["towns"][town] or [])]


def step(ctx) -> None:
    demo = ctx.scoring.demo
    try:
        seed, n = int(demo["seed"]), int(demo["households_per_tract"])
        operator = int(demo.get("operator_household", 1))
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"scoring.yaml demo needs integer seed and households_per_tract: {e}") from e
    if n < 1:
        raise ConfigError(f"scoring.yaml demo.households_per_tract must be >= 1, got {n}")
    queued = {r["geoid"] for rows in ctx["queue"].values() for r in rows}
    ctx["households"] = households(queued, ctx["cape_tracts"], ctx.languages.household_language_mix,
                                   n, seed, operator)
    ctx["responders"] = responders(load_responders())
    hh = ctx["households"]
    langs = {l: sum(h["lang"] == l for h in hh) for l in ("en", "pt", "es")}
    print(f"       synthetic: {len(hh)} households in {len(queued)} tracts; langs {langs}; "
          f"responders {len(ctx['responders'])}")
