// Pure Priority_Queue helpers. The queue for every hour is already in the static timeline
// (CapeTimeline.queue), so changing the hour never fetches (Req 8.3, 9.1).
import { shortTractName } from "./mapValues";
import type { CapeTimeline, CapeTracts, Channel, Chip, Geoid, HourKey, QueueRow } from "./types";

/** Reach_Channel as text, so the badge never relies on color alone (Req 29.4). */
export const CHANNEL_LABEL: Record<Channel, string> = {
  sms: "Text",
  door_knock: "Door-knock",
};

/** Descriptive note shown with the channel; only the door-knock channel has one. */
export const CHANNEL_NOTE: Record<Channel, string | null> = {
  sms: null,
  door_knock: "Phones likely degraded",
};

export function channelLabel(channel: Channel): string {
  return CHANNEL_LABEL[channel] ?? channel;
}

export function channelNote(channel: Channel): string | null {
  return CHANNEL_NOTE[channel] ?? null;
}

/** Queue rows for an hour in rank order (Req 9.1). Unknown hours give an empty list.
 *  Returns a new array; the timeline is never mutated. */
export function queueAt(timeline: Pick<CapeTimeline, "queue">, hour: HourKey): QueueRow[] {
  const rows = timeline.queue[hour];
  if (!rows) return [];
  return [...rows].sort((a, b) => a.rank - b.rank);
}

/** Priority as a number with 3 decimals ("0.590"); "n/a" when missing. */
export function formatPriority(p: number | null | undefined): string {
  return typeof p === "number" && Number.isFinite(p) ? p.toFixed(3) : "n/a";
}

/** The two Why_Chips shown in a queue row (Req 9.2). */
export function rowChips(row: Pick<QueueRow, "why_chips">): Chip[] {
  return row.why_chips.slice(0, 2);
}

/** One-line row reason: "<need reason> · <lifelines reason>" (empty when the row has no chips). */
export function rowReason(row: Pick<QueueRow, "why_chips">): string {
  return rowChips(row).map((c) => c.text).join(" · ");
}

/** GEOID -> short tract name ("Tract 101.02") from the tract geometry file. */
export function tractNames(tracts: CapeTracts): Map<Geoid, string> {
  return new Map(tracts.features.map((f) => [f.properties.geoid, shortTractName(f.properties.name)]));
}

/** Short tract name, falling back to "Tract {GEOID}" when the geometry file lacks the tract. */
export function tractNameOf(names: Map<Geoid, string>, geoid: Geoid): string {
  return names.get(geoid) ?? `Tract ${geoid}`;
}
