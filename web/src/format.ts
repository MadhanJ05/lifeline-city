// Pure formatting helpers. No Date timezone conversion anywhere: hour keys are already
// America/New_York local time ("YYYY-MM-DDTHH:MM") and are formatted as written.

const MASK_PREFIX = "+1 *** *** ";

/** Masked_Phone_Number: "+1 *** *** 1234". Only the last 4 digits survive; anything else
 *  (fewer than 4 digits, non-string input) is fully masked. Never returns the full number. */
export function maskPhone(n: unknown): string {
  const digits = typeof n === "string" || typeof n === "number" ? String(n).replace(/\D/g, "") : "";
  return MASK_PREFIX + (digits.length >= 4 ? digits.slice(-4) : "****");
}

const HOUR_KEY = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

interface ParsedHour {
  year: number;
  month: number; // 1-12
  day: number;
  hour: number; // 0-23
  minute: number;
}

/** Parse a local hour key. Returns null for anything that is not a valid "YYYY-MM-DDTHH:MM". */
export function parseHourKey(key: string): ParsedHour | null {
  const m = HOUR_KEY.exec(key);
  if (!m) return null;
  const [year, month, day, hour, minute] = m.slice(1).map(Number) as [number, number, number, number, number];
  if (month < 1 || month > 12 || hour > 23 || minute > 59) return null;
  // Date.UTC is used only as a calendar (weekday, day validity); no zone conversion happens.
  const d = new Date(Date.UTC(year, month - 1, day));
  if (d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) return null;
  return { year, month, day, hour, minute };
}

function clock(hour: number, minute: number): string {
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  const suffix = hour < 12 ? "AM" : "PM";
  return minute === 0 ? `${h12} ${suffix}` : `${h12}:${String(minute).padStart(2, "0")} ${suffix}`;
}

/** "2026-02-23T09:00" -> "Mon Feb 23, 9 AM". Invalid keys are returned unchanged. */
export function formatHour(key: string): string {
  const p = parseHourKey(key);
  if (!p) return key;
  const weekday = WEEKDAYS[new Date(Date.UTC(p.year, p.month - 1, p.day)).getUTCDay()];
  return `${weekday} ${MONTHS[p.month - 1]} ${p.day}, ${clock(p.hour, p.minute)}`;
}

/** Share in [0, 1] -> "61%". null, undefined or NaN -> "n/a". */
export function formatPct(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "n/a";
  const s = (x * 100).toFixed(digits);
  return `${Number(s) === 0 ? (0).toFixed(digits) : s}%`;
}

/** 1 -> "1st", 2 -> "2nd", 3 -> "3rd", 11 -> "11th", 22 -> "22nd". Non-integers are rounded. */
export function ordinal(n: number): string {
  const i = Math.round(n);
  const mod100 = Math.abs(i) % 100;
  const mod10 = Math.abs(i) % 10;
  const suffix = mod100 >= 11 && mod100 <= 13 ? "th" : mod10 === 1 ? "st" : mod10 === 2 ? "nd" : mod10 === 3 ? "rd" : "th";
  return `${i}${suffix}`;
}

/** Percentile rank in [0, 1] -> "86th percentile", matching the pipeline's Why_Chip wording. */
export function formatPercentile(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "n/a";
  return `${ordinal(pct * 100)} percentile`;
}
