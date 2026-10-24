// Pure helpers for the ReachPanel (Req 12.4 to 12.7, 14.7, 15.1 to 15.3, 17.10).
// Channel, rule and every count are shown as text; nothing relies on color.
import { SIMULATED_LABEL } from "./labels";
import type { Channel, Chip, DoorKnockEntry, Lang, RadioText, SmsText } from "./types";
import { LANGS } from "./types";

/** Language names for the switcher, written with their accents (Req 14.7). */
export const LANG_LABEL: Record<Lang, string> = {
  en: "English",
  pt: "Português",
  es: "Español",
};

export const DEFAULT_LANG: Lang = "en";

export function langLabel(lang: string): string {
  return (LANG_LABEL as Record<string, string>)[lang] ?? lang;
}

/** Which Reach sections show for a channel. door_knock never offers "Send check-ins" (Req 12.5, 12.6, 15.6);
 *  every channel shows the AM radio script (Req 12.7). */
export interface ReachSections {
  smsPreview: boolean;
  sendButton: boolean;
  doorKnockList: boolean;
  radio: boolean;
}

export function reachSections(channel: Channel): ReachSections {
  const sms = channel === "sms";
  return { smsPreview: sms, sendButton: sms, doorKnockList: !sms, radio: true };
}

const ENCODING_LABEL: Record<SmsText["encoding"], string> = { gsm7: "GSM-7", ucs2: "UCS-2" };

/** "1 SMS segment, GSM-7" or "2 SMS segments, UCS-2". */
export function segmentText(sms: Pick<SmsText, "segments" | "encoding">): string {
  const noun = sms.segments === 1 ? "SMS segment" : "SMS segments";
  return `${sms.segments} ${noun}, ${ENCODING_LABEL[sms.encoding] ?? sms.encoding.toUpperCase()}`;
}

/** "1 simulated household" / "12 simulated households". */
export function householdsText(n: number): string {
  return n === 1 ? "1 simulated household" : `${n} simulated households`;
}

/** "84 words, about 30 seconds read aloud". */
export function radioLengthText(r: Pick<RadioText, "words">): string {
  return `${r.words} ${r.words === 1 ? "word" : "words"}, about 30 seconds read aloud`;
}

export const SEND_NOT_CONNECTED_NOTE = "Connected in the check-in loop";
export const DOOR_KNOCK_HEADING = `Door-knock list (${SIMULATED_LABEL})`;
export const DOOR_KNOCK_EXPLANATION =
  "Phones likely degraded, so no SMS is sent and a missing reply is never counted as silence.";
export const RADIO_HEADING = "AM radio script for the county station";
export const RADIO_MISSING = "No radio script cached for this town at this hour (town not in the queue)";
export const NOT_IN_QUEUE_CHIP = "Not in the queue at this hour";

/** The two tract-level Why_Chip texts for a door-knock entry, or the not-in-queue note (Req 15.2). */
export function entryChipTexts(entry: Pick<DoorKnockEntry, "why_chips">): string[] {
  const chips: Chip[] = entry.why_chips.slice(0, 2);
  return chips.length > 0 ? chips.map((c) => c.text) : [NOT_IN_QUEUE_CHIP];
}

/** Roving selection for the language radiogroup: arrows wrap, Home/End jump. null = key not handled. */
export function nextLang(current: Lang, key: string, langs: readonly Lang[] = LANGS): Lang | null {
  const i = Math.max(0, langs.indexOf(current));
  switch (key) {
    case "ArrowRight":
    case "ArrowDown":
      return langs[(i + 1) % langs.length]!;
    case "ArrowLeft":
    case "ArrowUp":
      return langs[(i - 1 + langs.length) % langs.length]!;
    case "Home":
      return langs[0]!;
    case "End":
      return langs[langs.length - 1]!;
    default:
      return null;
  }
}
