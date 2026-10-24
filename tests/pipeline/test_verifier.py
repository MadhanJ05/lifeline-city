"""Unit tests for pipeline/verifier.py (Req 11.4, 11.9, 13.3 to 13.9, 14.1, 14.5, 15.4, 16.2, 16.3, 27.1 to 27.3)."""
import math

import pytest

from pipeline.common import PipelineError, load_languages
from pipeline.verifier import (Render, Tol, banned_hits, display_forms, lint_outreach, run_verifier,
                               verify_briefing, verify_claim)

LANGS = load_languages()
TOL = Tol(0.01, 0.01)
M = {"out_pct": 0.8234, "hours_dark": 40.0, "customers": 12345.0, "need.seniors_alone.pct": 0.92}
ASK = {"en": "Reply 1 if OK, 2 if you need help.", "pt": "Responda 1 se estiver bem, 2 se precisar de ajuda.",
       "es": "Responda 1 si esta bien, 2 si necesita ayuda."}
DOOR = {"en": "Are you OK? Do you need help?", "pt": "Você está bem? Precisa de ajuda?",
        "es": "¿Está bien? ¿Necesita ayuda?"}
SITUATION = {"en": "Power is out for about 82 percent of homes in Falmouth.",
             "pt": "A energia está cortada em cerca de 82 por cento das casas em Falmouth.",
             "es": "No hay electricidad en cerca del 82 por ciento de las casas en Falmouth."}
NEIGHBORS = {"en": "Please check on neighbors who live alone. The next update will air at 4 in the afternoon.",
             "pt": "Por favor, visite os vizinhos que moram sozinhos. A próxima atualização vai ao ar às 4 da tarde.",
             "es": "Por favor, visite a los vecinos que viven solos. La próxima actualización saldrá a las 4 de la tarde."}
RADIO_ALLOWED = display_forms(M["out_pct"]) | {"4"}


def sms(lang, body=None, region="cape"):
    co, help_ = LANGS.co_line[lang].sms, LANGS.help_line[region].sentence[lang].sms
    return f"{co} {ASK[lang] if body is None else body} {help_}"


def doorstep(lang):
    return f"{LANGS.co_line[lang].full} {DOOR[lang]} {LANGS.help_line['cape'].sentence[lang].full}"


def radio(lang):
    return (f"{SITUATION[lang]} {LANGS.co_line[lang].full} {LANGS.help_line['cape'].sentence[lang].full} "
            f"{NEIGHBORS[lang]}")


def briefing(**over):
    b = {"kind": "template", "verifier": "pass", "headline": "Dark for 40 hours, 82% without power",
         "claims": [{"text": "About 82% of customers are out (0.82)", "field": "out_pct", "value": 0.8234},
                    {"text": "Dark for 40 hours", "field": "hours_dark", "value": 40}],
         "action": "Send SMS check-ins. Air the AM radio script."}
    b.update(over)
    return b


# ---------------------------------------------------------------- claims


def test_verify_claim_accepts_within_tolerance_and_rejects_outside():
    assert verify_claim({"field": "out_pct", "value": 0.8234}, M, TOL) == []
    assert verify_claim({"field": "out_pct", "value": 0.83}, M, TOL) == []           # abs_tol 0.01
    assert verify_claim({"field": "customers", "value": 12400}, M, TOL) == []        # rel_tol 1% of 12345
    assert verify_claim({"field": "customers", "value": 12500}, M, TOL) == ["value_mismatch:customers"]
    assert verify_claim({"field": "out_pct", "value": 0.84}, M, {"abs_tol": 0.01, "rel_tol": 0.01}) \
        == ["value_mismatch:out_pct"]
    assert verify_claim({"field": "nope", "value": 1}, M, TOL) == ["missing_field:nope"]
    for bad in (math.nan, math.inf, None, True):
        assert verify_claim({"field": "out_pct", "value": bad}, M, TOL) == ["bad_value:out_pct"]


def test_display_forms():
    assert display_forms(0.8234) == {"0.8234", "1", "0.8", "0.82", "82"}
    assert display_forms(40.0) == {"40", "4000"}
    assert display_forms(math.nan) == set()


# ---------------------------------------------------------------- briefings


def test_verify_briefing_accepts_grounded_briefing():
    assert verify_briefing(briefing(), M, TOL, ["neglected"]) == []
    assert verify_briefing(briefing(headline="Call 911 or 2-1-1, 40 hours dark"), M, TOL, []) == []


def test_verify_briefing_rejections():
    one = briefing(claims=briefing()["claims"][:1])
    assert "claim_count:1" in verify_briefing(one, M, TOL, [])
    assert "missing_headline" in verify_briefing(briefing(headline="  "), M, TOL, [])
    assert "number_not_allowed:55" in verify_briefing(briefing(headline="Dark for 55 hours"), M, TOL, [])
    wrong = briefing(claims=[*briefing()["claims"], {"text": "x", "field": "hours_dark", "value": 45}])
    assert "value_mismatch:hours_dark" in verify_briefing(wrong, M, TOL, [])
    assert "banned_term:neglected" in verify_briefing(briefing(headline="A Neglected area"), M, TOL, ["neglected"])


def test_banned_hits_whole_words_case_accents_plural():
    pt = LANGS.banned_terms["pt"]
    assert banned_hits("Bairro NEGLIGENCIADO", pt) == ["negligenciado"]
    assert banned_hits("homes ignored", ["ignored"]) == ["ignored"]
    assert banned_hits("abandoneds", ["abandoned"]) == ["abandoned"]
    assert banned_hits("unignoredly", ["ignored"]) == []
    assert banned_hits("ábandonado", LANGS.banned_terms["es"]) == ["abandonado"]


# ---------------------------------------------------------------- outreach lint


@pytest.mark.parametrize("lang", ["en", "pt", "es"])
def test_well_formed_renders_pass(lang):
    for kind in ("sms_checkin", "sms_confirm", "sms_reprompt"):
        assert lint_outreach(sms(lang), kind, lang, "cape", (), LANGS) == []
    assert lint_outreach(doorstep(lang), "doorstep", lang, "cape", (), LANGS) == []
    assert lint_outreach(radio(lang), "radio", lang, "cape", RADIO_ALLOWED, LANGS) == []


def test_lint_rejections():
    en = sms("en")
    assert "co_line_not_first" in lint_outreach("Hello. " + en, "sms_checkin", "en", "cape", (), LANGS)
    assert "exclamation" in lint_outreach(sms("en", "Reply now!"), "sms_checkin", "en", "cape", (), LANGS)
    assert "acronym:ASAP" in lint_outreach(sms("en", "Reply ASAP."), "sms_checkin", "en", "cape", (), LANGS)
    assert any(r.startswith("promise:") for r in
               lint_outreach(sms("en", "Help comes within 30 minutes."), "sms_checkin", "en", "cape", (), LANGS))
    long_ = "We " + "really " * 20 + "care."
    assert "sentence_too_long:22" in lint_outreach(sms("en", long_), "sms_checkin", "en", "cape", (), LANGS)
    # Boston help sentence on a Cape message: no 2-1-1 and wrong closing sentence
    boston = sms("en", region="boston")
    reasons = lint_outreach(boston, "sms_checkin", "en", "cape", (), LANGS)
    assert "missing_help_line:2-1-1" in reasons and "help_sentence_not_last" in reasons
    no911 = en.replace("911", "nine")
    assert "missing_911" in lint_outreach(no911, "sms_checkin", "en", "cape", (), LANGS)
    assert "help_sentence_not_last" in lint_outreach(en + " Bye.", "sms_checkin", "en", "cape", (), LANGS)
    assert "banned_term:abandonado" in lint_outreach(sms("es", "Nadie esta abandonado."), "sms_checkin", "es",
                                                      "cape", (), LANGS)


def test_lint_pt_es_sms_must_be_unaccented_gsm7():
    reasons = lint_outreach(sms("pt", "Responda 1 se você estiver bem."), "sms_checkin", "pt", "cape", (), LANGS)
    assert "accented_chars" in reasons and "not_gsm7" in reasons
    # accents are fine in doorstep text
    assert lint_outreach(doorstep("pt"), "doorstep", "pt", "cape", (), LANGS) == []


def test_lint_radio_order_and_numbers():
    en = radio("en")
    assert "number_not_allowed:4" in lint_outreach(en, "radio", "en", "cape", display_forms(0.8234), LANGS)
    assert "number_not_allowed:83" in lint_outreach(en.replace("82", "83"), "radio", "en", "cape",
                                                    RADIO_ALLOWED, LANGS)
    swapped = f"{LANGS.co_line['en'].full} {SITUATION['en']} {NEIGHBORS['en']} " \
              f"{LANGS.help_line['cape'].sentence['en'].full}"
    assert "co_line_not_after_situation" in lint_outreach(swapped, "radio", "en", "cape", RADIO_ALLOWED, LANGS)
    two = "Storm update. " + en
    assert "co_line_not_after_situation" in lint_outreach(two, "radio", "en", "cape", RADIO_ALLOWED, LANGS)


# ---------------------------------------------------------------- run_verifier

H = "2026-02-24T09:00"
REPORT = {"hours": {H: {"sms": {"count": 1, "towns": ["Falmouth"]}, "door_knock": {"count": 0, "towns": []}}},
          "has_mixed_hour": False}
QUEUE = {H: [{"geoid": "g1", "town": "Falmouth",
              "why_chips": [{"text": "Seniors living alone, 92nd percentile", "field": "need.seniors_alone.pct",
                             "value": 0.92}, {"text": "82% without power", "field": "out_pct", "value": 0.8234}]}]}


def _renders():
    out = [Render(k, l, "Falmouth", sms(l)) for k in ("sms_checkin", "sms_confirm", "sms_reprompt")
           for l in ("en", "pt", "es")]
    out += [Render("doorstep", l, "Falmouth", doorstep(l)) for l in ("en", "pt", "es")]
    out += [Render("radio", l, "Falmouth", radio(l), frozenset(RADIO_ALLOWED), hour=H) for l in ("en", "pt", "es")]
    return out


def test_run_verifier_counts_and_report():
    briefs = {H: {"g1": briefing(kind="verified", verifier="pass"), "g2": briefing(verifier="fallback"),
                  "g3": briefing(kind="verified", verifier="regenerated")},
              "2026-02-24T10:00": {"g1": briefing()}}
    fails = [{"kind": "briefing", "key": f"{H}/g2", "attempt": 1, "reasons": ["missing_field:x"]}]
    log = run_verifier(briefs, lambda g, h: M, _renders(), QUEUE, REPORT, LANGS, TOL, "ran", fails)
    assert log["counts"] == {"pass": 1, "regenerated": 1, "fallback": 1}
    assert log["template_briefings"] == {"checked": 2, "pass": 2}
    assert log["outreach"] == {"sms": {"checked": 9}, "doorstep": {"checked": 3}, "radio": {"checked": 3},
                               "why_chip": {"checked": 2}}
    assert log["key_hour_channels"] == REPORT["hours"] and log["key_hour_channels"] is not REPORT["hours"]
    assert log["has_mixed_hour"] is False and log["llm_step"] == "ran" and log["failures"] == fails


def test_run_verifier_failing_template_briefing_stops():
    bad = {H: {"g9": briefing(headline="Dark for 99 hours")}}
    with pytest.raises(PipelineError) as e:
        run_verifier(bad, lambda g, h: M, [], {}, REPORT, LANGS, TOL)
    assert e.value.args[:2] == (H, "g9") and "number_not_allowed:99" in e.value.args[2]


def test_run_verifier_failing_render_names_kind_lang_town_term():
    r = Render("doorstep", "pt", "Yarmouth", doorstep("pt").replace("bem?", "bem? Ninguém está abandonado."))
    with pytest.raises(PipelineError) as e:
        run_verifier({}, lambda g, h: M, [r], {}, REPORT, LANGS, TOL)
    assert e.value.args == ("doorstep", "pt", "Yarmouth", "abandonado")
    r = Render("sms_checkin", "en", "Bourne", sms("en", "Reply now!"))
    with pytest.raises(PipelineError) as e:
        run_verifier({}, lambda g, h: M, [r], {}, REPORT, LANGS, TOL)
    assert e.value.args[:3] == ("sms_checkin", "en", "Bourne") and "exclamation" in e.value.args[3]


def test_run_verifier_banned_why_chip_stops():
    q = {H: [{"geoid": "g1", "town": "Truro", "why_chips": [{"text": "Ignored area", "field": "x", "value": 1}]}]}
    with pytest.raises(PipelineError) as e:
        run_verifier({}, lambda g, h: M, [], q, REPORT, LANGS, TOL)
    assert e.value.args == ("why_chip", "en", "Truro", "ignored")


# ---------------------------------------------------------------- Property 3
# Feature: lifeline-city, Property 3: Verifier accepts exactly the grounded claims
from hypothesis import given, strategies as st  # noqa: E402

field_names = st.text("abcxyz._", min_size=1, max_size=10)
metric_values = st.one_of(st.just(0.0), st.floats(-1, 1), st.floats(-1e3, 1e3), st.floats(-1e9, 1e9))
tols = st.builds(Tol, st.one_of(st.just(0.0), st.floats(0, 1e-6), st.floats(0, 100)),
                 st.one_of(st.just(0.0), st.floats(0, 0.5)))
metric_dicts = st.dictionaries(field_names, metric_values, min_size=1, max_size=6)


def _bound(mv, t):
    return max(t.abs_tol, t.rel_tol * abs(mv))


@st.composite
def claim_case(draw, kind=None):
    """(metrics, tol, claim, kind) with kind copied | within | outside | missing."""
    m, t = draw(metric_dicts), draw(tols)
    kind = kind or draw(st.sampled_from(("copied", "within", "outside", "missing")))
    if kind == "missing":
        f = draw(field_names.filter(lambda s: s not in m))
        return m, t, {"field": f, "value": draw(st.one_of(metric_values, st.sampled_from(list(m.values()))))}, kind
    f = draw(st.sampled_from(sorted(m)))
    mv, b = m[f], _bound(m[f], t)
    if kind == "copied":
        v = mv
    elif kind == "within":   # half the bound keeps float rounding inside the tolerance
        v = mv + draw(st.floats(-0.5, 0.5)) * b
    else:                    # 10% margin plus a few ulps so the push is strictly outside
        push = (1 + draw(st.floats(0.1, 10))) * b + 4 * math.ulp(mv) + 1e-9
        v = mv + draw(st.sampled_from((-1, 1))) * push
    return m, t, {"field": f, "value": v}, kind


@pytest.mark.required_pbt
@given(claim_case())
def test_property_3_verifier_accepts_exactly_grounded_claims(case):
    """**Validates: Requirements 11.4, 30.3**"""
    m, t, c, kind = case
    reasons = verify_claim(c, m, t)
    grounded = c["field"] in m and abs(c["value"] - m[c["field"]]) <= _bound(m[c["field"]], t)
    assert (reasons == []) == grounded
    expected = {"copied": [], "within": [], "missing": [f"missing_field:{c['field']}"],
                "outside": [f"value_mismatch:{c['field']}"]}[kind]
    assert reasons == expected


@st.composite
def briefing_case(draw):
    """(metrics, tol, briefing, bad_reason or None): 2 to 4 copied claims, optionally one replaced by a bad one."""
    m, t = draw(metric_dicts), draw(tols)
    fields = draw(st.lists(st.sampled_from(sorted(m)), min_size=2, max_size=4))
    claims = [{"text": "Grounded claim", "field": f, "value": m[f]} for f in fields]
    bad = None
    if draw(st.booleans()):
        if draw(st.booleans()):  # missing field
            c = {"field": draw(field_names.filter(lambda s: s not in m)), "value": draw(metric_values)}
            bad = f"missing_field:{c['field']}"
        else:                    # value pushed outside tolerance
            f = draw(st.sampled_from(sorted(m)))
            push = (1 + draw(st.floats(0.1, 10))) * _bound(m[f], t) + 4 * math.ulp(m[f]) + 1e-9
            c = {"field": f, "value": m[f] + draw(st.sampled_from((-1, 1))) * push}
            bad = f"value_mismatch:{f}"
        claims[draw(st.integers(0, len(claims) - 1))] = {"text": "Bad claim", **c}
    return m, t, {"headline": "Status update", "claims": claims, "action": "Send check-ins."}, bad


@pytest.mark.required_pbt
@given(briefing_case())
def test_property_3_verify_briefing_rejects_any_ungrounded_claim(case):
    """**Validates: Requirements 11.4, 30.3**"""
    m, t, b, bad = case
    reasons = verify_briefing(b, m, t, [])
    if bad is None:
        assert reasons == []
    else:
        assert bad in reasons
