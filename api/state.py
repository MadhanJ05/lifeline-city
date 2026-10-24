"""In-memory check-in state (design.md "Check-in state machine (`api/state.py`)").

`CheckInStore` holds every Check_In_Run, reply and Escalation for one API process (Req 18.10). It is
guarded by a `threading.Lock` because FastAPI runs sync endpoints on a thread pool, and it reads time only
through an injected clock so tests can drive it with a fake one. Every run, message and Escalation it
holds carries `synthetic: true` (Req 17.9).

`CheckInState` is the holder that lives on `app.state.checkins`. Endpoints always go through
`state.store`, so `reset()` can swap in a fresh, empty `CheckInStore` atomically (Req 21.1). The read-only
processed data (`app.state.store`) is never touched by a reset.

Per-household state machine:

    sent --1/OK--> ok          sent --2/HELP--> escalated (one Escalation + confirmation)
    sent --?--> sent           (first unrecognized reply gets the one re-prompt; later ones are recorded)
    sent --timeout--> silent   (only when the run telecom is 0, Req 20.1)
    silent --1/OK--> ok        silent --2/HELP--> escalated     (a late recognized reply replaces silent)
    ok --2/HELP--> escalated   escalated stays escalated

Decisions (documented here so `api/main.py`, the web app and the tests agree):

- Time. `created_at` on a run is the store clock value at send (monotonic scale, only differences
  matter). Every other time in a run record (message `at`, Escalation `created_at`, `elapsed_s`,
  `timeout_s`) is seconds since the run started, for the UI.
- Advancing is lazy: `get_run`, `run_for`, `send` (existing run) and `process_reply` call `advance`
  first, under the lock. Scheduled replies are applied in due order at their scheduled time; the timeout
  is applied in between, so a reply due after the timeout counts as late. No background threads.
- Counters are status counts: `sent` (awaiting a reply), `ok`, `need_help` (escalated) and `silent`.
  They always sum to the number of households. The run is `complete` when no household is still `sent`.
- Generated replies come from `seeded_schedule`, which depends only on (seed, geoid, hour), so a rerun
  after a reset replays the same replies. The operator household (#`demo.operator_household`) never gets
  one; the presenter replies for it in the Phone_Simulator. Once the operator replies for any household,
  that household's pending generated replies are dropped (Req 18.6: generated replies only for households
  not driven by the operator).
- Escalations go to the town's responders from `api.reach.town_responders` (config order), round-robin by
  escalation order within the town across runs.
- Phone numbers: with a Twilio sender, household #1..n map to `DEMO_PHONE_NUMBERS` in order and the raw
  number is passed only to the Sender. Run records only ever hold `mask_phone(number)`, and only when a
  number is actually used; with the simulator `phone` is None.
"""
from __future__ import annotations

import copy
import random
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from api.data import NotFound
from api.sms import (OutboundMessage, Sender, SimulatorSender, classify, demo_phone_numbers, make_sender,
                     mask_phone, reply_keywords, reply_timeout_seconds)

if TYPE_CHECKING:
    from api.data import Household, Store

Clock = Callable[[], float]
"""Seconds on a monotonic scale. Only differences matter (reply delays and the reply timeout)."""

HouseholdStatus = Literal["sent", "ok", "escalated", "silent"]
ReplyKind = Literal["ok", "help", "unclear", "none"]
RejectCode = Literal["phones_degraded", "no_households"]

TERMINAL: frozenset[str] = frozenset({"ok", "escalated", "silent"})
REPLY_KINDS: tuple[ReplyKind, ...] = ("ok", "help", "unclear", "none")
SIMULATED = "Simulated"

# Unrecognized bodies for generated "unclear" replies, per language. Checked against `classify` when the
# schedule is drawn; anything that would classify falls back to "?".
UNCLEAR_BODIES: Mapping[str, tuple[str, ...]] = {
    "en": ("?", "what?", "who is this"),
    "pt": ("?", "oi?", "quem e?"),
    "es": ("?", "hola?", "quien es?"),
}


class Rejected(Exception):
    """A send the API refuses: `phones_degraded` (door_knock tract-hour) or `no_households` (Req 15.6)."""

    def __init__(self, code: RejectCode, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code: RejectCode = code
        self.detail = detail or code


class CheckInError(RuntimeError):
    """The processed data cannot support a run (missing SMS text for a language, or no responders)."""


# ---------------------------------------------------------------- pure helpers


class Delays(NamedTuple):
    lo: float
    hi: float
    clamped: bool


def effective_delays(reply_delay_s: Sequence[float], timeout_s: float) -> Delays:
    """Reply delay range kept strictly below the reply timeout.

    When `max(reply_delay_s) >= timeout_s` both ends are capped at 0.9 * timeout and `clamped` is True,
    so the caller (API startup) can log a warning. Negative values become 0 and the ends are ordered.
    """
    lo, hi = (float(x) for x in reply_delay_s)
    lo, hi = max(0.0, min(lo, hi)), max(0.0, max(lo, hi))
    if hi < timeout_s:
        return Delays(lo, hi, False)
    cap = 0.9 * float(timeout_s)
    return Delays(min(lo, cap), cap, True)


@dataclass(frozen=True)
class ScheduledReply:
    household_id: str
    kind: ReplyKind
    delay_s: float
    body: str | None          # None for kind "none"


def seeded_schedule(seed: Any, geoid: str, hour: str, households: Sequence[Household],
                    reply_mix: Mapping[str, float], delays: tuple[float, float],
                    keywords: Mapping[str, Mapping[str, Sequence[str]]],
                    operator_number: int | None) -> list[ScheduledReply]:
    """Generated replies for one tract-hour, from `random.Random(f"{seed}:{geoid}:{hour}")` only.

    One draw per non-operator household in household-number order: a kind from `reply_mix` (weights in
    the fixed order ok, help, unclear, none), a delay uniform in `delays`, and a body: "1" or an OK
    keyword, "2" or a help keyword (from the household's language), or an unrecognized body. Every draw
    is made even for kind "none" so one household's kind never shifts another's delay.
    """
    rng = random.Random(f"{seed}:{geoid}:{hour}")
    weights = [max(0.0, float(reply_mix.get(k, 0.0))) for k in REPLY_KINDS]
    if sum(weights) <= 0:
        weights = [0.0, 0.0, 0.0, 1.0]
    lo, hi = delays
    out: list[ScheduledReply] = []
    for hh in sorted(households, key=lambda h: h.number):
        if hh.is_operator or hh.number == operator_number:
            continue
        kind: ReplyKind = rng.choices(REPLY_KINDS, weights=weights)[0]
        delay = rng.uniform(lo, hi)
        words = keywords.get(hh.lang, {})
        options = {
            "ok": ("1", *words.get("ok", ())),
            "help": ("2", *words.get("help", ())),
            "unclear": UNCLEAR_BODIES.get(hh.lang, ("?",)),
            "none": ("",),
        }[kind]
        body: str | None = rng.choice(options)
        if kind == "none":
            body = None
        elif kind == "unclear" and classify(body, keywords) is not None:
            body = "?"
        out.append(ScheduledReply(hh.id, kind, delay, body))
    return out


def status_counters(households: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    """{sent, ok, need_help, silent} as status counts; they sum to the number of households."""
    statuses = [h["status"] for h in households.values()]
    return {"sent": statuses.count("sent"), "ok": statuses.count("ok"),
            "need_help": statuses.count("escalated"), "silent": statuses.count("silent")}


# ---------------------------------------------------------------- per-run internals


@dataclass
class _Pending:
    household_id: str
    due: float                # store clock value
    body: str


@dataclass
class _RunPlan:
    """What `advance` needs without the Store: texts, keywords, responders, and pending replies."""

    started_at: float
    timeout_s: float
    town: str
    keywords: Mapping[str, Mapping[str, Sequence[str]]]
    texts: Mapping[str, Mapping[str, str]]           # lang -> {confirm, reprompt}
    responders: tuple[tuple[str, str], ...]          # (id, label), config order
    phones: Mapping[str, str]                        # household_id -> raw number, Twilio sender only
    pending: list[_Pending] = field(default_factory=list)
    timed_out: bool = False


# ---------------------------------------------------------------- store


class CheckInStore:
    """Check-in runs, replies and Escalations for the demo, in memory only.

    State:
      * `runs`: run_id -> run record (JSON-ready; see `send`).
      * `run_ids`: (geoid, hour) -> run_id, so a repeated send on a tract-hour returns the existing run.
      * `escalations`: escalation_id -> Escalation record (routed to a simulated responder).
      * `counters`: monotonically increasing id counters for runs and escalations.
      * `plans`: run_id -> internal `_RunPlan` (pending generated replies, timing, texts).

    All mutation happens with `lock` held. `now()` is the single source of time. A new store is empty,
    which is exactly the state at API start.
    """

    def __init__(self, clock: Clock = time.monotonic, sender: Sender | None = None,
                 timeout_s: float | None = None, phones: Sequence[str] | None = None) -> None:
        self.lock = threading.Lock()
        self.clock = clock
        self.sender: Sender = sender if sender is not None else SimulatorSender()
        self.timeout_s = float(timeout_s if timeout_s is not None else reply_timeout_seconds())
        self._phones: tuple[str, ...] = tuple(phones) if phones is not None else demo_phone_numbers()
        self.runs: dict[str, dict[str, Any]] = {}
        self.run_ids: dict[tuple[str, str], str] = {}
        self.escalations: dict[str, dict[str, Any]] = {}
        self.counters: dict[str, int] = {"run": 0, "escalation": 0}
        self.plans: dict[str, _RunPlan] = {}

    def now(self) -> float:
        return self.clock()

    def snapshot(self) -> dict[str, Any]:
        """A comparable copy of the whole state; a fresh store's snapshot is the API-start state."""
        with self.lock:
            return {
                "runs": copy.deepcopy(self.runs),
                "run_ids": dict(self.run_ids),
                "escalations": copy.deepcopy(self.escalations),
                "counters": dict(self.counters),
                "pending": {rid: [(p.household_id, p.due, p.body) for p in plan.pending]
                            for rid, plan in self.plans.items()},
            }

    # ------------------------------------------------------------ public API

    def send(self, store: Store, geoid: str, hour: str) -> tuple[dict[str, Any], bool]:
        """Start a Check_In_Run for tract-hour (geoid, hour); returns (run, created).

        Raises `NotFound` for an unknown tract or hour, `Rejected("phones_degraded")` on a door_knock
        tract-hour (no message, no run; Req 15.6), `Rejected("no_households")` for a tract without
        Synthetic_Households, and `CheckInError` when the data lacks SMS text or responders.
        """
        th = store.tract_hour(geoid, hour)
        if th["channel"] == "door_knock" or th["telecom"] != 0:
            raise Rejected("phones_degraded", f"phones likely degraded in {th['town']} at {hour}; "
                                              "use the door-knock list")
        households = store.households_for(geoid)
        if not households:
            raise Rejected("no_households", f"tract {geoid} has no simulated households")

        with self.lock:
            existing = self.run_ids.get((geoid, hour))
            if existing is not None:
                self._advance(existing)
                return copy.deepcopy(self.runs[existing]), False

        plan, schedule, checkins = self._prepare(store, geoid, hour, th["town"], households)

        with self.lock:
            existing = self.run_ids.get((geoid, hour))   # lost a race with a concurrent send
            if existing is not None:
                self._advance(existing)
                return copy.deepcopy(self.runs[existing]), False
            now = self.now()
            plan.started_at = now
            self.counters["run"] += 1
            run_id = f"run-{self.counters['run']}"
            run: dict[str, Any] = {
                "id": run_id, "geoid": geoid, "town": th["town"], "hour": hour, "telecom": th["telecom"],
                "created_at": now, "elapsed_s": 0.0, "timeout_s": plan.timeout_s,
                "households": {}, "counters": {}, "complete": False, "status": "active",
                "synthetic": True,
            }
            for hh in households:
                phone = plan.phones.get(hh.id)
                run["households"][hh.id] = {
                    "id": hh.id, "label": hh.label, "number": hh.number, "lang": hh.lang,
                    "status": "sent", "is_operator": bool(hh.is_operator), "phone": phone and mask_phone(phone),
                    "messages": [], "reprompts": 0, "unrecognized": 0, "escalation_id": None,
                    "silent_reason": None, "synthetic": True,
                }
            self.runs[run_id] = run
            self.run_ids[(geoid, hour)] = run_id
            self.plans[run_id] = plan
            for hh in households:
                self._send_out(run, hh.id, "checkin", checkins[hh.lang], 0.0)
            by_id = {hh.id: hh for hh in households}
            plan.pending = sorted((_Pending(s.household_id, now + s.delay_s, s.body)
                                   for s in schedule if s.body is not None),
                                  key=lambda p: (p.due, by_id[p.household_id].number))
            self._refresh(run)
            return copy.deepcopy(run), True

    def get_run(self, run_id: str) -> dict[str, Any]:
        """The run after `advance`. Raises `NotFound` for an unknown run id."""
        with self.lock:
            self._require(run_id)
            self._advance(run_id)
            return copy.deepcopy(self.runs[run_id])

    advance = get_run
    """`advance(run_id)`: deliver due replies, apply the timeout, refresh counters; returns the run."""

    def run_for(self, geoid: str, hour: str) -> dict[str, Any] | None:
        """The advanced run for a tract-hour, or None if no check-in was sent there."""
        with self.lock:
            run_id = self.run_ids.get((geoid, hour))
            if run_id is None:
                return None
            self._advance(run_id)
            return copy.deepcopy(self.runs[run_id])

    def process_reply(self, store: Store | None, run_id: str, household_id: str, body: str,
                      generated: bool = False) -> dict[str, Any]:
        """Process a reply for one household of a run (Req 19) and return the advanced run.

        Operator replies (`generated=False`) are timed at now and drop that household's pending
        generated replies. `store` is accepted for symmetry with `send`; the run already holds the
        keywords and texts it needs. Raises `NotFound` for an unknown run or household.
        """
        del store
        with self.lock:
            run = self._require(run_id)
            if household_id not in run["households"]:
                raise NotFound(f"unknown household {household_id!r} in run {run_id!r}")
            self._advance(run_id)
            plan = self.plans[run_id]
            if not generated:
                plan.pending = [p for p in plan.pending if p.household_id != household_id]
            self._apply_reply(run, plan, household_id, str(body), self.now() - plan.started_at, generated)
            self._refresh(run)
            return copy.deepcopy(run)

    # ------------------------------------------------------------ internals (lock held)

    def _require(self, run_id: str) -> dict[str, Any]:
        try:
            return self.runs[run_id]
        except KeyError:
            raise NotFound(f"unknown check-in run {run_id!r}") from None

    def _prepare(self, store: Store, geoid: str, hour: str, town: str,
                 households: Sequence[Household]) -> tuple[_RunPlan, list[ScheduledReply], dict[str, str]]:
        """Everything a run needs from the Store, validated before any state changes."""
        from api.reach import town_responders  # local import keeps api.reach free of a state dependency

        sms = store.content.sms.get(town, {})
        langs = sorted({hh.lang for hh in households})
        missing = [lang for lang in langs if lang not in sms]
        if missing:
            raise CheckInError(f"no SMS text for {town} in {missing}; run python -m pipeline.run")
        responders = town_responders(store, town)
        if not responders:
            raise CheckInError(f"no responder with a role listed for {town} in config/responders.yaml")

        demo = store.scoring.get("demo") or {}
        delays = effective_delays(demo.get("reply_delay_s", (3, 20)), self.timeout_s)
        keywords = reply_keywords(store)
        operator = demo.get("operator_household")
        schedule = seeded_schedule(demo.get("seed", 0), geoid, hour, households, demo.get("reply_mix") or {},
                                   (delays.lo, delays.hi), keywords, int(operator) if operator else None)
        twilio = getattr(self.sender, "channel", "simulator") == "twilio"
        phones = {hh.id: self._phones[hh.number - 1] for hh in households
                  if twilio and 1 <= hh.number <= len(self._phones)}
        plan = _RunPlan(
            started_at=0.0, timeout_s=self.timeout_s, town=town, keywords=keywords,
            texts={lang: {"confirm": sms[lang]["confirm"].text, "reprompt": sms[lang]["reprompt"].text}
                   for lang in langs},
            responders=tuple((r.id, r.label) for r in responders), phones=phones,
        )
        return plan, schedule, {lang: sms[lang]["checkin"].text for lang in langs}

    def _send_out(self, run: dict[str, Any], household_id: str, kind: str, text: str, at: float) -> None:
        hh = run["households"][household_id]
        plan = self.plans[run["id"]]
        result = self.sender.send(OutboundMessage(household_id=household_id, lang=hh["lang"], kind=kind,  # type: ignore[arg-type]
                                                  text=text, phone=plan.phones.get(household_id)))
        hh["messages"].append({"direction": "out", "kind": kind, "text": text, "at": round(at, 3),
                               "channel": result.channel, "simulated": result.channel == "simulator",
                               "synthetic": True})

    def _apply_reply(self, run: dict[str, Any], plan: _RunPlan, household_id: str, body: str, at: float,
                     generated: bool) -> None:
        hh = run["households"][household_id]
        cls = classify(body, plan.keywords)
        msg: dict[str, Any] = {"direction": "in", "kind": "reply", "text": body, "at": round(at, 3),
                               "class": cls, "generated": generated, "simulated": generated,
                               "synthetic": True}
        if generated:
            msg["label"] = SIMULATED
        hh["messages"].append(msg)
        if cls == "help":
            if hh["escalation_id"] is None:
                self._escalate(run, plan, hh, at)
                self._send_out(run, household_id, "confirm", plan.texts[hh["lang"]]["confirm"], at)
            hh["status"], hh["silent_reason"] = "escalated", None
        elif cls == "ok":
            if hh["status"] != "escalated":
                hh["status"], hh["silent_reason"] = "ok", None
        else:
            hh["unrecognized"] += 1
            if hh["reprompts"] == 0:
                hh["reprompts"] = 1
                self._send_out(run, household_id, "reprompt", plan.texts[hh["lang"]]["reprompt"], at)

    def _escalate(self, run: dict[str, Any], plan: _RunPlan, hh: dict[str, Any], at: float) -> None:
        town = run["town"]
        nth = sum(1 for e in self.escalations.values() if e["town"] == town)
        responder_id, responder_label = plan.responders[nth % len(plan.responders)]
        self.counters["escalation"] += 1
        esc_id = f"esc-{self.counters['escalation']}"
        self.escalations[esc_id] = {
            "id": esc_id, "run_id": run["id"], "geoid": run["geoid"], "hour": run["hour"], "town": town,
            "household_id": hh["id"], "household_label": hh["label"], "lang": hh["lang"],
            "responder_id": responder_id, "responder_label": responder_label,
            "created_at": round(at, 3), "status": "assigned", "synthetic": True,
        }
        hh["escalation_id"] = esc_id

    def _apply_timeout(self, run: dict[str, Any], plan: _RunPlan) -> None:
        """Households still `sent` become silent, only when the run telecom is 0 (Req 20.1, 20.2)."""
        plan.timed_out = True
        if run["telecom"] != 0:
            return
        for hh in run["households"].values():
            if hh["status"] == "sent":
                hh["status"] = "silent"
                hh["silent_reason"] = "unclear_reply" if hh["unrecognized"] else "no_reply"

    def _advance(self, run_id: str) -> None:
        run, plan = self.runs[run_id], self.plans[run_id]
        now = self.now()
        timeout_at = plan.started_at + plan.timeout_s
        due = [p for p in plan.pending if p.due <= now]
        plan.pending = [p for p in plan.pending if p.due > now]
        for p in due:
            if not plan.timed_out and p.due >= timeout_at:
                self._apply_timeout(run, plan)
            self._apply_reply(run, plan, p.household_id, p.body, p.due - plan.started_at, generated=True)
        if not plan.timed_out and now >= timeout_at:
            self._apply_timeout(run, plan)
        run["elapsed_s"] = round(max(0.0, now - plan.started_at), 3)
        self._refresh(run)

    @staticmethod
    def _refresh(run: dict[str, Any]) -> None:
        run["counters"] = status_counters(run["households"])
        run["complete"] = all(h["status"] in TERMINAL for h in run["households"].values())
        run["status"] = "complete" if run["complete"] else "active"


class CheckInState:
    """Holder on `app.state.checkins`: the current `CheckInStore` plus `reset()`."""

    def __init__(self, clock: Clock = time.monotonic, sender_factory: Callable[[], Sender] = make_sender,
                 timeout_s: float | None = None, phones: Sequence[str] | None = None) -> None:
        self._clock = clock
        self._sender_factory = sender_factory
        self._timeout_s = timeout_s
        self._phones = phones
        self._lock = threading.Lock()
        self.store = self._new_store()

    def _new_store(self) -> CheckInStore:
        return CheckInStore(self._clock, sender=self._sender_factory(), timeout_s=self._timeout_s,
                            phones=self._phones)

    def reset(self) -> CheckInStore:
        """Swap in a fresh, empty store with the same clock and settings and return it (Req 21.1).

        Requests already holding the old store finish against it; every later request sees the new one.
        """
        fresh = self._new_store()
        with self._lock:
            self.store = fresh
        return fresh


__all__ = [
    "CheckInError", "CheckInState", "CheckInStore", "Clock", "Delays", "Rejected", "ScheduledReply",
    "effective_delays", "seeded_schedule", "status_counters",
]
