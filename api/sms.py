"""SMS helpers for the check-in loop (design.md "API (`api/`)", `sms.py`).

* `normalize` and `classify`: reply parsing (Req 19.1 to 19.3). Pure; the keyword table is passed in,
  usually `reply_keywords(store)` from `config/languages.yaml`.
* `Sender` protocol and `SimulatorSender`: every outbound check-in, confirmation and re-prompt goes
  through a Sender. Twilio is not built, so `make_sender` returns the simulator for every `SMS_MODE`
  value (Req 18.2, 18.3).
* `mask_phone`, `demo_phone_numbers`, `reply_timeout_seconds`, `sms_mode`: environment values, read
  only from environment variables loaded from `.env` (Req 26.1). Phone numbers are only ever logged or
  shown masked as "+1 *** *** dddd" (Req 26.4).

Classification rule (documented in `classify`): the normalized body must equal "1", "2" or a keyword
from any Supported_Language. As the one exception, a body whose first token is "1" or "2" takes that
class ("2 ajuda" -> help) unless another token is a keyword of the opposite class. Everything else,
including "12" and keywords inside longer text, is unrecognized (None).
"""
from __future__ import annotations

import logging
import os
import threading
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from dotenv import load_dotenv

if TYPE_CHECKING:
    from api.data import Store

ROOT = Path(__file__).resolve().parent.parent

# Secrets and demo phone numbers come only from environment variables loaded from .env (Req 26.1).
# Real environment variables win over .env values.
load_dotenv(ROOT / ".env", override=False)

log = logging.getLogger(__name__)

ReplyClass = Literal["ok", "help"]
MessageKind = Literal["checkin", "confirm", "reprompt"]
SmsMode = Literal["simulator", "twilio"]

DEFAULT_REPLY_TIMEOUT_SECONDS = 30
DIGIT_CLASSES: Mapping[str, ReplyClass] = {"1": "ok", "2": "help"}

# ---------------------------------------------------------------- reply parsing


def _strip_edges(text: str) -> str:
    """Drop punctuation and symbols (Unicode categories P* and S*) at both ends: "sí." -> "sí"."""
    start, end = 0, len(text)
    while start < end and unicodedata.category(text[start])[0] in "PS":
        start += 1
    while end > start and unicodedata.category(text[end - 1])[0] in "PS":
        end -= 1
    return text[start:end]


def normalize(body: str) -> str:
    """Trim, collapse whitespace, casefold, remove accents and strip surrounding punctuation.

    Accents are removed by NFKD decomposition and dropping combining marks, the same as
    `pipeline.common.normalize` (the API does not import the pipeline). "  Sí. " -> "si".
    """
    text = " ".join(str(body).split()).casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(_strip_edges(text).split())


def keyword_classes(keywords: Mapping[str, Mapping[str, Sequence[str]]]) -> dict[str, ReplyClass]:
    """Normalized keyword -> class across every language, from `reply_keywords` {lang: {ok, help}}.

    Raises ValueError for a non-string keyword (an unquoted YES parses as a YAML boolean) or a keyword
    configured as both ok and help.
    """
    table: dict[str, ReplyClass] = dict(DIGIT_CLASSES)
    for lang, classes in keywords.items():
        for cls in ("ok", "help"):
            for word in classes.get(cls, ()):
                if not isinstance(word, str):
                    raise ValueError(f"reply_keywords.{lang}.{cls}: keyword {word!r} must be a quoted string")
                key = normalize(word)
                if not key:
                    raise ValueError(f"reply_keywords.{lang}.{cls}: empty keyword")
                if table.get(key, cls) != cls:
                    raise ValueError(f"reply_keywords: {key!r} is configured as both ok and help")
                table[key] = cls
    return table


def classify(body: str, keywords: Mapping[str, Mapping[str, Sequence[str]]]) -> ReplyClass | None:
    """Classify a reply body as "ok", "help" or None (unrecognized).

    Rule, applied to `normalize(body)`:
      1. The whole body equals "1" (ok), "2" (help) or a keyword of any Supported_Language.
         A pt household replying "OK" or "yes" is understood the same as an en one.
      2. Otherwise, if the first token is "1" or "2", the reply takes that class, unless another token
         is a keyword of the opposite class ("1 help" is ambiguous -> None).
      3. Anything else is None. Matching is whole-message, never substring: "12", "okay", "hello" and
         "I need help now" are unrecognized and get the one re-prompt.
    """
    table = keyword_classes(keywords)
    text = normalize(body)
    if text in table:
        return table[text]
    tokens = [_strip_edges(t) for t in text.split(" ")]
    first = tokens[0] if tokens else ""
    if first in DIGIT_CLASSES:
        cls = DIGIT_CLASSES[first]
        if any(table.get(t, cls) != cls for t in tokens[1:]):
            return None
        return cls
    return None


def reply_keywords(store: Store) -> Mapping[str, Mapping[str, Sequence[str]]]:
    """The `reply_keywords` table from `config/languages.yaml`, as loaded by the Store."""
    return store.languages["reply_keywords"]


# ---------------------------------------------------------------- phone numbers


def mask_phone(number: str) -> str:
    """"+1 *** *** dddd" with the number's last four digits; fewer than four digits -> all masked."""
    digits = "".join(c for c in str(number) if c.isdigit())
    last4 = digits[-4:] if len(digits) >= 4 else "****"
    return f"+1 *** *** {last4}"


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def demo_phone_numbers(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """`DEMO_PHONE_NUMBERS` (comma-separated), in order; household #1..n map to these. Never logged raw."""
    raw = _env(env).get("DEMO_PHONE_NUMBERS", "") or ""
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def reply_timeout_seconds(env: Mapping[str, str] | None = None) -> int:
    """`DEMO_REPLY_TIMEOUT_SECONDS` as a positive int; unset or invalid -> 30."""
    raw = (_env(env).get("DEMO_REPLY_TIMEOUT_SECONDS", "") or "").strip()
    if not raw:
        return DEFAULT_REPLY_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        log.warning("DEMO_REPLY_TIMEOUT_SECONDS must be a positive integer; using %d",
                    DEFAULT_REPLY_TIMEOUT_SECONDS)
        return DEFAULT_REPLY_TIMEOUT_SECONDS
    return value


def sms_mode(env: Mapping[str, str] | None = None) -> SmsMode:
    """"twilio" only when SMS_MODE is exactly "twilio"; anything else (including unset) is "simulator"."""
    return "twilio" if _env(env).get("SMS_MODE") == "twilio" else "simulator"


# ---------------------------------------------------------------- senders


@dataclass(frozen=True)
class OutboundMessage:
    """One outbound SMS. `phone` is None for simulated households (the usual case)."""

    household_id: str
    lang: str
    kind: MessageKind
    text: str
    phone: str | None = None

    def __repr__(self) -> str:  # never expose a raw number in logs or tracebacks (Req 26.4)
        phone = None if self.phone is None else mask_phone(self.phone)
        return (f"OutboundMessage(household_id={self.household_id!r}, lang={self.lang!r}, "
                f"kind={self.kind!r}, text={self.text!r}, phone={phone!r})")

    __str__ = __repr__


@dataclass(frozen=True)
class SendResult:
    channel: SmsMode
    ok: bool
    error: str | None = None


@runtime_checkable
class Sender(Protocol):
    def send(self, to: OutboundMessage) -> SendResult: ...


class SimulatorSender:
    """Delivers to the in-app Phone_Simulator: records messages in memory, no network."""

    channel: SmsMode = "simulator"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sent: list[OutboundMessage] = []

    def send(self, to: OutboundMessage) -> SendResult:
        with self._lock:
            self._sent.append(to)
        return SendResult(channel="simulator", ok=True)

    @property
    def sent(self) -> tuple[OutboundMessage, ...]:
        with self._lock:
            return tuple(self._sent)

    def clear(self) -> None:
        with self._lock:
            self._sent.clear()


_twilio_notice_logged = False


def make_sender(env: Mapping[str, str] | None = None) -> Sender:
    """The Sender for this process. Twilio is not built, so every SMS_MODE value gets the simulator."""
    global _twilio_notice_logged
    if sms_mode(env) == "twilio" and not _twilio_notice_logged:
        log.info("Twilio is not built; using the simulator")
        _twilio_notice_logged = True
    return SimulatorSender()


__all__ = [
    "DEFAULT_REPLY_TIMEOUT_SECONDS", "MessageKind", "OutboundMessage", "ReplyClass", "SendResult", "Sender",
    "SimulatorSender", "SmsMode", "classify", "demo_phone_numbers", "keyword_classes", "make_sender",
    "mask_phone", "normalize", "reply_keywords", "reply_timeout_seconds", "sms_mode",
]
