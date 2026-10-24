/** Pure helpers for the tract drawer tablist (WAI-ARIA tabs pattern, Req 29.1). */

export const DRAWER_TABS = ["briefing", "why", "reach"] as const;
export type DrawerTab = (typeof DRAWER_TABS)[number];

export const DRAWER_TAB_LABEL: Record<DrawerTab, string> = {
  briefing: "Briefing",
  why: "Why flagged",
  reach: "Reach",
};

/** Tab for a key press on the tablist: ArrowLeft/Right wrap, Home/End jump. Null for any other key. */
export function nextTab(current: DrawerTab, key: string): DrawerTab | null {
  const i = DRAWER_TABS.indexOf(current);
  const n = DRAWER_TABS.length;
  switch (key) {
    case "ArrowRight":
      return DRAWER_TABS[(i + 1) % n] ?? null;
    case "ArrowLeft":
      return DRAWER_TABS[(i - 1 + n) % n] ?? null;
    case "Home":
      return DRAWER_TABS[0] ?? null;
    case "End":
      return DRAWER_TABS[n - 1] ?? null;
    default:
      return null;
  }
}

/** Default tab: Reach when a check-in run exists for the tract-hour, else Briefing. */
export function defaultTab(hasRun: boolean): DrawerTab {
  return hasRun ? "reach" : "briefing";
}

/** Tab on screen: the user's pick wins; otherwise the default for the run state. */
export function shownTab(picked: DrawerTab | null, hasRun: boolean): DrawerTab {
  return picked ?? defaultTab(hasRun);
}
