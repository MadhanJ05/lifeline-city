"""Step 12 `verifier`: grounded Briefing claims and resident-outreach style checks.

Rules: .kiro/steering/outreach-style.md. Pure functions, no I/O; `run_verifier` returns the
verifier_log.json dict and raises PipelineError on any Template_Briefing, render or Why_Chip failure.
  verify_claim     claim field is a metrics key and |value - m[field]| <= max(abs_tol, rel_tol*|m[field]|)  (11.4)
  verify_briefing  headline, 2 to 4 grounded claims, text numbers only from claim display forms, no Banned_Term
  lint_outreach    CO line first, 911 + help line, help sentence last, no "!", acronyms, promises,
                   en sentences <= 20 words, radio numbers, pt/es SMS GSM-7 without accents, no Banned_Term
"""
from __future__ import annotations

import copy
import math
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NamedTuple

from pipeline.common import Languages, PipelineError, normalize, segments, strip_accents

KINDS = ("sms_checkin", "sms_confirm", "sms_reprompt", "doorstep", "radio")
SMS_KINDS = KINDS[:3]
HELP_NUMBERS = ("911", "2-1-1", "311")   # the only digit tokens allowed outside metric values
MAX_EN_WORDS = 20


class Tol(NamedTuple):
    abs_tol: float
    rel_tol: float


class Render(NamedTuple):
    """One rendered resident text. `allowed_numbers` is used by radio scripts only."""
    kind: str
    lang: str
    town: str
    text: str
    allowed_numbers: frozenset = frozenset()
    region: str = "cape"
    hour: str | None = None


def _tol(tol: Tol | Mapping[str, float]) -> Tol:
    return tol if isinstance(tol, Tol) else Tol(float(tol["abs_tol"]), float(tol["rel_tol"]))


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# ---------------------------------------------------------------- claims


def verify_claim(c: Mapping[str, Any], m: Mapping[str, float], tol: Tol | Mapping[str, float]) -> list[str]:
    """[] accepts the claim. Reasons: missing_field, bad_value, value_mismatch (Req 11.4)."""
    t, field, value = _tol(tol), c.get("field"), c.get("value")
    if field not in m:
        return [f"missing_field:{field}"]
    if not _finite(value) or not _finite(m[field]):
        return [f"bad_value:{field}"]
    if abs(value - m[field]) > max(t.abs_tol, t.rel_tol * abs(m[field])):
        return [f"value_mismatch:{field}"]
    return []


# ---------------------------------------------------------------- numbers in text


def _canon(x: float) -> str:
    """Canonical number string: abs value, at most 6 dp, no trailing zeros ("0.80" -> "0.8", "40.0" -> "40")."""
    r = round(abs(float(x)), 6)
    return str(int(r)) if r == int(r) else f"{r:.6f}".rstrip("0").rstrip(".")


def display_forms(v: float) -> set[str]:
    """v, round(v), round(v, 1), round(v, 2), round(100*v) as canonical strings; {} when v is not finite."""
    if not _finite(v):
        return set()
    return {_canon(x) for x in (v, round(v), round(v, 1), round(v, 2), round(100 * v))}


_ALLOWED_TOKEN = re.compile(r"(?<![\d-])(?:911|2-1-1|311)(?![\d-])")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str, keep: Iterable[str] = HELP_NUMBERS) -> list[str]:
    """Number tokens in `text` after removing the allowed help-number tokens in `keep`."""
    keep = set(keep)
    stripped = _ALLOWED_TOKEN.sub(lambda mt: " " if mt.group(0) in keep else mt.group(0), text)
    return _NUMBER.findall(stripped)


def _token_ok(token: str, allowed: set[str]) -> bool:
    """A token matches when either comma reading ("12,345" thousands, "8,5" decimal) is an allowed form."""
    for cand in {token.replace(",", ""), token.replace(",", ".")}:
        try:
            if _canon(float(cand)) in allowed:
                return True
        except ValueError:
            continue
    return False


def _bad_numbers(text: str, allowed: set[str], keep: Iterable[str] = HELP_NUMBERS) -> list[str]:
    return [f"number_not_allowed:{n}" for n in _numbers(text, keep) if not _token_ok(n, allowed)]


# ---------------------------------------------------------------- banned terms


def banned_hits(text: str, terms: Iterable[str]) -> list[str]:
    """Banned_Terms found in `text` as whole words after normalize(), with an optional plural "s" (Req 27.2)."""
    norm = normalize(text)
    return [t for t in dict.fromkeys(terms)
            if re.search(rf"(?<!\w){re.escape(normalize(t))}s?(?!\w)", norm)]


def all_banned(langs: Languages) -> list[str]:
    return [t for lang in langs.banned_terms for t in langs.banned_terms[lang]]


# ---------------------------------------------------------------- briefings


def verify_briefing(b: Mapping[str, Any], m: Mapping[str, float], tol: Tol | Mapping[str, float],
                    banned: Iterable[str]) -> list[str]:
    """[] accepts the Briefing (Req 11.1, 11.4, 27.2)."""
    reasons: list[str] = []
    headline = b.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        reasons.append("missing_headline")
        headline = ""
    claims = b.get("claims") or []
    if not 2 <= len(claims) <= 4:
        reasons.append(f"claim_count:{len(claims)}")
    allowed: set[str] = set()
    for c in claims:
        reasons += verify_claim(c, m, tol)
        allowed |= display_forms(c.get("value"))
    texts = [headline] + [str(c.get("text", "")) for c in claims]
    for text in texts:
        reasons += _bad_numbers(text, allowed)
    reasons += [f"banned_term:{t}" for t in banned_hits(" \n ".join(texts + [str(b.get("action", ""))]), banned)]
    return reasons


# ---------------------------------------------------------------- resident outreach


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]


def lint_outreach(text: str, kind: str, lang: str, region: str, allowed_numbers: Iterable[Any],
                  langs: Languages) -> list[str]:
    """[] accepts a rendered resident text (Req 13.3, 13.4, 13.6, 13.7, 13.8, 14.1, 14.5, 15.4, 16.2, 16.3, 27.2)."""
    if kind not in KINDS:
        raise PipelineError(f"lint_outreach: unknown kind {kind!r}")
    sms = kind in SMS_KINDS
    form = "sms" if sms else "full"
    fix = strip_accents if sms else (lambda s: s)
    co = fix(getattr(langs.co_line[lang], form))
    help_line = langs.help_line[region]
    help_sentence = fix(getattr(help_line.sentence[lang], form))
    reasons: list[str] = []

    # CO line first; radio: directly after the one-sentence situation statement
    if kind == "radio":
        i = text.find(co)
        pre = text[:i].strip() if i > 0 else ""
        if not pre or len(_sentences(pre)) != 1 or pre[-1] not in ".?":
            reasons.append("co_line_not_after_situation")
    elif not text.lstrip().startswith(co):
        reasons.append("co_line_not_first")

    if "911" not in text:
        reasons.append("missing_911")
    if help_line.number not in text:
        reasons.append(f"missing_help_line:{help_line.number}")
    if kind != "radio" and not text.rstrip().endswith(help_sentence):
        reasons.append("help_sentence_not_last")

    if "!" in text or "¡" in text:
        reasons.append("exclamation")
    allowed_acr = set(langs.allowed_acronyms)
    reasons += [f"acronym:{w}" for w in dict.fromkeys(re.findall(r"[^\W\d_]{2,}", text))
                if w.isupper() and w not in allowed_acr]
    reasons += [f"promise:{p}" for p in langs.promise_patterns.get(lang, []) if re.search(p, text, re.IGNORECASE)]

    if lang == "en":
        reasons += [f"sentence_too_long:{len(s.split())}" for s in _sentences(text) if len(s.split()) > MAX_EN_WORDS]
    if kind == "radio":
        allowed = {_canon(float(x)) for x in allowed_numbers if _finite(float(x))}
        reasons += _bad_numbers(text, allowed, keep=("911", help_line.number))
    if sms and lang in ("pt", "es"):
        if any(ord(ch) > 127 for ch in text):
            reasons.append("accented_chars")
        if segments(text).encoding != "gsm7":
            reasons.append("not_gsm7")

    reasons += [f"banned_term:{t}" for t in banned_hits(text, all_banned(langs))]
    return reasons


def _term(reasons: list[str]) -> str | None:
    return next((r.split(":", 1)[1] for r in reasons if r.startswith("banned_term:")), None)


# ---------------------------------------------------------------- step 12


def run_verifier(briefings: Mapping[str, Mapping[str, Mapping[str, Any]]],
                 metrics_of: Callable[[str, str], Mapping[str, float]],
                 renders: Iterable[Render],
                 queue: Mapping[str, Iterable[Mapping[str, Any]]],
                 report: Mapping[str, Any],
                 langs: Languages,
                 tol: Tol | Mapping[str, float],
                 llm_step: str = "no_llm",
                 llm_failures: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Check every Briefing, resident render and Why_Chip; return the verifier_log.json dict (Req 11.9, 11.16).

    briefings  {hour: {geoid: Briefing}}; kind "verified" counts its verifier (pass | regenerated),
               kind "template" with verifier "fallback" counts as fallback
    queue      {hour: [QueueRow]} for the Why_Chips;  report  lifelines key_hour_report {hours, has_mixed_hour}
    Raises PipelineError(hour, geoid, reasons) for a failing Briefing and
    PipelineError(kind, lang, town[, hour], term | reasons) for a failing render or Why_Chip (13.9, 27.3).
    """
    banned = all_banned(langs)
    counts = {"pass": 0, "regenerated": 0, "fallback": 0}
    templates = {"checked": 0, "pass": 0}
    for h in sorted(briefings):
        for g in sorted(briefings[h]):
            b = briefings[h][g]
            reasons = verify_briefing(b, metrics_of(g, h), tol, banned)
            if reasons:
                raise PipelineError(h, g, reasons)
            if b.get("kind") == "template":
                templates["checked"] += 1
                templates["pass"] += 1
                if b.get("verifier") == "fallback":
                    counts["fallback"] += 1
            elif b.get("verifier") in ("pass", "regenerated"):
                counts[b["verifier"]] += 1

    outreach = {k: {"checked": 0} for k in ("sms", "doorstep", "radio", "why_chip")}
    for r in renders:
        reasons = lint_outreach(r.text, r.kind, r.lang, r.region, r.allowed_numbers, langs)
        if reasons:
            where = (r.kind, r.lang, r.town) + ((r.hour,) if r.hour else ())
            raise PipelineError(*where, _term(reasons) or reasons)
        outreach["sms" if r.kind in SMS_KINDS else r.kind]["checked"] += 1

    for h in sorted(queue):
        for row in queue[h]:
            for chip in row.get("why_chips", []):
                hits = banned_hits(str(chip.get("text", "")), banned)
                if hits:
                    raise PipelineError("why_chip", "en", row.get("town"), hits[0])
                outreach["why_chip"]["checked"] += 1

    return {
        "counts": counts,
        "template_briefings": templates,
        "outreach": outreach,
        "failures": [dict(f) for f in llm_failures],
        "llm_step": llm_step,
        "key_hour_channels": copy.deepcopy(dict(report.get("hours", {}))),
        "has_mixed_hour": bool(report.get("has_mixed_hour", False)),
    }


def step(ctx) -> None:
    """Design step 12: check the final Content_Cache; store the verifier_log.json dict in ctx["verifier_log"]."""
    log = run_verifier(ctx["content"]["briefings"], ctx["flat_metrics"], ctx["renders"], ctx["queue"],
                       ctx["key_hour_report"], ctx.languages, ctx.scoring.verifier,
                       ctx["llm_step"] if "llm_step" in ctx else "no_llm",
                       ctx["llm_failures"] if "llm_failures" in ctx else ())
    ctx["verifier_log"] = log
    c, t, o = log["counts"], log["template_briefings"], log["outreach"]
    print(f"       verifier: llm_step {log['llm_step']}; LLM pass {c['pass']}, regenerated {c['regenerated']}, "
          f"fallback {c['fallback']}; template briefings {t['pass']}/{t['checked']}; "
          + ", ".join(f"{k} {v['checked']}" for k, v in o.items())
          + f"; failures {len(log['failures'])}")
