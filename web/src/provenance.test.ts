import { describe, expect, it } from "vitest";
import {
  ACS_CUSTOMERS_LABEL,
  MODELED_TELECOM_LABEL,
  NO_TOWN_REPORTS_LABEL,
  RECONSTRUCTED_LABEL,
} from "./labels";
import { sourceBadges, tooltipNotes } from "./provenance";
import type { CapeTimeline, CapeTowns } from "./types";

const town = (name: string, anchor_count: number, customers_label: string | null) => ({
  type: "Feature" as const,
  properties: { name, anchor_count, customers_label },
  geometry: { type: "Polygon" as const, coordinates: [] },
});
const towns = {
  type: "FeatureCollection",
  features: [town("Falmouth", 2, null), town("Sandwich", 2, ACS_CUSTOMERS_LABEL), town("Chatham", 0, ACS_CUSTOMERS_LABEL)],
} as unknown as CapeTowns;
const labels = {
  reconstructed: RECONSTRUCTED_LABEL,
  modeled_telecom: MODELED_TELECOM_LABEL,
  acs_customers: ACS_CUSTOMERS_LABEL,
};
const timeline = {
  labels,
  towns: {
    Falmouth: { telecom_rule: ["none", "modeled"] },
    Chatham: { telecom_rule: ["none", "none"] },
  },
} as unknown as CapeTimeline;
const ctx = { timeline, towns, sources: { provenance_labels: {}, acs_vintage: { tract: 2024 } } };

describe("sourceBadges", () => {
  it("lists the outage, telecom, ACS-customer and no-reports labels for Priority and Lost lifelines", () => {
    for (const layer of ["priority", "lifelines"] as const) {
      const b = sourceBadges(layer, ctx);
      const byId = Object.fromEntries(b.map((x) => [x.id, x]));
      expect(byId.reconstructed?.label).toBe(RECONSTRUCTED_LABEL);
      expect(byId.modeled_telecom?.label).toBe(MODELED_TELECOM_LABEL);
      expect(byId.acs_customers?.label).toBe(ACS_CUSTOMERS_LABEL);
      expect(byId.acs_customers?.detail).toContain("Sandwich, Chatham");
      expect(byId.no_town_reports?.label).toBe(NO_TOWN_REPORTS_LABEL);
      expect(byId.no_town_reports?.detail).toContain("Chatham");
      expect(byId.observed_telecom).toBeDefined();
    }
  });

  it("shows only Need and telecom-pin sources on the Need layer", () => {
    expect(sourceBadges("need", ctx).map((b) => b.id)).toEqual(["need", "observed_telecom"]);
  });

  it("falls back to the fixed labels when the data has no label keys", () => {
    const b = sourceBadges("lifelines", { ...ctx, timeline: { labels: {} } });
    expect(b.find((x) => x.id === "reconstructed")?.label).toBe(RECONSTRUCTED_LABEL);
  });
});

describe("tooltipNotes", () => {
  it("adds the no-reports and ACS labels for Chatham on Lost lifelines", () => {
    expect(tooltipNotes("lifelines", "Chatham", 0, timeline, towns)).toEqual([NO_TOWN_REPORTS_LABEL, ACS_CUSTOMERS_LABEL]);
  });
  it("adds the modeled telecom label when the modeled rule fired", () => {
    expect(tooltipNotes("priority", "Falmouth", 0, timeline, towns)).toEqual([]);
    expect(tooltipNotes("priority", "Falmouth", 1, timeline, towns)[0]).toContain(MODELED_TELECOM_LABEL);
  });
  it("adds nothing on the Need layer", () => {
    expect(tooltipNotes("need", "Chatham", 0, timeline, towns)).toEqual([]);
  });
});
