// Pure helpers for the PhoneSimulator (Req 14.8, 17.10, 18.4, 18.5, 26.5).
// The "Simulated" label and the sender name live outside the message body; every phone number
// on screen goes through maskPhone. Reply keywords mirror config/languages.yaml (reply_keywords).
import { escalationTimeText, statusText } from "./checkin";
import { maskPhone } from "./format";
import { SIMULATED_LABEL } from "./labels";
import { langLabel } from "./reach";
import type { Lang, RunHousehold, RunMessage } from "./types";

export const SIMULATOR_HEADING = `Phone simulator (${SIMULATED_LABEL})`;
export const SENDER_NAME = "Lifeline City";
export const NO_PHONE_TEXT = "Simulated household (no real phone)";
export const REPLY_HINT = "Reply 1 if OK, 2 if you need help. Words like AJUDA or AYUDA also work.";
export const NO_RUN_SMS_NOTE = "Send check-ins to open the phone simulator.";
export const NO_RUN_DOOR_KNOCK_NOTE = "Phones likely degraded: no SMS.";
/** Same limit as the API ReplyRequest body (one SMS). */
export const REPLY_MAX_LENGTH = 160;

// ---------------------------------------------------------------- household picker

/** "Simulated household #1 · Português · Awaiting reply · presenter". */
export function householdOptionLabel(h: Pick<RunHousehold, "label" | "lang" | "status" | "is_operator">): string {
  const parts = [h.label, langLabel(h.lang), statusText(h.status)];
  if (h.is_operator) parts.push("presenter");
  return parts.join(" · ");
}

/** Default household: the operator household (#1), else the first one, else null. */
export function defaultHouseholdId(households: readonly Pick<RunHousehold, "id" | "is_operator">[]): string | null {
  return (households.find((h) => h.is_operator) ?? households[0])?.id ?? null;
}

/** Keep the picked household while it is still in the run (polls refresh the run); otherwise the default. */
export function resolveHouseholdId(
  households: readonly Pick<RunHousehold, "id" | "is_operator">[],
  selected: string | null,
): string | null {
  if (selected !== null && households.some((h) => h.id === selected)) return selected;
  return defaultHouseholdId(households);
}

// ---------------------------------------------------------------- phone numbers

/** The "To:" line. A phone (already masked by the API) is masked again; no phone means no real number. */
export function toLineText(phone: string | null | undefined): string {
  return `To: ${phone ? maskPhone(phone) : NO_PHONE_TEXT}`;
}

function digitsOf(s: string): string {
  return s.replace(/\D/g, "");
}

/** Runs of digits that read as one number: digits joined only by spaces, dots, dashes or parentheses. */
const DIGIT_RUN = /\d(?:[\s().-]*\d)*/g;

/** True when `rendered` shows more of `phone` than its last 4 digits: any 5 consecutive digits of the
 *  number (country code included) appear in one digit run of the text. Use it to check rendered output. */
export function revealsPhone(rendered: string, phone: string): boolean {
  const full = digitsOf(phone);
  if (full.length <= 4) return false;
  for (const run of rendered.match(DIGIT_RUN) ?? []) {
    const d = digitsOf(run);
    for (let i = 0; i + 5 <= d.length; i++) {
      if (full.includes(d.slice(i, i + 5))) return true;
    }
  }
  return false;
}

/** Mask anything in free text that looks like a phone number (7 or more digits in one run), e.g. a
 *  number typed into the reply box. Short codes such as 911, 2-1-1 and 311 stay as written. */
export function maskPhonesInText(text: string): string {
  return text.replace(DIGIT_RUN, (run) => (digitsOf(run).length >= 7 ? maskPhone(run) : run));
}

// ---------------------------------------------------------------- thread

const KIND_LABEL: Record<RunMessage["kind"], string> = {
  checkin: "Check-in",
  confirm: "Confirmation",
  reprompt: "Re-prompt",
  reply: "Reply",
};

export function messageKindLabel(m: Pick<RunMessage, "kind">): string {
  return KIND_LABEL[m.kind] ?? m.kind;
}

/** Inbound only: who wrote the reply. Seeded replies are "Simulated reply"; the presenter's are typed here. */
export function messageSourceLabel(m: Pick<RunMessage, "direction" | "generated">): string | null {
  if (m.direction !== "in") return null;
  return m.generated ? `${SIMULATED_LABEL} reply` : "Typed in simulator";
}

/** Inbound only: how the API classified the reply. `class: null` means not understood; absent means unknown. */
export function messageClassText(m: Pick<RunMessage, "direction" | "class">): string | null {
  if (m.direction !== "in" || m.class === undefined) return null;
  if (m.class === "ok") return "Understood: OK";
  if (m.class === "help") return "Understood: need help";
  return "Not understood";
}

/** Run-relative time: "at 12 s". */
export function messageTimeText(at: number): string {
  return escalationTimeText(at);
}

/** Thread label for the log region. */
export function threadLabel(h: Pick<RunHousehold, "label">): string {
  return `Messages with ${h.label} (${SIMULATED_LABEL})`;
}

// ---------------------------------------------------------------- reply box

export interface QuickReply {
  body: string;
  /** Accessible name, e.g. "Reply AJUDA (need help)". */
  label: string;
}

/** Display forms of the reply keywords in config/languages.yaml. The API ignores case and accents,
 *  so "SÍ" is shown with its accent (UI text keeps accents, Req 14.7). */
const KEYWORDS: Record<Lang, { ok: string; help: string }> = {
  en: { ok: "YES", help: "HELP" },
  pt: { ok: "SIM", help: "AJUDA" },
  es: { ok: "SÍ", help: "AYUDA" },
};

/** "1", "2", then the language's OK and help words. */
export function quickReplies(lang: Lang): QuickReply[] {
  const k = KEYWORDS[lang] ?? KEYWORDS.en;
  return [
    { body: "1", label: "Reply 1 (OK)" },
    { body: "2", label: "Reply 2 (need help)" },
    { body: k.ok, label: `Reply ${k.ok} (OK)` },
    { body: k.help, label: `Reply ${k.help} (need help)` },
  ];
}

/** Body sent to the API, or null when there is nothing to send. */
export function replyBody(draft: string): string | null {
  const body = draft.trim().slice(0, REPLY_MAX_LENGTH);
  return body.length > 0 ? body : null;
}

export function replyLabel(h: Pick<RunHousehold, "label">): string {
  return `Reply as ${h.label}`;
}

/** Text for a failed reply post. */
export function replyErrorText(e: unknown): string {
  if (e && typeof e === "object") {
    const status = "status" in e && typeof e.status === "number" ? e.status : null;
    if (status === 404) return "This check-in run is no longer available. Send check-ins again.";
    const detail = "detail" in e && typeof e.detail === "string" ? e.detail : null;
    const message = "message" in e && typeof e.message === "string" ? e.message : null;
    if (detail || message) return `Could not send the reply: ${detail ?? message}`;
  }
  return "Could not send the reply.";
}
