import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  channelLabel,
  channelNote,
  formatPriority,
  queueAt,
  rowChips,
  tractNameOf,
  tractNames,
} from "./queue";
import type { CapeTimeline, CapeTracts, Channel, QueueRow } from "./types";

const H = "2026-02-24T09:00";

function row(rank: number, geoid: string, channel: Channel = "sms"): QueueRow {
  return {
    rank,
    geoid,
    town: "Falmouth",
    priority: 0.5,
    need_t: 0.5,
    channel,
    why_chips: [
      { text: "Seniors living alone, 98th percentile", field: "need.seniors_alone.pct", value: 0.98 },
      { text: "100% without power", field: "out_pct", value: 1 },
      { text: "extra", field: "hours_dark", value: 3 },
    ],
  };
}

describe("channel labels", () => {
  it("names each channel in text", () => {
    expect(channelLabel("sms")).toBe("SMS check-ins");
    expect(channelLabel("door_knock")).toBe("Door-knock list");
  });

  it("notes degraded phones only for door-knock", () => {
    expect(channelNote("door_knock")).toBe("Phones likely degraded");
    expect(channelNote("sms")).toBeNull();
  });
});

describe("queueAt", () => {
  it("returns rows in rank order without mutating the timeline", () => {
    const rows = [row(3, "c"), row(1, "a"), row(2, "b")];
    const timeline = { queue: { [H]: rows } } as Pick<CapeTimeline, "queue">;
    expect(queueAt(timeline, H).map((r) => r.geoid)).toEqual(["a", "b", "c"]);
    expect(rows.map((r) => r.geoid)).toEqual(["c", "a", "b"]);
  });

  it("returns an empty list for an unknown hour", () => {
    expect(queueAt({ queue: {} }, H)).toEqual([]);
  });

  it("is a rank-ordered permutation of the stored rows for any order", () => {
    fc.assert(
      fc.property(fc.shuffledSubarray([...Array(10).keys()].map((i) => i + 1), { minLength: 0 }), (ranks) => {
        const rows = ranks.map((r) => row(r, `g${r}`));
        const out = queueAt({ queue: { [H]: rows } }, H);
        expect(out).toHaveLength(rows.length);
        expect(out.map((r) => r.rank)).toEqual([...ranks].sort((a, b) => a - b));
      }),
    );
  });
});

describe("formatPriority", () => {
  it("shows 3 decimals", () => {
    expect(formatPriority(0.590239)).toBe("0.590");
    expect(formatPriority(0)).toBe("0.000");
    expect(formatPriority(null)).toBe("n/a");
    expect(formatPriority(Number.NaN)).toBe("n/a");
  });

  it("round-trips any priority in [0, 1] within 0.0005", () => {
    fc.assert(
      fc.property(fc.double({ min: 0, max: 1, noNaN: true }), (p) => {
        const s = formatPriority(p);
        expect(s).toMatch(/^[01]\.\d{3}$/);
        expect(Math.abs(Number(s) - p)).toBeLessThanOrEqual(0.0005 + 1e-12);
      }),
    );
  });
});

describe("row helpers", () => {
  it("shows the first two Why_Chips", () => {
    expect(rowChips(row(1, "a")).map((c) => c.field)).toEqual(["need.seniors_alone.pct", "out_pct"]);
  });

  it("looks up short tract names with a GEOID fallback", () => {
    const tracts = {
      features: [{ properties: { geoid: "25001014800", name: "Census Tract 148" } }],
    } as unknown as CapeTracts;
    const names = tractNames(tracts);
    expect(tractNameOf(names, "25001014800")).toBe("Tract 148");
    expect(tractNameOf(names, "25001999999")).toBe("Tract 25001999999");
  });
});
