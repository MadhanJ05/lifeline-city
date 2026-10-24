"""Step 3 `need`: six Need_Indicators, percentile ranks and need_t per Cape tract (Req 2.1 to 2.6).

Formulas: .kiro/steering/scoring.md. Reused by the Boston block (need_scores on Boston tracts only).

Output in ctx:
  need  DataFrame indexed by GEOID: raw <k> for each INDICATORS entry, pct_<k>, need_t, need_missing (list),
        dme_allocated, medicare_benes_allocated, empower_masked (a masked ZIP feeds elec_dependent)
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from pipeline import fetch
from pipeline.common import PipelineError, pct_rank

INDICATORS = ("seniors_alone", "disability", "limited_english", "no_vehicle", "renter", "elec_dependent")
METRIC = 26986  # NAD83 / Massachusetts Mainland, metres
EMPOWER_COUNTS = ("Power_Dependent_Devices_DME", "Medicare_Benes")
MASKED_VALUE = 11  # emPOWER reports counts of 1 to 10 as 11 (Req 2.6)
MASK_MIN_WEIGHT = 1e-3  # a masked ZIP flags a tract only if > 0.1% of the ZIP lies in it (ignores edge slivers)

# Pinned ACS IDs (fetch checks each against the vintage's groups/<TABLE>.json and records its label).
ACS_VARS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {  # indicator: (numerator terms, denominator)
    "seniors_alone": (("B11010_005E", "B11010_012E"), ("B11001_001E",)),
    "limited_english": (("C16002_004E", "C16002_007E", "C16002_010E", "C16002_013E"), ("C16002_001E",)),
    "no_vehicle": (("B25044_003E", "B25044_010E"), ("B25044_001E",)),
    "renter": (("B25003_003E",), ("B25003_001E",)),
}
DISABILITY_PCT = "S1810_C03_001E"
POPULATION = "B01003_001E"
NEED_ACS_VARS = tuple(sorted({v for num, den in ACS_VARS.values() for v in num + den} | {DISABILITY_PCT, POPULATION}))


def check_acs_vars(labels: dict[str, str]) -> None:
    """Fail loudly unless every pinned ID was fetched and found in the vintage's variable list."""
    missing = [v for v in NEED_ACS_VARS if v not in fetch.ACS_TRACT_VARS or v not in labels]
    if missing:
        raise PipelineError("acs_variables", f"pinned Need variables not verified for the vintage: {missing}")


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den.where(den != 0)).astype(float)


def indicator_values(acs: pd.DataFrame, elec_per_1000: pd.Series) -> pd.DataFrame:
    """Raw indicator values indexed like `acs` (GEOID index). ACS sentinel negatives and zero
    denominators become NaN; a NaN numerator term makes the indicator NaN."""
    a = acs[list(NEED_ACS_VARS)].apply(pd.to_numeric, errors="coerce")
    a = a.where(a >= 0)
    out = pd.DataFrame(index=acs.index)
    for k, (num, den) in ACS_VARS.items():
        out[k] = _ratio(a[list(num)].sum(axis=1, min_count=len(num)), a[den[0]])
    out["disability"] = a[DISABILITY_PCT] / 100
    out["elec_dependent"] = elec_per_1000.reindex(acs.index).astype(float)
    return out[list(INDICATORS)]


def allocate_zip_counts(zips: gpd.GeoDataFrame, tracts: gpd.GeoDataFrame) -> pd.DataFrame:
    """Area-weighted ZIP -> tract allocation in EPSG:26986, indexed by tract GEOID.

    W[z,t] = area(z ∩ t) / area(z); allocated_t = Σ_z count_z · W[z,t], so a ZIP shared with a
    neighboring county contributes only its in-tract share. Counts of 11 are used as reported and
    flagged: <count>_masked is True when a ZIP with that count = 11 has W[z,t] > MASK_MIN_WEIGHT.
    Null ZIP counts contribute nothing; a tract with no non-null overlapping ZIP gets NaN.
    """
    z = zips[["Zip_Code", *EMPOWER_COUNTS, "geometry"]].to_crs(METRIC).copy()
    z["geometry"] = z.geometry.make_valid()
    for c in EMPOWER_COUNTS:
        z[c] = pd.to_numeric(z[c], errors="coerce")
    z["zip_area"] = z.geometry.area
    t = tracts[["GEOID", "geometry"]].to_crs(METRIC).copy()
    t["geometry"] = t.geometry.make_valid()
    ov = gpd.overlay(z, t, how="intersection", keep_geom_type=True)
    w = ov.geometry.area / ov["zip_area"]
    idx = pd.Index(tracts["GEOID"], name="GEOID")
    out = pd.DataFrame(index=idx)
    for c in EMPOWER_COUNTS:
        out[c] = (ov[c] * w).groupby(ov["GEOID"]).sum(min_count=1).reindex(idx)
        out[f"{c}_masked"] = ((ov[c] == MASKED_VALUE) & (w > MASK_MIN_WEIGHT)).groupby(ov["GEOID"]).any() \
            .reindex(idx, fill_value=False).astype(bool)
    return out


def need_scores(raw: pd.DataFrame) -> pd.DataFrame:
    """pct_<k> ranked within the rows passed in (one region); need_t = mean of the non-null pct_<k>;
    need_missing = indicators whose raw value is NaN (Req 2.2 to 2.4)."""
    out = raw[list(INDICATORS)].astype(float).copy()
    pct = pd.DataFrame({f"pct_{k}": pct_rank(out[k]) for k in INDICATORS}, index=out.index)
    out = out.join(pct)
    out["need_t"] = pct.mean(axis=1, skipna=True)
    isna = raw[list(INDICATORS)].isna().to_numpy()
    out["need_missing"] = [[k for k, m in zip(INDICATORS, row) if m] for row in isna]
    return out


def step(ctx) -> None:
    labels = {e["id"]: e["label"] for e in ctx.sources.get("acs_variables", []) if e.get("geo") == "tract"}
    check_acs_vars(labels)
    tracts = ctx["cape_tracts"]
    zips = ctx["empower_zips"]
    alloc = allocate_zip_counts(zips, tracts)
    pop = tracts.set_index("GEOID")["population"].astype(float)
    dme = alloc["Power_Dependent_Devices_DME"]
    elec = dme / pop.where(pop > 0) * 1000

    acs = ctx["acs_tract"].set_index("GEOID").reindex(tracts["GEOID"])
    need = need_scores(indicator_values(acs, elec))
    need["dme_allocated"] = dme
    need["medicare_benes_allocated"] = alloc["Medicare_Benes"]
    need["empower_masked"] = alloc["Power_Dependent_Devices_DME_masked"]
    need.index.name = "GEOID"
    ctx["need"] = need

    # ZIP-level masked flags (aggregate public data) for ZIPs overlapping Cape tracts.
    cape = tracts.to_crs(METRIC).union_all()
    zm = zips.to_crs(METRIC)
    touching = zm[zm.geometry.intersection(cape).area > 0]
    dme_z = pd.to_numeric(touching["Power_Dependent_Devices_DME"], errors="coerce")
    masked = sorted(touching.loc[dme_z == MASKED_VALUE, "Zip_Code"])
    for zc in masked:
        ctx.source("empower_masked_zips", Zip_Code=zc, field="Power_Dependent_Devices_DME")

    missing = {k: int(sum(k in m for m in need["need_missing"])) for k in INDICATORS}
    missing = {k: n for k, n in missing.items() if n}
    print(f"       need: {len(need)} tracts, need_t {need['need_t'].min():.3f}..{need['need_t'].max():.3f}; "
          f"missing {missing or 'none'}; masked ZIPs {len(masked)}/{len(touching)}, "
          f"masked tracts {int(need['empower_masked'].sum())}")
