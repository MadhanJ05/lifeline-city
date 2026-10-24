import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { ApiError, parseErrorDetail } from "./api";
import {
  POLL_INTERVAL_MS,
  SEND_REJECT_TEXT,
  checkInLists,
  countersAnnouncement,
  countersText,
  elapsedText,
  escalationStatusText,
  escalationTimeText,
  nextPollDelay,
  runMatches,
  sendErrorText,
  shouldPoll,
  silentHouseholds,
  silentReasonText,
  syncRunSource,
} from "./checkin";
import { LANGS, type HouseholdStatus, type Run, type RunHousehold, type RunHouseholdStatus } from "./types";

const RUN_STATUSES: RunHouseholdStatus[] = ["sent", "ok", "escalated", "silent"];
const ALL_STATUSES: HouseholdStatus["status"][] = [...RUN_STATUSES, "awaiting_door_knock", "not_contacted"];

const household = (n: number, status: RunHouseholdStatus): RunHousehold => ({
  id: `hh-${n}`,
  label: `Simulated household #${n}`,
  number: n,
  lang: LANGS[n % 3]!,
  status,
  is_operator: n === 1,
  phone: null,
  messages: [],
  reprompts: 0,
  unrecognized: 0,
  escalation_id: null,
  silent_reason: status === "silent" ? "no_reply" : null,
  synthetic: true,
});

const makeRun = (statuses: RunHouseholdStatus[], status: Run["status"] = "active"): Run => ({
  id: "run-1",
  geoid: "25001010100",
  town: "Falmouth",
  hour: "2026-02-23T09:00",
  telecom: 0,
  created_at: 1000,
  elapsed_s: 0,
  timeout_s: 30,
  households: statuses.map((s, i) => household(i + 1, s)),
  counters: { sent: 0, ok: 0, need_help: 0, silent: 0 },
  complete: status === "complete",
  status,
  synthetic: true,
  escalations: [],
});

const statusesArb = fc.array(fc.constantFrom(...RUN_STATUSES), { maxLength: 20 });

describe("polling", () => {
  it("shouldPoll is true iff the run status is active", () => {
    fc.assert(
      fc.property(fc.constantFrom<Run["status"]>("active", "complete"), (status) => {
        const run = makeRun(["sent"], status);
        expect(shouldPoll(run)).toBe(status === "active");
        expect(nextPollDelay(run)).toBe(status === "active" ? POLL_INTERVAL_MS : null);
      }),
    );
    expect(shouldPoll(null)).toBe(false);
    expect(shouldPoll(undefined)).toBe(false);
    expect(POLL_INTERVAL_MS).toBe(2000);
  });

  it("syncRunSource clears on a key change, adopts a new initial run, else keeps state", () => {
    const a = makeRun(["sent"]);
    const b = makeRun(["ok"], "complete");
    const prev = { run: a, initial: null, key: "g|h|0" };
    expect(syncRunSource(prev, null, "g|h|0")).toBe(prev); // a sent run survives re-renders
    expect(syncRunSource(prev, null, "g|h|1")).toEqual({ run: null, initial: null, key: "g|h|1" }); // reset
    expect(syncRunSource(prev, b, "g|h|0").run).toBe(b); // detail refetch carries a run
  });

  it("runMatches compares tract and hour", () => {
    const r = makeRun([]);
    expect(runMatches(r, r.geoid, r.hour)).toBe(true);
    expect(runMatches(r, r.geoid, "2026-02-23T10:00")).toBe(false);
    expect(runMatches(null, r.geoid, r.hour)).toBe(false);
  });
});

describe("counters and times", () => {
  it("countersText labels sent as Awaiting reply and shows every count as text", () => {
    expect(countersText({ sent: 3, ok: 5, need_help: 1, silent: 2 })).toBe(
      "Awaiting reply 3 · OK 5 · Need help 1 · Silent 2",
    );
    fc.assert(
      fc.property(fc.nat(500), fc.nat(500), fc.nat(500), fc.nat(500), (sent, ok, need_help, silent) => {
        expect(countersText({ sent, ok, need_help, silent })).toBe(
          `Awaiting reply ${sent} · OK ${ok} · Need help ${need_help} · Silent ${silent}`,
        );
      }),
    );
  });

  it("announces completion only when complete", () => {
    const c = { sent: 0, ok: 1, need_help: 0, silent: 0 };
    expect(countersAnnouncement({ counters: c, complete: false })).toBe(countersText(c));
    expect(countersAnnouncement({ counters: c, complete: true })).toMatch(/Check-in run complete\.$/);
  });

  it("escalationTimeText is 'at N s' with N the rounded non-negative seconds", () => {
    fc.assert(
      fc.property(fc.double({ min: 0, max: 1e5, noNaN: true }), (s) => {
        expect(escalationTimeText(s)).toBe(`at ${Math.round(s)} s`);
      }),
    );
    expect(escalationTimeText(14.4)).toBe("at 14 s");
    expect(escalationTimeText(Number.NaN)).toBe("at 0 s");
    expect(escalationStatusText("assigned")).toBe("Assigned to a person (Simulated)");
  });

  it("elapsedText caps elapsed at the reply window", () => {
    expect(elapsedText(12.2, 30)).toBe("12 s of 30 s");
    expect(elapsedText(95, 30)).toBe("30 s of 30 s");
  });
});

describe("household lists", () => {
  it("silentHouseholds returns exactly the silent households, in order", () => {
    fc.assert(
      fc.property(statusesArb, (statuses) => {
        const run = makeRun(statuses);
        const silent = silentHouseholds(run);
        expect(silent.every((h) => h.status === "silent")).toBe(true);
        expect(silent.map((h) => h.id)).toEqual(run.households.filter((h) => h.status === "silent").map((h) => h.id));
      }),
    );
    expect(silentHouseholds(null)).toEqual([]);
    expect(silentReasonText("unclear_reply")).toMatch(/unclear/);
    expect(silentReasonText(null)).toMatch(/No reply/);
  });

  it("door_knock never yields silent households, and every household awaits a door knock", () => {
    const hhArb = fc.array(
      fc.record({
        id: fc.string({ minLength: 1, maxLength: 6 }),
        label: fc.constant("Simulated household #1"),
        lang: fc.constantFrom(...LANGS),
        status: fc.constantFrom(...ALL_STATUSES),
        synthetic: fc.constant(true as const),
      }),
      { maxLength: 15 },
    );
    fc.assert(
      fc.property(hhArb, fc.option(statusesArb, { nil: null }), (households, runStatuses) => {
        const lists = checkInLists("door_knock", households, runStatuses ? makeRun(runStatuses) : null);
        expect(lists.silent).toEqual([]);
        expect(lists.awaitingDoorKnock).toHaveLength(households.length);
        expect(lists.awaitingDoorKnock.every((h) => h.status === "awaiting_door_knock")).toBe(true);
      }),
    );
  });

  it("sms lists the run's silent households and no door-knock statuses", () => {
    const run = makeRun(["ok", "silent", "sent", "silent"]);
    const lists = checkInLists("sms", [], run);
    expect(lists.awaitingDoorKnock).toEqual([]);
    expect(lists.silent.map((h) => h.number)).toEqual([2, 4]);
  });
});

describe("send errors", () => {
  it("parses string and {code, message} details", () => {
    expect(parseErrorDetail({ detail: "not found" })).toEqual({ code: null, message: "not found" });
    expect(parseErrorDetail({ detail: { code: "phones_degraded", message: "use the door-knock list" } })).toEqual({
      code: "phones_degraded",
      message: "use the door-knock list",
    });
    expect(parseErrorDetail(null)).toEqual({ code: null, message: null });
  });

  it("maps 409 codes to fixed wording and falls back to the API detail", () => {
    const degraded = new ApiError("HTTP 409", "/api/checkins/send", 409, "phones_degraded", "x");
    expect(sendErrorText(degraded)).toBe(SEND_REJECT_TEXT.phones_degraded);
    const none = new ApiError("HTTP 409", "/api/checkins/send", 409, "no_households", "x");
    expect(sendErrorText(none)).toBe(SEND_REJECT_TEXT.no_households);
    const other = new ApiError("HTTP 404 for /api/checkins/send", "/api/checkins/send", 404, null, "unknown tract");
    expect(sendErrorText(other)).toBe("Could not send check-ins: unknown tract");
    expect(sendErrorText(new ApiError("Network error", "/x", null))).toBe("Could not send check-ins: Network error");
  });
});
