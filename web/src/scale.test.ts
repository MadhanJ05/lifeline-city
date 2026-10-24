import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  BOSTON_ENTRY_ID,
  CAPE_ENTRY_ID,
  PREVIEW_BADGE,
  entryOptionLabel,
  entryView,
  previewModel,
  tierText,
  viewForId,
} from "./scale";
import type { CatalogEntry } from "./types";

const NEED = ["seniors living alone", "disability"];

function entry(over: Partial<CatalogEntry>): CatalogEntry {
  return {
    id: "plymouth_noreaster",
    place: "Plymouth",
    hazard: "noreaster",
    hazard_label: "Nor'easter",
    tier: 1,
    mode: "preview",
    lost_lifelines_inputs: ["power", "phones", "blocked roads"],
    need_inputs: NEED,
    label: "Configuration preview",
    ...over,
  };
}

const cape = entry({ id: CAPE_ENTRY_ID, place: "Barnstable County (Cape Cod)", hazard: "blizzard", hazard_label: "Blizzard", mode: "live", label: undefined, data_endpoint: "/api/tracts" });
const bostonPreview = entry({ id: BOSTON_ENTRY_ID, place: "Boston", hazard: "blizzard", hazard_label: "Blizzard", tier: 2 });

describe("entryOptionLabel", () => {
  it("shows place, hazard and tier", () => {
    expect(entryOptionLabel(cape)).toBe("Barnstable County (Cape Cod) — Blizzard (Tier 1)");
    expect(entryOptionLabel(bostonPreview)).toBe("Boston — Blizzard (Tier 2)");
  });
});

describe("entryView", () => {
  it("cape opens the map", () => {
    expect(entryView(cape)).toEqual({ kind: "cape" });
  });
  it("boston is a preview while its mode is preview (Req 23.12)", () => {
    expect(entryView(bostonPreview)).toEqual({ kind: "preview", entryId: BOSTON_ENTRY_ID });
  });
  it("live boston opens the Boston switch point", () => {
    expect(entryView({ ...bostonPreview, mode: "live" })).toEqual({ kind: "boston", entryId: BOSTON_ENTRY_ID });
  });
  it("other entries open a preview", () => {
    expect(entryView(entry({}))).toEqual({ kind: "preview", entryId: "plymouth_noreaster" });
  });
  it("unknown id falls back to the Cape map", () => {
    expect(viewForId([cape, bostonPreview], "nope")).toEqual({ kind: "cape" });
    expect(viewForId([cape, bostonPreview], BOSTON_ENTRY_ID).kind).toBe("preview");
  });
});

describe("tierText", () => {
  it("explains both tiers", () => {
    expect(tierText(1)).toContain("every Massachusetts town");
    expect(tierText(2)).toContain("Voice (311 silence)");
  });
});

describe("previewModel", () => {
  it("lists tier and inputs for the hazard", () => {
    const m = previewModel(entry({ hazard: "flood", hazard_label: "Flood", place: "Lowell", lost_lifelines_inputs: ["flood zones", "river gauges", "road closures"] }));
    expect(m.heading).toBe("Lowell: Flood");
    expect(m.badge).toBe(PREVIEW_BADGE);
    expect(m.tierLabel).toBe("Tier 1");
    expect(m.lostLifelinesInputs).toEqual(["flood zones", "river gauges", "road closures"]);
    expect(m.needInputs).toEqual(NEED);
    expect(m.noScoresText).toContain("No scores are shown");
  });

  // Previews never expose scores: whatever extra numeric fields an entry carries, the only number
  // in the view model is the tier, and no score-like key is copied (Req 24.5).
  it("has no numeric field other than tier, for any entry", () => {
    const word = fc.string({ minLength: 1, maxLength: 20 });
    fc.assert(
      fc.property(
        fc.record({
          place: word,
          hazard_label: word,
          tier: fc.constantFrom(1 as const, 2 as const),
          need_inputs: fc.array(word, { maxLength: 6 }),
          lost_lifelines_inputs: fc.array(word, { maxLength: 4 }),
          extra: fc.dictionary(fc.constantFrom("score", "priority", "need_t", "silence_t", "lifelines"), fc.double()),
        }),
        ({ extra, ...fields }) => {
          const e = { ...entry(fields), ...extra } as CatalogEntry;
          const m = previewModel(e);
          const numeric = Object.entries(m).filter(([, v]) => typeof v === "number");
          expect(numeric).toEqual([["tier", fields.tier]]);
          for (const k of Object.keys(extra)) expect(k in m).toBe(false);
          for (const v of [...m.needInputs, ...m.lostLifelinesInputs]) expect(typeof v).toBe("string");
        },
      ),
    );
  });
});
