// Pure map logic: per-tract layer values, legend stops, sorting, telecom pin grouping.
// Everything is computed client-side from the timeline, so changing the hour never fetches.
import type { ExpressionSpecification } from "maplibre-gl";
import type { CapeTimeline, CapeTracts, Geoid, HourKey, TelecomEvent, Town } from "./types";

export type Layer = "priority" | "need" | "lifelines";

export const LAYERS: readonly { id: Layer; label: string }[] = [
  { id: "priority", label: "Priority" },
  { id: "need", label: "Need" },
  { id: "lifelines", label: "Lost lifelines" },
];
export const DEFAULT_LAYER: Layer = "priority";

export function layerLabel(layer: Layer): string {
  return LAYERS.find((l) => l.id === layer)?.label ?? layer;
}

// ---------------------------------------------------------------- hours

/** Integer hour index in [0, n - 1]; non-finite input maps to 0. */
export function clampHourIdx(idx: number, n: number): number {
  if (n <= 0 || !Number.isFinite(idx)) return 0;
  return Math.min(n - 1, Math.max(0, Math.round(idx)));
}

/** Demo default: the third key demo hour (2026-02-24T09:00) when present, else hour 0. */
export function defaultHourIdx(hours: readonly HourKey[], keyHours: readonly HourKey[]): number {
  const k = keyHours[2];
  const i = k === undefined ? -1 : hours.indexOf(k);
  return i >= 0 ? i : 0;
}

const HOUR_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;
const pad = (n: number) => String(n).padStart(2, "0");

/** The key one hour later ("2026-02-23T23:00" -> "2026-02-24T00:00"). Naive local-clock arithmetic;
 *  the demo window has no DST change. Invalid keys are returned unchanged. */
export function nextHourKey(key: HourKey): HourKey {
  const m = HOUR_RE.exec(key);
  if (!m) return key;
  const [y, mo, d, h, mi] = m.slice(1).map(Number) as [number, number, number, number, number];
  const t = new Date(Date.UTC(y, mo - 1, d, h + 1, mi));
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}T${pad(t.getUTCHours())}:${pad(t.getUTCMinutes())}`;
}

// ---------------------------------------------------------------- layer values

export interface TractRef {
  geoid: Geoid;
  name: string;
  town: Town;
  need_t: number | null;
}

export function tractRefs(tracts: CapeTracts): TractRef[] {
  return tracts.features.map(({ properties: p }) => ({
    geoid: p.geoid,
    name: p.name,
    town: p.town,
    need_t: Number.isFinite(p.need_t) ? p.need_t : null,
  }));
}

/** "Census Tract 101.02" -> "Tract 101.02". */
export function shortTractName(name: string): string {
  return name.replace(/^Census Tract\s+/i, "Tract ");
}

const finite = (x: number | null | undefined): number | null =>
  typeof x === "number" && Number.isFinite(x) ? x : null;

/** Town whose lost-lifelines values the tract inherits (timeline first, geometry as fallback). */
export function tractTown(ref: TractRef, timeline: CapeTimeline): Town {
  return timeline.tracts[ref.geoid]?.town ?? ref.town;
}

/** Active-layer value of one tract at one hour; null when the data has no value. */
export function tractValue(layer: Layer, ref: TractRef, hourIdx: number, timeline: CapeTimeline): number | null {
  switch (layer) {
    case "need":
      return finite(ref.need_t);
    case "priority":
      return finite(timeline.tracts[ref.geoid]?.priority[hourIdx]);
    case "lifelines":
      return finite(timeline.towns[tractTown(ref, timeline)]?.lifelines[hourIdx]);
  }
}

export function layerValues(
  layer: Layer,
  refs: readonly TractRef[],
  hourIdx: number,
  timeline: CapeTimeline,
): Map<Geoid, number | null> {
  return new Map(refs.map((r) => [r.geoid, tractValue(layer, r, hourIdx, timeline)]));
}

/** Smallest multiple of 0.1 at or above x, kept in [0.1, 1]. */
export function niceCeil(x: number): number {
  if (!Number.isFinite(x) || x <= 0) return 0.1;
  const tenths = Math.ceil(x * 10 - 1e-9);
  return Math.min(1, Math.max(1, tenths) / 10);
}

/** Upper end of the color scale. Need and Lost lifelines span [0, 1]. Priority uses the largest
 *  value over the whole replay so colors stay comparable from hour to hour. */
export function layerDomainMax(layer: Layer, timeline: CapeTimeline): number {
  if (layer !== "priority") return 1;
  let max = 0;
  for (const s of Object.values(timeline.tracts)) for (const v of s.priority) if (v > max) max = v;
  return niceCeil(max);
}

// ---------------------------------------------------------------- legend and color

/** Single-hue sequential ramps, dark to bright (design.md "Map colors"). Lightness rises
 *  monotonically, so each ramp still reads in grayscale and values are also shown as text. */
export const RAMPS: Record<Layer, readonly string[]> = {
  priority: ["#151A21", "#3A2A17", "#7A4512", "#C46A17", "#F2A541", "#FFD38A"],
  need: ["#151A21", "#2A2140", "#4B3577", "#7651B8", "#A985F0", "#D9C8FF"],
  lifelines: ["#151A21", "#3A1D22", "#6E2A2F", "#AE3B3B", "#EE5F55", "#FFA594"],
};
/** Priority ramp; kept for callers that predate per-layer ramps. */
export const RAMP: readonly string[] = RAMPS.priority;
/** Neutral dark grey for tracts with no value; distinct from every ramp's first stop. */
export const NO_VALUE_COLOR = "#2A313B";

/** Relative luminance (WCAG) of a #RRGGBB color. */
export function luminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return Number.NaN;
  const n = parseInt(m[1]!, 16);
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
}

export interface LegendStop {
  value: number;
  color: string;
  label: string;
}

/** Evenly spaced stops from 0 to max, one per ramp color, labeled with two decimals. */
export function legendStops(max: number, ramp: readonly string[] = RAMP): LegendStop[] {
  const n = ramp.length;
  return ramp.map((color, i) => {
    const value = n === 1 ? max : (max * i) / (n - 1);
    return { value, color, label: value.toFixed(2) };
  });
}

/** fill-color: interpolate the "value" feature state over the stops; grey when there is no value. */
export function fillColorExpression(stops: readonly LegendStop[]): ExpressionSpecification {
  const pairs = stops.flatMap((s) => [s.value, s.color]);
  return [
    "case",
    ["==", ["typeof", ["feature-state", "value"]], "number"],
    ["interpolate", ["linear"], ["feature-state", "value"], ...pairs],
    NO_VALUE_COLOR,
  ] as ExpressionSpecification;
}

/** "Priority 0.590"; "Priority n/a" when missing. */
export function formatLayerValue(layer: Layer, v: number | null | undefined): string {
  return `${layerLabel(layer)} ${typeof v === "number" && Number.isFinite(v) ? v.toFixed(3) : "n/a"}`;
}

export interface SortedTract {
  ref: TractRef;
  value: number | null;
}

/** Highest value first, missing values last, ties by GEOID ascending (deterministic). */
export function sortByValue(refs: readonly TractRef[], values: Map<Geoid, number | null>): SortedTract[] {
  return refs
    .map((ref) => ({ ref, value: values.get(ref.geoid) ?? null }))
    .sort((a, b) => {
      if (a.value === null || b.value === null) {
        if (a.value !== b.value) return a.value === null ? 1 : -1;
      } else if (a.value !== b.value) {
        return b.value - a.value;
      }
      return a.ref.geoid < b.ref.geoid ? -1 : a.ref.geoid > b.ref.geoid ? 1 : 0;
    });
}

// ---------------------------------------------------------------- geometry

type Bounds = [[number, number], [number, number]];

/** [[minLon, minLat], [maxLon, maxLat]] over every coordinate of the collection. */
export function bboxOf(fc: CapeTracts): Bounds {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const visit = (p: readonly number[]) => {
    const [x, y] = p;
    if (x === undefined || y === undefined) return;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  };
  for (const f of fc.features) {
    const g = f.geometry;
    if (g.type === "Polygon") g.coordinates.forEach((ring) => ring.forEach(visit));
    else g.coordinates.forEach((poly) => poly.forEach((ring) => ring.forEach(visit)));
  }
  return [[minX, minY], [maxX, maxY]];
}

// ---------------------------------------------------------------- telecom pins

/** Same rule as pipeline/telecom.py is_active: starts before the hour ends and ends after it starts. */
export function isEventActive(ev: Pick<TelecomEvent, "start_local" | "end_effective">, hour: HourKey): boolean {
  return ev.start_local < nextHourKey(hour) && ev.end_effective > hour;
}

export interface PinGroup {
  key: string;
  lon: number;
  lat: number;
  kind: "town" | "cape_wide";
  /** Town name, or "Cape-wide marker" for areas that match no Cape town. */
  caption: string;
  eventIds: string[];
}

export const CAPE_WIDE_CAPTION = "Cape-wide marker";

/** One group per pin location (several events share the Cape-wide marker), in first-seen order. */
export function pinGroups(events: readonly TelecomEvent[]): PinGroup[] {
  const groups = new Map<string, PinGroup>();
  for (const ev of events) {
    for (const pin of ev.pins) {
      const key = `${pin.lon.toFixed(5)},${pin.lat.toFixed(5)}`;
      let g = groups.get(key);
      if (!g) {
        g = {
          key,
          lon: pin.lon,
          lat: pin.lat,
          kind: pin.kind,
          caption: pin.kind === "town" && pin.town ? pin.town : CAPE_WIDE_CAPTION,
          eventIds: [],
        };
        groups.set(key, g);
      }
      if (!g.eventIds.includes(ev.id)) g.eventIds.push(ev.id);
    }
  }
  return [...groups.values()];
}

export interface PinFeatureProps {
  pin_id: string;
  event_id: string;
  group: string;
  kind: "town" | "cape_wide";
}

/** One point feature per event pin (Req 8.4). */
export function pinFeatures(groups: readonly PinGroup[]) {
  return {
    type: "FeatureCollection" as const,
    features: groups.flatMap((g) =>
      g.eventIds.map((id) => ({
        type: "Feature" as const,
        properties: { pin_id: `${id}@${g.key}`, event_id: id, group: g.key, kind: g.kind } satisfies PinFeatureProps,
        geometry: { type: "Point" as const, coordinates: [g.lon, g.lat] },
      })),
    ),
  };
}

/** "state_public_safety_radio" -> "State public safety radio". */
export function humanize(s: string): string {
  const t = s.replace(/_/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}
