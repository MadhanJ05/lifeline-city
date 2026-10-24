// Provenance labels for what is on screen (Req 8.8, 25.3, 25.4). Pure functions.
import {
  ACS_CUSTOMERS_LABEL,
  MODELED_TELECOM_LABEL,
  NO_TOWN_REPORTS_LABEL,
  RECONSTRUCTED_LABEL,
  hasNoTownReports,
} from "./labels";
import type { Layer } from "./mapValues";
import type { CapeTimeline, CapeTowns, Sources, Town } from "./types";

export interface Badge {
  id: "need" | "reconstructed" | "modeled_telecom" | "acs_customers" | "no_town_reports" | "observed_telecom";
  label: string;
  /** What the label applies to, e.g. "Sandwich, Chatham customer counts". */
  detail: string;
}

export interface ProvenanceContext {
  timeline: Pick<CapeTimeline, "labels">;
  towns: CapeTowns;
  sources: Pick<Sources, "provenance_labels" | "acs_vintage">;
}

function label(ctx: ProvenanceContext, key: string, fallback: string): string {
  return ctx.timeline.labels[key] ?? ctx.sources.provenance_labels[key] ?? fallback;
}

/** Towns whose customer counts use the ACS housing-unit fallback (Sandwich, Chatham). */
export function acsCustomerTowns(towns: CapeTowns): Town[] {
  return towns.features.filter((f) => f.properties.customers_label).map((f) => f.properties.name);
}

/** Towns with no town reports (Chatham): out_pct is the Cape-wide share. */
export function noReportTowns(towns: CapeTowns): Town[] {
  return towns.features.filter((f) => hasNoTownReports(f.properties)).map((f) => f.properties.name);
}

/** Badges for the active layer plus the telecom pins, which are always on the map. */
export function sourceBadges(layer: Layer, ctx: ProvenanceContext): Badge[] {
  const out: Badge[] = [];
  if (layer === "need" || layer === "priority") {
    const v = ctx.sources.acs_vintage.tract;
    out.push({
      id: "need",
      label: `ACS ${v ? `${v} ` : ""}5-year and HHS emPOWER, tract percentile ranks`,
      detail: "Need",
    });
  }
  if (layer === "lifelines" || layer === "priority") {
    out.push({
      id: "reconstructed",
      label: label(ctx, "reconstructed", RECONSTRUCTED_LABEL),
      detail: "Town outage curves and hours dark",
    });
    out.push({
      id: "modeled_telecom",
      label: label(ctx, "modeled_telecom", MODELED_TELECOM_LABEL),
      detail: "Telecom term",
    });
    const acs = acsCustomerTowns(ctx.towns);
    if (acs.length) {
      out.push({
        id: "acs_customers",
        label: label(ctx, "acs_customers", ACS_CUSTOMERS_LABEL),
        detail: `${acs.join(", ")} customer counts and outage share`,
      });
    }
    const none = noReportTowns(ctx.towns);
    if (none.length) {
      out.push({ id: "no_town_reports", label: NO_TOWN_REPORTS_LABEL, detail: `${none.join(", ")} outage share` });
    }
  }
  out.push({
    id: "observed_telecom",
    label: "Observed telecom events cite their source",
    detail: "Telecom pins (select a pin for the citation)",
  });
  return out;
}

/** Extra lines for a tract tooltip: the labels that apply to the value shown. */
export function tooltipNotes(
  layer: Layer,
  town: Town,
  hourIdx: number,
  timeline: Pick<CapeTimeline, "labels" | "towns">,
  towns: CapeTowns,
): string[] {
  if (layer === "need") return [];
  const notes: string[] = [];
  const props = towns.features.find((f) => f.properties.name === town)?.properties;
  if (props && hasNoTownReports(props)) notes.push(NO_TOWN_REPORTS_LABEL);
  if (props?.customers_label) notes.push(props.customers_label);
  const rule = timeline.towns[town]?.telecom_rule[hourIdx];
  if (rule === "modeled" || rule === "both") {
    notes.push(`Phones likely degraded. ${timeline.labels.modeled_telecom ?? MODELED_TELECOM_LABEL}`);
  }
  if (rule === "observed" || rule === "both") notes.push("Observed telecom event active (see pin for source)");
  return notes;
}
