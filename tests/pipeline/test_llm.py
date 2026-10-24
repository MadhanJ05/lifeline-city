"""LLM operator Briefings (step 11) with a fake client: Req 1.4, 11.2, 11.5 to 11.7, 11.11 to 11.15, 11.18, 11.19.
No real Anthropic calls are made here."""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from pipeline import llm
from pipeline.common import HOURS, load_languages, load_scoring
from pipeline.content import action_for, template_briefing
from pipeline.run import Ctx
from pipeline.verifier import Tol, all_banned

LANGS = load_languages()
TOL = Tol(0.01, 0.01)
BANNED = all_banned(LANGS)
M = {"out_pct": 0.8234, "hours_dark": 40.0, "telecom": 1.0, "customers": 12345.0, "need.seniors_alone.pct": 0.92}
GOOD = {"headline": "Dark for 40 hours, 82% without power",
        "claims": [{"text": "82% of customers without power", "field": "out_pct", "value": 0.8234},
                   {"text": "Dark for 40 hours", "field": "hours_dark", "value": 40}]}
UNGROUNDED = {"headline": "Half the town is out",
              "claims": [{"text": "50% without power", "field": "out_pct", "value": 0.5},
                         {"text": "Dark for 40 hours", "field": "hours_dark", "value": 40}]}
BAD_SCHEMA = {"headline": "Dark for 40 hours", "claims": [{"text": "Dark for 40 hours", "field": "hours_dark",
                                                            "value": 40}]}


def resp(body=None, stop="end_turn", text=None):
    return SimpleNamespace(stop_reason=stop,
                           content=[SimpleNamespace(type="text", text=json.dumps(body) if text is None else text)])


class FakeClient:
    """Stands in for anthropic.Anthropic(): messages.create pops the next outcome (a response or an exception)."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if not self.outcomes:
            raise AssertionError("unexpected Anthropic call")
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


def brief(client, cache, failures=None, channel="sms"):
    return llm.llm_briefing(M, "Falmouth", channel, client, tol=TOL, banned=BANNED, cache_dir=cache,
                            key="h/g", failures=failures)


def test_pass_and_request_shape(tmp_path):
    c = FakeClient(resp(GOOD))
    b = brief(c, tmp_path)
    assert (b["kind"], b["verifier"], b["action"]) == ("verified", "pass", action_for("sms"))
    assert b["headline"] == GOOD["headline"] and len(c.calls) == 1
    kw = c.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == 4000 and "temperature" not in kw
    assert kw["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": llm.BRIEFING_SCHEMA}}
    assert kw["system"] == llm.SYSTEM
    sent = json.loads(kw["messages"][0]["content"])
    assert kw["messages"][0]["role"] == "user"
    assert sent == {"town": "Falmouth", "channel": "sms", "metrics": llm.clean_metrics(M)}   # only these (11.2)
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_schema_has_no_unsupported_array_bounds():
    """The API rejects array minItems other than 0 or 1 (400 at checkpoint 8); the claim count is checked locally."""
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "array":
                assert node.get("minItems", 0) in (0, 1) and "maxItems" not in node
            for v in node.values():
                walk(v)
    walk(llm.BRIEFING_SCHEMA)
    claim = {"text": "x", "field": "out_pct", "value": 0.5}
    assert llm.schema_errors({"headline": "h", "claims": [claim]}) == ["schema:claim_count:1"]
    assert llm.schema_errors({"headline": "h", "claims": [claim] * 5}) == ["schema:claim_count:5"]
    assert llm.schema_errors({"headline": "h", "claims": [claim] * 2}) == []


def test_regenerated_sends_reasons(tmp_path):
    failures = []
    c = FakeClient(resp(UNGROUNDED), resp(GOOD))
    b = brief(c, tmp_path, failures, channel="door_knock")
    assert (b["kind"], b["verifier"], b["action"]) == ("verified", "regenerated", action_for("door_knock"))
    assert "value_mismatch:out_pct" in c.calls[1]["messages"][0]["content"]
    assert [(f["attempt"], f["key"]) for f in failures] == [(1, "h/g")]


def test_fallback_after_two_rejections(tmp_path):
    failures = []
    b = brief(FakeClient(resp(UNGROUNDED), resp(BAD_SCHEMA)), tmp_path, failures)
    assert b == {**template_briefing(M, "sms"), "verifier": "fallback"}
    assert [f["attempt"] for f in failures] == [1, 2]
    assert any(r.startswith("schema:claim_count") for r in failures[1]["reasons"])


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_refusal_and_max_tokens_are_rejected_and_cached(tmp_path, stop):
    b = brief(FakeClient(resp(GOOD, stop=stop), resp(GOOD, stop=stop)), tmp_path)
    assert b["verifier"] == "fallback" and b["kind"] == "template"
    entries = [json.loads(p.read_text()) for p in tmp_path.glob("*.json")]
    assert len(entries) == 2 and {e["stop_reason"] for e in entries} == {stop}
    assert brief(None, tmp_path) == b                    # the re-run repeats the outcome from the cache


def test_exception_is_rejected_and_not_cached(tmp_path):
    failures = []
    b = brief(FakeClient(RuntimeError("boom"), resp(GOOD)), tmp_path, failures)
    assert b["verifier"] == "regenerated"
    assert failures[0]["reasons"] == ["exception:RuntimeError"]
    assert len(list(tmp_path.glob("*.json"))) == 1       # only attempt 2's completed response


def test_unparsable_text_is_rejected(tmp_path):
    b = brief(FakeClient(resp(text="not json"), resp(text="")), tmp_path)
    assert b["verifier"] == "fallback"


def test_cache_hit_reused_without_client(tmp_path):
    first = brief(FakeClient(resp(UNGROUNDED), resp(GOOD)), tmp_path)
    again = brief(FakeClient(), tmp_path)                # a client call would raise
    no_llm = brief(None, tmp_path)
    assert first == again == no_llm and no_llm["verifier"] == "regenerated"


def test_no_client_no_cache_keeps_template(tmp_path):
    failures = []
    assert brief(None, tmp_path, failures) == template_briefing(M, "sms")
    assert failures == [] and not list(tmp_path.iterdir())


def test_cache_key_covers_metrics():
    p = llm.build_prompt(M, "Falmouth", "sms")
    assert llm.cache_key(llm.MODEL, llm.SYSTEM, p, M) != llm.cache_key(llm.MODEL, llm.SYSTEM, p, {**M, "out_pct": 0.9})


# ---------------------------------------------------------------- step 11 gating


def _ctx(mixed_hours, queued, no_llm=False):
    """Ctx with two hours: HOURS[3] (key hour) and HOURS[4] (not a key hour), both with the same queue."""
    key, other = HOURS[3], HOURS[4]
    scoring = load_scoring().model_copy(update={"key_demo_hours": [key]})
    ctx = Ctx(scoring=scoring, languages=LANGS, no_llm=no_llm)
    geoids = ["25001000100", "25001000200", "25001000300"]
    ctx["channel"] = pd.DataFrame("sms", index=HOURS, columns=geoids)
    ctx["channel"].loc[key, geoids[1]] = "door_knock"
    ctx["flat_metrics"] = lambda g, h: dict(M)
    ctx["queue"] = {h: [{"geoid": g, "town": "Falmouth"} for g in geoids[:queued]] for h in (key, other)}
    ctx["content"] = {"briefings": {h: {g: template_briefing(M, str(ctx["channel"].at[h, g])) for g in geoids}
                                    for h in (key, other)}}
    ctx["key_hour_report"] = {"hours": {key: {}}, "has_mixed_hour": mixed_hours}
    return ctx, key, other, geoids


def test_llm_briefings_calls_only_key_hour_queued_pairs(tmp_path):
    ctx, key, other, geoids = _ctx(True, queued=2)
    before_other = json.dumps(ctx["content"]["briefings"][other], sort_keys=True)
    c = FakeClient(resp(GOOD), resp(GOOD))
    ran, failures, stats = llm.llm_briefings(ctx, c, ctx["key_hour_report"], cache_dir=tmp_path)
    assert ran and len(c.calls) == 2 and stats["pass"] == 2 and failures == []
    b = ctx["content"]["briefings"]
    assert [b[key][g]["kind"] for g in geoids] == ["verified", "verified", "template"]
    assert b[key][geoids[1]]["action"] == action_for("door_knock")
    assert json.dumps(b[other], sort_keys=True) == before_other


def test_skipped_key_hours_makes_no_calls(tmp_path, capsys):
    ctx, key, _, geoids = _ctx(False, queued=3)
    ran, _, _ = llm.llm_briefings(ctx, FakeClient(), ctx["key_hour_report"], cache_dir=tmp_path)
    assert not ran and "adjust key_demo_hours" in capsys.readouterr().out
    assert all(ctx["content"]["briefings"][key][g]["kind"] == "template" for g in geoids)
    llm.step(ctx)
    assert ctx["llm_step"] == "skipped_key_hours" and ctx["llm_failures"] == []


def test_make_client_without_key_or_with_no_llm(monkeypatch):
    assert llm.make_client(True) == (None, "no_llm")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.make_client(False) == (None, "no_key")
