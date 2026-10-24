# Product: Lifeline City

Source of truth: `DECISIONS.md` overrides `LIFELINE_CITY_HANDOFF.md` wherever they conflict. The handoff guardrails (aggregate-only real data, synthetic records labeled "Simulated", descriptive language, secrets in `.env`, pre-computed demo data) still apply in full.

## One-liner

An AI agent that helps emergency managers find the residents who go silent during a disaster, before it is too late.

Pitch line: "Boston can hear its quiet blocks. Most of Massachusetts can't hear anything at all. Lifeline listens for both."

## Framing (locked)

- Cape Cod (Barnstable County, Blizzard of 2026) is the **case study, not the product boundary**. The product serves any Massachusetts town and any hazard.
- Most of the 351 MA towns have no open 311 data. Lifeline works on the data every town has; 311 is a bonus where it exists.
- Evidence base: the Barnstable County after-action report (`data/raw/reports/`). Telecom failed region-wide with no backup protocol, help only reached people who asked, and success was measured only by who reached shelters.
- Silence is a question, not a verdict. Lifeline asks it, then routes a human.

## Tiers

| Tier | Where | Layers |
|---|---|---|
| Tier 1 | Every MA town | Need + Lost lifelines + Reach |
| Tier 2 | Cities with open 311 (Boston) | Tier 1 + Voice (311 silence) |

Other hazards only swap the "lost lifelines" input:

- Blizzard, nor'easter, ice storm: power, phones, blocked roads.
- Flood: flood zones, gauges, road closures.
- Heat: power plus heat index.

Only the Cape blizzard (Tier 1) and Boston Voice (Tier 2, static) carry real data in the demo. Other town/hazard combinations appear in the scale selector as configuration previews listing the inputs they would use. They never show fabricated scores.

## Users

- **Primary: emergency managers and ops staff** (county emergency managers, town emergency management directors, MEMA, Boston OEM). Desktop, single page.
- **Residents:** SMS only. No app, no login, works on a flip phone, in English, Portuguese or Spanish.
- **Responders (synthetic, labeled "Simulated"):** police/fire wellness checks, Council on Aging, Elder Services, Meals on Wheels drivers. They receive door-knock lists when phones are degraded.

## Demo scope (DECISIONS.md Section 6 Keep list)

1. Cape Need + Lost lifelines map with an hourly time slider (2026-02-23 01:00 to 2026-02-27 23:00 local).
2. Ranked queue of priority tracts at the selected hour.
3. Tract drawer with a "why flagged" panel and a verified briefing.
4. Reach panel: SMS check-ins vs. door-knock list vs. AM radio script, chosen per tract-hour.
5. Check-in loop on the in-app phone simulator. Real Twilio SMS only if it works within 20 minutes; otherwise simulator only.
6. Boston Voice as one static storm-window view.
7. Town/hazard selector that tells the scale story.

Simplifications: 3 languages; door-knock list instead of nearest-volunteer dispatch; polling instead of server-sent events; all AI briefings and messages pre-generated and cached.

## Non-goals (do not build)

- Real 911, 211 or CAD integration. Lifeline never replaces 911.
- Nearest-volunteer dispatch, routing optimization, volunteer onboarding.
- Any real resident-level data, real household contacts, or real responder rosters.
- Mobile app or resident login.
- Hourly Boston 311 replay. 2022 storm validation.
- Server-sent events or websockets (use polling).
- Live LLM calls during the demo.
- Languages beyond English, Portuguese, Spanish.
- WiFi building sensing (Phase 2 slide only).

## Language rules

- Descriptive only: "quieter than expected", "dark for 40 hours". Never "neglected", "ignored", or causal claims about why.
- Every escalation ends with a human.
