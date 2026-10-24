// Pure helpers for the TractDrawer and WhyFlagged panel (Req 10.1 to 10.5, 25.3, 25.4, 29.4).
// Every value is shown as text; nothing here relies on color.
import { formatHour, formatPct, formatPercentile } from "./format";
import { MODELED_TELECOM_LABEL } from "./labels";
import type {
  ActiveTelecomEvent,
  Briefing,
  Citation,
  Component,
  Indicator,
  NeedValue,
  TelecomRule,
  TractDetail,
} from "./types";

// ---------------------------------------------------------------- briefing

export type BriefingBadge = "Verified" | "Template";

/** "Verified" only for an LLM briefing that passed the verifier (pass or regenerated);
 *  every other briefing, including the fallback, is a "Template" (Req 10.4). */
export function briefingBadge(b: Pick<Briefing, "kind">): BriefingBadge {
  return b.kind === "verified" ? "Verified" : "Template";
}

export function briefingNote(b: Pick<Briefing, "kind" | "verifier">): string {
  if (b.kind === "verified") {
    return b.verifier === "regenerated"
      ? "Every number checked against this tract-hour's metrics (regenerated once)."
      : "Every number checked against this tract-hour's metrics.";
  }
  return "Built from this tract-hour's metrics with a fixed template.";
}

// ---------------------------------------------------------------- Need indicators

export const INDICATORS: readonly Indicator[] = [
  "seniors_alone",
  "disability",
  "limited_english",
  "no_vehicle",
  "renter",
  "elec_dependent",
];

export const INDICATOR_LABEL: Record<Indicator, string> = {
  seniors_alone: "Seniors living alone",
  disability: "Disability",
  limited_english: "Limited-English households",
  no_vehicle: "No-vehicle households",
  renter: "Renter share",
  elec_dependent: "Electricity-dependent Medicare beneficiaries",
};

export const INDICATOR_SOURCE: Record<Indicator, string> = {
  seniors_alone: "ACS",
  disability: "ACS",
  limited_english: "ACS",
  no_vehicle: "ACS",
  renter: "ACS",
  elec_dependent: "HHS emPOWER",
};

export const EMPOWER_MASKING_NOTE = "emPOWER counts of 1 to 10 are reported as 11";

export function indicatorLabel(id: string): string {
  return (INDICATOR_LABEL as Record<string, string>)[id] ?? id;
}

const finite = (x: number | null | undefined): x is number => typeof x === "number" && Number.isFinite(x);

/** Raw value as text: shares as "16.8%", emPOWER as "6.9 per 1,000". Missing -> "n/a". */
export function formatNeedRaw(v: NeedValue | null | undefined): string {
  if (!v || !finite(v.raw)) return "n/a";
  if (v.unit === "per_1000") return `${v.raw.toFixed(1)} per 1,000`;
  return formatPct(v.raw, 1);
}

export interface NeedRow {
  id: Indicator;
  label: string;
  source: string;
  raw: string;
  rank: string;
  missing: boolean;
}

/** One row per Need indicator, in the fixed order; missing indicators are flagged, not dropped. */
export function needRows(d: Pick<TractDetail, "need" | "need_missing">): NeedRow[] {
  const missing = new Set<string>(d.need_missing);
  return INDICATORS.map((id) => {
    const v = d.need[id];
    const isMissing = missing.has(id) || !v || !finite(v.raw) || !finite(v.pct);
    return {
      id,
      label: INDICATOR_LABEL[id],
      source: INDICATOR_SOURCE[id],
      raw: isMissing ? "Missing" : formatNeedRaw(v),
      rank: isMissing ? "Missing" : formatPercentile(v?.pct),
      missing: isMissing,
    };
  });
}

/** Human names of the missing indicators (Req 10.1). */
export function missingIndicatorNames(d: Pick<TractDetail, "need" | "need_missing">): string[] {
  return needRows(d).filter((r) => r.missing).map((r) => r.label);
}

// ---------------------------------------------------------------- lifelines components

export const COMPONENTS: readonly Component[] = ["out_pct", "hours_dark", "wires", "telecom"];

export const COMPONENT_LABEL: Record<Component, string> = {
  out_pct: "Customers without power (out_pct)",
  hours_dark: "Hours dark (hours_dark)",
  wires: "Downed-wire calls (wires)",
  telecom: "Phones (telecom)",
};

/** The [0, 1] term each weight multiplies (scoring.md: hours_dark enters as min(h / cap, 1)). */
export function componentTerm(c: Component, comp: TractDetail["components"], hoursDarkCap: number): number {
  switch (c) {
    case "out_pct":
      return comp.out_pct;
    case "hours_dark":
      return hoursDarkCap > 0 ? Math.min(comp.hours_dark / hoursDarkCap, 1) : 0;
    case "wires":
      return comp.wires;
    case "telecom":
      return comp.telecom;
  }
}

function hoursText(h: number): string {
  return h === 1 ? "1 hour" : `${h} hours`;
}

/** Component value as text, including the raw value behind a percentile. */
export function componentValueText(c: Component, comp: TractDetail["components"], hoursDarkCap: number): string {
  switch (c) {
    case "out_pct":
      return formatPct(comp.out_pct);
    case "hours_dark":
      return comp.hours_dark > 0
        ? `${hoursText(comp.hours_dark)} (cap ${hoursDarkCap})`
        : "0 hours (not counted as dark)";
    case "wires":
      return `${formatPercentile(comp.wires)} (${comp.wires_raw.toFixed(1)} per 1,000 customers)`;
    case "telecom":
      return comp.telecom === 1 ? "1 (phones likely degraded)" : "0 (phones likely working)";
  }
}

export interface ComponentRow {
  id: Component;
  label: string;
  weight: number;
  value: string;
  term: number;
  contribution: number;
  notes: string[];
}

/** Provenance notes for out_pct and hours_dark: the out_pct label (reconstructed, or the Cape-wide
 *  share for Chatham) and, for out_pct, the ACS customers label for Sandwich and Chatham (Req 25.4). */
export function componentNotes(
  c: Component,
  d: Pick<TractDetail, "out_pct_label" | "customers_label" | "components">,
): string[] {
  const notes: string[] = [];
  if (c === "out_pct" || c === "hours_dark") {
    if (d.out_pct_label) notes.push(d.out_pct_label);
    if (d.customers_label) notes.push(d.customers_label);
  }
  if (c === "out_pct" && d.components.pinned) notes.push("Matches a reported value at this hour");
  if (c === "out_pct" && finite(d.components.lower_bound)) {
    notes.push(`At least ${formatPct(d.components.lower_bound)} (reported lower bound)`);
  }
  if (c === "wires") notes.push("Percentile rank across the 15 Cape towns at this hour");
  return notes;
}

/** Rows for the lifelines table. Contributions come from the pipeline as stored (weight × term). */
export function componentRows(
  d: Pick<TractDetail, "components" | "weights" | "contributions" | "out_pct_label" | "customers_label">,
  hoursDarkCap: number,
): ComponentRow[] {
  return COMPONENTS.map((id) => ({
    id,
    label: COMPONENT_LABEL[id],
    weight: d.weights[id] ?? 0,
    value: componentValueText(id, d.components, hoursDarkCap),
    term: componentTerm(id, d.components, hoursDarkCap),
    contribution: d.contributions[id] ?? 0,
    notes: componentNotes(id, d),
  }));
}

export function sumContributions(rows: Pick<ComponentRow, "contribution">[]): number {
  return rows.reduce((s, r) => s + r.contribution, 0);
}

/** Fixed 3-decimal number ("0.355"); "n/a" when missing. */
export function fmt3(x: number | null | undefined): string {
  return finite(x) ? x.toFixed(3) : "n/a";
}

/** Weight as written in config ("0.4"). */
export function fmtWeight(x: number | null | undefined): string {
  return finite(x) ? String(Number(x.toFixed(4))) : "n/a";
}

// ---------------------------------------------------------------- telecom rule

export interface TelecomRuleView {
  /** "Phones likely degraded (Modeled)", "Phones likely working", ... */
  headline: string;
  /** Rule that held, in words. */
  rule: string;
  /** Provenance label: the Modeled label, the observed citation text, or null. */
  label: string | null;
  citations: Citation[];
}

/** Which telecom rule held at the tract-hour (Req 10.3, 25.3). */
export function telecomRuleView(
  d: Pick<TractDetail, "telecom_rule" | "telecom_label" | "telecom_citations">,
  model: { out_pct_threshold: number; consecutive_hours: number } = { out_pct_threshold: 0.8, consecutive_hours: 8 },
): TelecomRuleView {
  const rule: TelecomRule = d.telecom_rule;
  const modeledRule = `Modeled rule: ${formatPct(model.out_pct_threshold)} or more of customers without power in each of the last ${model.consecutive_hours} hours.`;
  const observedRule = "Observed event that sets the reach flag is active.";
  switch (rule) {
    case "modeled":
      return {
        headline: "Phones likely degraded (Modeled)",
        rule: modeledRule,
        label: d.telecom_label ?? MODELED_TELECOM_LABEL,
        citations: [],
      };
    case "observed":
      return {
        headline: "Phones likely degraded (Observed)",
        rule: observedRule,
        label: d.telecom_label,
        citations: d.telecom_citations,
      };
    case "both":
      return {
        headline: "Phones likely degraded (Modeled and Observed)",
        rule: `${modeledRule} ${observedRule}`,
        label: d.telecom_label ?? MODELED_TELECOM_LABEL,
        citations: d.telecom_citations,
      };
    default:
      return {
        headline: "Phones likely working",
        rule: `No telecom rule held. The modeled rule needs ${formatPct(model.out_pct_threshold)} or more of customers without power in each of ${model.consecutive_hours} consecutive hours.`,
        label: null,
        citations: [],
      };
  }
}

// ---------------------------------------------------------------- active telecom events

/** "state_public_safety_radio" -> "State public safety radio". */
export function humanize(s: string): string {
  const t = s.replace(/_/g, " ").trim();
  return t ? t[0]!.toUpperCase() + t.slice(1) : t;
}

export function affectsText(a: ActiveTelecomEvent["affects"]): string {
  return a === "residents" ? "Residents" : "Responder systems";
}

/** "Mon Feb 23, 4 AM to Mon Feb 23, 4 PM", with the assumed-duration label when no end was reported. */
export function eventWindowText(e: Pick<ActiveTelecomEvent, "start_local" | "end_local" | "end_effective" | "end_assumed" | "end_label">): string {
  const start = formatHour(e.start_local.slice(0, 16));
  if (e.end_local && !e.end_assumed) return `${start} to ${formatHour(e.end_local.slice(0, 16))}`;
  const end = formatHour(e.end_effective.slice(0, 16));
  return `${start} to ${end} (${e.end_label ?? "Assumed duration (no end time reported)"})`;
}

/** Context note: an observed event sets the channel only when drives_reach_flag is true. */
export function eventChannelNote(e: Pick<ActiveTelecomEvent, "drives_reach_flag">): string {
  return e.drives_reach_flag
    ? "Sets the phones flag for this town."
    : "Context only: does not set the reach channel.";
}

/** Only http(s) URLs become links; anything else is shown as text. */
export function safeUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  try {
    const url = new URL(u);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}
