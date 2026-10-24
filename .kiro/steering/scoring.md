# Scoring

Formulas below are copied exactly from `DECISIONS.md` Section 3. Do not change them in code; change only the weights and thresholds in `config/scoring.yaml`.

## Formulas (DECISIONS.md Section 3, verbatim)

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

## Need indicators

Six indicators per 2020 tract, each converted to a percentile rank within its region (Cape tracts among Cape tracts, Boston tracts among Boston tracts):

1. Seniors living alone (ACS)
2. Disability (ACS)
3. Limited-English households (ACS)
4. No-vehicle households (ACS)
5. Renter share (ACS)
6. Electricity-dependent Medicare beneficiaries per 1,000 (HHS emPOWER, ZIP to tract by area weight)

## Boston Voice: `silence_t` (handoff Section 5, static view only)

One storm-window view per tract. No hourly replay (cut in DECISIONS.md Section 6).

- Unit: 2020 tracts clipped to the City of Boston. Drop tracts with population under 500 or mostly non-residential (Logan, Harbor Islands, large parks).
- Voice signal: all resident-originated 311 requests (any case type); drop worker/system-generated channels per `config/channels.yaml`. Union the legacy 2026 file and the NEW SYSTEM file. Drop the default-coordinate pile-up near 42.3594, -71.0587.
- Storm window W: 2026-02-22 14:00 to 2026-02-25 23:59 local.
- Baseline B: 2026-01-05 to 2026-03-31, excluding the storm week, about Jan 24 to 27, Feb 7 to 9, holidays, and any day whose citywide storm-type count exceeds 3x the median daily count.

```
r_t          = (c_t + k * r_city_pc * pop_t) / (d + k)     # k = 7 pseudo-days
S            = sum_t(O_t) / sum_t(r_t * D)                 # D = storm window days
lambda_t     = r_t * D * S
O_t          = resident requests in tract t during W
p_t          = PoissonCDF(O_t ; lambda_t)                  # small p = significantly quiet
acute_t      = clip(-log10(p_t), 0, 6)
ratio_t      = O_t / lambda_t                              # shown in UI
rate_pc_t    = baseline requests per 1,000 residents per 30 days
structural_t = percentile rank of (-rate_pc_t)
silence_t    = mean(pct(acute_t), structural_t)            # weights configurable
```

## Reach channel (DECISIONS.md Section 4)

```
channel(t,h) = "sms"        if telecom(town(t), h) = 0
               "door_knock" if telecom(town(t), h) = 1
radio        = every priority area (every tract in the ranked queue) also gets an AM radio script
```

## Implementation notes (clarifications, not changes)

- Percentile rank: average-rank method scaled to [0, 1]. `wires` is ranked across the 15 Cape towns at the same hour h.
- Missing Need indicator for a tract: average the indicators that exist and show which are missing in the "why flagged" panel.
- `hours_dark`, literal reading: h minus the first hour where `out_pct >= 0.5`, set to 0 whenever `out_pct(T,h) < 0.5`, capped at 72.
- Modeled telecom at hour h: `out_pct >= 0.8` in each of the 8 consecutive hours ending at h. Label "Modeled". Observed telecom events cite their source. Show which rule fired.
- Observed events in `cape_telecom_events.csv`: only rows with `drives_reach_flag = true` may set `telecom = 1`; in the current curated data none do, so the modeled rule drives the channel. Every row is a map pin and briefing context: split `town_or_area` on `;`, and never let "Cape-wide" rows flip every town. Match town names exactly after splitting, never by substring: "Barnstable County MACC", "Barnstable County Sheriff dispatch" and "Outer Cape" are not towns. If a flagged row has no `end_local`, use `telecom_observed_default_hours` and label it an assumption.
- Because the lifelines weights sum to 1 and every term is in [0, 1], `lifelines` and both priorities are in [0, 1]. Tests must hold this.
- Ranked queue: top `queue_size` tracts by priority at hour h (default 10), ties broken by `need_t`, then GEOID.

## `config/scoring.yaml` keys

```yaml
lifelines_weights: {out_pct: 0.4, hours_dark: 0.3, wires: 0.1, telecom: 0.2}
hours_dark_cap: 72
dark_threshold: 0.5
telecom_model: {out_pct_threshold: 0.8, consecutive_hours: 8}
telecom_observed_default_hours: null   # set during design; label as assumption
access_hazard_wires_pct: 0.8
queue_size: 10
key_demo_hours: ["2026-02-23T09:00", "2026-02-23T17:00", "2026-02-24T09:00", "2026-02-25T15:00", "2026-02-26T13:00"]   # LLM briefings only at these hours; re-checked at the first --no-llm run so at least one hour shows both sms and door_knock
boston: {k_pseudo_days: 7, acute_cap: 6, silence_weights: {acute: 0.5, structural: 0.5}, min_tract_pop: 500}
```
