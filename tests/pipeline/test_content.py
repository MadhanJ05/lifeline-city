"""Unit tests for pipeline/content.py: Resident_Templates, renders and Template_Briefings."""
import pandas as pd
import pytest

from pipeline import content
from pipeline.common import CAPE_TOWNS, HOURS, PipelineError, load_languages, load_scoring
from pipeline.run import Ctx
from pipeline.verifier import SMS_KINDS, display_forms, lint_outreach, verify_briefing

LANGS = load_languages()
TOL = {"abs_tol": 0.01, "rel_tol": 0.01}


@pytest.mark.parametrize("lang", ["en", "pt", "es"])
def test_sms_fit_two_gsm7_segments_and_lint_for_every_town(lang):
    for town in CAPE_TOWNS:
        for kind in SMS_KINDS:
            s = content.render_sms(kind, town, lang, LANGS)
            assert s.encoding == "gsm7" and s.segments <= 2, (kind, town, s)
            assert lint_outreach(s.text, kind, lang, "cape", (), LANGS) == []
            assert s.text.startswith(LANGS.co_line[lang].sms)
            assert s.text.endswith(content.help_sentence("cape", lang, LANGS, "sms"))
            if lang != "en":
                assert s.text.isascii()


def test_confirmation_names_town_and_repeats_911():
    s = content.render_sms("sms_confirm", "Provincetown", "pt", LANGS)
    assert "Provincetown" in s.text and s.text.count("911") >= 2


@pytest.mark.parametrize("lang", ["en", "pt", "es"])
def test_doorstep_uses_full_forms(lang):
    text = content.render_doorstep("Falmouth", lang, LANGS)
    assert text.startswith(LANGS.co_line[lang].full)
    assert text.endswith(LANGS.help_line["cape"].sentence[lang].full)
    assert lint_outreach(text, "doorstep", lang, "cape", (), LANGS) == []
    if lang == "pt":
        assert "Você está bem?" in text


@pytest.mark.parametrize("hour,en,pt,es", [
    (8, "8 in the morning", "às 8 da manhã", "a las 8 de la mañana"),
    (16, "4 in the afternoon", "às 4 da tarde", "a las 4 de la tarde"),
    (13, "1 in the afternoon", "à 1 da tarde", "a la 1 de la tarde"),
    (0, "midnight", "à meia-noite", "a la medianoche"),
    (12, "noon", "ao meio-dia", "al mediodía"),
])
def test_spoken_hour_has_no_am_pm(hour, en, pt, es):
    assert [content.spoken_hour(hour, l)[0] for l in ("en", "pt", "es")] == [en, pt, es]


@pytest.mark.parametrize("lang", ["en", "pt", "es"])
def test_radio_order_numbers_and_next_update(lang):
    rt = content.render_radio("Chatham", "2026-02-24T22:00", {"out_pct": 0.8234}, lang, LANGS, 2)
    assert "82" in rt.text and "Chatham" in rt.text
    assert rt.text.index("82") < rt.text.index(LANGS.co_line[lang].full)
    assert rt.allowed_numbers == frozenset(display_forms(0.8234))  # midnight: no clock number
    assert lint_outreach(rt.text, "radio", lang, "cape", rt.allowed_numbers, LANGS) == []
    en = content.render_radio("Chatham", "2026-02-24T08:00", {"out_pct": 0.5}, "en", LANGS, 2)
    assert en.text.endswith("The next update will air at 10 in the morning.") and "10" in en.allowed_numbers


def test_action_for():
    assert content.action_for("sms") == "Send SMS check-ins. Air the AM radio script."
    assert content.action_for("door_knock") == "Send door-knock list to responders. Air the AM radio script."
    with pytest.raises(PipelineError):
        content.action_for("fax")


@pytest.mark.parametrize("dark,tel,channel", [(0, 0, "sms"), (1, 0, "sms"), (40, 1, "door_knock")])
def test_template_briefing_is_grounded(dark, tel, channel):
    m = {"out_pct": 0.8234, "hours_dark": float(dark), "telecom": float(tel),
         "need.seniors_alone.pct": 0.9213, "need.renter.pct": 0.4, "need_t": 0.7}
    b = content.template_briefing(m, channel)
    assert verify_briefing(b, m, TOL, []) == []
    assert 2 <= len(b["claims"]) <= 4 and b["action"] == content.action_for(channel)
    assert b["kind"] == "template" and b["verifier"] == "pass"
    assert any(c["text"] == "Seniors living alone: 92nd percentile" for c in b["claims"])


def _ctx(queue):
    ctx = Ctx(scoring=load_scoring(), languages=LANGS)
    ctx["out_pct"] = pd.DataFrame(0.6, index=HOURS, columns=list(CAPE_TOWNS))
    ctx["queue"] = queue
    return ctx


def test_render_all_covers_towns_and_queued_town_hours():
    h = HOURS[10]
    out, renders = content.render_all(_ctx({h: [{"geoid": "g1", "town": "Truro"}]}), LANGS)
    assert set(out["sms"]) == set(CAPE_TOWNS) and set(out["doorstep"]) == set(CAPE_TOWNS)
    assert list(out["radio"]) == [h] and set(out["radio"][h]["Truro"]) == {"en", "pt", "es"}
    assert len(renders) == 15 * 3 * 4 + 3


def test_render_all_stops_on_sms_over_two_segments(monkeypatch):
    long = dict(content.TEMPLATES["es"], sms_confirm="{CO} " + "Gracias. " * 20 + "{town}. {HELP}")
    monkeypatch.setitem(content.TEMPLATES, "es", long)
    with pytest.raises(PipelineError) as e:
        content.render_all(_ctx({}), LANGS)
    assert e.value.args[:3] == ("sms_confirm", "es", "Barnstable")


def test_render_all_names_banned_term(monkeypatch):
    bad = dict(content.TEMPLATES["en"], doorstep="{CO} You are not abandoned. {HELP}")
    monkeypatch.setitem(content.TEMPLATES, "en", bad)
    with pytest.raises(PipelineError) as e:
        content.render_all(_ctx({}), LANGS)
    assert e.value.args == ("doorstep", "en", "Barnstable", "abandoned")


# ---------------------------------------------------------------- Property 4 (required)
# Feature: lifeline-city, Property 4: SMS segment rules and the 2-segment cap
import json
import math

from hypothesis import given
from hypothesis import strategies as st

from pipeline.common import PROCESSED, segments

# Independent reference tables, transcribed from the 3GPP TS 23.038 GSM 7-bit default alphabet,
# in code-point order (0x00..0x7F); ESC (0x1B) is not a character and is left out.
REF_GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅå"            # 0x00-0x0F
    "Δ_ΦΓΛΩΠΨΣΘΞ" "ÆæßÉ"             # 0x10-0x1F (ESC at 0x1B omitted)
    " !\"#¤%&'()*+,-./"              # 0x20-0x2F
    "0123456789:;<=>?"               # 0x30-0x3F
    "¡ABCDEFGHIJKLMNO"               # 0x40-0x4F
    "PQRSTUVWXYZÄÖÑÜ§"               # 0x50-0x5F
    "¿abcdefghijklmno"               # 0x60-0x6F
    "pqrstuvwxyzäöñüà"               # 0x70-0x7F
)
# Extension table (ESC + code): FF 0x0A, ^ 0x14, { 0x28, } 0x29, \ 0x2F, [ 0x3C, ~ 0x3D, ] 0x3E, | 0x40, € 0x65.
REF_GSM7_EXT = "\f^{}\\[~]|€"


def ref_segments(text: str) -> tuple[str, int, int]:
    """Reference (encoding, units, segments) per Req 14.2."""
    if all(c in REF_GSM7_BASIC or c in REF_GSM7_EXT for c in text):
        units = sum(2 if c in REF_GSM7_EXT else 1 for c in text)
        single, multi, enc = 160, 153, "gsm7"
    else:
        # UTF-16 code units: astral-plane characters (most emoji) are surrogate pairs.
        units = sum(2 if ord(c) > 0xFFFF else 1 for c in text)
        single, multi, enc = 70, 67, "ucs2"
    return enc, units, (1 if units <= single else math.ceil(units / multi))


def test_reference_tables_are_the_full_3gpp_alphabet():
    assert len(REF_GSM7_BASIC) == len(set(REF_GSM7_BASIC)) == 127
    assert len(REF_GSM7_EXT) == 10 and not set(REF_GSM7_EXT) & set(REF_GSM7_BASIC)
    # Only uppercase Ç is in the basic table; lowercase ç forces UCS-2.
    assert "Ç" in REF_GSM7_BASIC and "ç" not in REF_GSM7_BASIC
    assert segments("ç").encoding == "ucs2" and segments("Ç").encoding == "gsm7"


# Outside both tables: pt/es accents (lowercase ç included), backtick, tab, typographic punctuation, emoji.
NON_GSM = "ãõáíúóâêôçÁÍÚÕÃ`\t…“”’😀🌀✓"
_chars = st.one_of(
    st.sampled_from(REF_GSM7_BASIC),
    st.sampled_from(REF_GSM7_EXT),
    st.sampled_from(NON_GSM),
)
# Mostly-GSM text exercises the 160/153 boundaries; a sprinkle of non-GSM exercises 70/67 and surrogates.
_gsm_text = st.text(alphabet=st.one_of(st.sampled_from(REF_GSM7_BASIC), st.sampled_from(REF_GSM7_EXT)),
                    min_size=0, max_size=400)
_mixed_text = st.text(alphabet=_chars, min_size=0, max_size=400)


@pytest.mark.required_pbt
@given(st.one_of(_gsm_text, _mixed_text))
def test_segments_match_reference_count(text):
    """**Validates: Requirements 14.2, 30.4**"""
    sc = segments(text)
    assert (sc.encoding, sc.units, sc.segments) == ref_segments(text)


def _cached_or_rendered_sms():
    """(town, lang, kind, text, recorded SmsText fields) from content.json, else from the Resident_Templates."""
    path = PROCESSED / "content.json"
    if path.exists():
        sms = json.loads(path.read_text(encoding="utf-8"))["sms"]
        assert set(sms) == set(CAPE_TOWNS)
        for town in CAPE_TOWNS:
            assert set(sms[town]) == set(LANGS.supported)
            for lang in LANGS.supported:
                for kind in SMS_KINDS:
                    yield town, lang, kind, sms[town][lang][content.SMS_KEY[kind]]
    else:
        for town in CAPE_TOWNS:
            for lang in LANGS.supported:
                for kind in SMS_KINDS:
                    yield town, lang, kind, content.render_sms(kind, town, lang, LANGS)._asdict()


@pytest.mark.required_pbt
def test_every_sms_render_is_within_two_segments():
    """**Validates: Requirements 14.3, 30.4**"""
    seen = 0
    for town, lang, kind, rec in _cached_or_rendered_sms():
        enc, units, segs = ref_segments(rec["text"])
        assert segs <= 2, (kind, lang, town, enc, units, segs)
        assert (rec["encoding"], rec["units"], rec["segments"]) == (enc, units, segs), (kind, lang, town)
        if lang in ("pt", "es"):
            assert enc == "gsm7", (kind, lang, town, rec["text"])
        seen += 1
    assert seen == len(CAPE_TOWNS) * len(LANGS.supported) * len(SMS_KINDS) == 15 * 3 * 3


# ---------------------------------------------------------------- Property 2 (required)
# Feature: lifeline-city, Property 2: Channel follows telecom and every queued tract-hour has a radio script
import numpy as np

from pipeline import lifelines

_N_HOURS = len(HOURS)


@st.composite
def _cape_world(draw):
    """A few towns and tracts, a 0/1 town-hour telecom matrix, need values and town out_pct levels."""
    towns = draw(st.lists(st.sampled_from(CAPE_TOWNS), min_size=1, max_size=4, unique=True))
    n_tracts = draw(st.integers(1, 6))
    geoids = [f"25001{i:06d}" for i in range(n_tracts)]
    town_of = {g: draw(st.sampled_from(towns)) for g in geoids}
    # Telecom per town as runs of 0/1 over the window (block structure like the real modeled rule),
    # plus fully random rows so arbitrary patterns are covered too.
    bits = st.integers(0, 1)
    runs = st.lists(st.tuples(bits, st.integers(1, 40)), min_size=1, max_size=8).map(
        lambda rs: ([b for b, n in rs for _ in range(n)] * _N_HOURS)[:_N_HOURS])
    row = st.one_of(runs, st.lists(bits, min_size=_N_HOURS, max_size=_N_HOURS),
                    st.just([0] * _N_HOURS), st.just([1] * _N_HOURS))
    tel = pd.DataFrame(0, index=HOURS, columns=list(CAPE_TOWNS))
    for T in towns:
        tel[T] = draw(row)
    unit = st.floats(0, 1, allow_nan=False)
    out_level = {T: draw(unit) for T in CAPE_TOWNS}
    need_t = {g: draw(unit) for g in geoids}
    need_pct = {g: draw(unit) for g in geoids}
    queue_n = draw(st.integers(1, n_tracts))
    return towns, geoids, town_of, tel, out_level, need_t, need_pct, queue_n


def _ctx_for(geoids, town_of, tel, out_level, need_t, need_pct, queue_n):
    ctx = Ctx(scoring=load_scoring(), languages=LANGS)
    out = pd.DataFrame({T: [out_level[T]] * _N_HOURS for T in CAPE_TOWNS}, index=HOURS)
    town_col = [town_of[g] for g in geoids]
    # System under test for Req 12.1, 12.2: channel from the tracts' town telecom values.
    chan = pd.DataFrame(lifelines.channel(tel[town_col].to_numpy()), index=HOURS, columns=geoids)
    nt = np.array([need_t[g] for g in geoids])
    queue = {}
    for h in HOURS:
        prio = nt * np.array([out.at[h, T] + tel.at[h, T] for T in town_col])
        rows = lifelines.build_queue(prio, nt, geoids, queue_n)
        for r in rows:
            r["town"] = town_of[r["geoid"]]
            r["channel"] = chan.at[h, r["geoid"]]
        queue[h] = rows
    hd = {T: lifelines.hours_dark(out[T].to_numpy(), 0.5, 48) for T in set(town_col)}
    pos = {h: i for i, h in enumerate(HOURS)}

    def flat_metrics(g, h):
        T = town_of[g]
        return {"out_pct": float(out.at[h, T]), "hours_dark": float(hd[T][pos[h]]),
                "telecom": float(tel.at[h, T]), "need_t": need_t[g], "need.seniors_alone.pct": need_pct[g]}

    ctx["out_pct"] = out
    ctx["telecom"] = tel
    ctx["channel"] = chan
    ctx["queue"] = queue
    ctx["flat_metrics"] = flat_metrics
    ctx["cape_tracts"] = pd.DataFrame({"GEOID": geoids, "town": town_col})
    return ctx


@pytest.mark.required_pbt
@given(_cape_world())
def test_channel_follows_telecom_and_queued_tract_hours_have_radio(world):
    """**Validates: Requirements 12.1, 12.2, 12.3, 16.1, 30.2**"""
    towns, geoids, town_of, tel, out_level, need_t, need_pct, queue_n = world
    ctx = _ctx_for(geoids, town_of, tel, out_level, need_t, need_pct, queue_n)
    result = content.build_templates(ctx, LANGS)
    chan = ctx["channel"]

    for h in HOURS:
        for g in geoids:
            t = int(tel.at[h, town_of[g]])
            expected = "door_knock" if t == 1 else "sms"
            assert chan.at[h, g] == expected, (h, g, t)
            assert result["briefings"][h][g]["action"] == content.action_for(expected), (h, g)

    queued = {(h, r["town"]) for h, rows in ctx["queue"].items() for r in rows}
    assert len(queued) >= 1
    for h, town in queued:
        scripts = result["radio"][h][town]
        assert {"en", "pt", "es"} <= set(scripts), (h, town)
        for lang in ("en", "pt", "es"):
            assert scripts[lang]["text"] and town in scripts[lang]["text"], (h, town, lang)
