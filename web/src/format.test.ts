import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { apiUnreachableText, apiUrl } from "./api";
import { formatHour, formatPct, formatPercentile, maskPhone, ordinal, parseHourKey } from "./format";
import { NO_TOWN_REPORTS_LABEL, hasNoTownReports } from "./labels";

// Reserved fictional numbers only (privacy.md): +1 617 555 0100 to +1 617 555 0199.
const fictional = fc.integer({ min: 100, max: 199 }).chain((n) =>
  fc.constantFrom(`+1617555${String(n).padStart(4, "0")}`, `+1 617 555 ${String(n).padStart(4, "0")}`,
                  `(617) 555-${String(n).padStart(4, "0")}`),
);
const MASKED = /^\+1 \*\*\* \*\*\* (\d{4}|\*{4})$/;

describe("maskPhone", () => {
  it("keeps only the last 4 digits", () => {
    expect(maskPhone("+16175550123")).toBe("+1 *** *** 0123");
    expect(maskPhone("+1 617 555 0199")).toBe("+1 *** *** 0199");
  });

  it("fully masks short, empty and non-string input", () => {
    expect(maskPhone("")).toBe("+1 *** *** ****");
    expect(maskPhone("12")).toBe("+1 *** *** ****");
    expect(maskPhone(null)).toBe("+1 *** *** ****");
    expect(maskPhone(undefined)).toBe("+1 *** *** ****");
    expect(maskPhone({ n: "+16175550123" })).toBe("+1 *** *** ****");
  });

  // Property 25 (web half): Phone masking shows only the last four digits.
  // **Validates: Requirements 26.5**
  it("property: never leaks more than 4 consecutive input digits and ends with the last 4", () => {
    fc.assert(
      fc.property(fc.oneof(fictional, fc.string(), fc.stringMatching(/^[+\d ()-]{0,20}$/)), (input) => {
        const out = maskPhone(input);
        expect(out).toMatch(MASKED);
        const digits = input.replace(/\D/g, "");
        if (digits.length >= 4) expect(out.endsWith(digits.slice(-4))).toBe(true);
        // No 5-digit window of the input appears in the output, and the output has one 4-digit run at most.
        for (let i = 0; i + 5 <= digits.length; i++) expect(out).not.toContain(digits.slice(i, i + 5));
        expect(out.slice(3)).not.toMatch(/\d{5}/);
      }),
    );
  });
});

describe("formatHour", () => {
  it("formats local hour keys without timezone conversion", () => {
    expect(formatHour("2026-02-23T09:00")).toBe("Mon Feb 23, 9 AM");
    expect(formatHour("2026-02-23T01:00")).toBe("Mon Feb 23, 1 AM");
    expect(formatHour("2026-02-24T00:00")).toBe("Tue Feb 24, 12 AM");
    expect(formatHour("2026-02-25T12:00")).toBe("Wed Feb 25, 12 PM");
    expect(formatHour("2026-02-27T23:00")).toBe("Fri Feb 27, 11 PM");
    expect(formatHour("2026-02-25T15:30")).toBe("Wed Feb 25, 3:30 PM");
  });

  it("returns invalid keys unchanged", () => {
    expect(formatHour("2026-02-30T09:00")).toBe("2026-02-30T09:00");
    expect(formatHour("2026-02-23 09:00")).toBe("2026-02-23 09:00");
    expect(formatHour("")).toBe("");
  });

  // **Validates: Requirements 8.2**
  it("property: stable, well-formed and keeps the key's own hour", () => {
    const key = fc
      .record({
        day: fc.integer({ min: 0, max: 365 * 3 }),
        hour: fc.integer({ min: 0, max: 23 }),
      })
      .map(({ day, hour }) => {
        const d = new Date(Date.UTC(2025, 0, 1 + day));
        const ymd = d.toISOString().slice(0, 10);
        return `${ymd}T${String(hour).padStart(2, "0")}:00`;
      });
    fc.assert(
      fc.property(key, (k) => {
        const out = formatHour(k);
        expect(formatHour(k)).toBe(out);
        expect(out).toMatch(/^(Sun|Mon|Tue|Wed|Thu|Fri|Sat) [A-Z][a-z]{2} \d{1,2}, \d{1,2} (AM|PM)$/);
        const p = parseHourKey(k)!;
        const h12 = p.hour % 12 === 0 ? 12 : p.hour % 12;
        expect(out.endsWith(`, ${h12} ${p.hour < 12 ? "AM" : "PM"}`)).toBe(true);
        expect(out).toContain(` ${p.day},`);
      }),
    );
  });

  it("gives every hour of the Cape timeline a distinct label", () => {
    const labels = new Set<string>();
    for (let i = 0; i < 119; i++) {
      const d = new Date(Date.UTC(2026, 1, 23, 1 + i));
      labels.add(formatHour(d.toISOString().slice(0, 16)));
    }
    expect(labels.size).toBe(119);
  });
});

describe("formatPct, ordinal, formatPercentile", () => {
  it("formats shares as percents", () => {
    expect(formatPct(0.614583)).toBe("61%");
    expect(formatPct(1)).toBe("100%");
    expect(formatPct(0.001492, 1)).toBe("0.1%");
    expect(formatPct(-0.000001)).toBe("0%");
    expect(formatPct(null)).toBe("n/a");
    expect(formatPct(Number.NaN)).toBe("n/a");
  });

  it("builds English ordinals", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 100, 101, 111].map(ordinal)).toEqual([
      "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "100th", "101st", "111th",
    ]);
  });

  it("matches the pipeline's percentile wording", () => {
    expect(formatPercentile(0.857143)).toBe("86th percentile");
    expect(formatPercentile(1)).toBe("100th percentile");
    expect(formatPercentile(null)).toBe("n/a");
  });
});

describe("api and labels", () => {
  it("builds encoded API URLs and the unreachable banner text", () => {
    expect(apiUrl("/api/tracts/25001010100", { hour: "2026-02-23T09:00" }, "http://localhost:8000")).toBe(
      "http://localhost:8000/api/tracts/25001010100?hour=2026-02-23T09%3A00",
    );
    expect(apiUnreachableText("http://localhost:8000")).toBe("API not reachable at http://localhost:8000");
  });

  it("labels towns with no town reports", () => {
    expect(NO_TOWN_REPORTS_LABEL).toBe("Estimated from the Cape-wide share (no town reports)");
    expect(hasNoTownReports({ anchor_count: 0 })).toBe(true);
    expect(hasNoTownReports({ anchor_count: 2 })).toBe(false);
  });
});
