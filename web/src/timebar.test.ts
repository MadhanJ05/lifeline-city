import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { barHourLabel, shortHourLabel, sparklinePath, tickPercent } from "./timebar";

describe("shortHourLabel / barHourLabel", () => {
  it("formats the key demo hours", () => {
    const keys = ["2026-02-23T09:00", "2026-02-23T17:00", "2026-02-24T09:00", "2026-02-25T15:00", "2026-02-26T13:00"];
    expect(keys.map(shortHourLabel)).toEqual(["Mon 9 AM", "Mon 5 PM", "Tue 9 AM", "Wed 3 PM", "Thu 1 PM"]);
  });
  it("handles midnight, noon and invalid keys", () => {
    expect(shortHourLabel("2026-02-27T00:00")).toBe("Fri 12 AM");
    expect(shortHourLabel("2026-02-27T12:00")).toBe("Fri 12 PM");
    expect(shortHourLabel("nope")).toBe("nope");
    expect(barHourLabel("2026-02-23T17:00")).toBe("Mon Feb 23 · 5 PM");
    expect(barHourLabel("")).toBe("");
  });
});

describe("tickPercent", () => {
  it("maps ends and handles n <= 1", () => {
    expect(tickPercent(0, 119)).toBe(0);
    expect(tickPercent(118, 119)).toBe(1);
    expect(tickPercent(59, 119)).toBeCloseTo(0.5);
    expect(tickPercent(0, 1)).toBe(0);
    expect(tickPercent(3, 0)).toBe(0);
  });
  it("is always within [0, 1]", () => {
    fc.assert(fc.property(fc.integer({ min: -500, max: 500 }), fc.integer({ min: -5, max: 500 }), (i, n) => {
      const p = tickPercent(i, n);
      return p >= 0 && p <= 1;
    }));
  });
});

describe("sparklinePath", () => {
  it("returns empty paths for no values", () => {
    expect(sparklinePath([], 100, 32)).toEqual({ line: "", area: "" });
  });
  it("draws a single value across the width", () => {
    const { line, area } = sparklinePath([5], 100, 32);
    expect(line).toBe("M0 0 L100 0");
    expect(area).toBe("M0 32 L0 0 L100 0 L100 32 Z");
  });
  it("puts the max at the top and zero on the baseline", () => {
    const { line } = sparklinePath([0, 10, 5], 100, 32);
    expect(line).toBe("M0 32 L50 0 L100 16");
  });
  it("produces well-formed paths inside the box", () => {
    fc.assert(fc.property(fc.array(fc.double({ min: -10, max: 1e6, noNaN: false }), { minLength: 1, maxLength: 150 }), (vals) => {
      const { line, area } = sparklinePath(vals, 1000, 32);
      expect(line).toMatch(/^M[\d.]+ [\d.]+( L[\d.]+ [\d.]+)+$/);
      expect(area).toMatch(/^M[\d.]+ 32( L[\d.]+ [\d.]+)+ Z$/);
      const nums = line.replace(/[ML]/g, "").trim().split(/\s+/).map(Number);
      return nums.every((x, i) => Number.isFinite(x) && x >= 0 && x <= (i % 2 === 0 ? 1000 : 32));
    }));
  });
});
