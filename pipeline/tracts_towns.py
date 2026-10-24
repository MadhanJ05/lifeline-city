"""Step 2 `tracts_towns`: Cape_Town_Boundaries, Cape_Tracts (pop > 0) and tract -> town (Req 1.5, 3.4, 3.5).

Outputs in ctx:
  cape_towns          GeoDataFrame EPSG:4326 [town, GEOID, geometry], one row per CAPE_TOWNS entry
  cape_tracts         GeoDataFrame EPSG:4326 [GEOID, population, town, assign_method, geometry]
  town_housing_units  {town: ACS B25001_001E housing units}, matched by cousub GEOID (used by Req 3.3)
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from pipeline.common import CAPE_TOWNS, PipelineError

STATE, COUNTY = "25", "001"
METRIC = 26986  # NAD83 / Massachusetts Mainland, metres
UNDEFINED_COUSUBFP = "00000"  # TIGER "County subdivisions not defined" (water) row


def cape_towns(cousub: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The 15 Cape towns from TIGER cousub rows in Barnstable County, named without a trailing " Town"."""
    rows = cousub[(cousub["STATEFP"] == STATE) & (cousub["COUNTYFP"] == COUNTY)
                  & (cousub["COUSUBFP"] != UNDEFINED_COUSUBFP)].copy()
    rows["town"] = rows["NAME"].str.replace(r" Town$", "", regex=True).str.strip()
    names = sorted(rows["town"])
    if names != sorted(CAPE_TOWNS):
        missing = sorted(set(CAPE_TOWNS) - set(names))
        extra = sorted(set(names) - set(CAPE_TOWNS))
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise PipelineError("cape_towns", f"cousub names do not match the 15 Cape towns: "
                            f"missing {missing}, extra {extra}, duplicated {dupes}")
    out = rows[["town", "GEOID", "geometry"]].sort_values("town").reset_index(drop=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=cousub.crs).to_crs(4326)


def cape_tracts(tracts: gpd.GeoDataFrame, pop: pd.DataFrame) -> gpd.GeoDataFrame:
    """Barnstable County tracts with ACS population (B01003_001E) > 0."""
    t = tracts[(tracts["STATEFP"] == STATE) & (tracts["COUNTYFP"] == COUNTY)]
    p = pop[["GEOID", "B01003_001E"]].rename(columns={"B01003_001E": "population"})
    t = t[["GEOID", "geometry"]].merge(p, on="GEOID", how="left", validate="one_to_one")
    t = t[t["population"].fillna(0) > 0]
    t["population"] = t["population"].astype(int)
    out = t[["GEOID", "population", "geometry"]].sort_values("GEOID").reset_index(drop=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=tracts.crs).to_crs(4326)


def assign_towns(tracts: gpd.GeoDataFrame, towns: gpd.GeoDataFrame) -> pd.DataFrame:
    """[GEOID, town, assign_method]: the town containing the tract centroid in EPSG:26986 ("centroid"),
    else the town with the nearest boundary ("nearest")."""
    cent = gpd.GeoDataFrame({"GEOID": tracts["GEOID"].values},
                            geometry=tracts.to_crs(METRIC).geometry.centroid.values, crs=METRIC)
    tw = towns[["town", "geometry"]].to_crs(METRIC)
    hit = gpd.sjoin(cent, tw, how="left", predicate="within").drop_duplicates("GEOID")
    town = hit.set_index("GEOID")["town"]
    method = pd.Series("centroid", index=town.index)
    for g in town.index[town.isna()]:
        pt = cent.geometry[cent["GEOID"] == g].iloc[0]
        dist = tw.geometry.boundary.distance(pt)
        town[g] = tw["town"].iloc[int(dist.values.argmin())]
        method[g] = "nearest"
    return pd.DataFrame({"GEOID": town.index, "town": town.values, "assign_method": method.values})


def step(ctx) -> None:
    towns = cape_towns(ctx["tiger_cousub"])
    tracts = cape_tracts(ctx["tiger_tract"], ctx["acs_tract"])
    tracts = tracts.merge(assign_towns(tracts, towns), on="GEOID", validate="one_to_one")
    ctx["cape_towns"] = towns
    ctx["cape_tracts"] = gpd.GeoDataFrame(tracts[["GEOID", "population", "town", "assign_method", "geometry"]],
                                          geometry="geometry", crs=4326)

    units = ctx["acs_cousub"].set_index("GEOID")["B25001_001E"]
    missing = [t for t, g in zip(towns["town"], towns["GEOID"]) if g not in units.index or pd.isna(units[g])]
    if missing:
        raise PipelineError("town_housing_units", f"no ACS B25001_001E for {missing}")
    ctx["town_housing_units"] = {t: int(units[g]) for t, g in zip(towns["town"], towns["GEOID"])}

    for _, r in tracts[tracts["assign_method"] == "nearest"].iterrows():
        ctx.source("tract_town_nearest", GEOID=r["GEOID"], town=r["town"])
    per_town = tracts.groupby("town").size().reindex(list(CAPE_TOWNS), fill_value=0)
    print(f"       tracts_towns: {len(tracts)} Cape tracts (pop > 0), "
          f"{int((tracts['assign_method'] == 'nearest').sum())} nearest; "
          + ", ".join(f"{t} {n}" for t, n in per_town.items()))
