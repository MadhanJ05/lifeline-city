// Pure helpers for the bottom time bar (Req 8.2, 8.3, 29.1). No DOM, no timezone conversion:
// hour keys are already America/New_York local time ("YYYY-MM-DDTHH:MM").
import { formatHour, parseHourKey } from "./format";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

function clock(hour: number, minute: number): string {
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  const suffix = hour < 12 ? "AM" : "PM";
  return minute === 0 ? `${h12} ${suffix}` : `${h12}:${String(minute).padStart(2, "0")} ${suffix}`;
}

/** "2026-02-23T17:00" -> "Mon 5 PM" (key-hour tick label). Invalid keys are returned unchanged. */
export function shortHourLabel(key: string): string {
  const p = parseHourKey(key);
  if (!p) return key;
  const weekday = WEEKDAYS[new Date(Date.UTC(p.year, p.month - 1, p.day)).getUTCDay()];
  return `${weekday} ${clock(p.hour, p.minute)}`;
}

/** "2026-02-23T17:00" -> "Mon Feb 23 · 5 PM" (big time readout). Invalid keys unchanged. */
export function barHourLabel(key: string): string {
  return parseHourKey(key) ? formatHour(key).replace(", ", " · ") : key;
}

/** Position of index idx on an n-step slider as a fraction in [0, 1]. n <= 1 -> 0. */
export function tickPercent(idx: number, n: number): number {
  if (!Number.isFinite(idx) || !Number.isFinite(n) || n <= 1) return 0;
  return Math.min(1, Math.max(0, idx / (n - 1)));
}

export interface SparkPaths {
  /** Open polyline "M x y L x y ..." ("" when there are no values). */
  line: string;
  /** Closed area under the line "M x h L ... L x h Z" ("" when there are no values). */
  area: string;
}

const r = (x: number) => Math.round(x * 100) / 100;

/** Sparkline paths for values on a width x height box. Point i sits at x = tickPercent(i, n) * width,
 *  so it lines up with the slider when the svg spans the thumb travel. Non-finite or negative values
 *  are drawn as 0; an all-zero series is a flat line on the baseline. A single value spans the width. */
export function sparklinePath(values: readonly number[], width: number, height: number): SparkPaths {
  const n = values.length;
  if (n === 0 || !(width > 0) || !(height > 0)) return { line: "", area: "" };
  const v = values.map((x) => (Number.isFinite(x) && x > 0 ? x : 0));
  const max = Math.max(...v);
  const y = (x: number) => r(max > 0 ? height - (x / max) * height : height);
  const pts: [number, number][] =
    n === 1 ? [[0, y(v[0]!)], [r(width), y(v[0]!)]] : v.map((x, i) => [r(tickPercent(i, n) * width), y(x)]);
  const line = pts.map(([px, py], i) => `${i === 0 ? "M" : "L"}${px} ${py}`).join(" ");
  const first = pts[0]!;
  const last = pts[pts.length - 1]!;
  const area = `M${first[0]} ${r(height)} ${pts.map(([px, py]) => `L${px} ${py}`).join(" ")} L${last[0]} ${r(height)} Z`;
  return { line, area };
}
