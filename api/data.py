"""Read-only data layer for the API: pydantic models for every processed file and the startup `Store`.

The API reads only `data/processed/` and `config/` (Req 28.1, structure.md) and serves briefings and
outreach text only from the Content_Cache, `content.json` (Req 11.10). `data/processed/llm_cache/` is
pipeline-internal and is not loaded. Shapes follow pipeline/export.py (design.md "Data Models").

Models are strict where the API reads fields and loose (`extra="allow"`) elsewhere, so the pipeline can
add fields without breaking startup. Each file's raw bytes are kept for pass-through endpoints.

A missing or invalid required file stops startup with "run python -m pipeline.run".
`boston_voice.geojson` is optional (the Boston Voice block is cuttable).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
CONFIG = ROOT / "config"

TZ_NAME = "America/New_York"
RUN_PIPELINE = "run python -m pipeline.run"

# Out_pct label for towns with no town reports (sources.json towns_without_anchors, e.g. Chatham).
NO_TOWN_REPORTS_LABEL = "Estimated from the Cape-wide share (no town reports)"

Lang = Literal["en", "pt", "es"]
Channel = Literal["sms", "door_knock"]
TelecomRule = Literal["none", "observed", "modeled", "both"]
Component = Literal["out_pct", "hours_dark", "wires", "telecom"]


class StoreError(RuntimeError):
    """The processed data or config cannot be loaded; the API must not start."""


class NotFound(KeyError):
    """Unknown geoid, town or hour. Endpoints map this to 404."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")


# ---------------------------------------------------------------- shared pieces


class Chip(_Model):
    text: str
    field: str
    value: float


Claim = Chip


class QueueRow(_Model):
    rank: int
    geoid: str
    town: str
    priority: float
    need_t: float
    channel: Channel
    why_chips: list[Chip]


class NeedValue(_Model):
    raw: float | None
    pct: float | None
    unit: Literal["share", "per_1000"]


# ---------------------------------------------------------------- cape_tracts.geojson, cape_towns.geojson


class TractProps(_Model):
    geoid: str
    name: str
    town: str
    town_assignment: Literal["centroid", "nearest"]
    population: int
    need_t: float
    need: dict[str, NeedValue]
    need_missing: list[str]
    empower_masked: bool
    households_n: int
    customers: float
    customers_label: str | None


class TownProps(_Model):
    name: str
    customers: float
    customers_source: str
    customers_label: str | None
    anchor_count: int
    label_point: tuple[float, float]


class TractFeature(_Model):
    type: Literal["Feature"]
    properties: TractProps
    geometry: dict[str, Any]


class TownFeature(_Model):
    type: Literal["Feature"]
    properties: TownProps
    geometry: dict[str, Any]


class TractCollection(_Model):
    type: Literal["FeatureCollection"]
    tz: str
    features: list[TractFeature]


class TownCollection(_Model):
    type: Literal["FeatureCollection"]
    tz: str
    features: list[TownFeature]


class BostonVoice(_Model):
    """boston_voice.geojson (optional). Kept loose: the Boston block owns its feature shape."""

    type: Literal["FeatureCollection"]
    tz: str
    features: list[dict[str, Any]]
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------- cape_timeline.json


class TownSeries(_Model):
    """Town-hour components; every array is aligned with `CapeTimeline.hours`."""

    out_pct: list[float]
    hours_dark: list[int]
    wires_raw: list[float]
    wires: list[float]
    telecom: list[Literal[0, 1]]
    telecom_rule: list[TelecomRule]
    telecom_event_ids: list[list[str]]
    contrib: dict[Component, list[float]]
    lifelines: list[float]
    pinned: list[bool]
    lower_bound: list[float | None]
    customers_label: str | None


class TractSeries(_Model):
    town: str
    priority: list[float]
    channel: list[Channel]
    rank: list[int | None]


class TelecomModel(_Model):
    out_pct_threshold: float
    consecutive_hours: int


class CapeTimeline(_Model):
    tz: str
    hours: list[str]
    key_demo_hours: list[str]
    weights: dict[Component, float]
    hours_dark_cap: float
    dark_threshold: float
    telecom_model: TelecomModel
    labels: dict[str, str]
    provenance: dict[str, str]
    cape_total: list[float]
    towns: dict[str, TownSeries]
    tracts: dict[str, TractSeries]
    queue: dict[str, list[QueueRow]]

    @model_validator(mode="after")
    def _aligned(self) -> CapeTimeline:
        n = len(self.hours)
        if len(set(self.hours)) != n or len(self.cape_total) != n:
            raise ValueError("hours must be unique and cape_total aligned with hours")
        for town, s in self.towns.items():
            arrays = [s.out_pct, s.hours_dark, s.wires_raw, s.wires, s.telecom, s.telecom_rule,
                      s.telecom_event_ids, s.lifelines, s.pinned, s.lower_bound, *s.contrib.values()]
            if any(len(a) != n for a in arrays):
                raise ValueError(f"town {town!r} arrays are not aligned with hours")
        for geoid, t in self.tracts.items():
            if t.town not in self.towns:
                raise ValueError(f"tract {geoid!r} has unknown town {t.town!r}")
            if not (len(t.priority) == len(t.channel) == len(t.rank) == n):
                raise ValueError(f"tract {geoid!r} arrays are not aligned with hours")
        if set(self.queue) - set(self.hours):
            raise ValueError("queue has hours outside the time grid")
        return self


# ---------------------------------------------------------------- telecom_events.json


class TelecomPin(_Model):
    kind: Literal["town", "cape_wide"]
    town: str | None = None
    caption: str
    lon: float
    lat: float


class TelecomEvent(_Model):
    id: str
    system: str
    status: str
    affects: Literal["residents", "responders"]
    start_local: str
    end_local: str | None
    end_assumed: bool
    source_name: str
    source_url: str
    drives_reach_flag: bool
    areas: list[str]
    matched_towns: list[str]
    pins: list[TelecomPin]


class TelecomEvents(_Model):
    tz: str
    events: list[TelecomEvent]


# ---------------------------------------------------------------- content.json (Content_Cache)


class SmsText(_Model):
    text: str
    encoding: Literal["gsm7", "ucs2"]
    units: int
    segments: Literal[1, 2]


class RadioText(_Model):
    text: str
    words: int


class Briefing(_Model):
    kind: Literal["verified", "template"]
    headline: str
    claims: list[Claim]
    action: str
    verifier: Literal["pass", "regenerated", "fallback"]


class HelpLine(_Model):
    number: str
    sentence: dict[Lang, str]


class ContentCache(_Model):
    tz: str
    region: str
    help_line: HelpLine
    sms: dict[str, dict[Lang, dict[Literal["checkin", "confirm", "reprompt"], SmsText]]]
    doorstep: dict[str, dict[Lang, str]]
    radio: dict[str, dict[str, dict[Lang, RadioText]]]
    briefings: dict[str, dict[str, Briefing]]


# ---------------------------------------------------------------- synthetic records


class Household(_Model):
    id: str
    geoid: str
    town: str
    number: int
    label: str
    lang: Lang
    lon: float
    lat: float
    is_operator: bool = False
    synthetic: Literal[True]


class Responder(_Model):
    id: str
    town: str
    role: str
    label: str
    synthetic: Literal[True]


class HouseholdsFile(_Model):
    tz: str
    households: list[Household]


class RespondersFile(_Model):
    tz: str
    responders: list[Responder]


# ---------------------------------------------------------------- scale_catalog, sources, verifier_log


class CatalogEntry(_Model):
    id: str
    place: str
    hazard: str
    tier: Literal[1, 2]
    mode: Literal["live", "preview"]
    lost_lifelines_inputs: list[str]
    need_inputs: list[str]
    data_endpoint: str | None = None


class ScaleCatalog(_Model):
    tz: str
    entries: list[CatalogEntry]


class Sources(_Model):
    tz: str
    provenance_labels: dict[str, str]
    inputs: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    towns_without_anchors: list[str]
    customer_count_sources: dict[str, str]
    assumptions: list[dict[str, Any]]
    fetches: list[dict[str, Any]]


class VerifierLog(_Model):
    tz: str
    counts: dict[str, int]
    template_briefings: dict[str, int]
    outreach: dict[str, dict[str, int]]
    failures: list[dict[str, Any]]
    llm_step: str
    key_hour_channels: dict[str, Any]
    has_mixed_hour: bool


# File name -> model, in load order. All required except OPTIONAL_FILES.
PROCESSED_FILES: dict[str, type[_Model]] = {
    "cape_tracts.geojson": TractCollection,
    "cape_towns.geojson": TownCollection,
    "cape_timeline.json": CapeTimeline,
    "telecom_events.json": TelecomEvents,
    "content.json": ContentCache,
    "households.json": HouseholdsFile,
    "responders.json": RespondersFile,
    "scale_catalog.json": ScaleCatalog,
    "sources.json": Sources,
    "verifier_log.json": VerifierLog,
}
OPTIONAL_FILES: dict[str, type[_Model]] = {"boston_voice.geojson": BostonVoice}
CONFIG_FILES = ("scoring.yaml", "languages.yaml", "responders.yaml")


# ---------------------------------------------------------------- Store


@dataclass(frozen=True)
class Store:
    """Everything the API serves, loaded once at startup. Treat it as read-only."""

    tracts: TractCollection
    towns: TownCollection
    timeline: CapeTimeline
    telecom_events: TelecomEvents
    content: ContentCache
    households: HouseholdsFile
    responders: RespondersFile
    scale_catalog: ScaleCatalog
    sources: Sources
    verifier_log: VerifierLog
    boston_voice: BostonVoice | None
    scoring: Mapping[str, Any]
    languages: Mapping[str, Any]
    responders_config: Mapping[str, Any]
    raw: Mapping[str, bytes]  # file name -> bytes as written by the pipeline, for pass-through endpoints
    _hour_idx: Mapping[str, int] = field(repr=False)
    _tract_town: Mapping[str, str] = field(repr=False)
    _tract_props: Mapping[str, TractProps] = field(repr=False)
    _households_by_tract: Mapping[str, tuple[Household, ...]] = field(repr=False)
    _responders_by_town: Mapping[str, tuple[Responder, ...]] = field(repr=False)
    _out_pct_label: Mapping[str, str] = field(repr=False)

    # ------------------------------------------------------------ lookups

    @property
    def hours(self) -> list[str]:
        return self.timeline.hours

    @property
    def geoids(self) -> list[str]:
        return list(self._tract_town)

    @property
    def town_names(self) -> list[str]:
        return list(self.timeline.towns)

    def hour_index(self, hour: str) -> int:
        try:
            return self._hour_idx[hour]
        except KeyError:
            raise NotFound(f"unknown hour {hour!r}") from None

    def tract_town(self, geoid: str) -> str:
        try:
            return self._tract_town[geoid]
        except KeyError:
            raise NotFound(f"unknown tract {geoid!r}") from None

    def tract_props(self, geoid: str) -> TractProps:
        self.tract_town(geoid)
        return self._tract_props[geoid]

    def _town(self, town: str) -> TownSeries:
        try:
            return self.timeline.towns[town]
        except KeyError:
            raise NotFound(f"unknown town {town!r}") from None

    def out_pct_label(self, town: str) -> str:
        """Provenance label for a town's out_pct and hours_dark values."""
        self._town(town)
        return self._out_pct_label[town]

    def town_hour(self, town: str, hour: str) -> dict[str, Any]:
        """Lost-lifelines components of `town` at `hour`, with their provenance label."""
        s, i = self._town(town), self.hour_index(hour)
        return {
            "town": town,
            "hour": hour,
            "out_pct": s.out_pct[i],
            "hours_dark": s.hours_dark[i],
            "wires_raw": s.wires_raw[i],
            "wires": s.wires[i],
            "telecom": s.telecom[i],
            "telecom_rule": s.telecom_rule[i],
            "telecom_event_ids": list(s.telecom_event_ids[i]),
            "contrib": {c: v[i] for c, v in s.contrib.items()},
            "lifelines": s.lifelines[i],
            "pinned": s.pinned[i],
            "lower_bound": s.lower_bound[i],
            "customers_label": s.customers_label,
            "out_pct_label": self._out_pct_label[town],
        }

    def tract_hour(self, geoid: str, hour: str) -> dict[str, Any]:
        """Priority, channel and rank of a tract-hour plus its town's components (Req 7.4)."""
        town, i = self.tract_town(geoid), self.hour_index(hour)
        t = self.timeline.tracts[geoid]
        return {
            **self.town_hour(town, hour),
            "geoid": geoid,
            "need_t": self._tract_props[geoid].need_t,
            "priority": t.priority[i],
            "channel": t.channel[i],
            "rank": t.rank[i],
        }

    def queue(self, hour: str) -> list[QueueRow]:
        self.hour_index(hour)
        return list(self.timeline.queue.get(hour, []))

    def households_for(self, geoid: str) -> tuple[Household, ...]:
        self.tract_town(geoid)
        return self._households_by_tract.get(geoid, ())

    def responders_for(self, town: str) -> tuple[Responder, ...]:
        self._town(town)
        return self._responders_by_town.get(town, ())


# ---------------------------------------------------------------- loading


def _invalid(name: str, err: ValidationError) -> StoreError:
    # Location and message only; input values are not echoed.
    first = err.errors()[0]
    loc = ".".join(str(p) for p in first.get("loc", ())) or "(root)"
    return StoreError(f"{name} is invalid ({err.error_count()} errors; first at {loc}: {first['msg']}); "
                      f"{RUN_PIPELINE}")


def _read_model(path: Path, model: type[_Model]) -> tuple[_Model, bytes]:
    data = path.read_bytes()
    try:
        return model.model_validate_json(data), data
    except ValidationError as e:
        raise _invalid(path.name, e) from None


def _read_yaml(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise StoreError(f"Missing config file {path}")
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise StoreError(f"{path.name} is not valid YAML: {e}") from None
    if not isinstance(obj, dict):
        raise StoreError(f"{path.name} must be a mapping")
    return MappingProxyType(obj)


def _group(items, key) -> Mapping[str, tuple]:
    out: dict[str, list] = {}
    for it in items:
        out.setdefault(key(it), []).append(it)
    return MappingProxyType({k: tuple(v) for k, v in out.items()})


def _check(ok: bool, msg: str) -> None:
    if not ok:
        raise StoreError(f"{msg}; {RUN_PIPELINE}")


def load_store(processed_dir: Path = PROCESSED, config_dir: Path = CONFIG) -> Store:
    """Load and index every processed file and the API's config. Raises `StoreError` on any problem."""
    processed_dir, config_dir = Path(processed_dir), Path(config_dir)
    config = {n: _read_yaml(config_dir / n) for n in CONFIG_FILES}
    missing = [n for n in PROCESSED_FILES if not (processed_dir / n).is_file()]
    if missing:
        raise StoreError(f"Missing required file(s) in {processed_dir}: {', '.join(missing)}; {RUN_PIPELINE}")

    models: dict[str, _Model] = {}
    raw: dict[str, bytes] = {}
    for name, model in {**PROCESSED_FILES, **OPTIONAL_FILES}.items():
        path = processed_dir / name
        if name in OPTIONAL_FILES and not path.is_file():
            continue
        models[name], raw[name] = _read_model(path, model)

    tl: CapeTimeline = models["cape_timeline.json"]  # type: ignore[assignment]
    tracts: TractCollection = models["cape_tracts.geojson"]  # type: ignore[assignment]
    households: HouseholdsFile = models["households.json"]  # type: ignore[assignment]
    responders: RespondersFile = models["responders.json"]  # type: ignore[assignment]
    sources: Sources = models["sources.json"]  # type: ignore[assignment]

    # Cross-file consistency: the files must come from the same pipeline run.
    props = {f.properties.geoid: f.properties for f in tracts.features}
    _check(set(props) == set(tl.tracts), "cape_tracts.geojson and cape_timeline.json list different tracts")
    _check(all(p.town == tl.tracts[g].town for g, p in props.items()),
           "cape_tracts.geojson and cape_timeline.json disagree on tract towns")
    _check(all(h.geoid in props for h in households.households), "households.json has unknown tracts")
    _check(all(r.town in tl.towns for r in responders.responders), "responders.json has unknown towns")

    reconstructed = tl.provenance.get("out_pct") or tl.labels["reconstructed"]
    no_reports = set(sources.towns_without_anchors)
    out_pct_label = {t: NO_TOWN_REPORTS_LABEL if t in no_reports else reconstructed for t in tl.towns}

    return Store(
        tracts=tracts,
        towns=models["cape_towns.geojson"],  # type: ignore[arg-type]
        timeline=tl,
        telecom_events=models["telecom_events.json"],  # type: ignore[arg-type]
        content=models["content.json"],  # type: ignore[arg-type]
        households=households,
        responders=responders,
        scale_catalog=models["scale_catalog.json"],  # type: ignore[arg-type]
        sources=sources,
        verifier_log=models["verifier_log.json"],  # type: ignore[arg-type]
        boston_voice=models.get("boston_voice.geojson"),  # type: ignore[arg-type]
        scoring=config["scoring.yaml"],
        languages=config["languages.yaml"],
        responders_config=config["responders.yaml"],
        raw=MappingProxyType(raw),
        _hour_idx=MappingProxyType({h: i for i, h in enumerate(tl.hours)}),
        _tract_town=MappingProxyType({g: tl.tracts[g].town for g in sorted(tl.tracts)}),
        _tract_props=MappingProxyType(props),
        _households_by_tract=_group(sorted(households.households, key=lambda h: (h.geoid, h.number)),
                                    lambda h: h.geoid),
        _responders_by_town=_group(responders.responders, lambda r: r.town),
        _out_pct_label=MappingProxyType(out_pct_label),
    )
