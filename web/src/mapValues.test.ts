import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  bboxOf,
  clampHourIdx,
  defaultHourIdx,
  fillColorExpression,
  formatLayerValue,
  humanize,
  isEventActive,
  layerDomainMax,
  layerValues,
  legendStops,
  LAYERS,
  nextHourKey,
  niceCeil,
  pinFeatures,
  pinGroups,
  shortTractName,
  sortByValue,
  tractRefs,
  type Layer,
  type TractRef,
} from "./mapValues";
import type { CapeTimeline, CapeTracts, TelecomEvent, TownSeries, TractSeries } from "./types";

const HOURS = ["2026-02-23T01:00", "2026-02-23T02:00", "2026-02-23T03:00"];

function townSeries(lifelines: number[]): TownSeries {
  return { lifelines, telecom_rule: lifelines.map(() => "none") } as unknown as TownSeries;
}

function timelineOf(tracts: Record<string, Partial<TractSeries>>, towns: Record<string, number[]>): CapeTimeline {
  return {
    hours: HOURS,
    key_demo_hours: [],
    labels: {},
    tracts: tracts as Record<string, TractSeries>,
    towns: Object.fromEntries(Object.entries(towns).map(([t, l]) => [t, townSeries(l)])),
  } as unknown as CapeTimeline;
}

const unit = fc.double({ min: 0, max: 1, noNaN: true });
const layerArb = fc.constantFrom<Layer>(...LAYERS.map((l) => l.id));

/** Random Cape-like data: tracts in 1 to 3 towns, every value in [0, 1]. */
const dataArb = fc
  .array(fc.record({ town: fc.constantFrom("Falmouth", "Chatham", "Truro"), need: unit,
                     priority: fc.array(unit, { minLength: 3, maxLength: 3 }) }), { minLength: 1, maxLength: 20 })
  .chain((rows) =>
    fc.record({
      rows: fc.constant(rows),
      lifelines: fc.record({
        Falmouth: fc.array(unit, { minLength: 3, maxLength: 3 }),
        Chatham: fc.array(unit, { minLength: 3, maxLength: 3 }),
        Truro: fc.array(unit, { minLength: 3, maxLength: 3 }),
      }),
    }),
  )
  .map(({ rows, lifelines }) => {
    const refs: TractRef[] = rows.map((r, i) => ({
      geoid: `25001${String(i).padStart(6, "0")}`, name: `Census Tract ${i}`, town: r.town, need_t: r.need,
    }));
    const tl = timelineOf(
      Object.fromEntries(rows.map((r, i) => [refs[i]!.geoid, { town: r.town, priority: r.priority }])),
      lifelines,
    );
    return { refs, tl };
  });

describe("layer values", () => {
  it("are in [0, 1] for every layer and hour (inputs in [0, 1])", () => {
    fc.assert(
      fc.property(dataArb, layerArb, fc.integer({ min: 0, max: 2 }), ({ refs, tl }, layer, h) => {
        for (const v of layerValues(layer, refs, h, tl).values()) {
          expect(v).not.toBeNull();
          expect(v!).toBeGreaterThanOrEqual(0);
          expect(v!).toBeLessThanOrEqual(1);
        }
      }),
    );
  });

  it("reads need_t, tract priority and the town's lifelines", () => {
    const refs: TractRef[] = [{ geoid: "A", name: "Census Tract 1", town: "Chatham", need_t: 0.7 }];
    const tl = timelineOf({ A: { town: "Chatham", priority: [0.1, 0.2, 0.3] } }, { Chatham: [0.4, 0.5, 0.6] });
    expect(layerValues("need", refs, 1, tl).get("A")).toBe(0.7);
    expect(layerValues("priority", refs, 1, tl).get("A")).toBe(0.2);
    expect(layerValues("lifelines", refs, 2, tl).get("A")).toBe(0.6);
    expect(layerValues("priority", refs, 5, tl).get("A")).toBeNull(); // out of range -> no value
  });

  it("tractRefs maps GeoJSON properties", () => {
    const fcol = {
      type: "FeatureCollection",
      features: [{ type: "Feature", properties: { geoid: "G", name: "Census Tract 9", town: "Truro", need_t: 0.5 },
                   geometry: { type: "Polygon", coordinates: [[[-70, 41.9], [-69.9, 42], [-70, 42], [-70, 41.9]]] } }],
    } as unknown as CapeTracts;
    expect(tractRefs(fcol)).toEqual([{ geoid: "G", name: "Census Tract 9", town: "Truro", need_t: 0.5 }]);
    expect(bboxOf(fcol)).toEqual([[-70, 41.9], [-69.9, 42]]);
  });
});

describe("sortByValue", () => {
  const entries = fc.uniqueArray(
    fc.record({ geoid: fc.stringMatching(/^[0-9]{11}$/), value: fc.option(unit, { nil: null }) }),
    { selector: (e) => e.geoid, maxLength: 30 },
  );
  it("sorts descending, missing last, ties by GEOID, independent of input order", () => {
    fc.assert(
      fc.property(
        entries.chain((es) => fc.tuple(fc.constant(es), fc.shuffledSubarray(es, { minLength: es.length }))),
        ([es, perm]) => {
        const refs = es.map((e) => ({ geoid: e.geoid, name: "", town: "T", need_t: null }));
        const values = new Map(es.map((e) => [e.geoid, e.value]));
        const out = sortByValue(refs, values);
        expect(out.map((r) => r.ref.geoid).sort()).toEqual(es.map((e) => e.geoid).sort());
        for (let i = 1; i < out.length; i++) {
          const a = out[i - 1]!, b = out[i]!;
          if (a.value === null) expect(b.value).toBeNull();
          if (a.value !== null && b.value !== null) {
            expect(a.value).toBeGreaterThanOrEqual(b.value);
            if (a.value === b.value) expect(a.ref.geoid < b.ref.geoid).toBe(true);
          }
          if (a.value === null && b.value === null) expect(a.ref.geoid < b.ref.geoid).toBe(true);
        }
        const shuffled = perm.map((e) => ({ geoid: e.geoid, name: "", town: "T", need_t: null }));
        expect(sortByValue(shuffled, values).map((r) => r.ref.geoid)).toEqual(out.map((r) => r.ref.geoid));
        },
      ),
    );
  });
});

describe("hours", () => {
  it("clampHourIdx returns an integer in [0, n - 1]", () => {
    fc.assert(
      fc.property(fc.oneof(fc.double(), fc.integer({ min: -500, max: 500 })), fc.integer({ min: 1, max: 200 }),
        (i, n) => {
          const c = clampHourIdx(i, n);
          expect(Number.isInteger(c)).toBe(true);
          expect(c).toBeGreaterThanOrEqual(0);
          expect(c).toBeLessThanOrEqual(n - 1);
        }),
    );
    expect(clampHourIdx(118, 119)).toBe(118);
    expect(clampHourIdx(119, 119)).toBe(118);
    expect(clampHourIdx(Number.NaN, 119)).toBe(0);
  });

  it("defaults to the third key demo hour, else 0", () => {
    const hours = ["a", "b", "c", "d"];
    expect(defaultHourIdx(hours, ["a", "b", "d"])).toBe(3);
    expect(defaultHourIdx(hours, ["a"])).toBe(0);
    expect(defaultHourIdx(hours, ["a", "b", "zz"])).toBe(0);
  });

  it("nextHourKey rolls over days and months", () => {
    expect(nextHourKey("2026-02-23T09:00")).toBe("2026-02-23T10:00");
    expect(nextHourKey("2026-02-23T23:00")).toBe("2026-02-24T00:00");
    expect(nextHourKey("2026-02-28T23:00")).toBe("2026-03-01T00:00");
    expect(nextHourKey("bad")).toBe("bad");
  });
});

describe("legend", () => {
  it("niceCeil rounds up to tenths within [0.1, 1]", () => {
    expect(niceCeil(0.595574)).toBe(0.6);
    expect(niceCeil(0.3)).toBe(0.3);
    expect(niceCeil(0)).toBe(0.1);
    expect(niceCeil(1.4)).toBe(1);
  });

  it("stops run from 0 to max, increasing, with text labels", () => {
    fc.assert(
      fc.property(fc.double({ min: 0.1, max: 1, noNaN: true }), (max) => {
        const s = legendStops(max);
        expect(s[0]!.value).toBe(0);
        expect(s[s.length - 1]!.value).toBeCloseTo(max, 12);
        for (let i = 1; i < s.length; i++) expect(s[i]!.value).toBeGreaterThan(s[i - 1]!.value);
        for (const x of s) expect(x.label).toMatch(/^\d\.\d\d$/);
      }),
    );
  });

  it("priority domain covers the largest priority in the replay", () => {
    const tl = timelineOf({ A: { town: "T", priority: [0.1, 0.59, 0.2] } }, { T: [0, 0, 0] });
    expect(layerDomainMax("priority", tl)).toBe(0.6);
    expect(layerDomainMax("need", tl)).toBe(1);
    expect(layerDomainMax("lifelines", tl)).toBe(1);
  });

  it("fill expression interpolates the value feature state", () => {
    const e = fillColorExpression(legendStops(1)) as unknown[];
    expect(e[0]).toBe("case");
    expect(JSON.stringify(e)).toContain('["feature-state","value"]');
  });

  it("formats values as text", () => {
    expect(formatLayerValue("priority", 0.59)).toBe("Priority 0.590");
    expect(formatLayerValue("lifelines", null)).toBe("Lost lifelines n/a");
    expect(shortTractName("Census Tract 101.02")).toBe("Tract 101.02");
    expect(humanize("state_public_safety_radio")).toBe("State public safety radio");
  });
});

describe("telecom pins", () => {
  const ev = (id: string, pins: TelecomEvent["pins"], start = "2026-02-23T04:18", end = "2026-02-23T16:18") =>
    ({ id, start_local: start, end_effective: end, pins }) as TelecomEvent;
  const capeWide = { kind: "cape_wide" as const, town: null, caption: "Cape-wide", lon: -70.25, lat: 41.85 };
  const bourne = { kind: "town" as const, town: "Bourne", caption: "Bourne", lon: -70.5871, lat: 41.7285 };

  it("groups events by pin location and keeps one feature per event pin", () => {
    const evs = [ev("e1", [capeWide]), ev("e2", [bourne]), ev("e3", [{ ...capeWide, caption: "Outer Cape" }]),
                 ev("e4", [bourne, capeWide])];
    const g = pinGroups(evs);
    expect(g.map((x) => [x.caption, x.eventIds])).toEqual([
      ["Cape-wide marker", ["e1", "e3", "e4"]],
      ["Bourne", ["e2", "e4"]],
    ]);
    expect(pinFeatures(g).features).toHaveLength(5);
  });

  it("is active when it starts before the hour ends and ends after it starts", () => {
    const e = ev("e", [], "2026-02-23T04:18", "2026-02-23T16:18");
    expect(isEventActive(e, "2026-02-23T03:00")).toBe(false);
    expect(isEventActive(e, "2026-02-23T04:00")).toBe(true);
    expect(isEventActive(e, "2026-02-23T16:00")).toBe(true);
    expect(isEventActive(e, "2026-02-23T17:00")).toBe(false);
  });

  it("matches a Date-based reference for whole-hour events", () => {
    const base = Date.UTC(2026, 1, 23, 0);
    const key = (h: number) => new Date(base + h * 3.6e6).toISOString().slice(0, 16);
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 118 }), fc.integer({ min: 0, max: 40 }), fc.integer({ min: 0, max: 118 }),
        (s, len, h) => {
          const e = ev("e", [], key(s), key(s + len));
          expect(isEventActive(e, key(h))).toBe(s < h + 1 && s + len > h);
        }),
    );
  });
});
