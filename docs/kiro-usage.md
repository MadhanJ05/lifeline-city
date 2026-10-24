# How Lifeline City was built with Kiro

Kiro held the project rules (steering), the plan (one spec) and the guardrails (hooks). `DECISIONS.md` is the source of truth; steering and the spec restate it so every agent turn starts from the same constraints. Every line of application code was generated in Kiro, running Claude Opus 5.5.

## At a glance

**Kiro tools used.**

- **Kiro IDE** for everything that shipped. The **Spec agent** built the core product:
  - **Quick Spec** first asked clarifying questions, then generated requirements, design and tasks.
  - **Spec task execution** then worked through the task list. The orchestrator dispatched one sub-agent per task, ran independent tasks in waves from the dependency graph in `tasks.meta.json`, and tracked status and property-test results.
- The **Default agent**, in vibe mode, did the final visual redesign, guided by a design steering file.
- **Autopilot** was on during the build, with a scoped allow-list of trusted shell commands so routine `uv`, `pytest`, `npm` and `git` steps ran without prompts.
- **Kiro CLI** was used for setup: GitHub sign-in, setting Claude Opus 5.5 as the default model (`chat.defaultModel`), and checking hackathon credits with `/usage`.
- We did not use Kiro Web, Crew, MCP servers or Powers. All data access is pipeline code, so it is cached, reproducible and testable without a live connection.

**Spec-driven vs vibe coding.** The core went through the spec: data reconstruction, scoring, verifier, API, check-in state machine. The look did not.
- **The spec caught design errors before any code existed.** During Quick Spec's clarify step, Kiro noticed that one hand-entered "Cape-wide cellular outage" row would have flagged every town as phones-down for the whole storm. That would have turned every text check-in into a door-knock and removed the demo's core contrast. It asked which events should set the flag, and the answer became Requirement 6.
- **It also pushed back on scope.** Kiro asked where the heavy Boston block should go, how much text the LLM should write, and which tests were required. The answers became a must-have line in `tasks.md` with an explicit cut order, which is what let a solo build finish everything above the line.
- **Vibe mode suited the redesign.** For a subjective, visual change, we iterated against the design steering file and a live dev server instead of writing more requirements.

**Agent hooks.** Four hooks, created with Kiro's createHook tool:
- **Required property tests on save:** they re-run on every save of a `pipeline/*.py` file.
- **Privacy guard:** a scan for phone numbers and street addresses runs on every save and file creation in `api/` and `data/processed/`, and again at the end of every agent turn. The end-of-turn run is there because files written by the pipeline or by agent tools don't fire editor save events.
- **What the guard caught:** 10-digit town IDs that looked like phone numbers. Kiro removed them from the exports rather than weakening the guard.

**Steering strategy.** The biggest difference came from one source of truth plus verbatim formulas:
- Every steering file points at `DECISIONS.md`.
- `scoring.md` copies the scoring formulas word for word, so generated code could change weights but never the math.
- When decisions changed mid-build (the phones-down rule, Python 3.13, a 2-1-1 help line for the Cape instead of 311), Kiro re-synced its own steering files and checked the formula block with a diff before writing code.
- A seventh file, `design.md`, carried the design system for the redesign.

**Property-based testing.** We used Hypothesis in Python and fast-check in TypeScript.
- **Four properties are required**, because each one protects a promise the demo makes:
  1. scores stay between 0 and 1
  2. the reach channel always follows the phones-down flag, and every queued area has a radio script
  3. the verifier accepts exactly the claims grounded in the data
  4. every text message fits in two SMS segments under real GSM-7 and UCS-2 encoding
- **Optional properties** cover phone masking and other pure logic.
- **What it caught:**
  - **Accented Portuguese texts.** While designing property 4, Kiro ran the segment check against the drafted templates. Portuguese with accents (ã, ç, õ) forces UCS-2 encoding and needs 3 segments; without accents it fits in 2. Text bodies in Portuguese and Spanish are now accent-free, while door scripts and radio keep their accents. A hand-picked unit test on English text would never have hit this.
  - **Ungrounded numbers in live AI output.** The same verifier logic as property 3, run against live model output, rejected 36 of 50 first-draft AI briefings for numbers that were not in the data.

**Work done outside Kiro.** Research on the storm and its after-action review, data sourcing (including Eversource's filing with the state utility regulator), the hand-entered outage CSVs and `DECISIONS.md` were prepared with Claude (Anthropic's assistant). Those documents were inputs to Kiro's steering and spec.

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

Current counts: `pytest --co -q` collects 294 Python tests (pipeline and API); `cd web && npx vitest --run` passes 113 tests in 11 files.

## Screenshots for the project card

- The spec: `tasks.md` in the Kiro spec view with the MVP line and checked tasks, plus a property section of `design.md`.
- Steering: the `.kiro/steering/` list with `scoring.md` open on the verbatim formulas.
- A hook firing: `required-pbt` running after a save in `pipeline/`, or `privacy-guard-stop` reporting a clean scan at the end of a turn.
