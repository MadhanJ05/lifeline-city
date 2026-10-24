"""Pipeline entry point: `python -m pipeline.run [--no-llm] [--skip-boston]`.

Steps run in design order (design.md, "Pipeline step order") and share one in-memory `Ctx`:
  fetch, tracts_towns, need, outage_curves, wires, telecom, lifelines, synthetic, content,
  key_hour_report, llm_briefings, verifier, voice_boston, scale_catalog, export, privacy_guard.
Each step is registered in STEPS as soon as it is built, so the pipeline runs after every task.
A step is a function `fn(ctx) -> None` that reads earlier outputs from `ctx` and stores its own.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pipeline.common import Languages, PipelineError, Scoring, load_languages, load_scoring


@dataclass
class Ctx:
    """Shared run state. Step outputs go in `out`; provenance for sources.json goes in `sources`."""

    scoring: Scoring
    languages: Languages
    no_llm: bool = False       # Req 11.15: no Anthropic calls, cache hits only
    skip_boston: bool = False  # skip the cuttable voice_boston step
    out: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        try:
            return self.out[key]
        except KeyError:
            raise PipelineError(f"step output {key!r} is missing: an earlier step did not run") from None

    def __setitem__(self, key: str, value: Any) -> None:
        self.out[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.out

    def source(self, kind: str, **entry: Any) -> None:
        """Append one provenance entry (a fetch, an input row, an exclusion, ...) under `kind`."""
        self.sources.setdefault(kind, []).append(entry)


Step = tuple[str, Callable[[Ctx], None]]

# Ordered step list. Later tasks append (name, fn) in design order; unbuilt steps are absent.
STEPS: list[Step] = []

from pipeline import (content, export, fetch, lifelines, llm, need, outage_curves, privacy_guard,  # noqa: E402
                      scale_catalog, synthetic, telecom, tracts_towns, verifier, wires)  # (Ctx-free modules only)

STEPS.append(("fetch", fetch.step))
STEPS.append(("tracts_towns", tracts_towns.step))
STEPS.append(("need", need.step))
STEPS.append(("outage_curves", outage_curves.step))
STEPS.append(("wires", wires.step))
STEPS.append(("telecom", telecom.step))
STEPS.append(("lifelines", lifelines.step))
STEPS.append(("synthetic", synthetic.step))
STEPS.append(("content", content.step))              # design step 9: Resident_Templates + Template_Briefings
STEPS.append(("key_hour_report", lifelines.key_hour_step))   # design step 10: always runs, also with --no-llm
STEPS.append(("llm_briefings", llm.step))             # design step 11: only after the key-hour report (11.18)
STEPS.append(("verifier", verifier.step))             # design step 12: ctx["verifier_log"]
# design step 13: voice_boston (cuttable, task 16) registers here, before scale_catalog, so that
# boston_blizzard switches from preview to live once ctx["boston_voice"] exists.
STEPS.append(("scale_catalog", scale_catalog.step))   # design step 14: ctx["scale_catalog"]
STEPS.append(("export", export.step))                 # design step 15: data/processed/*, sources.json last
STEPS.append(("privacy_guard", privacy_guard.step))   # design step 16: scan data/processed/ and api/ (1.11, 1.12)


def run(ctx: Ctx, steps: list[Step] | None = None) -> None:
    """Run each step in order, printing its timing. A PipelineError stops the run."""
    steps = STEPS if steps is None else steps
    if not any(name == "voice_boston" for name, _ in steps):
        ctx.skip_boston = True  # implied when voice_boston is not built
    total = time.perf_counter()
    for name, fn in steps:
        if name == "voice_boston" and ctx.skip_boston:
            print(f"[skip] {name} (--skip-boston)")
            continue
        t0 = time.perf_counter()
        try:
            fn(ctx)
        except PipelineError as e:
            raise PipelineError(": ".join(map(str, (name, *e.args)))) from e
        print(f"[ok]   {name:<16} {time.perf_counter() - t0:7.2f}s")
    print(f"done: {len(steps)} step(s) in {time.perf_counter() - total:.2f}s")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m pipeline.run", description=__doc__.splitlines()[0])
    p.add_argument("--no-llm", action="store_true", help="make no Anthropic API calls; use llm_cache hits only")
    p.add_argument("--skip-boston", action="store_true", help="skip the Boston Need + Voice step")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, steps: list[Step] | None = None) -> int:
    args = parse_args(argv)
    try:
        ctx = Ctx(scoring=load_scoring(), languages=load_languages(),
                  no_llm=args.no_llm, skip_boston=args.skip_boston)
        run(ctx, steps)
    except PipelineError as e:
        print(f"pipeline error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
