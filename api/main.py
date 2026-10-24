"""Lifeline City API: read and content endpoints (design.md "API (`api/`)").

Local demo only. There is NO authentication: run it bound to localhost
(`uvicorn api.main:app --host 127.0.0.1 --port 8000`) and never expose it publicly. CORS allows only the
local Vite origins (Req 28.2).

The API reads only `data/processed/` and `config/` through `api.data.load_store` (Req 28.1), loaded once
at startup. A `StoreError` stops startup with its message ("run python -m pipeline.run"). Briefings and
outreach text are served from the Content_Cache (`content.json`) only; nothing is generated here
(Req 11.10). Pass-through endpoints return the pipeline's bytes as written.

`SMS_MODE` is read from the process environment ("twilio" only when exactly "twilio", else "simulator").
No secret is ever returned. Check-in state lives in `api/state.py` on `app.state.checkins`;
`POST /api/demo/reset` swaps in a fresh, empty store (Req 21.1).

Check-in endpoints (design.md "API endpoints"): `POST /api/checkins/send`, `GET /api/checkins/{run_id}` and
`POST /api/simulator/reply`. Each returns the run after `advance`, as `Run` JSON: the state record with
`households` as a list in household-number order and the run's `escalations`. Logs carry run id, geoid,
hour, household id and reply class only: never a message body and never a raw phone number (run records
hold only `mask_phone` values; Req 26.4).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from api.data import (Channel, Chip, Lang, NeedValue, NotFound, QueueRow, Store, StoreError, TelecomRule,
                      load_store)
from api.reach import ChannelMismatch, Citation, DoorKnockEntry, ReachError, channel, door_knock_list, why_chips_for
from api.sms import reply_timeout_seconds
from api.state import CheckInError, CheckInState, CheckInStore, Rejected, effective_delays

log = logging.getLogger("lifeline.api")

ALLOWED_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
GEOJSON = "application/geo+json"
JSON = "application/json"
COMPONENTS = ("out_pct", "hours_dark", "wires", "telecom")

HourParam = Query(..., description="Hour key, YYYY-MM-DDTHH:MM local (America/New_York)")


# ---------------------------------------------------------------- response models


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Components(_Model):
    out_pct: float
    hours_dark: int
    wires: float          # percentile rank across the 15 towns at the hour
    wires_raw: float      # urgent downed-wire calls per 1,000 customers, cumulative
    telecom: Literal[0, 1]
    pinned: bool          # out_pct pinned to a reported anchor at this hour
    lower_bound: float | None


class HouseholdStatus(_Model):
    id: str
    label: str
    lang: Lang
    # Run statuses when a check-in run exists for the tract-hour, else the derived channel status (Req 20.2)
    status: Literal["sent", "ok", "escalated", "silent", "awaiting_door_knock", "not_contacted"]
    synthetic: Literal[True] = True


class SendRequest(_Model):
    geoid: str = Field(min_length=1, max_length=32)
    hour: str = Field(min_length=1, max_length=32)


class ReplyRequest(_Model):
    run_id: str = Field(min_length=1, max_length=64)
    household_id: str = Field(min_length=1, max_length=64)
    body: str = Field(min_length=1, max_length=160)


class TractDetail(_Model):
    geoid: str
    name: str
    town: str
    hour: str
    rank: int | None
    priority: float
    need_t: float
    need: dict[str, NeedValue]
    need_missing: list[str]
    empower_masked: bool
    components: Components
    weights: dict[str, float]
    contributions: dict[str, float]
    lifelines: float
    metrics: dict[str, float]     # flat tract-hour metrics; briefing claim and Why_Chip fields index into it
    telecom_rule: TelecomRule
    telecom_label: str | None
    telecom_citations: list[Citation]
    out_pct_label: str
    customers_label: str | None
    why_chips: list[Chip]
    active_events: list[dict[str, Any]]
    channel: Channel
    door_knock: list[DoorKnockEntry] | None
    households: list[HouseholdStatus]
    run: dict[str, Any] | None = None             # Run JSON (see `_run_json`) after advance, or None
    escalations: list[dict[str, Any]] = Field(default_factory=list)   # the run's Escalations


# ---------------------------------------------------------------- app


def _check_reply_delays(store: Store, timeout_s: float) -> None:
    """Warn at startup when `demo.reply_delay_s` reaches the reply timeout; runs use the clamped range."""
    demo = store.scoring.get("demo") or {}
    configured = demo.get("reply_delay_s", (3, 20))
    delays = effective_delays(configured, timeout_s)
    if delays.clamped:
        log.warning("demo.reply_delay_s %s is not below DEMO_REPLY_TIMEOUT_SECONDS %s; generated replies "
                    "use %.1f to %.1f s", list(configured), timeout_s, delays.lo, delays.hi)


def create_app(loader: Callable[[], Store] = load_store,
               checkins_factory: Callable[[], CheckInState] | None = None) -> FastAPI:
    """`checkins_factory` lets tests inject a CheckInState with a fake clock, sender or timeout."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            app.state.store = loader()
        except StoreError as e:
            log.error("Lifeline API cannot start: %s", e)
            raise
        checkins = checkins_factory() if checkins_factory is not None else CheckInState(
            timeout_s=reply_timeout_seconds())
        app.state.checkins = checkins
        _check_reply_delays(app.state.store, checkins.store.timeout_s)
        yield

    app = FastAPI(title="Lifeline City API (local demo, no auth)", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(ALLOWED_ORIGINS), allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, e: NotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": e.args[0] if e.args else "not found"})

    @app.exception_handler(ReachError)
    async def _reach_error(_: Request, e: ReachError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(e)})

    @app.exception_handler(Rejected)
    async def _rejected(_: Request, e: Rejected) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": {"code": e.code, "message": e.detail}})

    @app.exception_handler(CheckInError)
    async def _checkin_error(_: Request, e: CheckInError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(e)})

    _routes(app)
    return app


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_checkins(request: Request) -> CheckInState:
    return request.app.state.checkins


def _run_escalations(cs: CheckInStore, run_id: str) -> list[dict[str, Any]]:
    with cs.lock:
        return [dict(e) for e in cs.escalations.values() if e["run_id"] == run_id]


def _run_json(cs: CheckInStore, run: dict[str, Any]) -> dict[str, Any]:
    """Run JSON: households as a list in household-number order, plus the run's Escalations."""
    households = sorted(run["households"].values(), key=lambda h: h["number"])
    return {**run, "households": households, "escalations": _run_escalations(cs, run["id"])}


def _raw(store: Store, name: str, media_type: str = JSON) -> Response:
    return Response(content=store.raw[name], media_type=media_type)


def _flat_metrics(store: Store, geoid: str, th: dict[str, Any]) -> dict[str, float]:
    """Same field names as pipeline.lifelines.make_flat_metrics, so claim and chip fields resolve here."""
    props = store.tract_props(geoid)
    m: dict[str, float] = {"need_t": props.need_t}
    for k, v in props.need.items():
        if v.raw is not None:
            m[f"need.{k}.raw"] = v.raw
        if v.pct is not None:
            m[f"need.{k}.pct"] = v.pct
    m["customers"] = float(props.customers)
    m["population"] = float(props.population)
    for f in ("out_pct", "hours_dark", "wires", "wires_raw", "telecom", "lifelines"):
        m[f] = float(th[f])
    for c in COMPONENTS:
        m[f"contrib.{c}"] = float(th["contrib"][c])
        m[f"weight.{c}"] = float(store.timeline.weights[c])
    m["priority"] = float(th["priority"])
    if th["rank"] is not None:
        m["rank"] = float(th["rank"])
    return m


def _routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health(store: Store = Depends(get_store)) -> dict[str, Any]:
        sms_mode = "twilio" if os.environ.get("SMS_MODE") == "twilio" else "simulator"
        return {"ok": True, "boston_voice": store.boston_voice is not None, "sms_mode": sms_mode}

    @app.get("/api/hours")
    def hours(store: Store = Depends(get_store)) -> dict[str, Any]:
        tl = store.timeline
        return {"tz": tl.tz, "hours": tl.hours, "key_demo_hours": tl.key_demo_hours}

    @app.get("/api/towns")
    def towns(store: Store = Depends(get_store)) -> Response:
        return _raw(store, "cape_towns.geojson", GEOJSON)

    @app.get("/api/tracts")
    def tracts(store: Store = Depends(get_store)) -> Response:
        return _raw(store, "cape_tracts.geojson", GEOJSON)

    @app.get("/api/timeline")
    def timeline(store: Store = Depends(get_store)) -> Response:
        return _raw(store, "cape_timeline.json")

    @app.get("/api/telecom-events")
    def telecom_events(store: Store = Depends(get_store)) -> Response:
        return _raw(store, "telecom_events.json")

    @app.get("/api/sources")
    def sources(store: Store = Depends(get_store)) -> Response:
        return _raw(store, "sources.json")

    @app.get("/api/scale-catalog")
    def scale_catalog(store: Store = Depends(get_store)) -> Response:
        return _raw(store, "scale_catalog.json")

    @app.get("/api/queue", response_model=list[QueueRow])
    def queue(hour: str = HourParam, store: Store = Depends(get_store)) -> list[QueueRow]:
        return store.queue(hour)

    @app.get("/api/tracts/{geoid}", response_model=TractDetail)
    def tract_detail(geoid: str, hour: str = HourParam, store: Store = Depends(get_store),
                     checkins: CheckInState = Depends(get_checkins)) -> TractDetail:
        th = store.tract_hour(geoid, hour)  # NotFound -> 404
        props = store.tract_props(geoid)
        town = th["town"]
        ch = channel(store, geoid, hour)
        try:
            door_knock: list[DoorKnockEntry] | None = door_knock_list(store, geoid, hour)
        except ChannelMismatch:
            door_knock = None
        status = "awaiting_door_knock" if ch.channel == "door_knock" else "not_contacted"  # Req 20.2
        cs = checkins.store
        run = cs.run_for(geoid, hour)   # advanced; only sms tract-hours ever have a run (Req 15.6)
        run_json = _run_json(cs, run) if run is not None else None
        run_status = {h["id"]: h["status"] for h in run["households"].values()} if run is not None else {}
        # telecom_event_ids already holds the town's events plus Cape-wide ones active at the hour (Req 10.5).
        active_ids = set(th["telecom_event_ids"])
        active = [e.model_dump(exclude={"pins"}) for e in store.telecom_events.events if e.id in active_ids]
        return TractDetail(
            geoid=geoid, name=props.name, town=town, hour=hour, rank=th["rank"], priority=th["priority"],
            need_t=props.need_t, need=props.need, need_missing=props.need_missing,
            empower_masked=props.empower_masked,
            components=Components(out_pct=th["out_pct"], hours_dark=th["hours_dark"], wires=th["wires"],
                                  wires_raw=th["wires_raw"], telecom=th["telecom"], pinned=th["pinned"],
                                  lower_bound=th["lower_bound"]),
            weights=dict(store.timeline.weights), contributions=dict(th["contrib"]), lifelines=th["lifelines"],
            metrics=_flat_metrics(store, geoid, th),
            telecom_rule=ch.telecom_rule, telecom_label=ch.label, telecom_citations=ch.citations,
            out_pct_label=th["out_pct_label"], customers_label=props.customers_label or th["customers_label"],
            why_chips=why_chips_for(store, geoid, hour), active_events=active, channel=ch.channel,
            door_knock=door_knock,
            households=[HouseholdStatus(id=h.id, label=h.label, lang=h.lang, status=run_status.get(h.id, status))
                        for h in store.households_for(geoid)],
            run=run_json, escalations=run_json["escalations"] if run_json else [],
        )

    @app.get("/api/content/{geoid}")
    def content(geoid: str, hour: str = HourParam, store: Store = Depends(get_store)) -> dict[str, Any]:
        """Briefing and Reach content for a tract-hour, from the Content_Cache only (Req 11.10, 12.4, 12.7)."""
        ch = channel(store, geoid, hour)  # NotFound -> 404 for unknown geoid or hour
        town = store.tract_town(geoid)
        cc = store.content
        briefing = cc.briefings.get(hour, {}).get(geoid)
        sms = None
        if ch.channel == "sms":
            sms = {lang: msgs["checkin"].model_dump() for lang, msgs in cc.sms.get(town, {}).items()}
        radio = cc.radio.get(hour, {}).get(town)
        return {
            "geoid": geoid,
            "town": town,
            "hour": hour,
            "briefing": briefing.model_dump() if briefing else None,
            "reach": {
                "channel": ch.channel,
                "rule": ch.telecom_rule,
                "label": ch.label,
                "citations": [c.model_dump() for c in ch.citations],
                "sms": sms,
                "doorstep": dict(cc.doorstep.get(town, {})),
                "radio": {lang: r.model_dump() for lang, r in radio.items()} if radio else None,
            },
            "help_line": cc.help_line.model_dump(),
        }

    @app.post("/api/checkins/send")
    def checkins_send(req: SendRequest, store: Store = Depends(get_store),
                      checkins: CheckInState = Depends(get_checkins)) -> JSONResponse:
        """201 with a new Run, 200 with the existing run for the tract-hour (Req 18.1).

        409 `phones_degraded` on a door_knock tract-hour (no SMS, no run; Req 15.6), 409 `no_households`,
        404 for an unknown tract or hour, 500 when the processed data cannot support a run.
        """
        cs = checkins.store
        try:
            run, created = cs.send(store, req.geoid, req.hour)
        except Rejected as e:
            log.info("check-in send rejected: geoid=%s hour=%s code=%s", req.geoid, req.hour, e.code)
            raise
        log.info("check-in %s: run=%s geoid=%s hour=%s households=%d", "sent" if created else "existing",
                 run["id"], run["geoid"], run["hour"], len(run["households"]))
        return JSONResponse(status_code=201 if created else 200, content=_run_json(cs, run))

    @app.get("/api/checkins/{run_id}")
    def checkins_get(run_id: str, checkins: CheckInState = Depends(get_checkins)) -> dict[str, Any]:
        """The run after `advance`: due generated replies delivered, timeout applied (Req 18.9, 20.1)."""
        cs = checkins.store
        return _run_json(cs, cs.get_run(run_id))   # NotFound -> 404

    @app.post("/api/simulator/reply")
    def simulator_reply(req: ReplyRequest, store: Store = Depends(get_store),
                        checkins: CheckInState = Depends(get_checkins)) -> dict[str, Any]:
        """Process a reply typed by the Operator in the Phone_Simulator (Req 18.5, 19)."""
        cs = checkins.store
        run = cs.process_reply(store, req.run_id, req.household_id, req.body, generated=False)  # NotFound -> 404
        hh = run["households"][req.household_id]
        last_in = next((m for m in reversed(hh["messages"]) if m["direction"] == "in"), None)
        # Never log the body: class and status only.
        log.info("simulator reply: run=%s geoid=%s hour=%s household=%s class=%s status=%s", run["id"],
                 run["geoid"], run["hour"], req.household_id, last_in and last_in["class"], hh["status"])
        return _run_json(cs, run)

    @app.post("/api/demo/reset")
    def demo_reset(checkins: CheckInState = Depends(get_checkins)) -> dict[str, bool]:
        """Clear every run, reply, Escalation and counter back to the API-start state (Req 21.1)."""
        checkins.reset()
        log.info("demo reset: check-in state cleared")
        return {"ok": True}


app = create_app()
