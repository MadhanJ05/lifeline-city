"""Live step `locate`: where the outages in one collector snapshot are, by census tract, counted in
year-round homes (docs/live-data.md).

  python -m pipeline.locate                              the latest snapshot in data/live/
  python -m pipeline.locate --snapshot 20261026T201554Z

How one snapshot becomes tract numbers:
1. Place: each outage point (collector outages.csv) goes to the Cape town it falls in, or the nearest
   one within 2 km (points on piers or in harbors); anything farther is outside the county and drops.
2. Spread: its customers fill the nearest homes in that town, block by block, never past a block's
   homes (2020 Census housing units). Larger outages are placed first.
3. Reconcile: the utility's town report is the count. Each town's spread is scaled to its reported
   total and clipped to each block's homes, with the excess moved to the town's remaining homes. A town
   with a total but no points is spread over all its homes; a town reporting 0 is set to 0.
4. Year-round: customers out become year-round homes out by each block's year-round share. Year-round
   homes are the 2020 Census occupied homes per block, scaled to ACS households per tract, so summer
   homes that stand empty in a winter storm are not counted as people in the dark.

Writes data/live/located/<snapshot>.csv (one row per tract) and <snapshot>.json (per-town checks).
Every number is an estimate and carries its method label.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from pipeline import fetch
from pipeline.common import CAPE_TOWNS, ROOT, PipelineError, match_town
from pipeline.tracts_towns import METRIC, cape_towns

LIVE = ROOT / "data" / "live"
NEAREST_TOWN_M = 2000
UTILITY_SOURCES = ("eversource", "national_grid")

LABEL_POINTS = "Estimated from outage locations"
LABEL_TOWN = "Estimated from the town total"
LABEL_NONE = "No outages reported"


# ---------------------------------------------------------------- geography (built once per run)


def load_geography() -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """(blocks, towns). blocks: Cape 2020 blocks with homes > 0 and [GEOID, tract, town, x, y, homes,
    year_round]; towns: the 15 Cape towns in EPSG:26986."""
    towns = cape_towns(fetch.tiger("cousub")).to_crs(METRIC)
    blocks = fetch.census_blocks()
    households, _, _ = fetch.acs(["B11001_001E"], "tract")
    return prepare_blocks(blocks, households[["GEOID", "B11001_001E"]], towns), towns


def prepare_blocks(blocks: pd.DataFrame, households: pd.DataFrame, towns: gpd.GeoDataFrame) -> pd.DataFrame:
    """Add tract, town and metre coordinates; scale occupied homes to ACS households per tract."""
    b = blocks[blocks["homes"] > 0].copy()
    b["tract"] = b["GEOID"].str[:11]
    pts = gpd.GeoDataFrame(b[["GEOID"]], geometry=gpd.points_from_xy(b["lon"], b["lat"]), crs=4326).to_crs(METRIC)
    b["x"], b["y"] = pts.geometry.x.to_numpy(), pts.geometry.y.to_numpy()
    b["town"] = _town_of(pts, towns, max_m=None)
    hh = households.rename(columns={"GEOID": "tract", "B11001_001E": "households"})
    b = b.merge(hh, on="tract", how="left", validate="many_to_one")
    occ_sum = b.groupby("tract")["occupied"].transform("sum")
    scale = (b["households"] / occ_sum).where(occ_sum > 0, 0).fillna(1.0)  # no ACS value: keep the 2020 count
    b["year_round"] = np.minimum(b["occupied"] * scale, b["homes"])
    return b[["GEOID", "tract", "town", "x", "y", "homes", "year_round"]].reset_index(drop=True)


def _town_of(pts: gpd.GeoDataFrame, towns: gpd.GeoDataFrame, max_m: float | None) -> np.ndarray:
    """Town containing each point, else the nearest town within max_m (None: any distance), else None."""
    hit = gpd.sjoin(pts, towns[["town", "geometry"]], how="left", predicate="within")
    town = hit[~hit.index.duplicated()]["town"].reindex(pts.index)
    miss = town.isna()
    if miss.any():
        near = gpd.sjoin_nearest(pts[miss], towns[["town", "geometry"]], how="left", max_distance=max_m)
        town[miss] = near[~near.index.duplicated()]["town"].reindex(pts.index[miss])
    return town.astype(object).where(town.notna(), None).to_numpy()


# ---------------------------------------------------------------- the four steps


def place(outages: pd.DataFrame, towns: gpd.GeoDataFrame) -> pd.DataFrame:
    """Outage rows with [town, x, y]; town is missing (NaN) outside the county."""
    o = outages.copy()
    pts = gpd.GeoDataFrame(o[[]], geometry=gpd.points_from_xy(o["lon"], o["lat"]), crs=4326).to_crs(METRIC)
    o["x"], o["y"] = pts.geometry.x.to_numpy(), pts.geometry.y.to_numpy()
    o["town"] = _town_of(pts, towns, max_m=NEAREST_TOWN_M) if len(o) else []
    return o


def spread(outages: pd.DataFrame, blocks: pd.DataFrame) -> tuple[np.ndarray, float]:
    """(customers out per block, customers that found no room). Each outage fills the nearest homes
    in its town first, never past a block's homes; larger outages are placed first."""
    out = np.zeros(len(blocks))
    room = blocks["homes"].to_numpy(float).copy()
    bx, by = blocks["x"].to_numpy(), blocks["y"].to_numpy()
    by_town = blocks.groupby("town").indices
    unplaced = 0.0
    placed = outages[outages["town"].notna()].copy()
    placed["c"] = pd.to_numeric(placed["cust_out"], errors="coerce").fillna(0)
    for row in placed.sort_values(["c", "x", "y"], ascending=[False, True, True]).itertuples():
        idx = by_town.get(row.town)
        left = float(row.c)
        if idx is None or left <= 0:
            unplaced += left
            continue
        for i in idx[np.argsort((bx[idx] - row.x) ** 2 + (by[idx] - row.y) ** 2, kind="stable")]:
            take = min(room[i], left)
            out[i] += take
            room[i] -= take
            left -= take
            if left <= 0:
                break
        unplaced += left
    return out, unplaced


def _fit(x: np.ndarray, cap: np.ndarray) -> np.ndarray:
    """Clip x to cap, then move the clipped excess to the remaining room in proportion to it."""
    total = x.sum()
    x = np.minimum(x, cap)
    excess, room = total - x.sum(), cap - x
    if excess > 0 and room.sum() > 0:
        x = x + room * min(1.0, excess / room.sum())
    return x


def reconcile(spread_out: np.ndarray, blocks: pd.DataFrame,
              totals: dict[str, int]) -> tuple[np.ndarray, np.ndarray, dict[str, dict]]:
    """(customers out per block, method per block, check per town): each town scaled to its report."""
    out = spread_out.copy()
    homes = blocks["homes"].to_numpy(float)
    method = np.full(len(blocks), LABEL_NONE, dtype=object)
    checks: dict[str, dict] = {}
    for town, idx in sorted(blocks.groupby("town").indices.items()):
        from_points, reported = out[idx].sum(), totals.get(town)
        if reported is None:
            how = "points, no town report" if from_points else "no report, no points"
            label = LABEL_POINTS if from_points else LABEL_NONE
        elif reported <= 0:
            out[idx], how, label = 0.0, "town reports 0", LABEL_NONE
        elif from_points > 0:
            out[idx] = _fit(out[idx] * (reported / from_points), homes[idx])
            how, label = "points, scaled to town total", LABEL_POINTS
        else:
            out[idx] = _fit(homes[idx] * (reported / homes[idx].sum()), homes[idx])
            how, label = "town total only (no outage locations)", LABEL_TOWN
        method[idx] = label
        checks[town] = {"reported": reported, "from_points": round(float(from_points), 1),
                        "estimated": round(float(out[idx].sum()), 1), "homes": int(homes[idx].sum()),
                        "method": how}
    return out, method, checks


def by_tract(blocks: pd.DataFrame, out: np.ndarray, method: np.ndarray) -> pd.DataFrame:
    """One row per tract: homes, year-round homes, customers out and year-round homes out."""
    b = blocks[["tract", "town", "homes", "year_round"]].copy()
    b["customers_out"] = out
    b["year_round_out"] = out * (b["year_round"] / b["homes"])
    b["method"] = np.where(out > 0, method, None)
    g = b.groupby("tract")
    t = g[["homes", "year_round", "customers_out", "year_round_out"]].sum()
    t["towns"] = g["town"].agg(lambda s: ";".join(sorted(set(s))))
    labels = g["method"].agg(lambda s: set(s.dropna()))
    t["label"] = labels.map(lambda s: LABEL_POINTS if LABEL_POINTS in s else (LABEL_TOWN if s else LABEL_NONE))
    t["pct_year_round_out"] = (t["year_round_out"] / t["year_round"]).where(t["year_round"] > 0, 0.0)
    t = t.rename(columns={"year_round": "year_round_homes"}).reset_index()
    for c in ("customers_out", "year_round_out", "year_round_homes"):
        t[c] = t[c].round(1)
    t["pct_year_round_out"] = t["pct_year_round_out"].round(4)
    return t[["tract", "towns", "homes", "year_round_homes", "customers_out", "year_round_out",
              "pct_year_round_out", "label"]]


# ---------------------------------------------------------------- one snapshot


def town_totals(towns_rows: pd.DataFrame) -> tuple[dict[str, int], str]:
    """(Cape town -> customers out, which source). Utility town reports first; MEMA when the snapshot
    has none, with Cape towns MEMA doesn't list counted as 0 (MEMA lists only towns with outages)."""
    util = towns_rows[towns_rows["source"].isin(UTILITY_SOURCES)]
    rows, source = (util, "utility reports") if len(util) else (towns_rows[towns_rows["source"] == "mema"], "mema")
    totals: dict[str, int] = {t: 0 for t in CAPE_TOWNS} if source == "mema" else {}
    for r in rows.itertuples():
        t = match_town(r.town)
        v = pd.to_numeric(r.cust_out, errors="coerce")
        if t is not None:
            totals[t] = totals.get(t, 0) + (0 if pd.isna(v) else int(v))
    return totals, source


def locate(outages: pd.DataFrame, towns_rows: pd.DataFrame, blocks: pd.DataFrame,
           towns: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict]:
    """(tract table, summary) for one snapshot's rows."""
    placed = place(outages, towns)
    spread_out, unplaced = spread(placed, blocks)
    totals, totals_source = town_totals(towns_rows)
    out, method, checks = reconcile(spread_out, blocks, totals)
    tracts = by_tract(blocks, out, method)
    inside = placed["town"].notna()
    summary = {
        "totals_source": totals_source,
        "points": {"total": int(len(placed)), "in_county": int(inside.sum()), "outside_county": int((~inside).sum()),
                   "customers_without_room": round(unplaced, 1)},
        "county": {"customers_out": round(float(out.sum()), 1),
                   "year_round_out": round(float(tracts["year_round_out"].sum()), 1),
                   "homes": int(blocks["homes"].sum()), "year_round_homes": round(float(blocks["year_round"].sum()))},
        "towns": checks,
    }
    return tracts, summary


def _snapshot_rows(live: Path, stamp: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    read = lambda name: pd.read_csv(live / name, dtype={"snapshot_utc": str})  # noqa: E731
    outages, towns_rows = read("outages.csv"), read("towns.csv")
    return outages[outages["snapshot_utc"] == stamp], towns_rows[towns_rows["snapshot_utc"] == stamp]


def latest_snapshot(live: Path) -> str:
    stamps = sorted(p.name for p in (live / "snapshots").glob("*Z") if (p / "manifest.json").exists())
    if not stamps:
        raise PipelineError("locate", f"no snapshots in {live / 'snapshots'}; run python -m collector.run")
    return stamps[-1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", help="UTC stamp, e.g. 20261026T201554Z (default: latest)")
    ap.add_argument("--live-dir", type=Path, default=LIVE)
    args = ap.parse_args(argv)
    stamp = args.snapshot or latest_snapshot(args.live_dir)
    outages, towns_rows = _snapshot_rows(args.live_dir, stamp)
    blocks, towns = load_geography()
    tracts, summary = locate(outages, towns_rows, blocks, towns)
    out_dir = args.live_dir / "located"
    out_dir.mkdir(parents=True, exist_ok=True)
    tracts.to_csv(out_dir / f"{stamp}.csv", index=False)
    (out_dir / f"{stamp}.json").write_text(json.dumps({"snapshot_utc": stamp, **summary}, indent=2) + "\n",
                                           encoding="utf-8")
    c = summary["county"]
    print(f"{stamp}  {summary['points']['in_county']} outage points on the Cape | "
          f"{c['customers_out']:.0f} customers out = {c['year_round_out']:.0f} year-round homes "
          f"in {int((tracts['customers_out'] > 0).sum())} tracts | totals from {summary['totals_source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
