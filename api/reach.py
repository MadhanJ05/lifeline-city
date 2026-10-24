"""Reach channel lookup, door-knock list assembly and the access hazard rule (Req 15, 17.9).

Pure functions over the read-only `Store`: no I/O, no clock, no randomness.

Decisions (documented here so `api/main.py` and the tests agree):

- `channel()` returns the precomputed channel of the tract-hour and the telecom rule that fired, with a
  provenance label: the modeled-telecom label from `cape_timeline.json` for the modeled rule, and a
  citation ("Observed: <system> (<source>)") for each active event with `drives_reach_flag = true` for the
  observed rule. In the curated data no event drives the flag, so the observed branch is dormant.
- `door_knock_list()` raises `ChannelMismatch` when the tract-hour channel is `sms`. An empty list then
  means only "no synthetic households in this tract", never "phones are working". The detail endpoint
  maps the error to `door_knock: null`.
- Why_Chips are built and banned-term checked only by the pipeline, and only for Priority_Queue rows
  (Req 9.3, 27.2). An entry carries the queue row chips when the tract is queued at that hour, otherwise
  an empty list. The API never builds chips itself, and never borrows chips from another hour, because
  their values (for example "100% without power") belong to that other hour.
- Responders: only roles listed for the tract's town in `config/responders.yaml` (Req 15.5), in that
  config order, assigned round-robin by household number (#1 gets the first role, #2 the second, ...).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.data import Channel, Chip, Lang, Responder, Store, TelecomRule

ACCESS_HAZARD_NOTE = "Downed wires reported nearby. Treat every wire as live."


class ReachError(RuntimeError):
    """The data cannot produce a door-knock entry (missing doorstep script or responders)."""


class ChannelMismatch(ValueError):
    """A door-knock list was requested for a tract-hour whose Reach_Channel is not `door_knock`."""

    def __init__(self, geoid: str, hour: str, channel: str) -> None:
        super().__init__(f"tract {geoid} at {hour} uses channel {channel!r}, not 'door_knock'")
        self.geoid, self.hour, self.channel = geoid, hour, channel


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Citation(_Model):
    event_id: str
    system: str
    source_name: str
    source_url: str


class ReachChannel(_Model):
    channel: Channel
    telecom: Literal[0, 1]
    telecom_rule: TelecomRule
    label: str | None             # None when no telecom rule fired (channel is sms)
    citations: list[Citation]     # observed events that drive the flag; empty for modeled-only


class DoorKnockEntry(_Model):
    household_label: str          # "Simulated household #N"; no address, no phone number
    lang: Lang
    why_chips: list[Chip]
    responder_label: str          # role label, for example "Falmouth COA driver (Simulated)"
    doorstep_script: str
    access_hazard: str | None     # ACCESS_HAZARD_NOTE or None
    synthetic: Literal[True] = True


# ---------------------------------------------------------------- channel


def channel(store: Store, geoid: str, hour: str) -> ReachChannel:
    """Reach_Channel of tract-hour (geoid, hour) and the telecom rule behind it. Raises `NotFound`."""
    th = store.tract_hour(geoid, hour)
    rule: TelecomRule = th["telecom_rule"]
    citations: list[Citation] = []
    if rule in ("observed", "both"):
        active = set(th["telecom_event_ids"])
        citations = [Citation(event_id=e.id, system=e.system, source_name=e.source_name, source_url=e.source_url)
                     for e in store.telecom_events.events if e.id in active and e.drives_reach_flag]
    parts: list[str] = []
    if rule in ("modeled", "both"):
        parts.append(store.timeline.labels["modeled_telecom"])
    parts += [f"Observed: {c.system} ({c.source_name})" for c in citations]
    return ReachChannel(channel=th["channel"], telecom=th["telecom"], telecom_rule=rule,
                        label="; ".join(parts) or None, citations=citations)


# ---------------------------------------------------------------- access hazard


def access_hazard(store: Store, geoid: str, hour: str) -> bool:
    """True when wires(town(t), h) is at or above `access_hazard_wires_pct` (Req 15.3)."""
    threshold = float(store.scoring["access_hazard_wires_pct"])
    return store.tract_hour(geoid, hour)["wires"] >= threshold


# ---------------------------------------------------------------- door-knock list


def why_chips_for(store: Store, geoid: str, hour: str) -> list[Chip]:
    """Queue row chips when the tract is queued at `hour`, otherwise [] (see module docstring)."""
    for row in store.queue(hour):
        if row.geoid == geoid:
            return list(row.why_chips)
    return []


def town_responders(store: Store, town: str) -> list[Responder]:
    """Responders of `town` whose role is listed for it in responders.yaml, in config order (Req 15.5)."""
    roles = list((store.responders_config.get("towns") or {}).get(town) or [])
    by_role = {r.role: r for r in store.responders_for(town)}
    return [by_role[role] for role in roles if role in by_role]


def door_knock_list(store: Store, geoid: str, hour: str) -> list[DoorKnockEntry]:
    """One entry per Synthetic_Household of the tract (Req 15.1, 15.2, 15.3, 15.5, 17.9).

    Raises `ChannelMismatch` when the channel is `sms`, `NotFound` for an unknown tract or hour, and
    `ReachError` when the town has no doorstep script for a household language or no allowed responder.
    """
    ch = channel(store, geoid, hour)
    if ch.channel != "door_knock":
        raise ChannelMismatch(geoid, hour, ch.channel)
    households = store.households_for(geoid)
    if not households:
        return []

    town = store.tract_town(geoid)
    responders = town_responders(store, town)
    if not responders:
        raise ReachError(f"no responder with a role listed for {town} in config/responders.yaml")
    scripts = store.content.doorstep.get(town, {})
    chips = why_chips_for(store, geoid, hour)
    note = ACCESS_HAZARD_NOTE if access_hazard(store, geoid, hour) else None

    entries = []
    for hh in households:
        script = scripts.get(hh.lang)
        if not script:
            raise ReachError(f"no doorstep script for {town} in {hh.lang!r}; run python -m pipeline.run")
        entries.append(DoorKnockEntry(
            household_label=hh.label,
            lang=hh.lang,
            why_chips=chips,
            responder_label=responders[(hh.number - 1) % len(responders)].label,
            doorstep_script=script,
            access_hazard=note,
        ))
    return entries
