"""Step 11 `llm_briefings`: Anthropic operator Briefings at Key_Demo_Hours (design.md "pipeline/content.py:
LLM briefings (step 11)"). Kept in its own module; it builds on pipeline.content.

Briefings only: resident outreach (SMS, doorstep, radio) never uses the LLM. The recommended action always
comes from content.action_for, never from the model.

  client     anthropic.Anthropic() with ANTHROPIC_API_KEY from .env; None with --no-llm or no key (11.7, 11.15)
  request    messages.create(model, max_tokens=4000, system, messages, output_config) with no temperature
             (11.11). anthropic==2.3.0: OutputConfigParam = {effort, format: JSONOutputFormatParam
             {type: "json_schema", schema}}; the JSON body comes back as the text content block(s).
  rejected   an exception, stop_reason "refusal" | "max_tokens", or a body failing BRIEFING_SCHEMA (11.12)
  cache      data/processed/llm_cache/<sha256(model, system, prompt, metrics)>.json = {model, stop_reason, body},
             written as each response arrives (refusal and max_tokens included, exceptions not) and reused on
             re-runs, also with --no-llm (1.4, 11.13)
  fallback   attempt 1 verified -> "pass"; attempt 2 (reasons in the prompt) verified -> "regenerated";
             otherwise the Template_Briefing with verifier "fallback" (11.5, 11.6)

Step outputs in ctx:
  content["briefings"][h][geoid]  replaced at (Key_Demo_Hour, queued tract) pairs that got a response
  llm_step      "ran" | "no_llm" | "no_key" | "skipped_key_hours"
  llm_failures  [{kind: "briefing", key: "<hour>/<geoid>", attempt: 1 | 2, reasons: [str]}]
  llm_stats     {pairs, calls, cache_hits, pass, regenerated, fallback, template}
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, NamedTuple

from pipeline.common import LLM_CACHE, _clean
from pipeline.content import action_for, template_briefing
from pipeline.lifelines import MIXED_ADJUST
from pipeline.verifier import Tol, all_banned, verify_briefing

MODEL = "claude-opus-5-5"
MAX_TOKENS = 4000
EFFORT = "low"
REJECT_STOPS = ("refusal", "max_tokens")

# Structured outputs reject array `minItems` other than 0 or 1 (400 invalid_request_error), so the schema sent
# to the API has no array bounds. The 2 to 4 claim count is asked for in SYSTEM and enforced by schema_errors.
BRIEFING_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["headline", "claims"],
    "properties": {
        "headline": {"type": "string"},
        "claims": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["text", "field", "value"],
            "properties": {"text": {"type": "string"}, "field": {"type": "string"}, "value": {"type": "number"}}}},
    },
}

OUTPUT_CONFIG: dict[str, Any] = {"effort": EFFORT, "format": {"type": "json_schema", "schema": BRIEFING_SCHEMA}}

SYSTEM = (
    "You write a short operator briefing for an emergency manager during a winter power outage on Cape Cod. "
    "The user message is JSON with the town, the outreach channel and the metrics of one census tract at one hour.\n"
    "Rules:\n"
    "- Use descriptive language only. Never call a place or people neglected, ignored or abandoned, and make no "
    "causal claims (do not say why something happened or who is responsible).\n"
    "- Use only numbers that are present in the metrics JSON. Do not compute new numbers, totals or differences.\n"
    "- Write one headline and 2 to 4 claims. Each claim cites exactly one metric: `field` is the exact metrics "
    "key and `value` is that metric's exact value from the JSON.\n"
    "- Any number written in the headline or in a claim's text must be a cited claim value, that value rounded "
    "to 0, 1 or 2 decimals, or that value times 100 rounded to a whole number (for a share written as a percent, "
    "e.g. out_pct 0.734 as 73%). Write no other numbers, dates or times.\n"
    "- Do not recommend an action; the action is added separately. Keep the headline under 15 words and each "
    "claim under 20 words. Plain English, no exclamation marks."
)


class Attempt(NamedTuple):
    """One request outcome. `available` is False only when there is no client and no cached response."""
    body: dict[str, Any] | None
    reasons: list[str]
    available: bool
    source: str          # "cache" | "call" | "none"


# ---------------------------------------------------------------- client


def make_client(no_llm: bool) -> tuple[Any, str]:
    """(client, llm_step). None with --no-llm ("no_llm") or without ANTHROPIC_API_KEY ("no_key") (11.7, 11.15).
    The key is read from the environment (.env is loaded by pipeline.common) and never printed (26.2)."""
    if no_llm:
        return None, "no_llm"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "no_key"
    import anthropic  # imported lazily so --no-llm runs never touch the SDK
    return anthropic.Anthropic(), "ran"


# ---------------------------------------------------------------- prompt, schema, cache


def clean_metrics(metrics: Mapping[str, float]) -> dict[str, Any]:
    """Flat metrics as they are sent and hashed: floats rounded to 6 dp, sorted keys."""
    return dict(sorted(_clean(dict(metrics)).items()))


def build_prompt(metrics: Mapping[str, float], town: str, channel: str,
                 reasons: Iterable[str] | None = None) -> str:
    """User content: JSON of {town, channel, metrics} only (11.2); attempt 2 appends the rejection reasons."""
    prompt = json.dumps({"town": town, "channel": channel, "metrics": clean_metrics(metrics)},
                        sort_keys=True, ensure_ascii=False)
    reasons = list(reasons or [])
    if reasons:
        prompt += ("\n\nThe previous briefing for these metrics was rejected by the verifier for: "
                   + "; ".join(reasons)
                   + ". Write a new briefing that fixes every listed problem and follows all the rules.")
    return prompt


def cache_key(model: str, system: str, prompt: str, metrics: Mapping[str, float]) -> str:
    """sha256 of the canonical JSON of model, system, prompt and metrics (11.13)."""
    blob = json.dumps({"model": model, "system": system, "prompt": prompt, "metrics": clean_metrics(metrics)},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def schema_errors(body: Any) -> list[str]:
    """[] when `body` matches BRIEFING_SCHEMA (no jsonschema dependency; the schema is small and fixed)."""
    if not isinstance(body, dict):
        return ["schema:not_object"]
    errs = [f"schema:extra_key:{k}" for k in body if k not in ("headline", "claims")]
    if not isinstance(body.get("headline"), str):
        errs.append("schema:headline")
    claims = body.get("claims")
    if not isinstance(claims, list):
        return errs + ["schema:claims"]
    if not 2 <= len(claims) <= 4:
        errs.append(f"schema:claim_count:{len(claims)}")
    for i, c in enumerate(claims):
        if not isinstance(c, dict) or set(c) != {"text", "field", "value"}:
            errs.append(f"schema:claim[{i}]:keys")
            continue
        if not isinstance(c["text"], str) or not isinstance(c["field"], str):
            errs.append(f"schema:claim[{i}]:type")
        v = c["value"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            errs.append(f"schema:claim[{i}]:value")
    return errs


def _response_body(resp: Any) -> dict[str, Any] | None:
    """Parsed JSON of the text content blocks, or None when there is no parsable JSON."""
    text = "".join(getattr(b, "text", "") or "" for b in (getattr(resp, "content", None) or [])
                   if getattr(b, "type", "text") == "text")
    try:
        return json.loads(text) if text.strip() else None
    except (json.JSONDecodeError, ValueError):
        return None


def _check_entry(entry: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """The same checks for a fresh response and for a cache hit (11.12, 11.13)."""
    stop = entry.get("stop_reason")
    if stop in REJECT_STOPS:
        return None, [f"stop_reason:{stop}"]
    body = entry.get("body")
    if body is None:
        return None, ["schema:no_json"]
    errs = schema_errors(body)
    return (None, errs) if errs else (body, [])


def _write_entry(path: Path, entry: Mapping[str, Any]) -> None:
    """Write one cache entry as it arrives (atomic rename, so a crash never leaves a half file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_clean(dict(entry)), sort_keys=True, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def fetch_attempt(client: Any, system: str, prompt: str, metrics: Mapping[str, float],
                  cache_dir: Path = LLM_CACHE) -> Attempt:
    """Cache hit -> checks, no call. No client -> unavailable. Else one call; every completed response is
    cached (refusal and max_tokens too) and then read back, so a re-run sees exactly what this run saw."""
    path = Path(cache_dir) / f"{cache_key(MODEL, system, prompt, metrics)}.json"
    if path.exists():
        body, reasons = _check_entry(json.loads(path.read_text(encoding="utf-8")))
        return Attempt(body, reasons, True, "cache")
    if client is None:
        return Attempt(None, ["no_client"], False, "none")
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config=OUTPUT_CONFIG,
        )   # no temperature parameter: the model rejects it (11.11)
    except Exception as e:  # noqa: BLE001  any API failure is a rejected attempt; not cached (11.7)
        return Attempt(None, [f"exception:{type(e).__name__}"], True, "call")
    _write_entry(path, {"model": MODEL, "stop_reason": getattr(resp, "stop_reason", None),
                        "body": _response_body(resp)})
    body, reasons = _check_entry(json.loads(path.read_text(encoding="utf-8")))
    return Attempt(body, reasons, True, "call")


def request_briefing(client: Any, system: str, prompt: str, metrics: Mapping[str, float],
                     cache_dir: Path = LLM_CACHE) -> dict[str, Any] | None:
    """Design signature: the schema-valid body, or None for a rejected or unavailable attempt."""
    return fetch_attempt(client, system, prompt, metrics, cache_dir).body


# ---------------------------------------------------------------- one tract-hour


def llm_briefing(metrics: Mapping[str, float], town: str, channel: str, client: Any, *,
                 tol: Tol | Mapping[str, float], banned: Iterable[str], telecom_rule: str = "modeled",
                 cache_dir: Path = LLM_CACHE, key: str = "", failures: list[dict[str, Any]] | None = None,
                 stats: dict[str, int] | None = None) -> dict[str, Any]:
    """Verified_Briefing ("pass" | "regenerated") or the Template_Briefing ("fallback") (11.5, 11.6, 11.7, 11.12).
    With no client and no cached response the Template_Briefing is returned unchanged (verifier "pass")."""
    banned = list(banned)
    failures = [] if failures is None else failures
    stats = {} if stats is None else stats
    action = action_for(channel)
    reasons: list[str] = []
    for attempt, verdict in ((1, "pass"), (2, "regenerated")):
        a = fetch_attempt(client, SYSTEM, build_prompt(metrics, town, channel, reasons), metrics, cache_dir)
        if not a.available:
            if attempt == 1:   # nothing to verify: keep the Template_Briefing (11.15)
                stats["template"] = stats.get("template", 0) + 1
                return template_briefing(metrics, channel, telecom_rule)
            break
        stats["calls" if a.source == "call" else "cache_hits"] = stats.get(
            "calls" if a.source == "call" else "cache_hits", 0) + 1
        reasons = a.reasons
        if a.body is not None:
            b = {"kind": "verified", "headline": a.body["headline"],
                 "claims": [{"text": c["text"], "field": c["field"], "value": float(c["value"])}
                            for c in a.body["claims"]],
                 "action": action, "verifier": verdict}
            reasons = verify_briefing(b, metrics, tol, banned)
            if not reasons:
                stats[verdict] = stats.get(verdict, 0) + 1
                return b
        failures.append({"kind": "briefing", "key": key, "attempt": attempt, "reasons": list(reasons)})
    stats["fallback"] = stats.get("fallback", 0) + 1
    return {**template_briefing(metrics, channel, telecom_rule), "verifier": "fallback"}


# ---------------------------------------------------------------- step 11


def llm_briefings(ctx, client: Any, report: Mapping[str, Any], cache_dir: Path = LLM_CACHE
                  ) -> tuple[bool, list[dict[str, Any]], dict[str, int]]:
    """Replace Briefings at (Key_Demo_Hour, queued tract) pairs only (11.2, 11.14, 11.18).
    Returns (ran, failures, stats); ran is False when no key hour has both channels (11.19)."""
    stats = {"pairs": 0, "calls": 0, "cache_hits": 0, "pass": 0, "regenerated": 0, "fallback": 0, "template": 0}
    failures: list[dict[str, Any]] = []
    if not report.get("has_mixed_hour"):
        print(f"       {MIXED_ADJUST}")
        return False, failures, stats
    briefings = ctx["content"]["briefings"]
    fm, chan = ctx["flat_metrics"], ctx["channel"]
    rule = ctx["telecom_rule"] if "telecom_rule" in ctx else None
    tol, banned = ctx.scoring.verifier, all_banned(ctx.languages)
    for h in ctx.scoring.key_demo_hours:
        for row in ctx["queue"].get(h, []):
            g, town = str(row["geoid"]), str(row["town"])
            stats["pairs"] += 1
            briefings[h][g] = llm_briefing(
                fm(g, h), town, str(chan.at[h, g]), client, tol=tol, banned=banned,
                telecom_rule=str(rule.at[h, town]) if rule is not None else "modeled",
                cache_dir=cache_dir, key=f"{h}/{g}", failures=failures, stats=stats)
    return True, failures, stats


def step(ctx) -> None:
    """Design step 11; runs after key_hour_report (11.18). Sets llm_step, llm_failures and llm_stats."""
    report = ctx["key_hour_report"]
    client, llm_step = (None, "skipped_key_hours") if not report.get("has_mixed_hour") else make_client(ctx.no_llm)
    ran, failures, stats = llm_briefings(ctx, client, report)
    ctx["llm_step"] = llm_step if ran else "skipped_key_hours"
    ctx["llm_failures"] = failures
    ctx["llm_stats"] = stats
    print(f"       llm_briefings: {ctx['llm_step']}; key-hour pairs {stats['pairs']}, calls {stats['calls']}, "
          f"cache hits {stats['cache_hits']}; verified pass {stats['pass']}, regenerated {stats['regenerated']}, "
          f"fallback {stats['fallback']}, template kept {stats['template']}")
