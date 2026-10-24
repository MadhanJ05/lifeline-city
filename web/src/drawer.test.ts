import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  COMPONENTS,
  briefingBadge,
  componentNotes,
  componentRows,
  componentTerm,
  eventChannelNote,
  eventWindowText,
  formatNeedRaw,
  humanize,
  missingIndicatorNames,
  needRows,
  safeUrl,
  sumContributions,
  telecomRuleView,
} from "./drawer";
import { ACS_CUSTOMERS_LABEL, MODELED_TELECOM_LABEL, NO_TOWN_REPORTS_LABEL, RECONSTRUCTED_LABEL } from "./labels";
import type { Briefing, Component, TractDetail } from "./types";

const WEIGHTS: Record<Component, number> = { out_pct: 0.4, hours_dark: 0.3, wires: 0.1, telecom: 0.2 };
const CAP = 72;

/** Chatham at 2026-02-24T09:00 from the processed timeline. */
const chatham: Pick<
  TractDetail,
  "components" | "weights" | "contributions" | "lifelines" | "out_pct_label" | "customers_label"
> = {
  components: { out_pct: 0.886626, hours_dark: 24, wires: 0.866667, wires_raw: 4.337807, telecom: 1, pinned: false, lower_bound: null },
  weights: WEIGHTS,
  contributions: { out_pct: 0.35465, hours_dark: 0.1, wires: 0.086667, telecom: 0.2 },
  lifelines: 0.741317,
  out_pct_label: NO_TOWN_REPORTS_LABEL,
  customers_label: ACS_CUSTOMERS_LABEL,
};

describe("briefingBadge", () => {
  it('is "Verified" iff kind is "verified"', () => {
    const kinds: Briefing["kind"][] = ["verified", "template"];
    const verifiers: Briefing["verifier"][] = ["pass", "regenerated", "fallback"];
    for (const kind of kinds)
      for (const verifier of verifiers)
        expect(briefingBadge({ kind, verifier } as Briefing)).toBe(kind === "verified" ? "Verified" : "Template");
  });
});

describe("Need indicators", () => {
  it("formats shares as % and emPOWER per 1,000", () => {
    expect(formatNeedRaw({ raw: 0.168, pct: 0.67, unit: "share" })).toBe("16.8%");
    expect(formatNeedRaw({ raw: 6.865988, pct: 0.29, unit: "per_1000" })).toBe("6.9 per 1,000");
    expect(formatNeedRaw({ raw: null, pct: null, unit: "share" })).toBe("n/a");
  });

  it("lists all 6 indicators and names the missing ones", () => {
    const d = {
      need: {
        seniors_alone: { raw: 0.19, pct: 0.46, unit: "share" as const },
        elec_dependent: { raw: 12.5, pct: 0.9, unit: "per_1000" as const },
      },
      need_missing: ["disability" as const],
    };
    const rows = needRows(d);
    expect(rows.map((r) => r.id)).toEqual([
      "seniors_alone",
      "disability",
      "limited_english",
      "no_vehicle",
      "renter",
      "elec_dependent",
    ]);
    expect(rows[0]).toMatchObject({ raw: "19.0%", rank: "46th percentile", missing: false });
    expect(rows[5]).toMatchObject({ raw: "12.5 per 1,000", rank: "90th percentile", missing: false });
    expect(missingIndicatorNames(d)).toEqual([
      "Disability",
      "Limited-English households",
      "No-vehicle households",
      "Renter share",
    ]);
  });
});

describe("lifelines components", () => {
  it("sample contributions sum to lifelines within 1e-6", () => {
    const rows = componentRows(chatham, CAP);
    expect(rows.map((r) => r.id)).toEqual([...COMPONENTS]);
    expect(Math.abs(sumContributions(rows) - chatham.lifelines)).toBeLessThan(1e-6);
    expect(rows.find((r) => r.id === "wires")?.value).toBe("87th percentile (4.3 per 1,000 customers)");
    expect(rows.find((r) => r.id === "hours_dark")?.value).toBe("24 hours (cap 72)");
  });

  it("weight × term matches the scoring.md lifelines formula for any inputs", () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: 1, noNaN: true }),
        fc.integer({ min: 0, max: 200 }),
        fc.double({ min: 0, max: 1, noNaN: true }),
        fc.constantFrom<0 | 1>(0, 1),
        (out_pct, hours_dark, wires, telecom) => {
          const components = { out_pct, hours_dark, wires, wires_raw: 0, telecom, pinned: false, lower_bound: null };
          const contributions = Object.fromEntries(
            COMPONENTS.map((c) => [c, WEIGHTS[c] * componentTerm(c, components, CAP)]),
          ) as Record<Component, number>;
          const rows = componentRows(
            { components, weights: WEIGHTS, contributions, out_pct_label: RECONSTRUCTED_LABEL, customers_label: null },
            CAP,
          );
          const lifelines = 0.4 * out_pct + 0.3 * Math.min(hours_dark / 72, 1) + 0.1 * wires + 0.2 * telecom;
          expect(Math.abs(sumContributions(rows) - lifelines)).toBeLessThan(1e-9);
        },
      ),
    );
  });

  it("puts the Chatham out_pct and ACS labels next to out_pct and hours_dark", () => {
    const out = componentNotes("out_pct", chatham);
    const dark = componentNotes("hours_dark", chatham);
    for (const notes of [out, dark]) {
      expect(notes).toContain(NO_TOWN_REPORTS_LABEL);
      expect(notes).toContain(ACS_CUSTOMERS_LABEL);
    }
    expect(componentNotes("telecom", chatham)).toEqual([]);
  });
});

describe("telecom rule", () => {
  it("labels the modeled rule and lists observed citations", () => {
    const modeled = telecomRuleView({ telecom_rule: "modeled", telecom_label: MODELED_TELECOM_LABEL, telecom_citations: [] });
    expect(modeled.headline).toBe("Phones likely degraded (Modeled)");
    expect(modeled.label).toBe(MODELED_TELECOM_LABEL);

    const c = { event_id: "tel_99", system: "cell", source_name: "Report", source_url: "https://example.org/r" };
    const observed = telecomRuleView({ telecom_rule: "observed", telecom_label: "Observed: cell (Report)", telecom_citations: [c] });
    expect(observed.citations).toEqual([c]);

    const none = telecomRuleView({ telecom_rule: "none", telecom_label: null, telecom_citations: [] });
    expect(none.headline).toBe("Phones likely working");
    expect(none.label).toBeNull();
  });
});

describe("active telecom events", () => {
  it("shows the assumed-duration label when no end was reported", () => {
    const e = {
      start_local: "2026-02-23T04:18",
      end_local: null,
      end_effective: "2026-02-23T16:18",
      end_assumed: true,
      end_label: "Assumed duration: 12 hours (no end time reported)",
    };
    expect(eventWindowText(e)).toBe(
      "Mon Feb 23, 4:18 AM to Mon Feb 23, 4:18 PM (Assumed duration: 12 hours (no end time reported))",
    );
    expect(eventChannelNote({ drives_reach_flag: false })).toMatch(/does not set the reach channel/);
    expect(humanize("state_public_safety_radio")).toBe("State public safety radio");
  });

  it("links only http(s) sources", () => {
    expect(safeUrl("https://example.org/a")).toBe("https://example.org/a");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("")).toBeNull();
  });
});
