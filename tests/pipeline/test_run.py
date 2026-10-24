"""Tests for the pipeline/run.py skeleton: step order, flags, timings and error exit."""
import pytest

from pipeline.common import ConfigError, PipelineError
from pipeline.run import Ctx, main, parse_args, run


@pytest.fixture
def ctx():
    from pipeline.common import load_languages, load_scoring
    return Ctx(scoring=load_scoring(), languages=load_languages())


def test_flags_default_off_and_parse():
    a = parse_args([])
    assert (a.no_llm, a.skip_boston) == (False, False)
    a = parse_args(["--no-llm", "--skip-boston"])
    assert (a.no_llm, a.skip_boston) == (True, True)


def test_steps_run_in_order_and_share_ctx(ctx, capsys):
    seen = []
    steps = [("a", lambda c: (seen.append("a"), c.__setitem__("x", 1))),
             ("b", lambda c: seen.append(("b", c["x"])))]
    run(ctx, steps)
    assert seen == ["a", ("b", 1)]
    out = capsys.readouterr().out
    assert "[ok]   a" in out and "[ok]   b" in out and "done: 2 step(s)" in out


def test_skip_boston_skips_voice_and_is_implied_when_absent(ctx):
    calls = []
    ctx.skip_boston = True
    run(ctx, [("voice_boston", lambda c: calls.append(1))])
    assert calls == []
    fresh = Ctx(scoring=ctx.scoring, languages=ctx.languages)
    run(fresh, [])
    assert fresh.skip_boston is True


def test_missing_output_and_sources(ctx):
    with pytest.raises(PipelineError, match="'nope' is missing"):
        ctx["nope"]
    ctx.source("fetch", name="acs", url="https://example.invalid", vintage=2024)
    assert ctx.sources == {"fetch": [{"name": "acs", "url": "https://example.invalid", "vintage": 2024}]}


def test_pipeline_error_exits_nonzero_with_step_name(capsys):
    def boom(c):
        raise ConfigError("bad key")
    assert main(["--no-llm"], steps=[("need", boom)]) == 1
    assert "pipeline error: need: bad key" in capsys.readouterr().err


def test_empty_pipeline_exits_zero():
    assert main(["--no-llm"], steps=[]) == 0
