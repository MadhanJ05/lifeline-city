# Lifeline City: Hackathon Handoff

Drop this file in the repo root. Rename to `CLAUDE.md` for Claude Code, and/or split Section 11 into `.kiro/steering/` files for Kiro. Everything a fresh coding session needs is in here.

---

## 0. Read this first

**Rule check.** Hackachusetts requires that AI-generated code be built and submitted through Kiro, and one of the three judging criteria is "effective and thoughtful use of Kiro." Confirm with an organizer before generating submitted code in any other tool. Section 11 is the Kiro plan.

**Start-here prompt for the coding agent:**

```
Read HANDOFF.md fully. Then run Section 6.5 "Data go/no-go checks" in order.
Report results as a short table (check, result, pass/fail) and stop for my
decision before building anything else.
```

**Working rules for the agent:**
- Aggregate data only for real residents. Never create, store, or display individual-level real data.
- Every synthetic record carries `synthetic: true` and is labeled "Simulated" in the UI.
- Descriptive language only: "quieter than expected," never "neglected" or causal claims.
- Pre-compute and cache everything the demo shows. The demo must never wait on a live API except the SMS loop.
- Secrets live in `.env` only. Phone numbers never go in the repo.

---

## 1. Event context

- **Event:** Hackachusetts 2026 (Massachusetts AI Coalition, powered by Kiro), Saturday Oct 24, 2026.
- **Track:** Civic Action: tools that help communities and public services work better. City of Boston and state partners are involved.
- **Team:** max 4 people.
- **Timeline:** hacking officially started 11:30 AM. Submission window 6:00 to 8:00 PM; start submitting at 6:00. Submission is a SundAI project card with the track selected.
- **Judging:** 8 to 11 PM, includes virtual judges over Zoom on a judging platform. The project card and demo video must sell the project with nobody from the team in the room.
- **Finals:** about 50 finalists notified around midnight; finals Sunday at WHOOP. Top 3 per track.
- **Event data portal:** https://hackachusetts2026.vercel.app/#/civic (JavaScript app; open it in a browser, check the Civic page for curated datasets and starter kits, and use any that fit).

### Judging criteria (from the kickoff slide)

1. **Potential Value:** solves a real problem with a scalable, accessible, user-friendly solution that meets community needs.
2. **Implementation:** effective and thoughtful use of Kiro, AI development strategies, and creative integrations.
3. **Quality and Design:** originality, creativity, intuitive user experience, polished design.

How we hit each one:

| Criterion | Our answer |
|---|---|
| Value | Real storm, real city data, real gap (who 311 never hears). Works for any MA town and any hazard. Residents need only SMS, no app. |
| Implementation | Kiro specs in EARS format, steering files that encode privacy and outreach rules, hooks (privacy guard, translation check, tests). Multi-agent with a verifier. Integrations: Analyze Boston, Census API, HHS emPOWER, Twilio. |
| Quality and Design | Original "silence" framing. One map, one queue, one "why flagged" panel. Live phone moment in the demo. |

---

## 2. The idea

**Name:** Lifeline City

**Submitted one-liner (keep the reveal for judging):** An AI agent that helps emergency managers find the residents who go silent during a disaster, before it's too late.

**Pitch line:** "311 hears the loudest blocks. Lifeline listens for the quiet ones."

**Lineage:** Extends Lifeline, the earthquake rescue agent that won the Dell x NVIDIA hackathon. Lifeline found people under rubble. Lifeline City finds the people the city can't hear.

**Core insight.** Crisis dashboards rank areas by how many people ask for help, which rewards the loudest. In a disaster, the worst-off often go quiet: power out, phones dead, cell towers down, language barriers, seniors who won't call. Lifeline City models where we *should* be hearing from people, flags where we aren't, weights that by who lives there, then actually asks (check-ins) and routes humans.

**Two layers:**
1. **Detected silence (real data):** Boston 311 during the Blizzard of 2026 vs. what each census tract would normally say, weighted by need.
2. **Confirmed silence (live):** SMS check-ins to households in the top tracts. "Reply 1 if OK, 2 if you need help." No reply plus high need escalates to a human responder or vetted volunteer.

Silence is a question, not a verdict. Lifeline is the thing that asks it.

**Scope story for the pitch:**
- **Opening slide:** Cape Cod, where the blizzard did the most damage and communications failed.
- **Proof:** Boston, where 311 data makes silence measurable.
- **Scale:** any of Massachusetts' 351 cities and towns, any hazard (blizzard, outage, flood, heat are configs).
- **Phase 2 slide:** Lifeline's WiFi sensing for building-level confirmation that someone is still inside.

---

## 3. Facts for the pitch (paraphrased, with sources)

**Blizzard of 2026 (Feb 22 to 23, 2026), statewide**
- Peak of about 290,000 Eversource and National Grid customers without power, concentrated on Nantucket, Martha's Vineyard, Cape Cod, and parts of the South and North Shore; gusts reached 80 mph on the Outer Cape. https://www.statehousenews.com/news/blizzard-leaves-290-000-in-massachusetts-without-power/article_f6d1d5ef-be36-45f6-bf16-721acddd9bd7.html
- Healey issued a non-essential travel ban for Bristol, Plymouth, and Barnstable counties ($500 fine), cut the Pike to 40 mph, and MEMA told people to call 2-1-1 for warming centers and shelters. (same source)
- 93% of Falmouth still dark Tuesday morning; more than 154,000 still out two days after; Eversource targeted Friday 11:59 PM for near-full restoration. https://www.cbsnews.com/boston/news/power-outages-eversource-cape-cod-blizzard/
- Eversource said 164,000 Cape customers lost power and called the damage catastrophic; most of the Outer Cape, including nearly all of Wellfleet and Eastham, was still dark Wednesday night; 2,000 linemen, two helicopters, and drones deployed. https://provincetownindependent.org/local-journalism-project/next-generation/2026/02/25/blizzard-of-26-clobbers-cape-cod-power-grid/
- 350 National Guard troops activated; The RIDE paratransit canceled; cell towers down in many parts of the Cape with carriers on generators or reporting major outages. https://www.wbur.org/news/2026/02/24/massachusetts-blizzard-impacts-dig-out-power-outages-historic-storm
- Provincetown planned to prioritize shelter residents by age and health, some on oxygen; officials moved people with health issues closer to Cape Cod Hospital; Outer Cape Health staff lacked power and struggled to dispense medications; a Nauset shelter lost power and about 45 people were moved; Meals on Wheels couldn't run Tuesday. (WBUR, same link)
- A UMass Memorial doctor said the carbon monoxide poisoning cases she'd seen involved people unfamiliar with the risk. (WBUR, same link)
- A man was killed by a tractor-trailer while clearing snow off his car on the Pike; every gas station in Orleans ran out of fuel; a Rhode Island college student died of CO poisoning. https://www.boston25news.com/news/local/live-post-blizzard-updates-mass-begins-cleanup-after-historic-snowfall-new-england/WZA7BRXK4BD5ZLT55Y5GEKF3ZE/

**Boston response**
- Snow emergency and parking ban from 2 PM Sunday Feb 22; BPS and municipal buildings, including libraries and BCYF centers, closed Monday. https://www.boston.gov/node/16566231
- More than 670 vehicles towed; Public Works piled snow mid-block before hauling to snow farms. https://www.bostonglobe.com/2026/02/23/metro/boston-mayor-wu-snow-response/
- Wu said some outages were reported in the city but many were resolved. https://www.boston25news.com/news/local/stay-home-wu-cancels-school-tuesday-urges-boston-residents-clear-out-snow-safely/ATH2X2YXJVD3DKVMW6OOD3NFFM/
- Snow emergency lifted 6 PM Tuesday Feb 24; Neighborhood Services organized volunteer shoveling meet-ups. https://www.boston.gov/index%2Ephp/node/16566281
- Logan recorded 16.9 inches. (WBUR, above)

**Why 311 silence is structural**
- Research on Boston 311 (Dan O'Brien, Boston Area Research Initiative at Northeastern): most requests come from people living within two blocks of the issue, and about three quarters come from homeowners. Cited in https://www.mdpi.com/2078-2489/12/8/332
- Only about 34.8% of Boston housing units were owner-occupied (2017 to 2021). https://www.axios.com/local/boston/2023/08/28/effective-property-tax-rates

**It keeps happening**
- March 2018 nor'easter outages peaked at just over 451,000. https://www.cbsnews.com/boston/news/power-outages-march-noreaster-day-four/

---

## 4. Product spec

### Users
- **Primary:** emergency managers and ops staff (Boston OEM, MEMA, county emergency managers).
- **Residents:** SMS only. No app, no login, works on a flip phone, in their language.
- **Volunteers:** vetted responders (CERT, Medical Reserve Corps, opted-in neighbors).

### Core flows
1. **Replay:** operator scrubs time from Feb 21 to Feb 26, 2026. Tracts light up as they fall quieter than expected.
2. **Why flagged:** click a tract to see observed vs expected requests, need indicators, and a verified agent briefing.
3. **Check-ins:** one click sends multilingual SMS check-ins to (synthetic) households in that tract. Real SMS goes to teammates' demo phones.
4. **Escalate:** reply 2, or no reply within the timeout, creates an escalation. The nearest available volunteer is assigned. Address revealed only after the volunteer accepts.
5. **Live update:** map, queue, and event feed update in real time as replies arrive.

### Screens (single page)
- **Header:** "Blizzard of 2026 replay" plus data source badges and a "Simulated" badge legend.
- **Left (main):** Boston tract map. Layer toggle: Priority (default), Need, Acute silence, Structural silence. Time scrubber at the bottom.
- **Right:** ranked response queue (top 10 tracts). Each row: neighborhood + tract, priority, two "why" chips (example: "Heard 9, expected 41", "38% limited-English households"), buttons Send check-ins / View.
- **Drawer (tract detail):** sparkline of observed vs expected over time, need breakdown bars, verified briefing, outreach preview with a language switcher, check-in counters (sent / OK / need help / silent), escalations list.
- **Bottom:** live event feed.
- **Fallback panel:** in-app phone simulator so the loop still demos if SMS fails.

### Non-goals today
Real 211 or 911 integration, real routing optimization, real volunteer onboarding, any real resident data, mobile app.

---

## 5. Silence model (exact)

### Unit and scope
- Unit: 2020 census tract, clipped to the City of Boston. Suffolk County also contains Chelsea, Revere, and Winthrop, so clip to the Boston boundary.
- Drop tracts with population under 500 or that are mostly non-residential (Logan, Harbor Islands, large parks).

### The "voice" signal
- All **resident-originated** 311 requests (any case type) per tract. Using all types avoids near-zero baselines for snow-specific types on normal days.
- Drop city-worker-generated cases (Section 6.3).
- Storm-relevant types (plowing, unshoveled sidewalks, icy conditions, downed trees and branches, no heat, street lights, wires) are kept as a tagged subset for display ("what people are reporting").

### Time windows
- **Storm window W:** 2026-02-22 14:00 to 2026-02-25 23:59 local (snow emergency start through one day after it lifted). Sensitivity check: 2026-02-23 00:00 to 2026-02-24 18:00.
- **Baseline B:** 2026-01-05 to 2026-03-31, excluding: the storm week, the late-January 2026 snowstorm (around Jan 24 to 27), the Feb 7 to 9 cold emergency, holidays, and any day where citywide storm-type requests exceed a threshold (auto-detect: more than 3x the median daily count). Union legacy and NEW SYSTEM files for the whole baseline.

### Formulas

```
# Baseline daily rate per tract, shrunk toward the city per-capita rate
r_t      = (c_t + k * r_city_pc * pop_t) / (d + k)       # k = 7 pseudo-days
#   c_t = resident requests in tract t over baseline, d = baseline days

# Citywide surge during the storm window
S        = sum_t(O_t) / sum_t(r_t * D)                   # D = storm window days

# Expected and observed
lambda_t = r_t * D * S
O_t      = resident requests in tract t during W

# Acute silence (did this tract go quieter than its own normal?)
p_t          = PoissonCDF(O_t ; lambda_t)                # small p = significantly quiet
acute_t      = clip(-log10(p_t), 0, 6)
ratio_t      = O_t / lambda_t                            # shown in UI

# Structural silence (is this tract chronically quiet?)
rate_pc_t    = baseline requests per 1,000 residents per 30 days
structural_t = percentile rank of (-rate_pc_t)

# Need (equal-weight mean of percentile ranks)
need_t = mean(pct(seniors_living_alone), pct(disability), pct(limited_english_hh),
              pct(no_vehicle_hh), pct(renter_share), pct(elec_dependent_per_1k))

# Priority
silence_t  = mean(pct(acute_t), structural_t)            # weights configurable
priority_t = need_t * silence_t
```

- Weights live in `config/scoring.yaml`. Decide final weights after looking at real data. If acute silence turns out noisy (Boston outages were limited), lead with structural + need and show acute as a layer.
- Stretch: replace Poisson with negative binomial if overdispersion is obvious.

### Hourly replay
For the scrubber, compute cumulative O_t(h) and lambda_t(h) = r_t * (h/24) * S_h, where S_h is the citywide cumulative surge up to hour h. Precompute to `data/processed/timeline.json`.

### Validation
1. Citywide daily plot shows a clear spike on Feb 23 to 24 (proves both files are unioned correctly).
2. Re-run the same model on the January 29, 2022 blizzard. Spearman correlation of tract priority between storms. Tracts quiet in both = persistent silence. Strong slide.
3. Eyeball the map with a teammate who knows Boston.
4. All outputs are descriptive. No causal claims.

---

## 6. Data

### 6.1 Analyze Boston: 311 Service Requests (must have)

Page: https://data.boston.gov/dataset/311-service-requests

| File | Resource ID | Notes |
|---|---|---|
| 311 Service Requests - 2026 (legacy, 12-digit case IDs) | `1a0b420d-99f1-4887-9851-990b2a5a6e17` | storm + baseline |
| 311 Service Requests - NEW SYSTEM (case IDs start with "BCS-") | `254adca6-64ab-4c5c-9fc0-a6da622be185` | storm + baseline |
| 311 SERVICE REQUESTS - 2025 | `9d7c2214-4709-478a-a2e8-fb2020a5bb94` | comparison window |
| 311 SERVICE REQUESTS - 2024 | `dff4d804-5031-443a-8409-8344efd0e5c8` | optional |
| 311 SERVICE REQUESTS - 2022 | `81a7b022-f8fc-4da5-80e4-b160058ca207` | Jan 2022 blizzard fallback/validation |
| Data Dictionary - NEW SYSTEM (PDF) | `6e443a5d-8027-41d5-9574-35e8f84b8284` | field names for new file |
| CRM Value Codex (PDF) | `b237f352-49d1-4423-804f-b478e4f24e61` | decode values |
| Data Transition Guide | `6e86da47-9b6c-459a-ab97-0e64045081a0` | which case types live in which file |

Direct downloads seen on the page (filenames can change; prefer the API below):
- NEW SYSTEM: https://data.boston.gov/dataset/8048697b-ad64-4bfc-b090-ee00169f2323/resource/254adca6-64ab-4c5c-9fc0-a6da622be185/download/tmptw_y0qtt.csv
- 2026 legacy: https://data.boston.gov/dataset/8048697b-ad64-4bfc-b090-ee00169f2323/resource/1a0b420d-99f1-4887-9851-990b2a5a6e17/download/tmpht98t3gj.csv
- 2025: https://data.boston.gov/dataset/8048697b-ad64-4bfc-b090-ee00169f2323/resource/9d7c2214-4709-478a-a2e8-fb2020a5bb94/download/lagan_311_open_data_2025_rvsd3.csv
- 2022: https://data.boston.gov/dataset/8048697b-ad64-4bfc-b090-ee00169f2323/resource/81a7b022-f8fc-4da5-80e4-b160058ca207/download/lagan_311_open_data_2022_rvsd3.csv
- New system dictionary: https://data.boston.gov/dataset/8048697b-ad64-4bfc-b090-ee00169f2323/resource/6e443a5d-8027-41d5-9574-35e8f84b8284/download/311-service-requests-data-dictionary-new-system.pdf
- Codex: https://data.boston.gov/dataset/8048697b-ad64-4bfc-b090-ee00169f2323/resource/b237f352-49d1-4423-804f-b478e4f24e61/download/datadictionary-crmvaluecodeindex.pdf

CKAN API (Analyze Boston runs CKAN):
```
# current resource URLs
https://data.boston.gov/api/3/action/package_show?id=311-service-requests

# inspect fields (do this before any SQL)
https://data.boston.gov/api/3/action/datastore_search?resource_id=<ID>&limit=1

# filtered pull (verify field names first; quote identifiers)
https://data.boston.gov/api/3/action/datastore_search_sql?sql=SELECT * FROM "<ID>" WHERE "open_dt" >= '2026-01-01'
```
If datastore SQL is disabled or slow, download full CSVs and filter locally.

### 6.2 Critical caveats for 311
- **Split files.** Per the dataset page: starting October 2025, 311 began moving to a new backend. During the transition, cases land in either the legacy 2026 file or the NEW SYSTEM file depending on case type; full migration expected by mid-2026. **The blizzard week and the baseline are split across both files. Union them.** Use the Transition Guide to map case types between schemas.
- **Known bug (reported fixed).** The page says transitioned case types were being dropped from the 2026 legacy file, making volumes look much lower than prior years, fixed as of 8/25/2026. If volumes look suspiciously low, this is why. Exactly the kind of artifact that looks like silence but isn't.
- **Default coordinate pile-up.** Older Boston 311 files have historically assigned missing locations to a single downtown point near City Hall (about 42.3594, -71.0587). Check for a pile-up at one coordinate and drop those rows.

### 6.3 Expected fields (verify against files)
- Legacy schema typically includes: `case_enquiry_id, open_dt, closed_dt, case_status, case_title, subject, reason, type, queue, department, location, neighborhood, ward, precinct, location_zipcode, latitude, longitude, source`.
- Legacy `source` values have historically included: Constituent Call, Citizens Connect App, Self Service, Twitter (resident channels, **keep**), and Employee Generated, City Worker App, Maximo Integration (worker or system generated, **drop**). Find the equivalent channel field in the NEW SYSTEM dictionary.
- Normalize both files to: `case_id, opened_at (America/New_York), case_type, case_type_group, channel, is_resident, lat, lon, tract_geoid, is_storm_type, source_file`.

### 6.4 Other data
| Data | Where | Use |
|---|---|---|
| 2020 census tracts (MA) | Census TIGER: https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_25_tract.zip | spatial join unit |
| City of Boston boundary / Neighborhoods | Analyze Boston (search "boundary", "neighborhoods") | clip + friendly names |
| ACS 5-year (tract) | Census API, Suffolk County = state 25, county 025 | need indicators, population |
| HHS emPOWER (ZIP) | https://services2.arcgis.com/ZQ4jTQn6k7VPXEwO/arcgis/rest/services/HHS_emPOWER_REST_Service_Public/FeatureServer | electricity-dependent Medicare beneficiaries |
| ZIP boundaries | Analyze Boston ZIP layer if present, else Census ZCTA520 (national file is large) | emPOWER ZIP to tract |
| BCYF centers, library branches | Analyze Boston | warming center layer (nice to have) |
| Property Assessment (latest FY) | Analyze Boston | parcel owner-occupied flag (nice to have; ACS tenure is the fast fallback) |

**ACS variables (verify labels at `https://api.census.gov/data/<year>/acs/acs5/variables/<VAR>.json`; try the newest 5-year vintage first, fall back one year):**
- Population: `B01003_001E`
- Tenure: `B25003_001E` (occupied), `B25003_003E` (renter)
- No vehicle: `B25044_001E` (total), `B25044_003E` (owner, none), `B25044_010E` (renter, none)
- Limited-English households: `C16002_001E` total; limited = `_004E + _007E + _010E + _013E`
- Seniors living alone: `B11007_003E` / `B11007_001E` (verify label)
- Disability: subject table `S1810_C03_001E` (percent with a disability) at `/acs/acs5/subject`

Example:
```
https://api.census.gov/data/2023/acs/acs5?get=NAME,B01003_001E,B25003_001E,B25003_003E&for=tract:*&in=state:25&in=county:025
```

**emPOWER notes:** query the FeatureServer with `?f=json` to list layers, find the ZIP layer, then query with `where=1=1&outFields=*&f=geojson` filtered to Boston ZIPs. Counts from 1 to 10 are masked and shown as 11. Allocate ZIP counts to tracts by area-weighted overlay; state this simplification on the methods slide.

### 6.5 Data go/no-go checks (run first, ~30 minutes)
1. Pull legacy 2026 + NEW SYSTEM. Confirm both have rows for Feb 22 to 26, 2026.
2. Union them. Plot citywide daily resident requests and storm-type requests from Feb 15 to Mar 5, 2026. Expect a clear storm-type spike Feb 23 to 24.
3. Overlay the same window from 2025.
4. Report % of rows with valid coordinates and the size of any single-coordinate pile-up.
5. List distinct case types matching snow, plow, sidewalk, ice, tree, branch, heat, light, wire, power. Save as `config/storm_types.yaml` for human review.
6. Identify the channel field in each file and its values. Proposed keep/drop list for human review.
7. Spatial join to tracts. Report tracts with zero baseline requests.

**Decision by T+45 min:** go with 2026, or fall back to the January 29, 2022 blizzard (fully legacy schema, one file). Same method either way.

---

## 7. Architecture and stack

```
pipeline (Python)  ->  data/processed/*.json, *.geojson  ->  API (FastAPI)  ->  web (React + MapLibre)
                                                              ^      |
                                              Twilio webhook  |      v  SSE event stream
```

- **Pipeline:** Python 3.11, pandas, geopandas, shapely, scipy, requests, pyyaml.
- **API:** FastAPI + uvicorn. In-memory state plus a small SQLite file for check-ins, escalations, volunteers. SSE for live events.
- **Web:** Vite + React + TypeScript + Tailwind + MapLibre GL JS (no token needed) with a free dark basemap; if tiles fail, render tracts on a plain background. Recharts for sparklines.
- **LLM:** Anthropic API (for example `claude-sonnet-5-5` for briefings and verification, `claude-haiku-5-5` for outreach drafts; confirm current models at https://docs.claude.com) or Amazon Bedrock (AWS is a title sponsor). Pre-generate and cache all briefings and outreach for the top 15 tracts.
- **SMS:** Twilio + ngrok (or cloudflared) to expose the webhook.

### Repo structure
```
lifeline-city/
  CLAUDE.md / HANDOFF.md
  .kiro/
    steering/        product.md tech.md structure.md privacy.md outreach-style.md silence-model.md
    specs/lifeline-city/  requirements.md design.md tasks.md
    hooks/           (see Section 11)
  config/            scoring.yaml storm_types.yaml channels.yaml languages.yaml
  data/raw/          (gitignored)
  data/processed/    tracts.geojson timeline.json need.csv briefings.json outreach.json
  pipeline/          01_fetch.py 02_normalize_311.py 03_tracts_join.py 04_baseline.py
                     05_silence.py 06_need.py 07_timeline.py 08_validate_2022.py 09_export.py
  api/               main.py state.py sms.py events.py
    agents/          triage.py verifier.py outreach.py dispatch.py
    synthetic/       households.py volunteers.py
  web/               src/ (Map, Queue, Drawer, EventFeed, PhoneSim, Scrubber)
  docs/              pitch.md demo-script.md methods.md kiro-usage.md
  .env.example
```

### API endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/tracts` | GeoJSON with scores and components |
| GET | `/api/timeline?hour=` | per-tract cumulative observed vs expected |
| GET | `/api/tracts/{geoid}` | detail: metrics, verified briefing, outreach |
| POST | `/api/checkins/send` | `{geoid}`: real SMS to demo numbers, simulated sends for the rest |
| POST | `/api/sms/webhook` | Twilio inbound (form fields `From`, `Body`) |
| POST | `/api/escalations/{id}/assign` | assign nearest volunteer |
| GET | `/api/events` | SSE stream for the live feed |
| POST | `/api/demo/reset` | reset demo state |

### `.env.example`
```
ANTHROPIC_API_KEY=
AWS_REGION=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
DEMO_PHONE_NUMBERS=+1XXXXXXXXXX,+1XXXXXXXXXX
DEMO_REPLY_TIMEOUT_SECONDS=90
CENSUS_API_KEY=
```

---

## 8. Agents

1. **Triage agent (LLM):** input = one tract's metrics JSON. Output = JSON with `headline`, `claims[]` (each `{text, field, value}`), `recommended_action`. Prompt rule: use only numbers present in the input.
2. **Verifier (deterministic first, LLM optional):** every claim's `field` must exist and its `value` must match the metrics within tolerance. Fail: regenerate once. Fail again: fall back to a template briefing. Log verifier pass rate for the Kiro/AI-strategy slide. This is the Polygraph idea applied to civic trust.
3. **Outreach agent (LLM):** per language, an SMS of at most 2 segments. First line is carbon monoxide safety. Then "Reply 1 if OK, 2 if you need help." Then 911 for emergencies, 311 for city help. Plain language, about grade 6. Back-translate to English and compare intent as a check. Languages: English, Spanish, Haitian Creole, Cape Verdean Creole, Portuguese, Chinese, Vietnamese.
4. **Dispatcher (rules, not LLM):** nearest available volunteer within 1.5 km; volunteer sees only the tract until they accept, then the address.

---

## 9. SMS check-in loop

- **Synthetic households:** ~200 fake households placed at random points inside the top 10 tracts, language sampled from a tract mix (or a fixed list), `synthetic: true`. Map 1 to 2 of them to teammates' real phones.
- **Simulated replies** for the rest: reply probability decreases with the tract's silence score. Label "Simulated" in UI.
- **Real replies:** Twilio webhook parses `1` or `2` (also accept words like OK / HELP in each language). `2` creates an escalation. No reply within `DEMO_REPLY_TIMEOUT_SECONDS` marks the household silent and raises the tract's confirmed-silence count.
- **Twilio gotchas:**
  - Trial accounts only text verified numbers and prefix a trial notice. Verify teammates' numbers in advance.
  - Messages with non-GSM characters (Chinese, Vietnamese diacritics) use UCS-2, about 70 characters per segment. Keep them short.
  - Run `ngrok http 8000`, then set the number's Messaging webhook to `https://<ngrok>/api/sms/webhook`. The ngrok URL changes on restart.
- **Fallback:** in-app phone simulator panel (also useful for the recorded video).

---

## 10. Build plan and team split

Adjust times to the actual clock. Feature freeze is non-negotiable.

| Time | Data | Backend + agents | Frontend + design | Madhan (lead) |
|---|---|---|---|---|
| T+0:00 to 0:45 | Go/no-go checks (6.5) | FastAPI scaffold, Twilio hello world + ngrok | Vite/React/MapLibre scaffold, tracts on map | Kiro steering + spec (requirements in EARS) |
| T+0:45 | **Decision: 2026 or 2022** | | | |
| to T+2:30 | Pipeline to `tracts.geojson` v1 + `timeline.json` | Serve static data, SMS webhook end to end | Choropleth + layer toggle + queue | Review scoring weights, storm type list |
| to T+4:00 | Need index, 2022 validation | Triage + verifier + outreach, cache outputs; check-in loop + SSE | Drawer, why chips, scrubber, event feed | Verifier rules, outreach copy, CO line |
| to T+5:00 | Methods doc + numbers for slides | Escalations + dispatch, demo reset | Polish, "Simulated" badges, phone simulator | Pitch deck, demo script rehearsal |
| **Feature freeze** | | | | |
| to T+6:00 | Screenshots | Stability | Final polish | Record 90s video, write project card, Kiro screenshots |
| 6:00 PM | **Submit** | | | |

Cut order if behind: hourly scrubber, then 2022 validation, then structural layer UI. Never cut the check-in loop.

---

## 11. Kiro plan (a full judging criterion)

### Steering files (`.kiro/steering/`)
- `product.md`: mission, users, the silence insight, what we will not do.
- `tech.md`: stack from Section 7.
- `structure.md`: repo map from Section 7.
- `privacy.md`: aggregate only for real residents; synthetic records labeled; no phone numbers in repo; no individual-level real data; emPOWER masking respected.
- `outreach-style.md`: CO safety first, plain language, reply instructions, languages, segment limits, always a path to a human.
- `silence-model.md`: Section 5 formulas, so every generated change respects them.

### Spec (`.kiro/specs/lifeline-city/`)
`requirements.md` in EARS format. Starter set:
1. WHEN the replay clock advances, THE SYSTEM SHALL update each tract's observed and expected request counts.
2. WHEN a tract ranks in the top 10 by priority, THE SYSTEM SHALL list it in the response queue with the metrics that caused the flag.
3. WHEN an operator opens a tract, THE SYSTEM SHALL display a briefing in which every number matches the tract's computed metrics.
4. IF a generated briefing contains a claim that does not match the metrics, THEN THE SYSTEM SHALL discard it and display a template briefing.
5. WHEN an operator sends check-ins, THE SYSTEM SHALL send each household a message in its language that begins with carbon monoxide safety guidance.
6. WHEN a household replies 2, THE SYSTEM SHALL create an escalation and assign the nearest available verified volunteer.
7. IF a household has not replied within the timeout, THEN THE SYSTEM SHALL mark it silent and increase its tract's confirmed-silence count.
8. THE SYSTEM SHALL use only aggregated data for real residents and SHALL label every synthetic record as simulated.

Then `design.md` (architecture, data flow, scoring) and `tasks.md` (generated, then executed task by task).

### Hooks
- On save in `pipeline/`: run scoring unit tests (sum of expected equals sum of observed, no negative rates, p-values in range).
- On save of outreach templates: regenerate translations, back-translate, check reading level and segment length.
- Privacy guard on save in `api/` or `data/processed/`: scan for phone numbers, names, street addresses tied to real people; fail loudly.

### Evidence for judges
Screenshots of the spec, steering files, and a hook firing go on the project card and one slide. Put a short `docs/kiro-usage.md` in the repo.

---

## 12. Demo, video, submission card

### 3-minute live demo
1. **0:00 to 0:25** Cape story: towers down, Provincetown sorting shelter residents by age and health, Meals on Wheels stuck.
2. **0:25 to 0:45** Insight: 311 mostly hears homeowners within two blocks of a problem. "311 hears the loudest blocks. Lifeline listens for the quiet ones."
3. **0:45 to 1:30** Boston replay: scrub to Feb 23, silence appears, click the top tract, show heard vs expected, need breakdown, verified briefing.
4. **1:30 to 2:15** Send check-ins: teammate's phone buzzes in Portuguese or Spanish, they reply 2, the map updates and a volunteer is assigned in seconds.
5. **2:15 to 2:40** How it's built: Kiro spec, steering, hooks; verifier agent; privacy by design.
6. **2:40 to 3:00** Scale: any MA town, any hazard. Phase 2: building-level confirmation with Lifeline's WiFi sensing.

### 90-second video (for virtual judges)
Hook (Cape, 10s), insight (10s), replay + why panel (25s), live phone moment (25s), Kiro + architecture (10s), scale + close (10s). Captions on.

### Project card copy
- **Title:** Lifeline City
- **Tagline:** Finding the residents a disaster makes invisible.
- **Description:** use the submitted one-liner; keep the method for the demo.
- **Built with:** Kiro (specs, steering, hooks), Analyze Boston 311, US Census ACS, HHS emPOWER, Twilio, FastAPI, React, MapLibre, Claude or Bedrock.
- **Media:** map screenshot with the silence layer, phone screenshot, Kiro spec screenshot, video link.

---

## 13. Guardrails
- Real resident data stays aggregated. Synthetic households and volunteers are labeled everywhere.
- Language is descriptive: "quieter than expected." No claims about why.
- Not a replacement for 911. Every resident message includes 911 and 311.
- Every escalation ends with a human.
- Methods slide states simplifications: ZIP to tract allocation, emPOWER masking, Poisson assumption, replay window choices.

---

## 14. Risks and fallbacks
| Risk | Fallback |
|---|---|
| 2026 311 data split or incomplete | January 2022 blizzard, legacy file only |
| Acute silence is noisy | Lead with need + structural silence; acute as a layer |
| Twilio fails or trial limits bite | In-app phone simulator |
| LLM latency or errors | Cached briefings and outreach; template fallback |
| Map tiles fail | Tracts on plain background |
| Time crunch | Cut per Section 10 order |

---

## 15. Open items
- [ ] Confirm with organizers whether code generated outside Kiro is allowed.
- [ ] Open the event data portal's Civic page in a browser; note any curated datasets or starter kits to use.
- [ ] Verify teammates' numbers in Twilio.
- [ ] Choose LLM provider (Anthropic API or Bedrock) and confirm keys work.
- [ ] Optional: search for any state review of the utilities' blizzard response; strong slide if one exists.
