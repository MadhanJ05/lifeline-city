"""Shared pipeline helpers: time grid, ranks, text matching, SMS segments, JSON output, config loading.

Formulas and keys: .kiro/steering/scoring.md. Do not duplicate these helpers elsewhere (structure.md).
"""
from __future__ import annotations

import json
import math
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

# ---------------------------------------------------------------- errors


class PipelineError(RuntimeError):
    """A pipeline step failed; the run stops with a non-zero exit."""


class ConfigError(PipelineError):
    """A config file is missing a key or holds an invalid value."""


# ---------------------------------------------------------------- paths and .env

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
RAW = ROOT / "data" / "raw"
CACHE = RAW / "cache"
PROCESSED = ROOT / "data" / "processed"
LLM_CACHE = PROCESSED / "llm_cache"

# Secrets come only from environment variables loaded from .env (Req 26.2). Real env vars win.
load_dotenv(ROOT / ".env", override=False)

# ---------------------------------------------------------------- time grid

TZ = ZoneInfo("America/New_York")
_FMT = "%Y-%m-%dT%H:%M"
_START = datetime(2026, 2, 23, 1, 0, tzinfo=TZ)
HOURS: list[str] = [(_START + timedelta(hours=i)).strftime(_FMT) for i in range(119)]  # .. 2026-02-27T23:00


def hour_key(ts: datetime) -> str:
    """Floor a timestamp to its Hour key in local time. Naive timestamps are taken as local."""
    ts = ts.replace(tzinfo=TZ) if ts.tzinfo is None else ts.astimezone(TZ)
    return ts.replace(minute=0, second=0, microsecond=0).strftime(_FMT)


def hour_start(key: str) -> datetime:
    """Start of the Hour identified by `key` (an Hour is named by its start, Req glossary)."""
    return datetime.strptime(key, _FMT).replace(tzinfo=TZ)


def hour_end(key: str) -> datetime:
    """Exclusive end of the Hour identified by `key`."""
    return hour_start(key) + timedelta(hours=1)


# ---------------------------------------------------------------- ranks


def pct_rank(s: pd.Series) -> pd.Series:
    """Average rank / number of non-null values, in (0, 1]. Ties share a value; NaN stays NaN."""
    return s.rank(method="average", pct=True, na_option="keep")


# ---------------------------------------------------------------- text


def strip_accents(text: str) -> str:
    """NFKD-decompose and drop combining marks ("Português" -> "Portugues")."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Trim, collapse inner whitespace, casefold and remove accents."""
    return strip_accents(" ".join(str(text).split()).casefold())


CAPE_TOWNS = ("Barnstable", "Bourne", "Brewster", "Chatham", "Dennis", "Eastham", "Falmouth", "Harwich",
              "Mashpee", "Orleans", "Provincetown", "Sandwich", "Truro", "Wellfleet", "Yarmouth")
_TOWN_BY_NORM = {normalize(t): t for t in CAPE_TOWNS}


def match_town(part: str | None) -> str | None:
    """Return the Cape town whose whole name equals `part` (ignoring case, accents, outer space).

    Never matches by substring: "Barnstable County MACC" and "Outer Cape" return None.
    """
    if part is None or (isinstance(part, float) and math.isnan(part)):
        return None
    return _TOWN_BY_NORM.get(normalize(part))


# ---------------------------------------------------------------- SMS segments (Req 14.2)

GSM7_BASIC = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
                 "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM7_EXT = set("^{}\\[~]|€\f")  # escape + char: 2 septets each


class SegmentCount(NamedTuple):
    encoding: str  # "gsm7" | "ucs2"
    units: int     # septets (gsm7) or UTF-16 code units (ucs2)
    segments: int


def segments(text: str) -> SegmentCount:
    if all(c in GSM7_BASIC or c in GSM7_EXT for c in text):
        enc, units, single, multi = "gsm7", sum(2 if c in GSM7_EXT else 1 for c in text), 160, 153
    else:
        enc, units, single, multi = "ucs2", len(text.encode("utf-16-le")) // 2, 70, 67
    return SegmentCount(enc, units, 1 if units <= single else math.ceil(units / multi))


# ---------------------------------------------------------------- JSON output


def _clean(obj: Any) -> Any:
    """Round floats (including coordinates) to 6 dp, NaN/inf -> null, numpy/pandas -> builtins."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if not math.isfinite(f) else round(f, 6) + 0.0  # +0.0 turns -0.0 into 0.0
    if obj is None or obj is pd.NA or obj is pd.NaT:
        return None
    if isinstance(obj, datetime):
        return obj.astimezone(TZ).isoformat() if obj.tzinfo else obj.isoformat()
    if isinstance(obj, BaseModel):
        return _clean(obj.model_dump())
    return obj


def write_json(path: Path, obj: Any) -> None:
    """Deterministic JSON: sorted keys, floats rounded to 6 dp, UTF-8 (accents kept)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(obj), sort_keys=True, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------- provenance

PROVENANCE = {
    "reconstructed": "Reconstructed from MEMA, Eversource and public-safety reports.",
    "modeled_telecom": "Modeled: assumes tower backup lasts about 8 hours",
    "acs_customers": "Estimated from ACS housing units.",
    "observed_default": "Assumed duration: 12 hours (no end time reported)",
}

# ---------------------------------------------------------------- config models

_ALLOW = ConfigDict(extra="allow")
LANGS = ("en", "pt", "es")


class TelecomModel(BaseModel):
    out_pct_threshold: float
    consecutive_hours: int


class Scoring(BaseModel):
    model_config = _ALLOW
    lifelines_weights: dict[str, float]
    hours_dark_cap: float
    dark_threshold: float
    telecom_model: TelecomModel
    telecom_observed_default_hours: Any
    access_hazard_wires_pct: float
    queue_size: int
    key_demo_hours: list[str]
    verifier: dict[str, float] = {}
    demo: dict[str, Any] = {}
    boston: dict[str, Any] = {}

    @field_validator("lifelines_weights")
    @classmethod
    def _weights(cls, w: dict[str, float]) -> dict[str, float]:
        need = {"out_pct", "hours_dark", "wires", "telecom"}
        if set(w) != need:
            raise ValueError(f"lifelines_weights must have exactly {sorted(need)}, got {w}")
        if any(v < 0 for v in w.values()) or abs(sum(w.values()) - 1) > 1e-9:
            raise ValueError(f"lifelines_weights must be non-negative and sum to 1, got {w}")
        return w

    @field_validator("telecom_observed_default_hours")
    @classmethod
    def _default_hours(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ValueError(f"telecom_observed_default_hours must be a positive integer, got {v!r}")
        return v

    @field_validator("key_demo_hours")
    @classmethod
    def _key_hours(cls, v: list[str]) -> list[str]:
        bad = [h for h in v if h not in HOURS]
        if bad:
            raise ValueError(f"key_demo_hours outside the Demo_Window: {bad}")
        return v


class Sentence(BaseModel):
    sms: str
    full: str


class HelpLine(BaseModel):
    number: str
    sentence: dict[str, Sentence]

    @field_validator("sentence")
    @classmethod
    def _langs(cls, v: dict[str, Sentence]) -> dict[str, Sentence]:
        missing = [l for l in LANGS if l not in v]
        if missing:
            raise ValueError(f"help_line sentence missing languages {missing}")
        return v


class LanguageMix(BaseModel):
    model_config = _ALLOW
    label: str
    default: dict[str, float]
    by_town: dict[str, dict[str, float]] = {}


class Languages(BaseModel):
    model_config = _ALLOW
    supported: list[str]
    labels: dict[str, str]
    reply_keywords: dict[str, dict[str, list[str]]]
    co_line: dict[str, Sentence]
    help_line: dict[str, HelpLine]
    allowed_acronyms: list[str]
    banned_terms: dict[str, list[str]]
    promise_patterns: dict[str, list[str]]
    household_language_mix: LanguageMix

    @model_validator(mode="after")
    def _check(self) -> "Languages":
        missing = [r for r in ("cape", "boston") if r not in self.help_line]
        if missing:
            raise ValueError(f"help_line must have cape and boston, missing {missing}")
        mixes = {"default": self.household_language_mix.default, **self.household_language_mix.by_town}
        for name, mix in mixes.items():
            if any(v < 0 for v in mix.values()) or abs(sum(mix.values()) - 1) > 1e-9:
                raise ValueError(f"household_language_mix[{name}] must sum to 1, got {mix}")
            if set(mix) - set(self.supported):
                raise ValueError(f"household_language_mix[{name}] has unsupported languages {sorted(set(mix) - set(self.supported))}")
        bad_towns = [t for t in self.household_language_mix.by_town if t not in CAPE_TOWNS]
        if bad_towns:
            raise ValueError(f"household_language_mix.by_town has non-Cape towns {bad_towns}")
        return self


def _load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"{path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


def _validate(model: type[BaseModel], path: Path):
    try:
        return model.model_validate(_load_yaml(path))
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, err['loc'])) or '<root>'}: {err['msg']}" for err in e.errors())
        raise ConfigError(f"{path.name}: {msgs}") from e


def load_scoring(path: Path = CONFIG / "scoring.yaml") -> Scoring:
    return _validate(Scoring, Path(path))


def load_languages(path: Path = CONFIG / "languages.yaml") -> Languages:
    return _validate(Languages, Path(path))
