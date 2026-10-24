# Implementation Plan: Lifeline City

## Overview

The plan builds the Cape demo end to end in the order the requirements set: scaffold, offline Cape pipeline, Kiro hooks, local API, web app, check-in loop, then docs. The pipeline and API use Python 3.13 (pytest + Hypothesis). The web app uses TypeScript (Vite + React + Tailwind + MapLibre, Vitest + fast-check). Each pipeline step is registered in `pipeline/run.py` as soon as it is built, so the pipeline runs after every step. The four required property tests sit next to the code they test.

Resident outreach (SMS, doorstep, radio) comes only from hand-written Resident_Templates. The LLM is used only for operator Briefings at the Key_Demo_Hours, and only after the key-hour channel report shows a key hour with both channels.

Everything above the MVP line is the demo minimum. Boston Voice and the Optional items come after it.

Rough budget for about 5 hours: scaffold 15 min, pipeline 1 h 50 min (no staging, no LLM outreach drafts, no radio fitting), hooks 5 min, API 25 min, web 75 min, check-in loop 40 min, docs 15 min. That is about 4 h 45 min, leaving about 15 min for the `key_demo_hours` adjustment and the LLM run at checkpoint 8.

## Tasks

- [x] 1. Set up the repository and scaffold
  - [x] 1.1 Initialize git and write `.gitignore`
    - Run `git init` at the workspace root
    - Ignore `.env`, `data/raw/cache/`, `.venv/`, `web/node_modules/`, `web/dist/`, `__pycache__/`, `.pytest_cache/` and `.hypothesis/`
    - _Requirements: 26.3, 31.1_

  - [x] 1.2 Create the Python environment and package skeleton
    - Run `uv venv --python 3.13`. Write `requirements.txt` with exact pins for pandas, geopandas, shapely, numpy, scipy, requests, pyyaml, openpyxl, pydantic, python-dotenv, anthropic (a version that supports `output_config` with effort and JSON-schema structured outputs), fastapi, uvicorn, httpx, pytest and hypothesis. Install with `uv pip install -r requirements.txt`
    - In `pyproject.toml`, register the pytest marker `required_pbt` and set `testpaths = ["tests"]`
    - Create empty packages `pipeline/`, `api/`, `tests/pipeline/` and `tests/api/`
    - In `tests/conftest.py`, register the Hypothesis profile (`max_examples=100, deadline=None, derandomize=True`) and a `FICTIONAL_NUMBERS` constant limited to +1 617 555 0100 to 0199
    - _Requirements: 26.6, 30.5, 31.2_

  - [x] 1.3 Write the `config/` files
    - `scoring.yaml` as given in the design: `lifelines_weights`, `hours_dark_cap: 72`, `dark_threshold`, `telecom_model`, `telecom_observed_default_hours: 12` with the ASSUMPTION comment, `access_hazard_wires_pct`, `queue_size: 10`, the five initial `key_demo_hours` (adjusted at checkpoint 8), `verifier` tolerances, `demo` (including `operator_household: 1` and `radio_update_interval_hours`) and `boston`
    - `languages.yaml`:
      - supported languages, labels and reply keywords
      - `co_line` per language, with `sms` (unaccented GSM-7) and `full` (accented) forms
      - `help_line` per region with `number` and en, pt and es sentences in `sms` and `full` forms: cape "911 for emergencies, 2-1-1 for shelters and help" (number "2-1-1"), boston "911 for emergencies, 311 for city help" (number "311")
      - `allowed_acronyms: ["911", "2-1-1", "311", "OK"]`, banned terms and promise patterns
      - `household_language_mix` with a default mix and `by_town` for Barnstable and Yarmouth set to en 0.6, pt 0.3, es 0.1, labeled as an assumption
    - `responders.yaml` (roles and all 15 towns) and `hazards.yaml` (5 hazards, need inputs, `open_311_towns` and the 6 entries)
    - `channels.yaml` and `storm_types.yaml` with the provisional values from the design. Task 16.1 confirms them
    - _Requirements: 1.8, 6.8, 7.3, 11.2, 11.17, 13.4, 15.5, 17.3, 17.4, 19.2, 19.3, 24.1, 27.2_

  - [x] 1.4 Write `.env.example`
    - Empty values for `ANTHROPIC_API_KEY`, `AWS_REGION`, `CENSUS_API_KEY`, `SMS_MODE`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `DEMO_PHONE_NUMBERS` and `DEMO_REPLY_TIMEOUT_SECONDS`
    - _Requirements: 26.1, 26.2, 26.3_

- [x] 2. Build the pipeline foundations
  - [x] 2.1 Implement `pipeline/common.py`
    - `TZ`, `HOURS` (119 keys), `hour_key`, `hour_end`, `pct_rank`, `normalize`, `strip_accents`, `match_town` (whole name only, never substring), `segments` (GSM-7 basic and extension tables, UCS-2 otherwise), `write_json` (sorted keys, 6 dp), `PROVENANCE`, `CAPE_TOWNS`, paths and `.env` loading
    - `load_scoring` with pydantic. It raises `ConfigError` naming the weights when `lifelines_weights` do not sum to 1 or a weight is negative, and when `telecom_observed_default_hours` is not a positive integer
    - `load_languages` with pydantic. It raises `ConfigError` unless `help_line` has `cape` and `boston`, each with a number and en, pt and es sentences, and every language mix sums to 1
    - _Requirements: 1.5, 1.6, 1.8, 5.2, 6.5, 6.6, 6.8, 7.6, 13.4, 14.2, 26.2_

  - [x] 2.2 Implement the `pipeline/run.py` skeleton
    - `Ctx` dataclass, the ordered step list, and the CLI flags `--no-llm` and `--skip-boston`
    - _Requirements: 1.1, 11.15_

  - [x] 2.3 Implement `pipeline/fetch.py` and register the step
    - `cached_get` under `data/raw/cache/`, with no network call when a cache exists. Also: `acs` with the newest-vintage fallback, TIGER 2020 tract and cousub files, the emPOWER ZIP layer 1 (paged envelope query), and ACS B25001 housing units at the county-subdivision level
    - Raise `PipelineError(source, url)` when a fetch fails and no cache exists. Record each fetch and the vintage used in `Ctx` for `sources.json`
    - _Requirements: 1.1, 1.3, 1.7, 2.5, 3.3_

- [x] 3. Build the Cape geography, Need and outage curves
  - [x] 3.1 Implement `pipeline/tracts_towns.py` and register the step
    - Build the Cape towns from cousub rows with COUNTYFP 001, removing the trailing " Town". Raise `PipelineError` unless the names are exactly the 15 towns
    - Keep Cape_Tracts with population > 0. Assign tracts to towns by centroid in EPSG:26986, or by nearest boundary when the centroid is outside every town, and record `centroid` or `nearest`
    - _Requirements: 1.5, 3.4, 3.5_

  - [x] 3.2 Implement `pipeline/need.py` for the Cape and register the step
    - Pin the ACS variable IDs and check them against the vintage's `variables.json`. Sentinel negatives and zero denominators become NaN
    - `allocate_zip_counts` by area weight in EPSG:26986 for `Power_Dependent_Devices_DME` and `Medicare_Benes`. ZIPs reported as 11 keep the value 11 and are flagged as masked
    - `need_scores`: rank among Cape_Tracts only, set `need_t` to the mean of the available ranks, and record the `need_missing` list
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 3.3 Implement the Tab 3 curve, anchors and town customers in `pipeline/outage_curves.py`
    - Open the Eversource_Workbook with `read_only=True, data_only=True`. Build `tab3_curve` from header row 4 with the `12AM` to `11PM` labels. Stop with `PipelineError` (reporting the max and its hour) unless the peak is 269,063 at 2026-02-23T08:00
    - `load_anchors`: keep Barnstable rows only, dropping Plymouth, Scituate, Nantucket, Oak Bluffs and Edgartown. Take pct from `pct_out`, or from `customers_out / N` when `pct_out` is blank. Drop the sitrep #009 133,000 figure and record the exclusion without its value
    - `town_customers`: use the 2026-02-23T12:30 "MEMA via Patch" row. Sandwich and Chatham use ACS housing units, labeled "Estimated from ACS housing units."
    - _Requirements: 1.9, 3.1, 3.2, 3.3, 4.2, 4.3, 4.13, 4.14, 4.15_

  - [x] 3.4 Implement curve shaping and hourly scaling in `pipeline/outage_curves.py` and register the step
    - `ratio_shape` and `cape_total` (built from `cape_eversource` rows and shaped by Tab 3). `unscaled` per town: Chatham uses the Cape-wide share and is recorded as having no anchors
    - `scale_hour`: hold every Pinned_Town_Hour (the latest anchor wins) and respect lower bounds. Bisect the free towns to the Cape total. When the total cannot be matched, clip and record the hour and the unmatched customers
    - Attach "Reconstructed from MEMA, Eversource and public-safety reports." to `out_pct` and `hours_dark`
    - _Requirements: 4.1, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.16_

- [x] 4. Build wires, telecom and the scoring layer
  - [x] 4.1 Implement `pipeline/wires.py` and register the step
    - Read Tab 5 from row 5: C is the town, D the priority, E the received time and H the repair time. Column G is not read. Match towns with `match_town`. Report unmatched names with their call counts and continue the run
    - Count calls per hour. Compute the cumulative rate per 1,000 customers, then `pct_rank` across the 15 towns at each hour. Output town-hour arrays only. Log the Cape call count (about 1,082)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 4.2 Implement `pipeline/telecom.py` and register the step
    - Modeled rule: out_pct at or above 0.8 for 8 consecutive in-window hours. Split events on ";" and match each part as a whole name. A blank `end_local` gets 12 h, `end_assumed` and its label. Add `is_active`
    - `telecom_matrix` with the rule (none, observed, modeled or both) and the active event IDs. Place pins per matched town, or at the labeled Cape-wide marker when no town matches. Keep every event for `telecom_events.json`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.9, 8.4_

  - [x] 4.3 Implement `pipeline/lifelines.py` and register the step
    - `hours_dark` and `lifelines` with per-component contributions from the config weights. `priority`: each tract inherits its town's lifelines. `channel`: `door_knock` when telecom = 1, `sms` otherwise
    - `build_queue` sorted by (−priority, −need_t, GEOID), plus `flat_metrics` and `why_chips` (2 per row, each with `field` and `value` taken from the flat metrics)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 9.3, 12.1, 12.2_

  - [x] 4.4 Write the required property test for lifelines bounds
    - **Property 1: Lifelines and priority stay in [0, 1]**
    - In `tests/pipeline/test_lifelines.py` with marker `required_pbt`. Generate weights as non-negative floats normalized to sum to 1
    - **Validates: Requirements 7.3, 7.4, 7.5, 30.1**

  - [x] 4.5 Implement the key-hour channel report in `pipeline/lifelines.py` and register the step
    - `key_hour_report(queue, channel, key_demo_hours)`: for each Key_Demo_Hour, the `sms` and `door_knock` counts among queued tracts with their sorted, unique towns, plus `has_mixed_hour`. A key hour outside the Demo_Window raises `ConfigError`
    - Print the report on every run (including `--no-llm`), followed by "ok: at least one key hour shows both channels" or the "adjust key_demo_hours" message. Keep it in `Ctx` for `verifier_log.json` under `key_hour_channels`
    - Register it as design step 10. Tasks 5.1 and 5.4 insert the synthetic and content steps before it, and task 5.6 adds the LLM step after it
    - _Requirements: 11.16, 11.17, 11.18, 11.19_

- [x] 5. Build synthetic records, content and the verifier
  - [x] 5.1 Implement `pipeline/synthetic.py` and register the step
    - Generate `households_per_tract` households for every tract queued at any hour, seeded per GEOID. Rejection-sample each point inside the tract polygon. Draw the language from the town's `by_town` mix, or the default mix. Label each "Simulated household #N" with `synthetic: true` and no address
    - In Barnstable and Yarmouth tracts, set household #1 to `pt` after drawing, so the rng sequence and the other households are unchanged. Household #1 is also `demo.operator_household`, the one the presenter replies from
    - Generate one responder per (town, role) in `responders.yaml`, labeled "<Town> <role> (Simulated)"
    - _Requirements: 15.5, 17.1, 17.2, 17.3, 17.5, 17.6, 17.7, 17.8_

  - [x] 5.2 Implement `pipeline/verifier.py`
    - `verify_claim` rejects a missing field, a non-finite value, or a value outside `max(abs_tol, rel_tol·|m|)`. `verify_briefing` requires a headline and 2 to 4 claims, takes text numbers only from the claim display forms (plus 911, 2-1-1 and 311), and rejects banned terms. Add `display_forms`
    - `lint_outreach(text, kind, lang, region, allowed_numbers, langs)` checks:
      - the CO line comes first, or directly after the situation sentence in radio scripts
      - 911 and the region's `help_line.number` ("2-1-1" for the Cape) are present
      - SMS kinds and doorstep texts end with the region's Help_Line_Sentence in the message language
      - no "!", and no acronyms outside `allowed_acronyms`
      - no promised response times
      - English sentences have 20 words or fewer
      - radio numbers come only from the metric display forms, 911, the help line digits and the next-update hour
      - pt and es SMS bodies are GSM-7 with no accents
      - no banned terms, matched as whole words after `normalize`
    - `run_verifier` checks every Briefing (LLM and template), every resident render and every Why_Chip. It records pass, regenerated and fallback counts for LLM Briefings and copies the key-hour report into `key_hour_channels`. A failing Template_Briefing raises `PipelineError(hour, geoid, reasons)`. A failing render or Why_Chip raises `PipelineError(kind, lang, town[, term])`
    - _Requirements: 11.4, 11.9, 13.3, 13.4, 13.6, 13.7, 13.8, 13.9, 14.1, 14.5, 15.4, 16.2, 16.3, 27.1, 27.2, 27.3_

  - [x] 5.3 Write the required property test for the verifier
    - **Property 3: Verifier accepts exactly the grounded claims**
    - In `tests/pipeline/test_verifier.py` with marker `required_pbt`. Generate claims with missing fields, claims with values pushed outside tolerance, and claims copied from the metrics
    - **Validates: Requirements 11.4, 30.3**

  - [x] 5.4 Implement Resident_Templates, rendering and Template_Briefings in `pipeline/content.py` and register the content step
    - Hand-written en, pt and es `TEMPLATES` for the check-in, confirmation, re-prompt, doorstep and radio texts. The CO line comes first, except in radio, where it follows the situation sentence. Every SMS and doorstep text ends with `help_sentence(REGION, lang, form)`. pt and es SMS bodies have no accents. Doorstep and radio texts keep their accents
    - `render_sms` strips accents for pt and es and records segments. `render_doorstep` uses the `full` forms. `render_radio` fills one fixed template per language with `{town}`, `{out_pct_pct}` and `{next_update_spoken}` (hour plus `radio_update_interval_hours`, spoken without AM or PM). The confirmation repeats 911 through the help sentence
    - `render_all`: SMS kinds and doorstep for every (kind, lang, town) over the 15 towns, and radio for every (hour, town) with a queued tract in 3 languages. Each render goes through `verifier.lint_outreach`. A failure raises `PipelineError(kind, lang, town[, hour])` or names the Banned_Term. An SMS over 2 segments raises `PipelineError(kind, lang, town)`
    - `template_briefing`, `action_for`, and `build_templates`, which adds a Template_Briefing for every tract-hour. Register as design step 9
    - _Requirements: 11.1, 11.3, 11.8, 12.3, 13.1, 13.2, 13.3, 13.4, 13.6, 13.7, 13.9, 14.1, 14.3, 14.4, 14.5, 14.6, 15.4, 16.1, 16.2, 16.3, 19.5, 27.1, 27.3_

  - [x] 5.5 Write the required property test for SMS segments
    - **Property 4: SMS segment rules and the 2-segment cap**
    - In `tests/pipeline/test_content.py` with marker `required_pbt`. Compare `common.segments` with an independent reference count. Check `content.json` when it exists; otherwise render the Resident_Templates for 15 towns × 3 languages
    - **Validates: Requirements 14.2, 14.3, 30.4**

  - [x] 5.6 Implement LLM operator Briefings in `pipeline/content.py` and register the LLM and verifier steps
    - Briefings only; resident outreach never uses the LLM. Client `anthropic.Anthropic()` with `ANTHROPIC_API_KEY` from `.env`. With `--no-llm` or no key, the client is `None` and no calls are made
    - `request_briefing`:
      - `messages.create(model="claude-opus-5-5", max_tokens=4000, system=..., messages=[...], output_config={"effort": "low", "format": {"type": "json_schema", "schema": BRIEFING_SCHEMA}})`, with no `temperature` parameter
      - check the exact `output_config` shape against the `anthropic` version pinned in `requirements.txt`
      - an exception, `stop_reason` "refusal" or "max_tokens", or a body that fails the schema counts as a rejected attempt
      - cache each completed response (including refusal and max_tokens) in `data/processed/llm_cache/<sha256 of model, system, prompt, metrics>.json` as it arrives, and reuse cache hits on re-runs, even with `--no-llm`. Exceptions are not cached
    - `llm_briefing`: attempt 1 accepted by `verify_briefing` gives "pass". Otherwise one regenerate with the rejection reasons gives "regenerated". Otherwise the Template_Briefing with "fallback". The action always comes from `action_for`
    - `llm_briefings` runs as design step 11, after the key-hour report of task 4.5. When `has_mixed_hour` is false, skip with the "adjust key_demo_hours" message and `llm_step: "skipped_key_hours"`. Otherwise call only for (Key_Demo_Hour, queued tract) pairs, sending only that tract-hour's flat metrics, the town name and the channel
    - Register the verifier as design step 12 and store its log in `Ctx`, with `llm_step` set to ran, no_llm, no_key or skipped_key_hours
    - _Requirements: 1.4, 11.2, 11.5, 11.6, 11.7, 11.9, 11.11, 11.12, 11.13, 11.14, 11.15, 11.18, 11.19, 26.2_

  - [x] 5.7 Write the required property test for channel and radio coverage
    - **Property 2: Channel follows telecom and every queued tract-hour has a radio script**
    - In `tests/pipeline/test_content.py` with marker `required_pbt`. Generate telecom matrices and tract-to-town assignments, then run `build_templates(ctx, langs)` on a small generated `Ctx`
    - **Validates: Requirements 12.1, 12.2, 12.3, 16.1, 30.2**

- [x] 6. Finish the pipeline with the scale catalog, export and privacy guard
  - [x] 6.1 Implement `pipeline/scale_catalog.py` and register the step
    - Build the 6 entries from `hazards.yaml`, with tier 2 for `open_311_towns`. Only `cape_blizzard` carries scores (and `boston_blizzard` once `boston_voice` exists). Every other entry is a preview that lists its lost-lifelines inputs
    - _Requirements: 23.12, 24.1, 24.2, 24.5, 24.6_

  - [x] 6.2 Implement `pipeline/export.py` and register the step
    - Write directly to `data/processed/` with `write_json`, with no staging directory: `cape_tracts.geojson`, `cape_towns.geojson`, `cape_timeline.json`, `telecom_events.json`, `content.json`, `households.json`, `responders.json`, `scale_catalog.json` and `verifier_log.json`, then `sources.json` last. `llm_cache/` is already written by task 5.6
    - `sources.json` holds:
      - each input row's source name and URL
      - exclusions, without their values
      - unmatched Tab 5 towns and unmatched hours
      - towns without anchors and customer-count sources
      - assumptions, and fetches with the vintage used
    - Geometry in EPSG:4326, `tz` on every file, aggregates only and no phone numbers
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 1.10, 4.10, 4.12, 4.15, 4.16, 5.3, 5.7, 6.9, 7.8, 25.1, 25.2, 26.7_

  - [x] 6.3 Implement `pipeline/privacy_guard.py` and the guard step in `pipeline/run.py`
    - `PHONE` and `ADDRESS` patterns from the design, `scan(roots)`, and `main(argv)`, which prints only `path:line: kind` and exits 1 on any finding
    - In `run.py`, after export, scan every file under `data/processed/` (including `llm_cache/`) and `api/`. On any finding, print the findings and exit non-zero. The written files stay in place until a clean run overwrites them
    - _Requirements: 1.11, 1.12, 26.7, 31.4, 31.5_

- [ ] 7. Create the Kiro hooks with the createHook tool
  - [x] 7.1 Create the required property-test hook
    - Use the createHook tool, not hand-written JSON: id `required-pbt`, trigger `PostFileSave`, matcher `/pipeline/.*\.py$`, command `.venv/bin/python -m pytest -q -m required_pbt`
    - On failure, pytest reports the failing test name and Hypothesis prints the falsifying example
    - _Requirements: 31.2, 31.3_

  - [x] 7.2 Create the privacy-guard hooks
    - Use the createHook tool three times with the command `.venv/bin/python -m pipeline.privacy_guard api data/processed`:
      - `privacy-guard-save`: trigger `PostFileSave`, matcher `/(api|data/processed)/`
      - `privacy-guard-create`: trigger `PostFileCreate`, same matcher
      - `privacy-guard-stop`: trigger `Stop`
    - The guard exits non-zero and prints only the path, line and match type
    - _Requirements: 31.4, 31.5_

- [-] 8. Checkpoint: Cape pipeline and hooks
  - Run `python -m pipeline.run --no-llm` first. Read the key-hour channel report it prints: for each key_demo_hour, the `sms` and `door_knock` counts and towns among queued tracts.
  - Adjust `key_demo_hours` in `config/scoring.yaml` so that at least one hour shows both channels (Mon 2026-02-23 14:00 is probably too early for the 8-hour modeled rule). Re-run `--no-llm` after each change until the report prints "ok".
  - Only then run the LLM step with `python -m pipeline.run` and `ANTHROPIC_API_KEY` set. Then run `pytest -q`. The Tab 3 peak check and the privacy guard must pass, with exit 0.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Build the API read layer
  - [~] 9.1 Implement `api/data.py`
    - Pydantic models that mirror each processed file. A read-only `Store` loaded at startup from `data/processed/` and `config/`, indexed by tract→town, hour, households by tract and responders by town
    - A missing required file stops startup with "run python -m pipeline.run". `boston_voice.geojson` is optional
    - _Requirements: 11.10, 28.1_

  - [~] 9.2 Implement `api/reach.py`
    - Channel lookup per tract-hour. Door-knock entries with "Simulated household #N", the household language, the tract Why_Chips, a responder from the town's configured roles, the doorstep script in the household language and `synthetic: true`
    - Add the Access_Hazard_Note when `wires ≥ access_hazard_wires_pct`
    - _Requirements: 15.1, 15.2, 15.3, 15.5, 17.9_

  - [~] 9.3 Implement the read and content endpoints in `api/main.py`
    - Limit CORS to `http://localhost:5173` and `http://127.0.0.1:5173`. Add `/api/health`, `/api/hours`, `/api/towns`, `/api/tracts`, `/api/timeline`, `/api/queue`, `/api/telecom-events`, `/api/sources` and `/api/scale-catalog`
    - `/api/tracts/{geoid}?hour=` returns `TractDetail`: metrics, need, telecom rule and label, active events for the town or Cape-wide areas, channel, the door-knock list, and household statuses (`awaiting_door_knock` or `not_contacted`)
    - `/api/content/{geoid}?hour=` serves from the Content_Cache only. Unknown geoids and hours return 404
    - _Requirements: 8.2, 8.4, 9.1, 9.2, 10.1, 10.2, 10.3, 10.4, 10.5, 11.10, 12.4, 12.7, 15.1, 20.2, 24.1, 28.1, 28.2_

  - [~] 9.4 Add the demo reset endpoint
    - `api/state.py` with an empty `CheckInStore` and a `reset()` that swaps in a fresh store. `POST /api/demo/reset` returns `{ok: true}`
    - _Requirements: 21.1_

- [~] 10. Checkpoint: API
  - Run `pytest -q`. Ask the user to start `uvicorn api.main:app --port 8000` manually and check `/api/health` and `/api/queue?hour=2026-02-23T09:00`.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Build the web app
  - [~] 11.1 Scaffold `web/`
    - Vite + React 18 + TypeScript (strict) + Tailwind + MapLibre GL JS, with Vitest (`passWithNoTests: true`) and fast-check. Exact versions in `web/package.json`
    - `src/types.ts` mirrors every processed file and API model. `src/api.ts` reads `VITE_API_BASE ?? "http://localhost:8000"` and provides `useStaticData` and the "API not reachable at {VITE_API_BASE}" banner with a Retry button. `src/format.ts` holds `maskPhone` and local-hour formatting
    - _Requirements: 14.7, 26.5, 28.4_

  - [~] 11.2 Implement `MapView`, `TimeSlider` and `SourceBadges` and wire them into `App.tsx`
    - `MapView`:
      - choropleth layers Priority (default), Need and Lost lifelines, updated with `setFeatureState`
      - town boundaries
      - telecom pins whose popup shows system, status, affects, start time and citation
      - hover and focus tooltips, plus a keyboard tract list, that show the value as text
      - a numeric legend
      - the CARTO dark-matter basemap, falling back to a plain background
    - A range input from 0 to 118 with `aria-valuetext` in local time, plus key-hour buttons. Changing the hour updates every panel within 1 s
    - `SourceBadges` shows the provenance labels for the layers on screen. Add a shared `SimulatedBadge` here
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 17.10, 25.3, 25.4, 29.1, 29.2, 29.4_

  - [~] 11.3 Implement `Queue` and wire it into `App.tsx`
    - Each row is a `<button>` showing the town, tract, priority as a number, channel and 2 Why_Chips. Activating a row, or selecting a tract on the map, opens the drawer at the selected hour
    - _Requirements: 9.1, 9.2, 9.4, 9.5, 29.1_

  - [~] 11.4 Implement `TractDrawer` and `WhyFlagged` and wire them into `App.tsx`
    - `useTractDetail`. Focus moves into the drawer and Esc closes it. The Briefing shows a "Verified" or "Template" label
    - `WhyFlagged` shows:
      - each Need indicator's raw value and rank, and any missing indicators
      - each lifelines component with its weight and contribution
      - the telecom rule, with the "Modeled" label or the event citation
      - active telecom events with citations
      - the ACS-estimate label for Sandwich and Chatham
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 25.3, 25.4, 29.1, 29.4_

  - [~] 11.5 Implement `ReachPanel` inside the drawer
    - Show the channel and telecom rule, with an en, pt and es language switcher that keeps accented UI labels
    - For `sms` tract-hours, show the SMS preview and a "Send check-ins" button (connected in task 13.4). For `door_knock` tract-hours, show the Door_Knock_List with "Simulated" badges and the access hazard note
    - Show the AM radio script, labeled for the county AM station
    - _Requirements: 10.6, 12.4, 12.5, 12.6, 12.7, 14.7, 15.1, 15.2, 15.3, 17.10_

  - [~] 11.6 Implement `ScaleSelector` and the reset control in the header
    - List the 6 catalog entries with their tier. The Cape entry opens the map. Every other entry (Boston included until task 16) opens a Configuration_Preview with the tier and lost-lifelines inputs and no scores
    - Add a labeled "Reset demo" button that calls `POST /api/demo/reset` and refreshes the state
    - _Requirements: 21.2, 23.12, 24.1, 24.2, 24.3, 24.5, 29.1, 29.3_

- [~] 12. Checkpoint: web app
  - Run `cd web && npx vitest --run && npm run build` and `pytest -q`. Ask the user to run `npm run dev` manually and check keyboard navigation.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Build the check-in loop
  - [~] 13.1 Implement `api/sms.py`
    - `normalize`, and `classify` for "1", "2" and the `languages.yaml` keywords, ignoring case, spaces and accents
    - A `Sender` protocol. `SimulatorSender` handles every `SMS_MODE` value until Twilio is built
    - `mask_phone`, with environment values read from `.env`
    - _Requirements: 18.2, 18.3, 19.1, 19.2, 19.3, 26.1, 26.4_

  - [~] 13.2 Implement the check-in state machine in `api/state.py`
    - `CheckInStore` with a lock and an injected clock
    - `send` rejects `door_knock` tract-hours with `phones_degraded` and tracts with no households with `no_households`. It returns the existing run for the same tract-hour, and otherwise sends the check-in in each household's language
    - Seeded reply schedule from `(seed, geoid, hour)`, skipping the operator household (#`demo.operator_household`). Generated replies are labeled "Simulated"
    - `process_reply`:
      - help: one Escalation per household (round-robin over the town's responders) and a confirmation that repeats 911 through the Help_Line_Sentence
      - OK: set unless the household is already escalated
      - unrecognized: the first gets one re-prompt; later ones are recorded only
    - `advance` delivers due replies. It marks a household silent after `DEMO_REPLY_TIMEOUT_SECONDS` (default 30) only when run telecom is 0. A late recognized reply replaces silent. It updates the counters and the complete status
    - `reset()` swaps in a fresh store. Every run, reply and Escalation has `synthetic: true`
    - _Requirements: 15.6, 17.9, 18.1, 18.6, 18.10, 19.4, 19.5, 19.6, 19.7, 20.1, 20.2, 20.4, 21.1_

  - [~] 13.3 Add the check-in endpoints to `api/main.py`
    - `POST /api/checkins/send` returns 201, 200 for an existing run, 409 `phones_degraded` or `no_households`, or 404
    - `GET /api/checkins/{run_id}` runs `advance` first. `POST /api/simulator/reply` processes a typed reply
    - Reset uses the real store. `TractDetail` includes the run and household statuses. Phone numbers are logged masked only
    - At startup, clamp `reply_delay_s` below the timeout and log a warning
    - _Requirements: 15.6, 18.1, 18.5, 18.9, 19.8, 20.3, 21.1, 26.4_

  - [~] 13.4 Connect "Send check-ins", polling and counters in the web app
    - `useRunPolling` polls every 2 s while the run is active and stops on complete or unmount. "Send check-ins" in `ReachPanel` calls the send endpoint
    - The drawer shows:
      - the sent, OK, need help and silent counters
      - the Escalation list (label, language, time and responder label)
      - silent households, listed as needing human follow-up
      - "awaiting door knock" statuses
    - Reset clears the run and refetches
    - _Requirements: 10.6, 18.7, 18.8, 18.9, 19.8, 20.2, 20.3, 21.2_

  - [~] 13.5 Implement `PhoneSimulator` in the drawer
    - A household picker, defaulting to the operator household #1 (Portuguese in Barnstable and Yarmouth tracts), and a thread of outbound messages and replies, with the "Simulated" badge and sender name outside the message body. A keyboard-operable reply box posts to `/api/simulator/reply`. Any number goes through `maskPhone`
    - _Requirements: 14.8, 17.10, 18.4, 18.5, 26.5, 29.1, 29.3_

- [~] 14. Checkpoint: check-in loop
  - Run `pytest -q` and `cd web && npx vitest --run && npm run build`. Ask the user to run the API and web app manually and try send, reply, silence and reset.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Write the docs
  - [~] 15.1 Write `README.md`
    - List the run steps in order: `uv venv --python 3.13` and install, `python -m pipeline.run`, `uvicorn api.main:app --port 8000`, then `cd web && npm run dev`
    - State that the API has no authentication and is for localhost demo use only, that all households and responders are synthetic, and that SMS defaults to the simulator
    - _Requirements: 28.3, 31.7_

  - [~] 15.2 Write `docs/methods.md` (one page at most)
    - Cover the scoring formulas, the ZIP-to-tract area-weight simplification and emPOWER masking (1 to 10 reported as 11)
    - Cover the curve reconstruction (pins, lower bounds, scaling and unmatched hours), modeled telecom and the 12 h default
    - Cover the Barnstable and Yarmouth language-mix and ACS-customer assumptions, the Cape help line choice (Mass 2-1-1, where MEMA sent residents) and the excluded sitrep #009 figure
    - Keep it to one page; detail beyond that stays in code comments and the design
    - _Requirements: 2.7, 2.8, 4.15_

  - [~] 15.3 Write `docs/kiro-usage.md`
    - Describe the steering files, the lifeline-city spec and the task 7 hooks (triggers, commands and why the Stop hook exists)
    - _Requirements: 31.6_

---

### MVP line: everything above is the demo minimum

Everything above this line is required. Work below the line is listed in build order. Boston Voice (task 16) is the first block to cut if time runs short. Tasks 18 and 19 hold the Optional items, marked `*`. Start them only after everything above the line works.

---

- [ ] 16. Build the Boston Voice block (separate block, first to cut)
  - [~] 16.1 Add the Boston fetches and confirm the Boston config
    - In `pipeline/fetch.py`, add cached fetches for the 2026 legacy and NEW SYSTEM Boston 311 files and the Suffolk ACS and TIGER tract inputs
    - Confirm the `channels.yaml` keep and drop lists and the `storm_types.yaml` case types against the observed values. Fill `boston.exclude_geoids` in `scoring.yaml` (Logan Airport, Harbor Islands, large parks)
    - _Requirements: 1.3, 23.3, 23.5_

  - [~] 16.2 Implement Boston tracts, Boston Need and 311 cleaning in `pipeline/voice_boston.py`
    - `boston_tracts`: centroid inside Boston, population at or above `min_tract_pop`, configured exclusions removed. Compute Boston Need with `need.need_scores`, ranked among Boston_Tracts only
    - `requests_311`: map both schemas to timestamp, case type, channel and coordinates only, then union them. Keep the configured channels. Drop records with missing coordinates or in the 42.3594, -71.0587 pile-up. Join to tracts
    - _Requirements: 23.2, 23.3, 23.4, 23.8_

  - [~] 16.3 Implement the Voice scores, register the step and export `boston_voice.geojson`
    - Baseline days exclude the configured ranges, holidays and storm-type spike days above 3× the median. Implement the `voice()` formulas from the scoring steering with `k_pseudo_days`, `acute_cap` and `silence_weights`, and set `priority_Boston = need_t × silence_t`
    - Register the step before `scale_catalog` so `boston_blizzard` switches from preview to scored. Export tract aggregates with the storm-window metadata
    - _Requirements: 23.1, 23.5, 23.6, 23.7, 23.8, 24.6_

  - [~] 16.4 Serve `GET /api/boston/voice`
    - Add the Boston model to `api/data.py`. Return 404 when the file is absent. Add the `boston_voice` flag to `/api/health`
    - _Requirements: 23.9, 23.12_

  - [~] 16.5 Implement `BostonVoiceView` and route the Boston entry to it
    - A static map with the layers Priority (default), Need, Acute silence and Structural silence, a storm-window label and no time slider. "Heard 9, expected 41" text appears in the tooltip and in a top-15 table
    - `ScaleSelector` opens the view when the endpoint returns 200 and shows the Configuration_Preview on 404
    - _Requirements: 23.10, 23.11, 23.12, 24.4, 29.4_

- [~] 17. Checkpoint: Boston Voice
  - Run `python -m pipeline.run --no-llm`, `pytest -q` and `cd web && npx vitest --run && npm run build`.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 18. Optional items (only after everything above the MVP line works)
  - [ ]* 18.1 Add Twilio SMS behind `SMS_MODE` (20-minute timebox)
    - Pin `twilio` in `requirements.txt`. Use `TwilioSender` for households mapped to `DEMO_PHONE_NUMBERS` and the simulator for everything else
    - `POST /api/sms/twilio` validates `X-Twilio-Signature`. On failure it returns 403 and records no reply. Failed sends fall back to the simulator and log the masked number
    - If Twilio does not work within 20 minutes, stop and stay on the simulator
    - _Requirements: 18.2, 22.1, 22.2, 22.3, 22.4, 26.4_

  - [ ]* 18.2 Add Portuguese and Spanish back-translation checks
    - Record an English back-translation and an intent-match result for each pt and es Resident_Template in `content.json`
    - _Requirements: 13.5_

  - [ ]* 18.3 Extend the scale catalog beyond the 6 static entries
    - Add more Massachusetts town and hazard entries to `hazards.yaml`, each a Configuration_Preview with no scores
    - _Requirements: 24.7_

  - [ ]* 18.4 Run the contrast audit
    - Check text contrast against the dark background and fix any Tailwind colors below 4.5:1
    - _Requirements: 29.5_

- [ ] 19. Optional tests (in build order; each can be skipped)
  - [ ]* 19.1 Write the property test for the Need score
    - **Property 5: Need score is the mean of available ranks**
    - `tests/pipeline/test_need.py`
    - **Validates: Requirements 2.2, 2.3, 2.4, 23.2**

  - [ ]* 19.2 Write the property test for ZIP allocation
    - **Property 6: ZIP allocation conserves counts**
    - `tests/pipeline/test_need.py`
    - **Validates: Requirements 2.5, 2.6**

  - [ ]* 19.3 Write the property test for curve shaping
    - **Property 7: Shaped curves pass through their anchors**
    - `tests/pipeline/test_outage_curves.py`
    - **Validates: Requirements 4.4, 4.7, 4.8, 4.9**

  - [ ]* 19.4 Write the property test for hourly scaling
    - **Property 8: Scaling keeps pins and bounds and matches the Cape total when feasible**
    - `tests/pipeline/test_outage_curves.py`
    - **Validates: Requirements 4.1, 4.5, 4.6, 4.11, 4.12**

  - [ ]* 19.5 Write real-data example tests for the pipeline
    - In `tests/pipeline/test_run.py`, check that:
      - the Tab 3 peak on the real workbook is 269,063 at 2026-02-23T08:00
      - no processed file contains the sitrep #009 figure
      - files under `data/raw/` (excluding `cache/`) hash the same before and after a `--no-llm` run
      - two `--no-llm` runs give identical hashes, and no `.staging` directory exists
    - _Requirements: 1.2, 1.4, 1.10, 4.3, 4.15_

  - [ ]* 19.6 Write the property test for town matching
    - **Property 9: Town matching is exact and whole-name**
    - `tests/pipeline/test_common.py`
    - **Validates: Requirements 5.2, 6.5, 6.6**

  - [ ]* 19.7 Write the property test for wires aggregation
    - **Property 10: Wires aggregation conserves calls and is cumulative**
    - `tests/pipeline/test_wires.py`
    - **Validates: Requirements 5.1, 5.3, 5.4, 5.5, 5.6**

  - [ ]* 19.8 Write the property test for the telecom flag
    - **Property 11: Telecom matches the reference rule**
    - `tests/pipeline/test_telecom.py`
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**

  - [ ]* 19.9 Write the property test for hours dark
    - **Property 12: Hours dark follows the literal rule**
    - `tests/pipeline/test_lifelines.py`
    - **Validates: Requirements 7.1, 7.2**

  - [ ]* 19.10 Write the property test for weight validation
    - **Property 13: Weight validation rejects bad sums**
    - `tests/pipeline/test_lifelines.py`
    - **Validates: Requirements 7.6**

  - [ ]* 19.11 Write the property test for the queue sort
    - **Property 14: Queue matches the reference sort**
    - `tests/pipeline/test_lifelines.py`
    - **Validates: Requirements 7.7, 9.1**

  - [ ]* 19.12 Write the property test for template briefings and Why_Chips
    - **Property 15: Template briefings and Why_Chips are grounded**
    - `tests/pipeline/test_content.py`
    - **Validates: Requirements 9.3, 11.1, 11.3, 11.8**

  - [ ]* 19.13 Write the property test for outreach style rules
    - **Property 16: Outreach texts follow the style rules**
    - `tests/pipeline/test_content.py`
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.6, 13.7, 14.1, 14.5, 15.4, 16.1, 16.2, 16.3**

  - [ ]* 19.14 Write the property test for 911 and the region help line in every render
    - **Property 17: Every resident render carries 911 and its region's help line**
    - `tests/pipeline/test_content.py`. Include template variants with 911 or the help line removed, or padded past 2 segments, and check the `PipelineError` names the kind, language and town
    - **Validates: Requirements 13.4, 13.8, 13.9, 14.4, 19.5**

  - [ ]* 19.15 Write the property test for banned terms
    - **Property 18: Banned terms are always rejected**
    - `tests/pipeline/test_verifier.py`
    - **Validates: Requirements 27.2, 27.3**

  - [ ]* 19.16 Write the property test for synthetic generation
    - **Property 20: Synthetic generation is valid and deterministic**
    - `tests/pipeline/test_synthetic.py`, including household #1 as `pt` in Barnstable and Yarmouth with households #2..N unchanged
    - **Validates: Requirements 17.2, 17.3, 17.5, 17.6, 17.7, 17.8**

  - [ ]* 19.17 Write the property test for the privacy guard
    - **Property 26: Privacy guard finds injected identifiers without echoing them**
    - `tests/pipeline/test_privacy_guard.py`, using only the fictional 555-01xx numbers. 911, 2-1-1 and 311 produce no findings
    - **Validates: Requirements 1.12, 31.5**

  - [ ]* 19.18 Write the property test for the door-knock list
    - **Property 19: Door-knock list covers every household with the right fields**
    - `tests/api/test_reach.py`
    - **Validates: Requirements 15.1, 15.2, 15.3, 15.5, 17.9**

  - [ ]* 19.19 Write the property test for reply parsing
    - **Property 21: Reply classification ignores case, spacing and accents**
    - `tests/api/test_sms.py`
    - **Validates: Requirements 19.1, 19.2, 19.3**

  - [ ]* 19.20 Write the property test for phone masking
    - **Property 25: Phone masking shows only the last four digits**
    - `tests/api/test_sms.py` (Hypothesis) and `web/src/format.test.ts` (fast-check), using only the fictional 555-01xx numbers
    - **Validates: Requirements 26.4, 26.5**

  - [ ]* 19.21 Write the property test for the check-in state machine
    - **Property 22: Check-in state machine invariants**
    - `tests/api/test_state.py`, a Hypothesis `RuleBasedStateMachine` with a fake clock
    - **Validates: Requirements 15.6, 17.9, 18.1, 18.9, 19.4, 19.5, 19.6, 19.7, 20.1, 20.2, 20.4**

  - [ ]* 19.22 Write the property test for reset
    - **Property 23: Reset restores the start state**
    - `tests/api/test_state.py`
    - **Validates: Requirements 21.1**

  - [ ]* 19.23 Write API example tests
    - In `tests/api/test_main.py`, check that a send on a `door_knock` hour returns 409 and that CORS rejects a non-local origin
    - _Requirements: 15.6, 28.2_

  - [ ]* 19.24 Write the property test for Boston Voice values (Boston block only)
    - **Property 24: Boston Voice values are bounded and normalized**
    - `tests/pipeline/test_voice_boston.py`
    - **Validates: Requirements 23.6, 23.7**

  - [ ]* 19.25 Write the Twilio signature example test (only if 18.1 is built)
    - In `tests/api/test_main.py`, check that a mocked failing validator gets a 403 and that no reply is recorded
    - _Requirements: 22.3_

  - [ ]* 19.26 Write the property test for the key-hour report and LLM gating
    - **Property 27: Key-hour report and LLM gating**
    - `tests/pipeline/test_lifelines.py` (naive recount) and `tests/pipeline/test_briefings.py` (mocked client that counts calls; no real API calls)
    - **Validates: Requirements 11.14, 11.15, 11.16, 11.18, 11.19**

  - [ ]* 19.27 Write the property test for the briefing fallback chain and cache reuse
    - **Property 28: Briefing fallback chain and cache reuse**
    - `tests/pipeline/test_briefings.py`, mocked client and a `tmp_path` cache. Outcomes: exception, "refusal", "max_tokens", schema failure, rejected claim, grounded body
    - **Validates: Requirements 1.4, 11.5, 11.6, 11.7, 11.12, 11.13**

  - [ ]* 19.28 Write briefing-request and config example tests
    - In `tests/pipeline/test_briefings.py`, check that a mocked client receives `model="claude-opus-5-5"`, `max_tokens=4000`, `output_config` with effort "low" and the Briefing JSON schema, and no `temperature` key
    - In `tests/pipeline/test_config.py`, check that the `config/scoring.yaml` key hours give `has_mixed_hour = true` on the real `--no-llm` output, and that `languages.yaml` sets Barnstable and Yarmouth to en 0.6, pt 0.3, es 0.1
    - _Requirements: 11.11, 11.17, 17.4_

## Notes

- Implementation languages are Python 3.13 (pipeline, API) and TypeScript (web), as in the design.
- The required property tests are 4.4, 5.3, 5.5 and 5.7. They carry the `required_pbt` marker and run from the hook in task 7.1. Each property test has a `# Feature: lifeline-city, Property N: <title>` comment.
- Sub-tasks marked `*` are optional and appear only below the MVP line.
- Dev servers (`uvicorn`, `npm run dev`) are started manually. Automation uses only `pytest -q`, `npx vitest --run` and `npm run build`.
- Resident outreach is always rendered from Resident_Templates. If the LLM path runs out of time, `python -m pipeline.run --no-llm` keeps every Briefing without a cached response on its Template version without dropping a requirement.
- `data/processed/llm_cache/` is not git-ignored, so cached Briefings make re-runs reproducible. The privacy guard scans it with the rest of `data/processed/`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3"] },
    { "id": 4, "tasks": ["3.1", "3.3"] },
    { "id": 5, "tasks": ["3.2"] },
    { "id": 6, "tasks": ["3.4"] },
    { "id": 7, "tasks": ["4.1"] },
    { "id": 8, "tasks": ["4.2"] },
    { "id": 9, "tasks": ["4.3"] },
    { "id": 10, "tasks": ["4.4", "4.5", "5.2"] },
    { "id": 11, "tasks": ["5.1", "5.3"] },
    { "id": 12, "tasks": ["5.4"] },
    { "id": 13, "tasks": ["5.5", "5.6"] },
    { "id": 14, "tasks": ["5.7", "6.1"] },
    { "id": 15, "tasks": ["6.2"] },
    { "id": 16, "tasks": ["6.3"] },
    { "id": 17, "tasks": ["7.1", "7.2"] },
    { "id": 18, "tasks": ["9.1"] },
    { "id": 19, "tasks": ["9.2"] },
    { "id": 20, "tasks": ["9.3"] },
    { "id": 21, "tasks": ["9.4"] },
    { "id": 22, "tasks": ["11.1"] },
    { "id": 23, "tasks": ["11.2"] },
    { "id": 24, "tasks": ["11.3"] },
    { "id": 25, "tasks": ["11.4"] },
    { "id": 26, "tasks": ["11.5", "11.6"] },
    { "id": 27, "tasks": ["13.1"] },
    { "id": 28, "tasks": ["13.2"] },
    { "id": 29, "tasks": ["13.3"] },
    { "id": 30, "tasks": ["13.4"] },
    { "id": 31, "tasks": ["13.5"] },
    { "id": 32, "tasks": ["15.1", "15.2", "15.3"] },
    { "id": 33, "tasks": ["16.1"] },
    { "id": 34, "tasks": ["16.2"] },
    { "id": 35, "tasks": ["16.3"] },
    { "id": 36, "tasks": ["16.4"] },
    { "id": 37, "tasks": ["16.5", "18.1", "18.2"] },
    { "id": 38, "tasks": ["18.3", "19.1", "19.3", "19.5", "19.6", "19.7", "19.8", "19.9", "19.12", "19.15", "19.16", "19.17", "19.18", "19.19", "19.21", "19.23", "19.24", "19.27"] },
    { "id": 39, "tasks": ["18.4", "19.2", "19.4", "19.10", "19.13", "19.20", "19.22", "19.25", "19.28"] },
    { "id": 40, "tasks": ["19.11", "19.14"] },
    { "id": 41, "tasks": ["19.26"] }
  ]
}
```
