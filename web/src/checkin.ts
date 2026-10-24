// Pure helpers for the check-in loop in the drawer (Req 10.6, 18.7 to 18.9, 19.8, 20.2, 20.3).
// Every count and status is text; descriptive language only. Every escalation ends with a person.
import { SIMULATED_LABEL } from "./labels";
import type { Channel, HouseholdStatus, Run, RunCounters, RunHousehold } from "./types";

/** Poll cadence while a run is active (Req 18.7, tech.md). */
export const POLL_INTERVAL_MS = 2000;

/** Poll only while the run is active; a complete run (every household OK, need help or silent) stops (Req 18.8). */
export function shouldPoll(run: Pick<Run, "status"> | null | undefined): boolean {
  return run?.status === "active";
}

/** Delay before the next poll, or null to stop. */
export function nextPollDelay(run: Pick<Run, "status"> | null | undefined): number | null {
  return shouldPoll(run) ? POLL_INTERVAL_MS : null;
}

/** Hook state for useRunPolling. `initial` is the last TractDetail.run seen; `key` is the
 *  tract-hour + reset version the run belongs to. */
export interface RunSource<R = Run> {
  run: R | null;
  initial: R | null;
  key: string;
}

/** Derive the polled run from its sources. A key change (other tract or hour, or a demo reset) clears
 *  the run (Req 21.2); a new TractDetail.run replaces it; otherwise the state is returned unchanged. */
export function syncRunSource<R>(prev: RunSource<R>, initial: R | null, key: string): RunSource<R> {
  if (prev.key !== key) return { run: null, initial, key };
  if (prev.initial !== initial) return { run: initial, initial, key };
  return prev;
}

/** True when a run belongs to the tract-hour on screen. */
export function runMatches(run: Pick<Run, "geoid" | "hour"> | null | undefined, geoid: string, hour: string): boolean {
  return !!run && run.geoid === geoid && run.hour === hour;
}

// ---------------------------------------------------------------- counters and timing

/** UI names for the four counters. API "sent" means sent and still awaiting a reply. */
export const COUNTER_LABELS: Record<keyof RunCounters, string> = {
  sent: "Awaiting reply",
  ok: "OK",
  need_help: "Need help",
  silent: "Silent",
};

const COUNTER_ORDER: readonly (keyof RunCounters)[] = ["sent", "ok", "need_help", "silent"];

/** "Awaiting reply 3 · OK 5 · Need help 1 · Silent 1". */
export function countersText(c: RunCounters): string {
  return COUNTER_ORDER.map((k) => `${COUNTER_LABELS[k]} ${c[k]}`).join(" · ");
}

/** Text for the live region: counters, plus a completion note once every household has a final status. */
export function countersAnnouncement(run: Pick<Run, "counters" | "complete">): string {
  return `${countersText(run.counters)}${run.complete ? ". Check-in run complete." : ""}`;
}

function wholeSeconds(s: number): number {
  return Number.isFinite(s) ? Math.max(0, Math.round(s)) : 0;
}

/** "12 s of 30 s". Elapsed is capped at the reply window so a finished run reads "30 s of 30 s". */
export function elapsedText(elapsed_s: number, timeout_s: number): string {
  const t = wholeSeconds(timeout_s);
  return `${Math.min(wholeSeconds(elapsed_s), t)} s of ${t} s`;
}

/** Escalation time, run-relative: "at 14 s". */
export function escalationTimeText(created_at: number): string {
  return `at ${wholeSeconds(created_at)} s`;
}

/** Every escalation is assigned to a person (a simulated responder). */
export function escalationStatusText(status: string): string {
  return status === "assigned" ? `Assigned to a person (${SIMULATED_LABEL})` : `${status} (${SIMULATED_LABEL})`;
}

// ---------------------------------------------------------------- household lists

/** Silent households of a run: they need human follow-up (Req 20.3). */
export function silentHouseholds(run: Pick<Run, "households"> | null | undefined): RunHousehold[] {
  return run ? run.households.filter((h) => h.status === "silent") : [];
}

export const SILENT_REASON_TEXT: Record<NonNullable<RunHousehold["silent_reason"]>, string> = {
  no_reply: "No reply within the reply window",
  unclear_reply: "Replies were unclear; no OK or help received",
};

export function silentReasonText(reason: RunHousehold["silent_reason"]): string {
  return reason ? SILENT_REASON_TEXT[reason] : SILENT_REASON_TEXT.no_reply;
}

export const STATUS_TEXT: Record<HouseholdStatus["status"], string> = {
  sent: "Awaiting reply",
  ok: "OK",
  escalated: "Need help: assigned to a person",
  silent: "No reply: needs human follow-up",
  awaiting_door_knock: "Awaiting door knock",
  not_contacted: "Not contacted yet",
};

export function statusText(status: HouseholdStatus["status"]): string {
  return STATUS_TEXT[status] ?? status;
}

/** What the drawer lists below the Reach panel for a tract-hour.
 *  door_knock: every household awaits a door knock and none is ever silent, whatever the statuses say
 *  (phones likely degraded, so a missing reply means nothing; Req 20.2).
 *  sms: silent households from the run need human follow-up (Req 20.3). */
export interface CheckInLists {
  awaitingDoorKnock: HouseholdStatus[];
  silent: RunHousehold[];
}

export function checkInLists(channel: Channel, households: HouseholdStatus[], run: Run | null): CheckInLists {
  if (channel === "door_knock") {
    return { awaitingDoorKnock: households.map((h) => ({ ...h, status: "awaiting_door_knock" })), silent: [] };
  }
  return { awaitingDoorKnock: [], silent: silentHouseholds(run) };
}

// ---------------------------------------------------------------- send errors

export const SEND_REJECT_TEXT: Record<string, string> = {
  phones_degraded: "Phones are likely degraded here, so no check-ins were sent. Use the door-knock list.",
  no_households: "This tract has no simulated households, so no check-ins were sent.",
};

/** Text for a failed send: known 409 codes get fixed wording, anything else shows the API detail. */
export function sendErrorText(e: unknown): string {
  if (e && typeof e === "object") {
    const code = "code" in e && typeof e.code === "string" ? e.code : null;
    if (code && SEND_REJECT_TEXT[code]) return SEND_REJECT_TEXT[code];
    const detail = "detail" in e && typeof e.detail === "string" ? e.detail : null;
    const message = "message" in e && typeof e.message === "string" ? e.message : null;
    if (detail || message) return `Could not send check-ins: ${detail ?? message}`;
  }
  return "Could not send check-ins.";
}

export const SEND_EXISTS_NOTE = "Check-ins already sent for this tract-hour. Follow the run below.";
export const SEND_WAIT_NOTE = "Loading this hour…";
