# How Lifeline City was built with Kiro

Kiro held the project rules (steering), the plan (one spec) and the guardrails (hooks). `DECISIONS.md` is the source of truth; steering and the spec restate it so every agent turn starts from the same constraints.

## Steering (`.kiro/steering/`)

- `product.md`: the one-liner, Tier 1 / Tier 2 framing (Cape case study, any MA town and hazard), the DECISIONS.md Section 6 Keep list and an explicit non-goals list.
- `tech.md`: the pipeline → `data/processed/` → FastAPI → React/MapLibre flow, Python 3.13 via `uv`, CRS and timezone rules, polling instead of SSE, LLM use limited to cached operator briefings.
- `structure.md`: repo layout, which layer may read or write which folder, one type per processed file in `api/data.py` and `web/src/types.ts`, tests mirror source paths.
- `scoring.md`: the DECISIONS.md Section 3 formulas copied verbatim, plus the Boston `silence_t` math and the `config/scoring.yaml` keys. Code may change weights, never formulas.
- `privacy.md`: real data is aggregate only, synthetic records carry `synthetic: true` and show "Simulated", phone numbers live only in `.env` and are masked to the last four digits, required provenance labels.
- `outreach-style.md`: carbon monoxide safety first, 911 plus the regional help line in every resident message, SMS at most 2 segments counted with real GSM-7 / UCS-2 encoding, en/pt/es only, descriptive language.

## Spec (`.kiro/specs/lifeline-city/`)

- `requirements.md`: 31 requirements with 228 EARS acceptance criteria ("WHEN … THE Pipeline SHALL …"), scoped to the DECISIONS.md Keep list. Twilio and the extended scale catalog are marked Optional.
- `design.md`: architecture, the pipeline step order, JSON schemas for every `data/processed/` file, the API routes, the check-in state machine, error handling and 28 correctness properties (Properties 1 to 4 required).
- `tasks.md`: 19 top-level tasks in build order: pipeline → hooks → API → UI → check-in loop → docs, with a checkpoint after each block. An explicit MVP line sits after the docs; Boston Voice (task 16) is the first block to cut, and Optional items are marked `*`.

## Hooks (`.kiro/hooks/`, created with the createHook tool in task 7)

| id | trigger | matcher | command | purpose |
|---|---|---|---|---|
| `required-pbt` | PostFileSave | `/pipeline/.*\.py$` | `.venv/bin/python -m pytest -q -m required_pbt` (timeout 120 s) | Re-run Properties 1 to 4 on every pipeline edit; Hypothesis prints the falsifying example |
| `privacy-guard-save` | PostFileSave | `/(api\|data/processed)/` | `.venv/bin/python -m pipeline.privacy_guard api data/processed` | Catch unmasked phone numbers or street addresses on save |
| `privacy-guard-create` | PostFileCreate | `/(api\|data/processed)/` | same | Same check for new files |
| `privacy-guard-stop` | Stop | none | same | Re-scan at the end of every agent turn |

The guard prints only path, line and match type, never the matched value. The Stop hook exists because files written by the pipeline or by agent tools may not fire an editor save event, so the save and create hooks alone can miss them. As a second layer, `python -m pipeline.run` runs the same guard as its last step and exits non-zero on any finding.

## How the spec changed during the build

- The help line became per region: "2-1-1" on the Cape (Mass 211, where MEMA sent residents) and "311" in Boston, stored as `help_line` in `config/languages.yaml`.
- Resident outreach (SMS, doorstep, radio) moved to hand-written templates only; the LLM writes only operator briefings, checked by the verifier.
- `key_demo_hours` are validated by a key-hour channel report that runs even with `--no-llm`, so the set includes at least one hour with both `sms` and `door_knock`. The final set includes Mon Feb 23 5 PM (`2026-02-23T17:00`).
- The structured-output schema in `design.md` had `minItems: 2` on claims. The API rejected it (only 0 or 1 is allowed), so the schema sent to the API has no array bounds and the 2 to 4 claim count is enforced locally (`pipeline/llm.py`).
- Export writes directly to `data/processed/` with no staging directory; the privacy guard then runs over the result.
- Town (county subdivision) GEOIDs were dropped from exports: they are 10 digits and the guard read them as phone numbers.

## Verification

Required property tests, marked `required_pbt` (6 tests):

1. Lifelines and priority stay in [0, 1].
2. Channel follows telecom, and every queued tract-hour has a radio script.
3. The verifier accepts exactly the grounded claims.
4. Every SMS render is at most 2 segments under GSM-7 / UCS-2 rules.

Current counts: `pytest --co -q` collects 294 Python tests (pipeline and API); `cd web && npx vitest --run` passes 96 tests in 9 files.

## Screenshots for the project card

- The spec: `tasks.md` in the Kiro spec view with the MVP line and checked tasks, plus a property section of `design.md`.
- Steering: the `.kiro/steering/` list with `scoring.md` open on the verbatim formulas.
- A hook firing: `required-pbt` running after a save in `pipeline/`, or `privacy-guard-stop` reporting a clean scan at the end of a turn.
