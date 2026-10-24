# Methods

Cape Cod, Blizzard of 2026: 56 tracts (2020), 15 towns, 119 hours, 2026-02-23T01:00 to 2026-02-27T23:00 local. Weights: `config/scoring.yaml`. Provenance: `data/processed/sources.json`.

## Scoring

```
need_t           = mean of percentile ranks of the Need indicators (within the region shown)
out_pct(T,h)     = share of town T's customers out at hour h (0-1)
hours_dark(T,h)  = hours since out_pct first reached 0.5 (0 if below), capped at 72
wires(T,h)       = urgent downed-wire calls received in T up to hour h, per 1,000 customers (percentile rank)
telecom(T,h)     = 1 if an observed event with drives_reach_flag = true is active for T, OR modeled rule:
                   out_pct >= 0.8 for >= 8 consecutive hours  (ASSUMPTION about tower backup life; label it)
lifelines(T,h)   = 0.4*out_pct + 0.3*min(hours_dark/72,1) + 0.1*wires + 0.2*telecom
priority_Cape    = need_t * lifelines(town(t), h)
channel(t,h)     = "sms" if telecom(town(t), h) = 0, "door_knock" if 1; every queued tract also gets an AM radio script
```

- Need: six indicators (seniors alone, disability, limited English, no vehicle, renters, electricity-dependent Medicare per 1,000), percentile-ranked among Cape tracts. ACS 2024 5-year. Tracts take the town containing their centroid.
- emPOWER ZIP counts go to tracts by area weight, area(ZIP ∩ tract) / area(ZIP), assuming an even spread within each ZIP.
- emPOWER masking: counts of 1 to 10 are reported as 11. We use 11 as reported and never unmask (14 masked ZIPs).

## Outage curves

- Cape total: curated `cape_eversource` rows, shaped between and beyond them by Eversource Tab 3. Tab 3 is validated against its MA peak (269,063 at 2026-02-23 8 AM). Cape peak: 158,803 at 2026-02-24T08:00.
- Town anchors (MEMA, police, news): a non-lower-bound anchor pins its town-hour; a lower-bound anchor sets a floor. Between anchors, interpolate; outside them (or with one anchor), follow the Cape total shape.
- Scaling: non-pinned town-hours are scaled so the 15 towns sum to the Cape total, within [0, 1] and above floors. Unmatched hours are recorded; this run has 0.
- Chatham has no anchors: "Estimated from the Cape-wide share (no town reports)".
- Customers: MEMA town counts; Sandwich and Chatham "Estimated from ACS housing units."
- Excluded: the 133,000 figure from county sitrep #009 (Feb 26). It is absent from the curated CSVs; code also enforces the exclusion.
- Downed wires: Eversource Tab 5, town-hour counts only. 1,082 Cape calls kept; 638 calls from 62 non-Cape towns excluded.

## Telecom

- No curated event has `drives_reach_flag = true` (responder systems or Cape-wide reports), so events are map pins and briefing context only. The modeled rule alone sets the channel: "Modeled: assumes tower backup lasts about 8 hours".
- `telecom_observed_default_hours = 12`: assumed duration for a flagged event with no end time. Unused in this data.

## Outreach

- Help line: Cape uses 2-1-1 (statewide Mass 211, where MEMA directed residents); Boston would use 311. Every message includes 911.
- Assumed household language mix: en 0.85 / pt 0.10 / es 0.05; Barnstable and Yarmouth en 0.6 / pt 0.3 / es 0.1, with household #1 always pt.
- Resident SMS, doorstep and radio text are hand-written templates. Only operator briefings at the 5 `key_demo_hours` use an LLM, pre-generated. The verifier checks each number against tract-hour metrics: 14 passed, 35 regenerated, 1 template fallback.

## Scope and limitations

- Boston Voice (311 silence) is not built in this build.
- Limitations: reconstructed (not metered) outage curves; emPOWER area-weight assumption; modeled telecom assumption; synthetic households, responders and replies, labeled "Simulated".
