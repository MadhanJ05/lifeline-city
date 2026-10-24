// Fixed UI labels shared across components. Provenance wording comes from privacy.md and api/data.py.

/** Out_pct label for towns with no town reports (anchor_count 0 in cape_towns.geojson, e.g. Chatham).
 *  Must match api/data.py NO_TOWN_REPORTS_LABEL; the API sends it as TractDetail.out_pct_label. */
export const NO_TOWN_REPORTS_LABEL = "Estimated from the Cape-wide share (no town reports)";

/** Provenance labels (privacy.md). The API sends the same strings in timeline.labels and
 *  sources.provenance_labels; these constants are the fallback when a key is absent. */
export const RECONSTRUCTED_LABEL = "Reconstructed from MEMA, Eversource and public-safety reports.";
export const MODELED_TELECOM_LABEL = "Modeled: assumes tower backup lasts about 8 hours";
export const ACS_CUSTOMERS_LABEL = "Estimated from ACS housing units.";

/** Badge text for every synthetic record (households, responders, check-ins, door-knock lists). */
export const SIMULATED_LABEL = "Simulated";

/** True when a town's outage values have no town reports behind them. */
export function hasNoTownReports(town: { anchor_count: number }): boolean {
  return town.anchor_count === 0;
}
