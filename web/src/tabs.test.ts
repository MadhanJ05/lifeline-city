import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { DRAWER_TABS, defaultTab, nextTab, shownTab, type DrawerTab } from "./tabs";

const tabArb = fc.constantFrom<DrawerTab>(...DRAWER_TABS);

describe("nextTab", () => {
  it("moves right and left with wrap", () => {
    expect(nextTab("briefing", "ArrowRight")).toBe("why");
    expect(nextTab("reach", "ArrowRight")).toBe("briefing");
    expect(nextTab("briefing", "ArrowLeft")).toBe("reach");
  });

  it("Home and End jump to the ends", () => {
    expect(nextTab("why", "Home")).toBe("briefing");
    expect(nextTab("why", "End")).toBe("reach");
  });

  it("ignores other keys", () => {
    expect(nextTab("why", "Enter")).toBeNull();
    expect(nextTab("why", "ArrowDown")).toBeNull();
  });

  it("ArrowRight then ArrowLeft returns to the start (property)", () => {
    fc.assert(
      fc.property(tabArb, (t) => {
        const r = nextTab(t, "ArrowRight");
        expect(r).not.toBeNull();
        expect(nextTab(r as DrawerTab, "ArrowLeft")).toBe(t);
      }),
    );
  });
});

describe("defaultTab / shownTab", () => {
  it("defaults to Reach with a run, else Briefing", () => {
    expect(defaultTab(true)).toBe("reach");
    expect(defaultTab(false)).toBe("briefing");
  });

  it("a picked tab always wins", () => {
    fc.assert(
      fc.property(tabArb, fc.boolean(), (t, hasRun) => {
        expect(shownTab(t, hasRun)).toBe(t);
      }),
    );
    expect(shownTab(null, true)).toBe("reach");
  });
});
