import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_LANG,
  DOOR_KNOCK_HEADING,
  LANG_LABEL,
  NOT_IN_QUEUE_CHIP,
  entryChipTexts,
  householdsText,
  langLabel,
  nextLang,
  radioLengthText,
  reachSections,
  segmentText,
} from "./reach";
import { LANGS, type Channel, type Lang } from "./types";

describe("language labels", () => {
  it("keeps accented UI labels for pt and es", () => {
    expect(LANG_LABEL).toEqual({ en: "English", pt: "Português", es: "Español" });
    expect(langLabel("pt")).toBe("Português");
    expect(langLabel("xx")).toBe("xx");
    expect(DEFAULT_LANG).toBe("en");
  });
});

describe("reachSections", () => {
  it("sms shows the preview and the send button, no door-knock list", () => {
    expect(reachSections("sms")).toEqual({ smsPreview: true, sendButton: true, doorKnockList: false, radio: true });
  });

  it("door_knock never shows the send button or SMS preview; radio always shows", () => {
    fc.assert(
      fc.property(fc.constantFrom<Channel>("sms", "door_knock"), (ch) => {
        const s = reachSections(ch);
        expect(s.radio).toBe(true);
        expect(s.sendButton).toBe(ch === "sms");
        expect(s.smsPreview).toBe(ch === "sms");
        expect(s.doorKnockList).toBe(ch === "door_knock");
      }),
    );
  });
});

describe("text helpers", () => {
  it("segment text names count and encoding", () => {
    expect(segmentText({ segments: 1, encoding: "gsm7" })).toBe("1 SMS segment, GSM-7");
    expect(segmentText({ segments: 2, encoding: "ucs2" })).toBe("2 SMS segments, UCS-2");
  });

  it("household and radio counts read as text", () => {
    expect(householdsText(1)).toBe("1 simulated household");
    expect(householdsText(12)).toBe("12 simulated households");
    expect(radioLengthText({ words: 82 })).toBe("82 words, about 30 seconds read aloud");
  });

  it("door-knock heading carries the Simulated label", () => {
    expect(DOOR_KNOCK_HEADING).toBe("Door-knock list (Simulated)");
  });

  it("entry chips: two texts, or the not-in-queue note when empty", () => {
    const chip = (text: string) => ({ text, field: "f", value: 1 });
    expect(entryChipTexts({ why_chips: [chip("a"), chip("b"), chip("c")] })).toEqual(["a", "b"]);
    expect(entryChipTexts({ why_chips: [] })).toEqual([NOT_IN_QUEUE_CHIP]);
  });
});

describe("nextLang", () => {
  it("arrows wrap, Home/End jump, other keys are ignored", () => {
    expect(nextLang("en", "ArrowRight")).toBe("pt");
    expect(nextLang("es", "ArrowRight")).toBe("en");
    expect(nextLang("en", "ArrowLeft")).toBe("es");
    expect(nextLang("pt", "Home")).toBe("en");
    expect(nextLang("pt", "End")).toBe("es");
    expect(nextLang("pt", "Enter")).toBeNull();
  });

  it("right then left returns to the start language", () => {
    fc.assert(
      fc.property(fc.constantFrom<Lang>(...LANGS), (l) => {
        expect(nextLang(nextLang(l, "ArrowRight")!, "ArrowLeft")).toBe(l);
      }),
    );
  });
});
