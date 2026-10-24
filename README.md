# Lifeline City

**Finding the residents a disaster makes invisible.**

Hackachusetts 2026 · **Civic Action** track · built with **Kiro** (spec-driven, Claude Opus 5.5)

[▶ Demo video](VIDEO_LINK) · [How we used Kiro](docs/kiro-usage.md) · [Methods and assumptions](docs/methods.md)

---

## The problem

On February 22 and 23, 2026, a blizzard hit Massachusetts. Cape Cod took the worst of it:

- **153,000 customers lost power** at the peak, and the entire Outer Cape went dark (Barnstable County after-action review).
- **Cell and internet failed across the Cape.** Radio volunteers said 6 to 12 more hours of storm could have taken out cell service entirely. The county's 911 dispatch center had a major failure on Thursday.
- **Every tool the Cape used waited for someone to ask.** Shelters need you to get there, 2-1-1 needs you to call, police wellness checks start when a relative calls in, and the utility's medical list covers only people who filed paperwork. Eversource called **2,246** medical customers across its whole Massachusetts territory; federal HHS emPOWER data counts **2,021** people on electricity-dependent equipment in Barnstable County alone.

The county's own review measured success by who was sheltered, fed and transported. Nothing measured who stayed home and went quiet.

## What Lifeline does

Lifeline stops waiting for calls. For every neighborhood and every hour of the storm it estimates where people are most likely in trouble, then picks a way to reach them that still works.

| Layer | Question | Data | Detail |
|---|---|---|---|
| **Need** | Who lives here? | Census ACS 2024 (seniors living alone, disability, limited English, no car, renters) + HHS emPOWER (electricity-dependent Medicare patients) | 56 populated Cape census tracts |
| **Lost lifelines** | What did they just lose? | Power out (40%), hours in the dark (30%), phones likely down (20%), urgent downed-wire calls (10%) | 15 towns × 119 hours |
| **Reach** | How do we contact them now? | Phones working → text check-in in English, Portuguese or Spanish. Phones down → door-knock list for police, fire, Council on Aging, Elder Services and Meals on Wheels, plus an AM radio script | Every tract-hour |

**Priority = Need × Lost lifelines.** The top 10 neighborhoods are re-ranked every hour.

The key rule: **when phones are likely down, a missing reply means nothing.** Lifeline never counts silence there; it sends people instead. Phones are modeled as down once a town has been at least 80% dark for 8 hours in a row (roughly when tower backup runs out).

**Any town, any hazard.** Tier 1 (Need + Lost lifelines + Reach) uses only data every Massachusetts town has. Tier 2 adds **Voice** (neighborhoods that went quieter than expected on 311) for cities like Boston that publish 311 data; it is designed in the spec but not built in this demo. Other hazards only swap the lost-lifelines input (floods: flood zones and road closures; heat: power plus heat index).

## Features

- **Storm replay:** a Cape map with an hourly time slider from Mon Feb 23 1 AM to Fri Feb 27 11 PM and three layers (Priority, Need, Lost lifelines).
- **Ranked priority list** with two "why" chips per neighborhood and the reach channel.
- **Why flagged:** every score component, weight and source on one panel.
- **AI briefings with a fact-checker:** Claude writes operator briefings at five key hours. A deterministic verifier checks every number against the data. It rejected **36 of 50** first drafts for numbers that were not in the data; after one retry **49 of 50** passed, and the last one fell back to a labeled template.
- **Check-in loop:** send texts to simulated households, reply from an on-screen phone ("AJUDA" escalates a Portuguese household to a wellness check), and watch silent households land on a human follow-up list.
- **Door-knock lists and AM radio scripts** in three languages, carbon monoxide safety first, 911 and 2-1-1 in every message.
- **Provenance everywhere:** reconstructed, modeled, estimated and simulated values are labeled on screen.

## Try it (no API keys needed)

The processed data and the cached AI briefings are committed, so the app runs offline.

Requirements: Python 3.13 with [`uv`](https://docs.astral.sh/uv/), Node 25 / npm 11.

```sh
git clone https://github.com/MadhanJ05/lifeline-city && cd lifeline-city
uv venv --python 3.13 && uv pip install -r requirements.txt
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000     # terminal 1: API
cd web && npm ci && npm run dev                                 # terminal 2: open http://localhost:5173
```

**Demo path:**

1. Click the **Mon 5 PM** key hour: 6 Lower and Outer Cape neighborhoods are on door-knock lists while 4 still get texts.
2. Open **Barnstable tract 153** (rank 7). Read the verified briefing, then **Send check-ins**.
3. In the phone, household #1 (Português) replies **AJUDA**: it is escalated to a simulated police wellness check. After 30 seconds, households with no reply are marked silent.
4. Move to **Mon 6 PM**: Falmouth switches to a door-knock list as its phones pass the 8-hour mark.
5. Try the place and hazard selector, then **Reset demo**.

To rebuild everything from raw data, add `CENSUS_API_KEY` (and optionally `ANTHROPIC_API_KEY`) to `.env` and run `python -m pipeline.run` (or `--no-llm` to reuse the cached briefings).

## How it works

```
data/raw (public reports, curated CSVs) ──► pipeline/ (Python, run once) ──► data/processed/ ──► api/ (FastAPI) ◄──► web/ (React + MapLibre)
                                                 │
                                    Claude Opus 5.5 briefings + verifier
```

- `pipeline/` downloads and caches public data, rebuilds each town's hourly outage curve so it passes through every real report and adds up to the Cape total, scores every tract-hour, writes briefings and message text, and finishes with a privacy scan.
- `api/` serves the precomputed files and runs the check-in state machine (simulated texts, seeded replies, escalations, timeouts, reset).
- `web/` is the operator console.

The demo never waits on the internet or the AI.

## Data sources

- **Eversource final event report** for the February 2026 blizzard, filed with the Massachusetts Department of Public Utilities (docket 25-ERP-10): hourly outages and restorations, and 1,720 urgent downed-wire calls by town.
- **MEMA situation report #4** and the MEMA town outage snapshot (Feb 23, 12:30 PM), via Patch.
- **Barnstable County Blizzard Hernando after-action review** (July 2026).
- **Census ACS 2024 5-year**, **TIGER 2020** tracts and county subdivisions, **HHS emPOWER** ZIP data.
- Town and Cape-wide outage reports and telecom failures from Cape Wide News live blogs, police and town posts, WBUR, CBS Boston, Boston.com and the Provincetown Independent, hand-entered with a source link on every row (`data/raw/curated/`).

## Privacy and safety

- Real data appears only as tract or town totals. No real names, addresses or phone numbers.
- Every household, reply and responder is synthetic and labeled **Simulated**.
- Descriptive language only ("dark for 40 hours"), never blame.
- Lifeline does not replace 911. Every escalation ends with a person.
- A privacy guard blocks any output containing a phone number or street address, and Kiro hooks run it on every save.
- The API has no authentication and is for local demo use only.

## Limitations

- Town outage curves are **reconstructed** between real reports; Chatham has no town reports and is estimated from the Cape-wide share.
- The phones-down flag is **modeled** (8-hour rule); real telecom failures are shown as map pins.
- Households and replies are simulated; real texting (Twilio) and Boston Voice are designed but not built.

## Repo map

```
.kiro/       steering (7 files), spec (requirements, design, tasks), hooks
config/      scoring weights, languages and help lines, responders, hazards
data/        raw sources and curated CSVs, processed outputs (committed)
pipeline/    offline data pipeline, LLM briefings, verifier, privacy guard
api/         FastAPI app and check-in state machine
web/         React + MapLibre operator console
tests/       294 Python tests (pytest + Hypothesis); web has 96 Vitest + fast-check tests
docs/        methods.md, kiro-usage.md
```

## Tests

```sh
pytest -q                                   # pipeline + API
pytest -q -m required_pbt                   # the 4 required property-based tests
cd web && npx vitest --run && npm run build # web logic tests, typecheck and build
```
