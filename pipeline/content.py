"""Step 9 `content` (templates): Resident_Templates, rendered outreach and Template_Briefings.

Rules: .kiro/steering/outreach-style.md. Resident outreach (SMS, doorstep, radio) comes only from the
hand-written TEMPLATES below; the LLM is used only for operator Briefings (step 11, task 5.6).
The CO line and the help sentence come from config/languages.yaml and are never duplicated here.

  {CO}   co_line[lang].sms in SMS bodies, .full in doorstep and radio texts
  {HELP} help_line[REGION].sentence[lang].sms in SMS bodies, .full in doorstep and radio texts

Step outputs in ctx:
  content  {tz, region, help_line: {number, sentence: {lang: str}},
            sms: {town: {lang: {checkin|confirm|reprompt: {text, encoding, units, segments}}}},
            doorstep: {town: {lang: str}},
            radio: {hour: {town: {lang: {text, words}}}},
            briefings: {hour: {geoid: Briefing}}}          (design.md "Data Models", content.json)
  renders  [verifier.Render] for every resident text, re-checked by the verifier step
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from pipeline.common import CAPE_TOWNS, HOURS, Languages, PipelineError, hour_start, segments, strip_accents
from pipeline.lifelines import NEED_LABELS, _ordinal
from pipeline.need import INDICATORS
from pipeline.verifier import SMS_KINDS, Render, display_forms, lint_outreach

TEMPLATE_KINDS = ("sms_checkin", "sms_confirm", "sms_reprompt", "doorstep", "radio")
REGION = "cape"            # every resident render in the demo is a Cape message
MAX_SMS_SEGMENTS = 2       # Req 14.3, 14.4
SMS_KEY = {"sms_checkin": "checkin", "sms_confirm": "confirm", "sms_reprompt": "reprompt"}
TZ_NAME = "America/New_York"

# Hand-written per language, not word for word. pt and es SMS bodies are written without accents
# (render_sms also strips them as a guard); doorstep and radio texts keep their accents.
TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "sms_checkin": "{CO} Reply 1 if OK, 2 if you need help. {HELP}",
        "sms_confirm": "{CO} Thank you. We are passing your request to a person in {town}. {HELP}",
        "sms_reprompt": "{CO} Sorry, we did not understand. Reply 1 if OK, 2 if you need help. {HELP}",
        "doorstep": "{CO} Are you OK? Do you need help? {HELP}",
        "radio": ("Power is out for about {out_pct_pct} percent of homes in {town}. {CO} "
                  "Please check on neighbors who live alone, especially older neighbors and people who use "
                  "medical equipment. Knock on their door if you can do so safely. {HELP} "
                  "The next update will air at {next_update_spoken}."),
    },
    "pt": {
        "sms_checkin": "{CO} Responda 1 se estiver bem, 2 se precisar de ajuda. {HELP}",
        "sms_confirm": "{CO} Obrigado. Vamos passar seu pedido para uma pessoa em {town}. {HELP}",
        "sms_reprompt": "{CO} Desculpe, nao entendemos. Responda 1 se estiver bem, 2 se precisar de ajuda. {HELP}",
        "doorstep": "{CO} Você está bem? Precisa de ajuda? {HELP}",
        "radio": ("Cerca de {out_pct_pct} por cento das casas em {town} estão sem energia. {CO} "
                  "Por favor, veja como estão os vizinhos que moram sozinhos, principalmente os idosos e quem "
                  "usa equipamentos médicos. Bata à porta deles se puder fazer isso com segurança. {HELP} "
                  "A próxima atualização vai ao ar {next_update_spoken}."),
    },
    "es": {
        "sms_checkin": "{CO} Responda 1 si se encuentra bien, 2 si necesita ayuda. {HELP}",
        "sms_confirm": "{CO} Gracias. Vamos a pasar su pedido a una persona en {town}. {HELP}",
        "sms_reprompt": "{CO} Disculpe, no entendimos. Responda 1 si se encuentra bien, 2 si necesita ayuda. {HELP}",
        "doorstep": "{CO} ¿Se encuentra bien? ¿Necesita ayuda? {HELP}",
        "radio": ("Cerca del {out_pct_pct} por ciento de los hogares de {town} no tiene electricidad. {CO} "
                  "Por favor, vea cómo están sus vecinos que viven solos, sobre todo las personas mayores y "
                  "quienes usan equipos médicos. Toque a su puerta si puede hacerlo de forma segura. {HELP} "
                  "La próxima actualización saldrá al aire {next_update_spoken}."),
    },
}


class SmsText(NamedTuple):
    text: str
    encoding: str
    units: int
    segments: int


class RadioText(NamedTuple):
    text: str
    words: int
    allowed_numbers: frozenset   # metric display forms + the next-update clock number (Req 16.3)


# ---------------------------------------------------------------- shared lines


def co_sentence(lang: str, langs: Languages, form: str) -> str:
    return getattr(langs.co_line[lang], form)


def help_sentence(region: str, lang: str, langs: Languages, form: str) -> str:
    """langs.help_line[region].sentence[lang][form], form "sms" | "full"."""
    return getattr(langs.help_line[region].sentence[lang], form)


def _fill(kind: str, lang: str, langs: Languages, form: str, **slots: Any) -> str:
    try:
        tpl = TEMPLATES[lang][kind]
    except KeyError:
        raise PipelineError(kind, lang, "no Resident_Template") from None
    return tpl.format(CO=co_sentence(lang, langs, form), HELP=help_sentence(REGION, lang, langs, form), **slots)


# ---------------------------------------------------------------- renders


def render_sms(kind: str, town: str, lang: str, langs: Languages) -> SmsText:
    """CO line (sms form) + body + help sentence (sms form); pt/es accents stripped; segments recorded."""
    if kind not in SMS_KINDS:
        raise PipelineError(kind, lang, town, "not an SMS kind")
    text = _fill(kind, lang, langs, "sms", town=town)
    if lang in ("pt", "es"):
        text = strip_accents(text)
    sc = segments(text)
    return SmsText(text, sc.encoding, sc.units, sc.segments)


def render_doorstep(town: str, lang: str, langs: Languages) -> str:
    """CO line, "Are you OK? Do you need help?", help sentence; full forms with accents (Req 15.4)."""
    return _fill("doorstep", lang, langs, "full", town=town)


def spoken_hour(hour: int, lang: str) -> tuple[str, int | None]:
    """(phrase, clock number) for a 0..23 hour, with no AM or PM. en has no preposition ("at" is in the
    template); pt and es include theirs, since the article depends on the hour ("à 1", "às 4", "a la 1")."""
    hour %= 24
    if lang == "en":
        if hour == 0:
            return "midnight", None
        if hour == 12:
            return "noon", None
        n = hour if hour < 12 else hour - 12
        part = ("in the morning" if hour < 12 else "in the afternoon" if hour < 18
                else "in the evening" if hour < 21 else "at night")
        return f"{n} {part}", n
    if lang == "pt":
        if hour == 0:
            return "à meia-noite", None
        if hour == 12:
            return "ao meio-dia", None
        n = hour if hour < 12 else hour - 12
        part = ("da madrugada" if hour < 6 else "da manhã" if hour < 12 else "da tarde" if hour < 19
                else "da noite")
        return f"{'à' if n == 1 else 'às'} {n} {part}", n
    if lang == "es":
        if hour == 0:
            return "a la medianoche", None
        if hour == 12:
            return "al mediodía", None
        n = hour if hour < 12 else hour - 12
        part = ("de la madrugada" if hour < 6 else "de la mañana" if hour < 12 else "de la tarde" if hour < 20
                else "de la noche")
        return f"{'a la' if n == 1 else 'a las'} {n} {part}", n
    raise PipelineError("radio", lang, "unsupported language")


def next_update(h: str, interval_hours: int, lang: str) -> tuple[str, int | None]:
    return spoken_hour((hour_start(h).hour + int(interval_hours)) % 24, lang)


def render_radio(town: str, h: str, town_metrics: Mapping[str, float], lang: str, langs: Languages,
                 interval_hours: int = 2) -> RadioText:
    """Fixed template per language; {out_pct_pct} = round(100*out_pct), {next_update_spoken} = h + interval."""
    out = float(town_metrics["out_pct"])
    spoken, clock = next_update(h, interval_hours, lang)
    text = _fill("radio", lang, langs, "full", town=town, out_pct_pct=round(100 * out), next_update_spoken=spoken)
    allowed = set(display_forms(out)) | ({str(clock)} if clock is not None else set())
    return RadioText(text, len(text.split()), frozenset(allowed))


def _check(r: Render, langs: Languages) -> None:
    reasons = lint_outreach(r.text, r.kind, r.lang, r.region, r.allowed_numbers, langs)
    if reasons:
        where = (r.kind, r.lang, r.town) + ((r.hour,) if r.hour else ())
        term = next((x.split(":", 1)[1] for x in reasons if x.startswith("banned_term:")), None)
        raise PipelineError(*where, term or reasons)


def render_all(ctx, langs: Languages) -> tuple[dict[str, Any], list[Render]]:
    """SMS kinds and doorstep for every (kind, lang, town) over the 15 towns; radio for every (h, town)
    with a queued tract, in each language (Req 12.3, 13.1, 16.1). Every render is linted (Req 13.9, 27.3);
    an SMS over 2 segments raises PipelineError(kind, lang, town) (Req 14.4)."""
    supported = list(langs.supported)
    interval = int(ctx.scoring.demo.get("radio_update_interval_hours", 2))
    renders: list[Render] = []
    sms: dict[str, dict[str, dict[str, Any]]] = {}
    doorstep: dict[str, dict[str, str]] = {}
    for town in CAPE_TOWNS:
        sms[town], doorstep[town] = {}, {}
        for lang in supported:
            sms[town][lang] = {}
            for kind in SMS_KINDS:
                s = render_sms(kind, town, lang, langs)
                if s.segments > MAX_SMS_SEGMENTS:
                    raise PipelineError(kind, lang, town, f"{s.segments} segments ({s.encoding}, {s.units} units)")
                r = Render(kind, lang, town, s.text, region=REGION)
                _check(r, langs)
                renders.append(r)
                sms[town][lang][SMS_KEY[kind]] = s._asdict()
            text = render_doorstep(town, lang, langs)
            r = Render("doorstep", lang, town, text, region=REGION)
            _check(r, langs)
            renders.append(r)
            doorstep[town][lang] = text

    out_pct = ctx["out_pct"].reindex(index=HOURS, columns=list(CAPE_TOWNS))
    radio: dict[str, dict[str, dict[str, Any]]] = {}
    for h in HOURS:
        towns = sorted({str(row["town"]) for row in ctx["queue"].get(h, [])})
        if not towns:
            continue
        radio[h] = {}
        for town in towns:
            radio[h][town] = {}
            m = {"out_pct": float(out_pct.at[h, town])}
            for lang in supported:
                rt = render_radio(town, h, m, lang, langs, interval)
                r = Render("radio", lang, town, rt.text, rt.allowed_numbers, REGION, h)
                _check(r, langs)
                renders.append(r)
                radio[h][town][lang] = {"text": rt.text, "words": rt.words}
    return {"sms": sms, "doorstep": doorstep, "radio": radio}, renders


# ---------------------------------------------------------------- Template_Briefings


def action_for(channel: str) -> str:
    """Req 11.8."""
    if channel == "sms":
        return "Send SMS check-ins. Air the AM radio script."
    if channel == "door_knock":
        return "Send door-knock list to responders. Air the AM radio script."
    raise PipelineError(f"unknown Reach_Channel {channel!r}")


def _claim(text: str, field: str, m: Mapping[str, float]) -> dict[str, Any]:
    return {"text": text, "field": field, "value": float(m[field])}


def template_briefing(metrics: Mapping[str, float], channel: str, telecom_rule: str = "modeled") -> dict[str, Any]:
    """Headline + 4 claims from metric values exactly; every number in the text is a display form of a
    claim value (Python round, as in verifier.display_forms). Descriptive language only (Req 11.1, 11.3)."""
    out_pct = round(100 * float(metrics["out_pct"]))
    dark = int(round(float(metrics["hours_dark"])))
    phones_down = float(metrics["telecom"]) >= 1
    label = "modeled" if telecom_rule in ("modeled", "none") else "observed"

    dark_text = f"Dark for {dark} hour{'' if dark == 1 else 's'}" if dark > 0 else "Not counted as dark this hour"
    claims = [
        _claim(f"{out_pct}% of customers without power", "out_pct", metrics),
        _claim(dark_text, "hours_dark", metrics),
        _claim(f"Phones likely degraded ({label})" if phones_down else f"Phones likely working ({label})",
               "telecom", metrics),
    ]
    pcts = [(metrics[f"need.{k}.pct"], -i, k) for i, k in enumerate(INDICATORS) if f"need.{k}.pct" in metrics]
    if pcts:
        k = max(pcts)[2]
        f = f"need.{k}.pct"
        claims.append(_claim(f"{NEED_LABELS[k]}: {_ordinal(round(100 * float(metrics[f])))} percentile", f, metrics))

    second = "phones likely degraded" if phones_down else f"{out_pct}% without power"
    headline = f"Dark for {dark} hour{'' if dark == 1 else 's'}, {second}" if dark > 0 \
        else f"{out_pct}% of customers without power"
    return {"kind": "template", "headline": headline, "claims": claims, "action": action_for(channel),
            "verifier": "pass"}


def build_templates(ctx, langs: Languages) -> dict[str, Any]:
    """Step 9: render_all + a Template_Briefing for every Cape tract-hour (Req 11.3)."""
    outreach, renders = render_all(ctx, langs)
    fm, chan = ctx["flat_metrics"], ctx["channel"]
    town_of = ctx["cape_tracts"].set_index("GEOID")["town"]
    rule = ctx["telecom_rule"] if "telecom_rule" in ctx else None
    geoids = [str(g) for g in chan.columns]
    briefings: dict[str, dict[str, Any]] = {}
    for h in HOURS:
        chan_h = chan.loc[h]
        briefings[h] = {
            g: template_briefing(fm(g, h), str(chan_h[g]),
                                 str(rule.at[h, town_of[g]]) if rule is not None else "modeled")
            for g in geoids
        }
    content = {
        "tz": TZ_NAME,
        "region": REGION,
        "help_line": {"number": langs.help_line[REGION].number,
                      "sentence": {l: help_sentence(REGION, l, langs, "full") for l in langs.supported}},
        **outreach,
        "briefings": briefings,
    }
    ctx["content"] = content
    ctx["renders"] = renders
    return content


def step(ctx) -> None:
    content = build_templates(ctx, ctx.languages)
    renders = ctx["renders"]
    n_brief = sum(len(v) for v in content["briefings"].values())
    worst = {}
    for town, by_lang in content["sms"].items():
        for lang, by_kind in by_lang.items():
            for s in by_kind.values():
                if s["units"] > worst.get(lang, (0, 0, ""))[0]:
                    worst[lang] = (s["units"], s["segments"], town)
    sms_txt = ", ".join(f"{l} {u} chars/{n} seg ({t})" for l, (u, n, t) in worst.items())
    radio_n = sum(len(t) for t in content["radio"].values())
    print(f"       content: {len(renders)} renders (radio town-hours {radio_n}); "
          f"template briefings {n_brief}; max SMS {sms_txt}")
