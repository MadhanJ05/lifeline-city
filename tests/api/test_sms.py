"""Tests for api/sms.py: reply parsing, senders, phone masking and environment values.

Only the reserved fictional numbers from tests/conftest.py are used (Req 26.6).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

import api.sms as sms
from api.data import load_store
from api.sms import (OutboundMessage, Sender, SendResult, SimulatorSender, classify, demo_phone_numbers,
                     keyword_classes, make_sender, mask_phone, normalize, reply_keywords,
                     reply_timeout_seconds, sms_mode)
from tests.conftest import FICTIONAL_NUMBERS

ROOT = Path(__file__).resolve().parents[2]
KEYWORDS = yaml.safe_load((ROOT / "config" / "languages.yaml").read_text(encoding="utf-8"))["reply_keywords"]


# ---------------------------------------------------------------- normalize / classify


@pytest.mark.parametrize("body, expected", [
    ("  Sí. ", "si"), ("AJUDA", "ajuda"), ("¡Sí!", "si"), ("  ok   then ", "ok then"), ("", ""), ("...", ""),
])
def test_normalize(body, expected):
    assert normalize(body) == expected


@pytest.mark.parametrize("body, expected", [
    # digits
    ("1", "ok"), ("2", "help"), (" 2 ", "help"), ("1.", "ok"),
    # en
    ("ok", "ok"), ("OK", "ok"), ("Ok!", "ok"), ("yes", "ok"), ("YES", "ok"), ("help", "help"), ("HELP", "help"),
    # pt
    ("sim", "ok"), ("SIM", "ok"), ("  Ajuda ", "help"), ("ajuda", "help"), ("AJUDA", "help"),
    # es, with and without accents
    ("si", "ok"), ("Sí", "ok"), ("SÍ", "ok"), ("Sí.", "ok"), ("ayuda", "help"), ("AYÚDA", "help"),
    # first token is a digit
    ("2 ajuda", "help"), ("1 ok", "ok"), ("2, help", "help"), ("1 thanks", "ok"),
    # unrecognized
    ("hello", None), ("12", None), ("21", None), ("", None), ("okay", None), ("I need help now", None),
    ("3", None), ("1 help", None), ("2 ok", None), ("yes help", None),
])
def test_classify_table(body, expected):
    assert classify(body, KEYWORDS) == expected


def test_keywords_match_across_languages():
    """A keyword from any Supported_Language is accepted, whatever the household language."""
    table = keyword_classes(KEYWORDS)
    assert {k for k, v in table.items() if v == "ok"} == {"1", "ok", "yes", "sim", "si"}
    assert {k for k, v in table.items() if v == "help"} == {"2", "help", "ajuda", "ayuda"}


def test_keyword_config_errors():
    with pytest.raises(ValueError, match="quoted string"):
        keyword_classes({"en": {"ok": [True], "help": ["HELP"]}})
    with pytest.raises(ValueError, match="both ok and help"):
        keyword_classes({"en": {"ok": ["OK"]}, "pt": {"help": ["ok"]}})


def test_reply_keywords_from_store():
    store = load_store()
    assert classify("Ajuda", reply_keywords(store)) == "help"
    assert dict(reply_keywords(store)["es"]) == KEYWORDS["es"]


# ---------------------------------------------------------------- senders


def _msg(**kw) -> OutboundMessage:
    base = dict(household_id="25001015300-2", lang="pt", kind="checkin", text="Responda 1 ou 2.")
    return OutboundMessage(**{**base, **kw})


@pytest.mark.parametrize("mode", [None, "", "simulator", "twilio", "x", "TWILIO"])
def test_make_sender_is_simulator_for_every_mode(mode):
    env = {} if mode is None else {"SMS_MODE": mode}
    sender = make_sender(env)
    assert isinstance(sender, SimulatorSender) and isinstance(sender, Sender)


def test_make_sender_logs_twilio_notice_once(monkeypatch, caplog):
    monkeypatch.setattr(sms, "_twilio_notice_logged", False)
    with caplog.at_level(logging.INFO, logger="api.sms"):
        make_sender({"SMS_MODE": "twilio"})
        make_sender({"SMS_MODE": "twilio"})
    assert [r.getMessage() for r in caplog.records].count("Twilio is not built; using the simulator") == 1


def test_simulator_records_messages():
    sender = SimulatorSender()
    m1, m2 = _msg(), _msg(kind="confirm", text="Uma pessoa vai ajudar. Ligue 911.")
    assert sender.send(m1) == SendResult(channel="simulator", ok=True)
    sender.send(m2)
    assert sender.sent == (m1, m2)
    sender.clear()
    assert sender.sent == ()


def test_outbound_repr_masks_phone():
    number = FICTIONAL_NUMBERS[23]
    text = repr(_msg(phone=number))
    assert number not in text and number[2:] not in text
    assert mask_phone(number) in text and str(_msg(phone=number)) == text


@pytest.mark.parametrize("mode, expected", [
    (None, "simulator"), ("", "simulator"), ("simulator", "simulator"), ("twilio", "twilio"), ("x", "simulator"),
])
def test_sms_mode(mode, expected):
    assert sms_mode({} if mode is None else {"SMS_MODE": mode}) == expected


# ---------------------------------------------------------------- phone numbers and env values


def test_mask_phone_examples():
    assert mask_phone(FICTIONAL_NUMBERS[0]) == "+1 *** *** 0100"
    assert mask_phone("123") == "+1 *** *** ****"
    assert mask_phone("") == "+1 *** *** ****"


def _formats(number: str) -> list[str]:
    a, e, l = number[2:5], number[5:8], number[8:]
    return [number, f"+1 {a} {e} {l}", f"({a}) {e}-{l}", f"{a}.{e}.{l}", f"1-{a}-{e}-{l}", f"{a}{e}{l}"]


@given(st.sampled_from(FICTIONAL_NUMBERS), st.integers(min_value=0, max_value=5))
def test_mask_phone_shows_only_last_four(number, fmt):
    """Property 25 (Python half): Phone masking shows only the last four digits.

    **Validates: Requirements 26.4, 26.5**
    """
    formatted = _formats(number)[fmt]
    masked = mask_phone(formatted)
    last4 = number[-4:]
    assert masked == f"+1 *** *** {last4}"
    assert masked.endswith(last4)
    # Beyond the fixed "+1" prefix, the only digits shown are the last four.
    assert re.sub(r"\D", "", masked[2:]) == last4


def test_demo_phone_numbers():
    a, b = FICTIONAL_NUMBERS[1], FICTIONAL_NUMBERS[2]
    assert demo_phone_numbers({"DEMO_PHONE_NUMBERS": f" {a}, ,{b} "}) == (a, b)
    assert demo_phone_numbers({"DEMO_PHONE_NUMBERS": ""}) == ()
    assert demo_phone_numbers({}) == ()


@pytest.mark.parametrize("raw, expected", [
    (None, 30), ("", 30), ("  ", 30), ("45", 45), (" 12 ", 12), ("0", 30), ("-5", 30), ("abc", 30), ("2.5", 30),
])
def test_reply_timeout_seconds(raw, expected):
    assert reply_timeout_seconds({} if raw is None else {"DEMO_REPLY_TIMEOUT_SECONDS": raw}) == expected
