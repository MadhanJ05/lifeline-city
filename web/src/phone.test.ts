import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import {
  NO_PHONE_TEXT,
  REPLY_MAX_LENGTH,
  defaultHouseholdId,
  householdOptionLabel,
  maskPhonesInText,
  messageClassText,
  messageKindLabel,
  messageSourceLabel,
  messageTimeText,
  quickReplies,
  replyBody,
  replyErrorText,
  resolveHouseholdId,
  revealsPhone,
  toLineText,
} from "./phone";
import { LANGS, type RunMessage } from "./types";

// Reserved fictional numbers only (privacy.md): +1 617 555 0100 to +1 617 555 0199.
const last4 = fc.integer({ min: 100, max: 199 }).map((n) => String(n).padStart(4, "0"));
const fictional = last4.chain((l4) =>
  fc.constantFrom(
    `+1617555${l4}`,
    `+1 617 555 ${l4}`,
    `(617) 555-${l4}`,
    `617-555-${l4}`,
    `617.555.${l4}`,
    `+1 *** *** ${l4}`, // already masked by the API
  ),
);

const hh = (id: string, is_operator = false) => ({ id, is_operator });

const msg = (over: Partial<RunMessage>): RunMessage => ({
  direction: "out",
  kind: "checkin",
  text: "",
  at: 0,
  simulated: true,
  synthetic: true,
  ...over,
});

describe("household picker", () => {
  it("labels options with language, status and the presenter marker", () => {
    expect(householdOptionLabel({ label: "Simulated household #1", lang: "pt", status: "sent", is_operator: true }))
      .toBe("Simulated household #1 · Português · Awaiting reply · presenter");
    expect(householdOptionLabel({ label: "Simulated household #2", lang: "es", status: "ok", is_operator: false }))
      .toBe("Simulated household #2 · Español · OK");
  });

  it("defaults to the operator household, else the first, else null", () => {
    expect(defaultHouseholdId([hh("a"), hh("b", true)])).toBe("b");
    expect(defaultHouseholdId([hh("a"), hh("b")])).toBe("a");
    expect(defaultHouseholdId([])).toBeNull();
  });

  it("keeps a picked household while it is in the run, else falls back to the default", () => {
    const list = [hh("a", true), hh("b"), hh("c")];
    expect(resolveHouseholdId(list, "c")).toBe("c");
    expect(resolveHouseholdId(list, null)).toBe("a");
    expect(resolveHouseholdId(list, "gone")).toBe("a");
  });
});

describe("thread labels", () => {
  it("names each outbound kind", () => {
    expect(messageKindLabel({ kind: "checkin" })).toBe("Check-in");
    expect(messageKindLabel({ kind: "confirm" })).toBe("Confirmation");
    expect(messageKindLabel({ kind: "reprompt" })).toBe("Re-prompt");
  });

  it("tags inbound replies by source and leaves outbound untagged", () => {
    expect(messageSourceLabel(msg({ direction: "in", kind: "reply", generated: true }))).toBe("Simulated reply");
    expect(messageSourceLabel(msg({ direction: "in", kind: "reply", generated: false }))).toBe("Typed in simulator");
    expect(messageSourceLabel(msg({ direction: "out" }))).toBeNull();
  });

  it("shows the reply class as text", () => {
    expect(messageClassText(msg({ direction: "in", kind: "reply", class: "ok" }))).toBe("Understood: OK");
    expect(messageClassText(msg({ direction: "in", kind: "reply", class: "help" }))).toBe("Understood: need help");
    expect(messageClassText(msg({ direction: "in", kind: "reply", class: null }))).toBe("Not understood");
    expect(messageClassText(msg({ direction: "in", kind: "reply" }))).toBeNull();
    expect(messageClassText(msg({ direction: "out", class: "ok" }))).toBeNull();
  });

  it("formats run-relative time", () => {
    expect(messageTimeText(12.4)).toBe("at 12 s");
    expect(messageTimeText(-3)).toBe("at 0 s");
  });
});

describe("quick replies", () => {
  it("offers 1, 2 and the language's OK and help words", () => {
    expect(quickReplies("en").map((q) => q.body)).toEqual(["1", "2", "YES", "HELP"]);
    expect(quickReplies("pt").map((q) => q.body)).toEqual(["1", "2", "SIM", "AJUDA"]);
    expect(quickReplies("es").map((q) => q.body)).toEqual(["1", "2", "SÍ", "AYUDA"]);
  });

  it("gives every quick reply a distinct accessible label", () => {
    for (const lang of LANGS) {
      const labels = quickReplies(lang).map((q) => q.label);
      expect(new Set(labels).size).toBe(labels.length);
      for (const l of labels) expect(l).toMatch(/^Reply .+ \((OK|need help)\)$/);
    }
  });
});

describe("reply box", () => {
  it("trims, caps at 160 characters and rejects blank drafts", () => {
    expect(replyBody("  ajuda \n")).toBe("ajuda");
    expect(replyBody("   ")).toBeNull();
    expect(replyBody("x".repeat(200))).toHaveLength(REPLY_MAX_LENGTH);
  });

  it("explains errors", () => {
    expect(replyErrorText(new ApiError("HTTP 404", "/api/simulator/reply", 404))).toMatch(/no longer available/);
    expect(replyErrorText(new ApiError("Network error", "/api/simulator/reply", null))).toBe(
      "Could not send the reply: Network error",
    );
    expect(replyErrorText(null)).toBe("Could not send the reply.");
  });
});

describe("phone numbers", () => {
  it("masks the To: line and says when there is no phone", () => {
    expect(toLineText("+16175550123")).toBe("To: +1 *** *** 0123");
    expect(toLineText(null)).toBe(`To: ${NO_PHONE_TEXT}`);
    expect(toLineText("")).toBe(`To: ${NO_PHONE_TEXT}`);
  });

  it("detects a raw number in rendered text", () => {
    expect(revealsPhone("Call +1 617 555 0123 now", "+16175550123")).toBe(true);
    expect(revealsPhone("617-555", "+16175550123")).toBe(true);
    expect(revealsPhone("To: +1 *** *** 0123", "+16175550123")).toBe(false);
    expect(revealsPhone("Call 911 or 2-1-1", "+16175550123")).toBe(false);
  });

  it("masks phone-like runs in message text and keeps short codes", () => {
    expect(maskPhonesInText("call me at 617-555-0142")).toBe("call me at +1 *** *** 0142");
    expect(maskPhonesInText("Call 911 for emergencies, 2-1-1 for shelters and help.")).toBe(
      "Call 911 for emergencies, 2-1-1 for shelters and help.",
    );
    expect(maskPhonesInText("2")).toBe("2");
  });

  // Property 25 (Phone_Simulator half): Phone masking shows only the last four digits.
  // **Validates: Requirements 26.5**
  it("property: the To: line shows at most the last 4 digits of any fictional number", () => {
    fc.assert(
      fc.property(fictional, (phone) => {
        const line = toLineText(phone);
        const full = phone.replace(/\D/g, "");
        expect(revealsPhone(line, `+1617555${full.slice(-4)}`)).toBe(false);
        // The only digits shown are the country code and the last 4.
        expect(line.replace(/\D/g, "")).toBe(`1${full.slice(-4)}`);
        expect(line.endsWith(full.slice(-4))).toBe(true);
      }),
    );
  });
});
