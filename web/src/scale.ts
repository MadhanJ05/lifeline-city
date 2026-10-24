// Scale selector logic (Req 24, 23.12): entry labels, which view an entry opens, tier text, and the
// Configuration_Preview view model. Previews never carry scores: the view model is built from a
// whitelist of catalog fields, and its only number is the tier.
import type { CatalogEntry } from "./types";

export const CAPE_ENTRY_ID = "cape_blizzard";
export const BOSTON_ENTRY_ID = "boston_blizzard";
export const PREVIEW_BADGE = "Configuration preview";
export const BACK_TO_CAPE_LABEL = "Back to Cape Cod blizzard";
export const SELECTOR_LABEL = "Place and hazard";
/** Shown for a live non-Cape entry (Boston) until the Boston Voice view exists (task 16). */
export const BOSTON_PLACEHOLDER_TEXT = "Boston Voice view is not built in this build.";

/** Which main view an entry opens. "boston" is the switch point for BostonVoiceView (task 16). */
export type View = { kind: "cape" } | { kind: "boston"; entryId: string } | { kind: "preview"; entryId: string };

/** Option text: "{place} — {hazard_label} (Tier {tier})". */
export function entryOptionLabel(e: Pick<CatalogEntry, "place" | "hazard_label" | "tier">): string {
  return `${e.place} — ${e.hazard_label} (Tier ${e.tier})`;
}

/** Cape opens the map. A live non-Cape entry (Boston once its Voice file exists) opens the Boston
 *  view. Everything else, Boston included while it is a preview, opens a Configuration_Preview. */
export function entryView(e: Pick<CatalogEntry, "id" | "mode">): View {
  if (e.id === CAPE_ENTRY_ID) return { kind: "cape" };
  if (e.mode === "live") return { kind: "boston", entryId: e.id };
  return { kind: "preview", entryId: e.id };
}

/** View for a selected entry id; an unknown id falls back to the Cape map. */
export function viewForId(entries: readonly CatalogEntry[], id: string): View {
  const e = entries.find((x) => x.id === id);
  return e ? entryView(e) : { kind: "cape" };
}

/** Tier explanation (product.md tiers). */
export function tierText(tier: 1 | 2): string {
  return tier === 2
    ? "Tier 2: Need, Lost lifelines and Reach, plus Voice (311 silence). For cities with open 311 data."
    : "Tier 1: Need, Lost lifelines and Reach. Works in every Massachusetts town.";
}

export interface PreviewModel {
  id: string;
  heading: string;
  badge: string;
  tier: 1 | 2;
  tierLabel: string;
  tierText: string;
  needInputs: string[];
  lostLifelinesInputs: string[];
  noScoresText: string;
}

/** Configuration_Preview view model. Only whitelisted, descriptive fields are copied, so any score a
 *  catalog entry might carry never reaches the preview (Req 24.5, 24.6). */
export function previewModel(e: CatalogEntry): PreviewModel {
  return {
    id: e.id,
    heading: `${e.place}: ${e.hazard_label}`,
    badge: e.label ?? PREVIEW_BADGE,
    tier: e.tier,
    tierLabel: `Tier ${e.tier}`,
    tierText: tierText(e.tier),
    needInputs: [...e.need_inputs],
    lostLifelinesInputs: [...e.lost_lifelines_inputs],
    noScoresText: `No scores are shown because no data is loaded for ${e.place} and ${e.hazard_label.toLowerCase()}. This preview lists the inputs Lifeline would use.`,
  };
}

/** Reset control status text (Req 21.2). */
export const RESET_LABEL = "Reset demo";
export const RESET_DONE_TEXT = "Demo state reset";
export function resetErrorText(message: string): string {
  return `Could not reset the demo: ${message}`;
}
