# Lifeline City: Decisions (2026-10-24)

Read this together with `LIFELINE_CITY_HANDOFF.md`. **Where they conflict, this file wins.** The handoff's guardrails (aggregate-only real data, synthetic records labeled "Simulated", descriptive language, secrets in `.env`, pre-computed demo data) still apply in full.

## 1. Framing (locked)

- The **Cape is the case study, not the product boundary.** The product serves any Massachusetts town and any hazard.
- Most of the 351 towns have no open 311 data. Lifeline works on the data every town has; 311 is a bonus where it exists.
  - **Tier 1, every town:** Need + Lost lifelines + Reach.
  - **Tier 2, cities with open 311 (Boston):** adds Voice (311 silence).
- Other hazards only swap the "lost lifelines" input. Blizzard, nor'easter, ice storm: power, phones, blocked roads. Flood: flood zones, gauges, road closures. Heat: power plus heat index.
- Pitch line: "Boston can hear its quiet blocks. Most of Massachusetts can't hear anything at all. Lifeline listens for both."
- Evidence base: the Barnstable County after-action report (`data/raw/reports/`). Telecom failed region-wide with no backup protocol, help only reached people who asked, and success was measured only by who reached shelters.

## 2. Layers

| Layer | Unit | Where | Inputs |
|---|---|---|---|
| **Need** | 2020 census tract | Barnstable County (25001) and Boston | ACS: seniors living alone, disability, limited-English households, no-vehicle households, renter share. HHS emPOWER: electricity-dependent Medicare beneficiaries per 1,000 (ZIP to tract by area weight). |
| **Lost lifelines** | Town, hourly, 2026-02-23 01:00 to 2026-02-27 23:00 local | 15 Cape towns | % customers out, hours dark, urgent downed-wire calls, telecom-degraded flag |
| **Voice** | Census tract, one static storm-window view | Boston only | 311 observed vs. expected, per handoff Section 5 (no hourly replay) |
| **Reach** | Tract | Cape | Channel choice per tract-hour (Section 4) |

## 3. Scoring

Weights live in `config/scoring.yaml`. Every component is visible in the "why flagged" panel.

```
need_t           = mean of percentile ranks of the Need indicators (within the region shown)
out_pct(T,h)     = share of town T's customers out at hour h (0-1)
hours_dark(T,h)  = hours since out_pct first reached 0.5 (0 if below), capped at 72
wires(T,h)       = urgent downed-wire calls received in T up to hour h, per 1,000 customers (percentile rank)
telecom(T,h)     = 1 if an observed event with drives_reach_flag = true is active for T, OR modeled rule:
                   out_pct >= 0.8 for >= 8 consecutive hours  (ASSUMPTION about tower backup life; label it)
                   In the curated data every observed event has drives_reach_flag = false: they are either
                   responder systems (radio, dispatch, police/fire phones) or vague Cape-wide reports. So the
                   modeled rule drives the channel; observed events are map pins and briefing context only.
lifelines(T,h)   = 0.4*out_pct + 0.3*min(hours_dark/72,1) + 0.1*wires + 0.2*telecom
priority_Cape    = need_t * lifelines(town(t), h)
priority_Boston  = need_t * silence_t        (handoff Section 5)
```

Each tract inherits its town's lost-lifelines values; assign tracts to towns by centroid.

## 4. Reach logic

- **Phones working** (`telecom = 0`): send SMS check-ins. Reply 2 creates an escalation. No reply within the timeout counts as "silent."
- **Phones degraded** (`telecom = 1`): send no SMS and never infer silence from a missing reply. Households go to a **door-knock list** routed to responders that actually exist: police/fire wellness checks, the Council on Aging, Elder Services, Meals on Wheels drivers (all synthetic, labeled "Simulated"). Flag high downed-wire counts as an access hazard on the list.
- **Every priority area** also gets an **AM radio script** for the county station (the after-action report found it was never used).
- Languages: **English, Portuguese, Spanish.** Carbon monoxide safety first; always include 911 and the region's help line.
- **Help line is per region (overrides the handoff's "every message includes 911 and 311"):** Cape messages say "911 for emergencies, 2-1-1 for shelters and help". Cape towns don't run 311 lines; the state emergency agency directed residents to 2-1-1 (Mass 211) during the storm, and the county after-action report calls Mass 211 the main public help line in disasters. Boston messages keep 311.

## 5. Data (already downloaded to `data/raw/`)

| File | What it is | How to use |
|---|---|---|
| `eversource_dpu_25-ERP-10/eversource_final_event_report_tabs.xlsx` | Eversource final event report to the state utility regulator | **Tab 3**: hourly *new* outages and *new* restorations (Eversource MA). Customers out = running sum of (outages - restored); this peaks at 269,063 at 8-9 AM Feb 23, matching the report. **Tab 5**: 1,720 urgent downed-wire calls with town, priority, received/arrived/repaired timestamps. |
| `eversource_dpu_25-ERP-10/eversource_final_event_report_part1.pdf` | Narrative (162 pp) | Street-level broken poles and transformers by town. p.103: only 2,246 confirmed medical customers were called pre-storm, across all of Eversource MA. |
| `curated/cape_town_outage_anchors.csv` | Hand-entered town snapshots with sources | Anchors for each town's outage curve |
| `curated/cape_total_outage_timeline.csv` | Hand-entered Cape-wide and statewide totals with sources | Shape and scale for the curves |
| `curated/cape_telecom_events.csv` | Hand-entered telecom failures with sources. `affects` = residents or responders; `drives_reach_flag` = whether it may set `telecom = 1` | Map pins and briefing context. Do not let "Cape-wide" rows flip every town: that would make every tract door-knock and remove the SMS-vs-door-knock contrast |
| `reports/` | County after-action report, summary deck, state situation report #4 | Pitch evidence |
| `national_grid_dpu_25-ERP-09/` | National Grid outage events (not Cape) | Optional |

**Reconstructing town curves:** interpolate between each town's anchors, scale each hour so the Cape towns sum to the Cape-wide total, and shape gaps with the Eversource Tab 3 curve. Label everything **"Reconstructed from MEMA, Eversource and public-safety reports."** Do not use the 133,000 figure in county situation report #009 (Feb 26); it conflicts with every other source and looks stale. Town customer counts come from the Patch/MEMA snapshot (customers out / pct out); Sandwich and Chatham need another source (ACS housing units as a fallback, labeled).

**Environment:** Python 3.11 is not installed. Use Python 3.13 via `uv` (`uv venv --python 3.13`). Node 25 and npm 11 are installed.

**Still to fetch** (live public APIs): ACS 5-year tract data, HHS emPOWER ZIP layer, TIGER tracts, MA town boundaries, Boston 311 (handoff 6.1).

## 6. Solo scope (about 5.5 hours)

- **Keep:** Cape Need + Lost lifelines map with time slider; ranked queue; tract drawer with a verified briefing; Reach panel (SMS vs. door-knock list vs. radio script); check-in loop on the in-app phone simulator (real Twilio SMS only if it works within 20 minutes); Boston Voice as one static view; a town/hazard selector showing the scale story.
- **Simplify:** 3 languages; door-knock list instead of nearest-volunteer dispatch; polling instead of server-sent events; all AI briefings and messages pre-generated and cached.
- **Time cuts (2:15 PM):** resident outreach (SMS, doorstep, radio) uses hand-written templates in en/pt/es only, with no AI drafting; the AI writes only operator briefings at the key demo hours, checked by the verifier. Radio is one fixed template per language. Export writes directly to `data/processed/`, then the privacy guard runs and fails loudly (no staging, no raw-file manifest). `docs/methods.md` is one page.
- **Cut:** 2022 storm validation, hourly Boston replay.

## 7. Kiro working model

- **Kiro (Opus 5.5) generates** steering files, the spec (requirements in EARS, design, tasks), hooks, and **all code**.
- Claude Code handles research, data sourcing, this file, and review only.
- Steering should encode Sections 1-4 here plus the handoff's privacy and outreach rules.
