# Requirements Document

## Introduction

Lifeline City helps emergency managers find residents who may go silent during a disaster, then routes a human to them. This spec covers only the demo Keep list in `DECISIONS.md` Section 6 and the Kiro working model in Section 7, constrained by the Section 6 Simplify items and by the guardrails in `.kiro/steering/` (product, tech, structure, privacy, outreach-style, scoring). `DECISIONS.md` overrides `LIFELINE_CITY_HANDOFF.md` wherever the two conflict.

The case study is the Barnstable County (Cape Cod) Blizzard of 2026, served as Tier 1 (Need + Lost lifelines + Reach). Boston is served as Tier 2, a single static Voice view. The Cape is the case study, not the product boundary; the scale selector shows how other Massachusetts towns and hazards would be configured, without fabricated scores.

Delivery constraints:

- Solo builder with about 5 hours remaining.
- Build order: Cape pipeline, map and queue, tract drawer and briefings, Reach and the check-in loop, scale selector, then Boston Voice. Boston Voice (Requirement 23, which also holds Boston Need) is a separate block and is the first block cut if time runs out.
- Real Twilio SMS (Requirement 22, Optional) is attempted for at most 20 minutes; otherwise the demo stays on the phone simulator.
- Required tests are the four property-based tests in Requirement 30. Curve-reconstruction, reply-parsing and other tests are optional.
- Optional items, marked "(Optional)" below and built only if time remains after the required build order: Portuguese and Spanish back-translation checks (13.5), real Twilio SMS (Requirement 22), Scale_Selector entries beyond the 6 static entries (24.7), and the contrast audit (29.5).

Out of scope: 2022 storm validation, hourly Boston replay, nearest-volunteer dispatch and routing, server-sent events and websockets, languages other than English, Portuguese and Spanish, live LLM calls during the demo, LLM-drafted resident outreach, real 911, 211 or CAD integration, mobile app or resident login, any real resident-level data, and WiFi building sensing.

## Glossary

- **Pipeline**: The offline Python 3.13 process (`python -m pipeline.run`) that reads `data/raw/` and `config/` and writes `data/processed/`.
- **API**: The local FastAPI service that serves files from `data/processed/` and `config/` and holds check-in state in memory.
- **Web_App**: The single-page Vite, React and TypeScript application used by emergency managers.
- **Operator**: The emergency manager or ops staff member using the Web_App.
- **Map_View**: The Web_App map that renders Cape_Tracts, Cape_Town_Boundaries and telecom pins.
- **Time_Slider**: The Web_App control that selects one Hour of the Demo_Window.
- **Priority_Queue**: The ranked list of the top `queue_size` Cape_Tracts by priority_Cape at the selected Hour.
- **Why_Chip**: A short label in a Priority_Queue row that quotes one metric value of that tract-hour and records the metric field the value came from.
- **Tract_Drawer**: The Web_App detail panel for one Cape_Tract at the selected Hour.
- **Why_Flagged_Panel**: The Tract_Drawer section that shows every scoring component for the tract-hour.
- **Reach_Panel**: The Tract_Drawer section that shows the Reach_Channel and the outreach content for the tract-hour.
- **Phone_Simulator**: The in-app Web_App component that displays simulated SMS conversations with Synthetic_Households.
- **Boston_Voice_View**: The static Web_App view of Boston tracts scored with the Voice layer.
- **Scale_Selector**: The Web_App control that lists Massachusetts town and hazard combinations.
- **Configuration_Preview**: A Scale_Selector panel that lists the tier and data inputs a town and hazard combination would use, labeled "Configuration preview", with no scores.
- **Verifier**: The deterministic Pipeline component that checks Briefing claims and text against the tract-hour metrics and language rules.
- **Test_Suite**: The pytest and Hypothesis tests under `tests/` and the Vitest and fast-check tests under `web/`.
- **Repository**: The workspace at `/Users/madhan/lifeline` as committed to version control.
- **README**: The file `README.md` at the Repository root.
- **Methods_Doc**: The one-page file `docs/methods.md`.
- **Kiro_Usage_Doc**: The file `docs/kiro-usage.md`.
- **Property_Test_Hook**: The Kiro hook under `.kiro/hooks/` that runs the four required property-based tests of Requirement 30.
- **Privacy_Guard**: The scanner that checks files for unmasked phone numbers and street addresses, run by the Pipeline after writing outputs and by the Privacy_Guard_Hook.
- **Privacy_Guard_Hook**: The Kiro hook under `.kiro/hooks/` that runs the Privacy_Guard over `api/` and `data/processed/`.
- **Scoring_Config**: The file `config/scoring.yaml` holding weights, caps, thresholds and Key_Demo_Hours.
- **Languages_Config**: The file `config/languages.yaml` holding the per-town language mix (`by_town`), reply keywords and the Help_Line per region.
- **Content_Cache**: The file `data/processed/content.json` holding pre-generated Briefings and outreach text.
- **Cape_Town**: One of the 15 Barnstable County towns: Barnstable, Bourne, Brewster, Chatham, Dennis, Eastham, Falmouth, Harwich, Mashpee, Orleans, Provincetown, Sandwich, Truro, Wellfleet, Yarmouth.
- **Cape_Town_Boundary**: The polygon of a Cape_Town from the TIGER 2020 county subdivisions file `tl_2020_25_cousub`, filtered to COUNTYFP = 001.
- **Cape_Tract**: A 2020 census tract in Barnstable County (state 25, county 001) with population above 0.
- **Boston_Tract**: A 2020 census tract clipped to the City of Boston boundary, with population at or above `boston.min_tract_pop` and not mostly non-residential (for example Logan Airport, Harbor Islands, large parks).
- **Demo_Window**: The 119 Hours from 2026-02-23T01:00 to 2026-02-27T23:00 inclusive, America/New_York local time.
- **Hour**: A one-hour interval identified by its start timestamp in America/New_York local time, written in ISO 8601.
- **Tract-hour metrics**: The full set of scoring components and Need_Indicator values for one Cape_Tract at one Hour.
- **Percentile_Rank**: The average-rank method scaled to [0, 1], computed within a stated comparison group.
- **Need_Indicator**: One of six tract measures: seniors living alone, disability, limited-English households, no-vehicle households, renter share (ACS 5-year), and electricity-dependent Medicare beneficiaries per 1,000 residents (HHS emPOWER).
- **need_t**: The mean of the available Need_Indicator Percentile_Ranks for tract t.
- **emPOWER_ZIP_Layer**: The HHS emPOWER ZIP-level FeatureServer layer 1, which includes ZIP polygons and the fields `Zip_Code`, `COUNTY`, `Power_Dependent_Devices_DME` and `Medicare_Benes`.
- **Eversource_Workbook**: The file `data/raw/eversource_dpu_25-ERP-10/eversource_final_event_report_tabs.xlsx`.
- **Tab_3_Curve**: The hourly Eversource Massachusetts customers-out curve from Eversource_Workbook Tab 3, whose header row 4 holds `Date`, `Time` (labels `12AM` to `11PM`), `Customers Outages` and `Customers Restored` as new outages and new restorations per Hour; customers out is the running sum of `Customers Outages` minus `Customers Restored`.
- **Tab_5_Call**: One data row of Eversource_Workbook Tab 5 (header row 4, data from row 5, 1,720 rows), with column C the town name in uppercase, column D the priority `01`, `02` or `03`, column E the received timestamp and column H the repair timestamp; column G is not read.
- **Cape_Total_Curve**: The hourly Cape-wide Eversource customers-out curve built from `cape_total_outage_timeline.csv` rows with scope `cape_eversource`, with gaps shaped by the Tab_3_Curve.
- **Anchor**: A row of `cape_town_outage_anchors.csv` for a Cape_Town.
- **Pinned_Town_Hour**: A town-hour whose Hour contains the timestamp of an Anchor with `pct_is_lower_bound` not true; when two or more such Anchors fall in the same town-hour, the Anchor with the latest timestamp applies.
- **Observed_Telecom_Event**: A row of `cape_telecom_events.csv`.
- **Active_Event**: An Observed_Telecom_Event is active at Hour h when `start_local` is before the end of Hour h and the event end (`end_local`, or `start_local` plus `telecom_observed_default_hours` when `end_local` is blank) is after the start of Hour h.
- **Modeled_Telecom_Rule**: telecom(T,h) = 1 when out_pct(T) is at or above `telecom_model.out_pct_threshold` in each of the `telecom_model.consecutive_hours` consecutive Hours ending at h; an assumption about tower backup life, labeled "Modeled: assumes tower backup lasts about 8 hours".
- **Reach_Channel**: The outreach channel for a tract-hour: `sms` or `door_knock`.
- **Supported_Language**: English (`en`), Portuguese (`pt`) or Spanish (`es`).
- **CO_Safety_Line**: The carbon monoxide safety sentence: never run a generator, grill or stove indoors or in a garage; get fresh air and call 911 if dizzy or with a headache.
- **Help_Line**: The regional help line configured as `help_line` per region in the Languages_Config: 2-1-1 for the Cape (statewide Mass 211; MEMA directed residents there during the storm) and 311 for Boston.
- **Help_Line_Sentence**: The configured sentence, translated into each Supported_Language, that names 911 and the Help_Line for a region: Cape "911 for emergencies, 2-1-1 for shelters and help"; Boston "911 for emergencies, 311 for city help".
- **SMS_Check_In**: The resident SMS asking for a reply of 1 (OK) or 2 (need help).
- **Doorstep_Script**: The script a responder reads at the door in the household language.
- **AM_Radio_Script**: The roughly 30-second script for the county AM station, rendered from one fixed template per Supported_Language and filled per Cape_Town-hour.
- **Door_Knock_List**: The list of Synthetic_Households in a tract routed to Synthetic_Responders when phones are degraded.
- **Access_Hazard_Note**: The text "Downed wires reported nearby. Treat every wire as live." added to a Door_Knock_List entry.
- **Briefing**: An operator-facing summary with a headline, 2 to 4 claims (each with `text`, `field`, `value`) and one recommended action.
- **Verified_Briefing**: A Briefing generated by the Anthropic API that passed the Verifier.
- **Template_Briefing**: A deterministic Briefing built from tract-hour metrics without an LLM.
- **Key_Demo_Hours**: The Hours listed under `key_demo_hours` in the Scoring_Config, for which Verified_Briefings are generated. Values: 2026-02-23T09:00, 2026-02-23T17:00, 2026-02-24T09:00, 2026-02-25T15:00 and 2026-02-26T13:00 (2026-02-23T17:00 replaced the initial 2026-02-23T14:00 after the first No_LLM_Run, using the Key_Demo_Hour channel report of Requirement 11).
- **No_LLM_Run**: An execution of `python -m pipeline.run --no-llm`, which makes no Anthropic API calls.
- **Resident_Template**: A hand-written text template, one per message type and Supported_Language, for the SMS_Check_In, reply confirmation, re-prompt, Doorstep_Script or AM_Radio_Script.
- **Synthetic_Household**: A generated household record with `synthetic: true`, a point inside a Cape_Tract and one Supported_Language.
- **Synthetic_Responder**: A generated responder record with `synthetic: true` and a role label such as "Falmouth COA driver (Simulated)".
- **Check_In_Run**: One send of SMS_Check_Ins to all Synthetic_Households of one tract at one Hour, with its replies and statuses.
- **Escalation**: A need-help record for one Synthetic_Household, assigned to a Synthetic_Responder.
- **Reply_Timeout**: The number of seconds in `DEMO_REPLY_TIMEOUT_SECONDS`.
- **SMS_Mode**: The `SMS_MODE` environment variable, `simulator` (default) or `twilio`.
- **Masked_Phone_Number**: A phone number shown with all but the last four digits hidden, in the form `+1 *** *** 1234`.
- **Banned_Terms**: The configured list of blaming terms, including "neglected", "ignored" and "abandoned", with Portuguese and Spanish equivalents.

## Requirements

### Requirement 1: Offline, re-runnable pipeline

**User Story:** As the solo builder, I want an offline pipeline that precomputes every demo output, so that the demo runs with no network or LLM dependency.

#### Acceptance Criteria

1. WHEN `python -m pipeline.run` is executed, THE Pipeline SHALL write derived outputs only to `data/processed/` and fetch caches only to `data/raw/cache/`.
2. THE Pipeline SHALL leave every pre-existing file under `data/raw/` unmodified.
3. WHEN a network fetch (ACS, emPOWER_ZIP_Layer, TIGER 2020 tracts, TIGER 2020 county subdivisions, Boston 311) has a cached raw response under `data/raw/cache/`, THE Pipeline SHALL use the cached response and skip the fetch.
4. WHEN the Pipeline is executed again with unchanged inputs and caches, THE Pipeline SHALL produce the same `data/processed/` outputs, reusing the cached Anthropic API Briefing responses of Requirement 11.
5. THE Pipeline SHALL store geometry outputs in EPSG:4326 and compute areas, centroids and area-weighted overlays in EPSG:26986.
6. THE Pipeline SHALL write every timestamp in America/New_York local time in ISO 8601 format.
7. WHEN fetching ACS 5-year data, THE Pipeline SHALL use the newest vintage that responds and fall back one vintage year when the newest vintage fails.
8. THE Pipeline SHALL read every scoring weight, cap and threshold from the Scoring_Config.
9. THE Pipeline SHALL read the Eversource_Workbook in read-only mode using stored cell values rather than formulas.
10. THE Pipeline SHALL write outputs directly to `data/processed/`, with no staging directory.
11. WHEN the Pipeline has written every output, THE Pipeline SHALL run the Privacy_Guard over every file under `data/processed/`.
12. IF the Privacy_Guard reports a finding, THEN THE Pipeline SHALL report each file path, line number and match type without the matched value and exit with a non-zero status.

### Requirement 2: Need layer (Cape)

**User Story:** As an emergency manager, I want a Need score per Cape tract, so that I can see where residents are most likely to need help.

#### Acceptance Criteria

1. THE Pipeline SHALL compute the six Need_Indicators for every Cape_Tract.
2. THE Pipeline SHALL compute each Need_Indicator Percentile_Rank for a Cape_Tract among Cape_Tracts only.
3. THE Pipeline SHALL compute need_t as the mean of the available Need_Indicator Percentile_Ranks of tract t.
4. IF a Need_Indicator value is missing for a tract, THEN THE Pipeline SHALL compute need_t from the remaining Need_Indicators and record the missing indicator names for the Why_Flagged_Panel.
5. THE Pipeline SHALL read `Zip_Code`, `COUNTY`, `Power_Dependent_Devices_DME` and `Medicare_Benes` from the emPOWER_ZIP_Layer and allocate the ZIP counts to tracts by area-weighted overlay of the ZIP polygons included in that layer.
6. WHEN an HHS emPOWER ZIP count is reported as 11, THE Pipeline SHALL use the value 11 as reported and mark the ZIP as masked.
7. THE Methods_Doc SHALL state the ZIP-to-tract area-weight simplification and the emPOWER masking rule (counts of 1 to 10 reported as 11).
8. THE Methods_Doc SHALL fit on one page.

### Requirement 3: Cape towns and customer counts

**User Story:** As an emergency manager, I want each Cape tract tied to a town with a customer count, so that town outage shares are comparable.

#### Acceptance Criteria

1. THE Pipeline SHALL keep only Anchors whose county is Barnstable and discard rows for Plymouth, Scituate, Nantucket, Oak Bluffs and Edgartown.
2. THE Pipeline SHALL derive each Cape_Town customer count from the 2026-02-23T12:30 "MEMA via Patch" Anchor as `customers_out / (pct_out / 100)`.
3. IF a Cape_Town has no Anchor with both `customers_out` and `pct_out` (Sandwich and Chatham), THEN THE Pipeline SHALL use the town's ACS housing-unit count as the customer count and label the count "Estimated from ACS housing units."
4. THE Pipeline SHALL assign each Cape_Tract to the Cape_Town whose Cape_Town_Boundary contains the tract centroid.
5. IF a Cape_Tract centroid lies outside every Cape_Town_Boundary, THEN THE Pipeline SHALL assign the Cape_Tract to the Cape_Town with the nearest Cape_Town_Boundary.

### Requirement 4: Town outage curve reconstruction

**User Story:** As an emergency manager, I want an hourly outage share for every Cape town, so that I can see who was dark and for how long.

#### Acceptance Criteria

1. THE Pipeline SHALL produce out_pct(T,h) in [0, 1] for each of the 15 Cape_Towns at each of the 119 Hours of the Demo_Window.
2. THE Pipeline SHALL build the Tab_3_Curve as the running sum of `Customers Outages` minus `Customers Restored` over the Tab 3 Hours, parsing each Hour from the `Date` column and the `Time` label (`12AM` to `11PM`).
3. IF the Tab_3_Curve maximum is not 269,063 at Hour 2026-02-23T08:00, THEN THE Pipeline SHALL stop with an error that reports the computed maximum and its Hour.
4. THE Pipeline SHALL build the Cape_Total_Curve from `cape_total_outage_timeline.csv` rows with scope `cape_eversource` only, and shape the curve between and beyond those rows with the Tab_3_Curve.
5. THE Pipeline SHALL set out_pct(T,h) at every Pinned_Town_Hour to the Anchor value and exclude every Pinned_Town_Hour from scaling.
6. WHEN an Anchor has `pct_is_lower_bound = true`, THE Pipeline SHALL treat the Anchor `pct_out` as the minimum out_pct for that town-hour.
7. WHEN a Cape_Town has two or more Anchors, THE Pipeline SHALL interpolate the town's out_pct between consecutive Anchors.
8. WHEN a Cape_Town has two or more Anchors, THE Pipeline SHALL set the town's out_pct before the first Anchor and after the last Anchor to follow the Cape_Total_Curve shape through the nearest Anchor.
9. WHEN a Cape_Town has exactly one Anchor, THE Pipeline SHALL set the town's out_pct at each Hour to follow the Cape_Total_Curve shape through that Anchor, as the Anchor out_pct multiplied by the Cape_Total_Curve value at the Hour divided by the Cape_Total_Curve value at the Anchor Hour.
10. IF a Cape_Town has no Anchors (Chatham), THEN THE Pipeline SHALL assign the town the Cape-wide out share (Cape_Total_Curve divided by total Cape customers) as the town's unscaled out_pct at each Hour and record in `sources.json` that the town has no Anchors.
11. THE Pipeline SHALL scale only the customers-out values of town-hours that are not Pinned_Town_Hours, so that the sum across the 15 Cape_Towns at each Hour equals the Cape_Total_Curve value for that Hour, with every out_pct within [0, 1] and at or above any lower-bound Anchor for that town-hour.
12. IF the Cape_Total_Curve value at an Hour cannot be matched with every Pinned_Town_Hour held at its Anchor value and every out_pct within [0, 1], THEN THE Pipeline SHALL keep the Anchor values, clip the scaled values to [0, 1], and record the Hour and the unmatched customer count in `sources.json`.
13. WHEN an Anchor has a `customers_out` value and a blank `pct_out`, THE Pipeline SHALL convert `customers_out` to out_pct using the Cape_Town customer count.
14. WHEN an Anchor has a `pct_out` value and a blank `customers_out`, THE Pipeline SHALL use the Anchor `pct_out` directly.
15. THE Pipeline SHALL exclude the 133,000 customers-out figure from county situation report #009 (2026-02-26) from every computation and output.
16. THE Pipeline SHALL attach the provenance label "Reconstructed from MEMA, Eversource and public-safety reports." to every out_pct and hours_dark value in `data/processed/`.

### Requirement 5: Downed wires

**User Story:** As an emergency manager, I want downed-wire pressure per town, so that I can see access hazards and blocked-road risk.

#### Acceptance Criteria

1. THE Pipeline SHALL count each Tab_5_Call as one urgent downed-wire call, using column C as the town and column E as the received timestamp.
2. THE Pipeline SHALL match each Tab_5_Call town to a Cape_Town only when the whole town name equals the Cape_Town name, ignoring letter case.
3. IF a Tab_5_Call town is not a Cape_Town, THEN THE Pipeline SHALL exclude the call from the wires computation, report the town name and its call count in `sources.json`, and continue the run.
4. THE Pipeline SHALL aggregate Cape_Town Tab_5_Calls into counts per Cape_Town per Hour by received timestamp.
5. THE Pipeline SHALL compute the raw wires rate for Cape_Town T at Hour h as the calls received in T before the end of Hour h per 1,000 customers of T.
6. THE Pipeline SHALL compute wires(T,h) as the Percentile_Rank of the raw wires rate across the 15 Cape_Towns at Hour h.
7. THE Pipeline SHALL write downed-wire data to `data/processed/` only as town-hour aggregates, with no street addresses and no call-level rows.

### Requirement 6: Telecom flag

**User Story:** As an emergency manager, I want a phones-degraded flag per town and hour, so that outreach uses a channel that can reach people.

#### Acceptance Criteria

1. WHEN an Observed_Telecom_Event with `drives_reach_flag = true` is an Active_Event for Cape_Town T at Hour h, THE Pipeline SHALL set telecom(T,h) to 1 and record the rule "observed" with the event source citation.
2. WHEN the Modeled_Telecom_Rule holds for Cape_Town T at Hour h using only Hours inside the Demo_Window, THE Pipeline SHALL set telecom(T,h) to 1 and record the rule "modeled" with the label "Modeled: assumes tower backup lasts about 8 hours".
3. WHEN neither the observed rule nor the Modeled_Telecom_Rule holds for Cape_Town T at Hour h, THE Pipeline SHALL set telecom(T,h) to 0.
4. THE Pipeline SHALL record for each town-hour which telecom rule held: observed, modeled, both or none.
5. THE Pipeline SHALL split each Observed_Telecom_Event `town_or_area` value on ";", trim each part, and match a part to a Cape_Town only when the whole part equals the Cape_Town name, ignoring letter case.
6. IF an Observed_Telecom_Event part does not equal a Cape_Town name as a whole string (for example "Cape-wide", "Outer Cape", "Barnstable County MACC" or "Barnstable County Sheriff dispatch"), THEN THE Pipeline SHALL match the part to no Cape_Town, including by substring, leave telecom unchanged for every Cape_Town, and keep the event as a map pin and briefing context only.
7. IF an Observed_Telecom_Event with `drives_reach_flag = true` has a blank `end_local`, THEN THE Pipeline SHALL end the event `telecom_observed_default_hours` after `start_local` and label the duration as an assumption.
8. THE Scoring_Config SHALL define `telecom_observed_default_hours` as a positive integer.
9. THE Pipeline SHALL export every Observed_Telecom_Event to `telecom_events.json` with system, status, affects, start_local, end_local, source_name and source_url, regardless of `drives_reach_flag`.

### Requirement 7: Lifelines and priority scoring

**User Story:** As an emergency manager, I want one transparent priority score per tract and hour, so that I can rank where to reach out first.

#### Acceptance Criteria

1. THE Pipeline SHALL compute hours_dark(T,h) as h minus the first Hour of the Demo_Window at which out_pct(T) is at or above `dark_threshold`, in hours, capped at `hours_dark_cap`.
2. WHEN out_pct(T,h) is below `dark_threshold`, THE Pipeline SHALL set hours_dark(T,h) to 0.
3. THE Pipeline SHALL compute lifelines(T,h) as `0.4*out_pct + 0.3*min(hours_dark/72, 1) + 0.1*wires + 0.2*telecom`, taking the weights from `lifelines_weights` and the cap of 72 from `hours_dark_cap` in the Scoring_Config.
4. THE Pipeline SHALL compute priority_Cape(t,h) as need_t multiplied by lifelines(town(t),h), where each Cape_Tract inherits the lifelines values of the Cape_Town assigned in Requirement 3.
5. THE Pipeline SHALL produce lifelines(T,h) and priority_Cape(t,h) values within [0, 1] for every town-hour and tract-hour.
6. IF the `lifelines_weights` in the Scoring_Config do not sum to 1, THEN THE Pipeline SHALL stop with an error that names the configured weights.
7. THE Pipeline SHALL build the Priority_Queue for each Hour as the top `queue_size` Cape_Tracts by priority_Cape, breaking ties by higher need_t and then by ascending GEOID.
8. THE Pipeline SHALL export out_pct, hours_dark, wires, telecom, telecom rule, each weight, each weighted contribution, lifelines and priority_Cape for every Cape tract-hour to `cape_timeline.json`.

### Requirement 8: Map with hourly time slider

**User Story:** As an emergency manager, I want a Cape map with an hourly time slider, so that I can replay how need and lost lifelines changed during the storm.

#### Acceptance Criteria

1. THE Map_View SHALL render Cape_Tracts as a choropleth with the layers Priority (default), Need and Lost lifelines at the selected Hour.
2. THE Time_Slider SHALL offer each of the 119 Hours of the Demo_Window and display the selected Hour in local time.
3. WHEN the Operator changes the selected Hour, THE Web_App SHALL update the Map_View, Priority_Queue, Tract_Drawer and Reach_Panel to that Hour within 1 second.
4. THE Map_View SHALL show Cape_Town_Boundaries and one pin per Observed_Telecom_Event, placed at the Cape_Town matched under Requirement 6 or at a labeled Cape-wide marker for areas that match no Cape_Town.
5. WHEN the Operator selects a telecom pin, THE Map_View SHALL show the event system, status, affects, start time and source citation.
6. WHEN the Operator hovers over or focuses a Cape_Tract, THE Map_View SHALL show the active layer value as text.
7. IF basemap tiles fail to load, THEN THE Map_View SHALL render tract polygons on a plain background.
8. THE Web_App SHALL show source badges with the provenance labels from Requirements 3, 4 and 6 for the layers on screen.

### Requirement 9: Ranked priority queue

**User Story:** As an emergency manager, I want a ranked queue with reasons, so that I can decide where to act first and explain why.

#### Acceptance Criteria

1. THE Priority_Queue SHALL list the ranked Cape_Tracts for the selected Hour in rank order.
2. THE Priority_Queue SHALL show in each row the Cape_Town name, tract identifier, priority_Cape value as a number, Reach_Channel and two Why_Chips.
3. THE Pipeline SHALL build each Why_Chip from one value in the tract-hour metrics and record the metric field the value came from.
4. WHEN the Operator activates a Priority_Queue row, THE Web_App SHALL open the Tract_Drawer for that Cape_Tract at the selected Hour.
5. WHEN the Operator selects a Cape_Tract on the Map_View, THE Web_App SHALL open the Tract_Drawer for that Cape_Tract at the selected Hour.

### Requirement 10: Tract drawer and why-flagged panel

**User Story:** As an emergency manager, I want every scoring component for a tract in one place, so that I can trust and explain each flag.

#### Acceptance Criteria

1. THE Why_Flagged_Panel SHALL display need_t, each Need_Indicator raw value and Percentile_Rank, and the names of missing Need_Indicators.
2. THE Why_Flagged_Panel SHALL display out_pct, hours_dark, wires, telecom, each weight from the Scoring_Config, each weighted contribution, lifelines and priority_Cape for the selected tract-hour.
3. THE Why_Flagged_Panel SHALL display which telecom rule held, with the "Modeled" label for the Modeled_Telecom_Rule and the source citation for an observed event.
4. THE Tract_Drawer SHALL display the Briefing for the selected tract-hour labeled "Verified" for a Verified_Briefing or "Template" for a Template_Briefing.
5. THE Tract_Drawer SHALL display the Observed_Telecom_Events that are Active_Events for the tract's Cape_Town or for Cape-wide areas at the selected Hour, each with a source citation.
6. THE Tract_Drawer SHALL display the Reach_Panel, the check-in counters (sent, OK, need help, silent) and the Escalation list for the Cape_Tract.

### Requirement 11: Briefings and verifier

**User Story:** As an emergency manager, I want briefings whose numbers are checked against the data, so that I can rely on every claim.

#### Acceptance Criteria

1. THE Pipeline SHALL produce every Briefing with one headline, 2 to 4 claims (each with `text`, `field` and `value`) and one recommended action.
2. WHERE `ANTHROPIC_API_KEY` is set, THE Pipeline SHALL request a Briefing from the Anthropic API model `claude-opus-5-5` for each Priority_Queue Cape_Tract at each Key_Demo_Hour read from `key_demo_hours` in the Scoring_Config, supplying only that tract-hour metrics.
3. THE Pipeline SHALL produce a Template_Briefing for every Cape tract-hour without a Verified_Briefing.
4. THE Verifier SHALL reject a claim whose `field` is absent from the tract-hour metrics or whose `value` differs from the metric value by more than the configured verifier tolerance.
5. WHEN the Verifier rejects an Anthropic API Briefing, THE Pipeline SHALL request one regenerated Briefing.
6. IF the Verifier rejects the regenerated Briefing, THEN THE Pipeline SHALL store the Template_Briefing for that tract-hour.
7. IF `ANTHROPIC_API_KEY` is missing or an Anthropic API call fails, THEN THE Pipeline SHALL store the Template_Briefing for that tract-hour.
8. THE Pipeline SHALL set the Briefing recommended action to "Send SMS check-ins" when the Reach_Channel is `sms` and to "Send door-knock list to responders" when the Reach_Channel is `door_knock`, each followed by "Air the AM radio script".
9. THE Verifier SHALL check every Briefing in the Content_Cache, including Template_Briefings, and record pass, regenerated and fallback counts in `verifier_log.json`.
10. THE API SHALL serve Briefings and outreach text exclusively from the Content_Cache.
11. THE Pipeline SHALL send each Anthropic API Briefing request with `output_config` effort "low", structured outputs for the Briefing JSON, `max_tokens` 4000 and no `temperature` parameter.
12. IF an Anthropic API response has `stop_reason` "refusal" or "max_tokens", THEN THE Pipeline SHALL store the Template_Briefing for that tract-hour.
13. THE Pipeline SHALL cache each Anthropic API Briefing response in `data/processed/` and reuse the cached response when the Pipeline is executed again with unchanged tract-hour metrics.
14. THE Pipeline SHALL use the Anthropic API only for Briefings at Key_Demo_Hours.
15. WHEN a No_LLM_Run is executed, THE Pipeline SHALL make no Anthropic API calls and store Template_Briefings for every Cape tract-hour without a cached Verified_Briefing.
16. WHEN the Pipeline has built the Priority_Queues, THE Pipeline SHALL report for each Key_Demo_Hour the count of `sms` Cape_Tracts and the count of `door_knock` Cape_Tracts in the Priority_Queue, with the Cape_Towns of each group.
17. THE Scoring_Config `key_demo_hours` SHALL include at least one Hour whose Priority_Queue contains both an `sms` Cape_Tract and a `door_knock` Cape_Tract.
18. THE Pipeline SHALL run the Anthropic API Briefing step only after the Key_Demo_Hour channel report of criterion 16.
19. IF no Key_Demo_Hour Priority_Queue contains both an `sms` Cape_Tract and a `door_knock` Cape_Tract, THEN THE Pipeline SHALL skip the Anthropic API Briefing step and report that `key_demo_hours` needs adjustment.

### Requirement 12: Reach channel choice

**User Story:** As an emergency manager, I want the outreach channel chosen from the phones-degraded flag, so that SMS goes only where phones are likely working.

#### Acceptance Criteria

1. WHEN telecom(town(t),h) is 0, THE Pipeline SHALL set the Reach_Channel for tract-hour (t,h) to `sms`.
2. WHEN telecom(town(t),h) is 1, THE Pipeline SHALL set the Reach_Channel for tract-hour (t,h) to `door_knock`.
3. THE Pipeline SHALL attach an AM_Radio_Script to every tract-hour in the Priority_Queue.
4. THE Reach_Panel SHALL display the Reach_Channel, the telecom rule behind the channel, and a preview of the channel content with a language switcher for the three Supported_Languages.
5. WHILE the Reach_Channel for the selected tract-hour is `sms`, THE Reach_Panel SHALL offer a "Send check-ins" control.
6. WHILE the Reach_Channel for the selected tract-hour is `door_knock`, THE Reach_Panel SHALL display the Door_Knock_List in place of the "Send check-ins" control.
7. THE Reach_Panel SHALL display the AM_Radio_Script for the tract's Cape_Town at the selected Hour, labeled for the county AM station.

### Requirement 13: Shared outreach content rules

**User Story:** As a resident, I want short, calm messages in my language that put safety first, so that I know what to do and how to reach a person.

#### Acceptance Criteria

1. THE Pipeline SHALL produce every SMS_Check_In, Doorstep_Script and AM_Radio_Script in each of the three Supported_Languages.
2. THE Pipeline SHALL render every SMS_Check_In, reply confirmation, re-prompt, Doorstep_Script and AM_Radio_Script from the Resident_Template for its message type and Supported_Language, fill town names and metric values from the tract-hour or town-hour metrics, and store the rendered text in the Content_Cache.
3. THE Pipeline SHALL place the CO_Safety_Line first in every SMS_Check_In, Doorstep_Script, reply confirmation and re-prompt, and directly after the situation sentence in every AM_Radio_Script.
4. THE Pipeline SHALL include 911 for emergencies and the Help_Line_Sentence for the message region in every resident-facing message.
5. (Optional) WHERE back-translation checks are built, THE Pipeline SHALL record in the Content_Cache, for each Portuguese and Spanish text, an English back-translation and the result of comparing the back-translation's intent with the English version.
6. THE Pipeline SHALL write resident-facing text with no exclamation points, no acronyms other than 911, 2-1-1 and 311, and no promised response times.
7. THE Pipeline SHALL limit each sentence of English resident-facing text to 20 words or fewer.
8. THE Verifier SHALL reject every rendered resident-facing text that lacks 911 or the Help_Line configured for the message region.
9. IF the Verifier rejects a rendered Resident_Template text, THEN THE Pipeline SHALL stop with an error naming the message type, the Supported_Language and the Cape_Town.

### Requirement 14: SMS check-in message

**User Story:** As a resident with a basic phone, I want a check-in text that fits in two segments, so that the message arrives whole.

#### Acceptance Criteria

1. THE Pipeline SHALL order each SMS_Check_In as the CO_Safety_Line, then "Reply 1 if OK, 2 if you need help." in the household language, then the Help_Line_Sentence for the region.
2. THE Pipeline SHALL count SMS segments with GSM-7 encoding (160 characters for one segment, 153 per segment otherwise, extension characters counted as 2) when every character is in the GSM-7 set, and with UCS-2 encoding (70 characters for one segment, 67 per segment otherwise) when any character is outside the GSM-7 set.
3. THE Pipeline SHALL keep every SMS_Check_In, reply confirmation and re-prompt within 2 segments for every Cape_Town name substituted into the text.
4. IF a rendered Resident_Template SMS_Check_In, reply confirmation or re-prompt exceeds 2 segments, THEN THE Pipeline SHALL stop with an error naming the message type, the Supported_Language and the Cape_Town.
5. THE Pipeline SHALL write every Portuguese and Spanish SMS_Check_In, reply confirmation and re-prompt body without accented characters, so that the body stays in GSM-7 (for example "fogareiro", "tontura ou mal-estar").
6. THE Pipeline SHALL keep accented characters in Portuguese and Spanish Doorstep_Script and AM_Radio_Script text.
7. THE Web_App SHALL keep accented characters in Portuguese and Spanish UI text.
8. THE Phone_Simulator SHALL show the "Simulated" label and the sender name outside the message body.

### Requirement 15: Door-knock list

**User Story:** As a responder, I want a door-knock list with language and hazards, so that I can check on households when phones are down.

#### Acceptance Criteria

1. WHILE the Reach_Channel for tract-hour (t,h) is `door_knock`, THE API SHALL provide one Door_Knock_List entry for each Synthetic_Household in Cape_Tract t.
2. THE API SHALL include in each Door_Knock_List entry the "Simulated household #N" label, the household Supported_Language, the tract-level Why_Chips, the assigned Synthetic_Responder role label and the Doorstep_Script in the household language.
3. WHEN wires(town(t),h) is at or above `access_hazard_wires_pct`, THE API SHALL add the Access_Hazard_Note to each Door_Knock_List entry for tract-hour (t,h).
4. THE Pipeline SHALL order each Doorstep_Script as the CO_Safety_Line, then "Are you OK? Do you need help?" in the household language, then the Help_Line_Sentence for the region.
5. THE Pipeline SHALL assign Door_Knock_List entries only to Synthetic_Responder types listed for the tract's Cape_Town in `config/responders.yaml`, drawn from police or fire wellness checks, Council on Aging, Elder Services and Meals on Wheels drivers.
6. IF a check-in send is requested for a tract-hour whose Reach_Channel is `door_knock`, THEN THE API SHALL reject the request with an error and send no SMS.

### Requirement 16: AM radio script

**User Story:** As a county emergency manager, I want a ready-to-read AM radio script for each priority area, so that residents without phones still hear how to get help.

#### Acceptance Criteria

1. THE Pipeline SHALL produce an AM_Radio_Script in each Supported_Language for every Cape_Town-hour that has at least one Cape_Tract in the Priority_Queue, by filling the fixed AM_Radio_Script Resident_Template for that Supported_Language with that Cape_Town-hour metrics.
2. THE Pipeline SHALL order each AM_Radio_Script as a descriptive statement of what is happening that names Cape_Towns and no tracts, the CO_Safety_Line, a request to check on neighbors who live alone, how to get help with the Help_Line_Sentence for the region, and when the next update airs.
3. THE Pipeline SHALL include in each AM_Radio_Script only numbers present in that Cape_Town-hour metrics, apart from 911, the Help_Line and the next-update time.

### Requirement 17: Synthetic households and responders

**User Story:** As the solo builder, I want clearly labeled synthetic households and responders, so that the demo shows the loop without any real resident data.

#### Acceptance Criteria

1. THE Pipeline SHALL generate the configured number of Synthetic_Households for every Cape_Tract that appears in the Priority_Queue at any Hour of the Demo_Window.
2. THE Pipeline SHALL place each Synthetic_Household at a generated point inside its Cape_Tract polygon and label the household "Simulated household #N" with no street address.
3. THE Pipeline SHALL sample each Synthetic_Household language from the `by_town` language mix in the Languages_Config for the tract's Cape_Town.
4. THE Languages_Config SHALL set the `by_town` mix for Barnstable and for Yarmouth to en 0.6, pt 0.3 and es 0.1, labeled as an assumption.
5. THE Pipeline SHALL assign the Supported_Language `pt` to Synthetic_Household #1 in every Barnstable and Yarmouth Cape_Tract that has Synthetic_Households.
6. THE Pipeline SHALL generate Synthetic_Households and Synthetic_Responders from a fixed random seed so that repeated runs produce the same records.
7. THE Pipeline SHALL generate Synthetic_Responders with role labels only, in the form "<Cape_Town> <role> (Simulated)".
8. THE Pipeline SHALL set `synthetic: true` on every Synthetic_Household and Synthetic_Responder record.
9. THE API SHALL set `synthetic: true` on every Check_In_Run, reply, Escalation and Door_Knock_List entry.
10. THE Web_App SHALL display the label "Simulated" on every synthetic record wherever the record appears, including the Map_View, Priority_Queue, Tract_Drawer, Reach_Panel, Phone_Simulator and Door_Knock_List.

### Requirement 18: Check-in run on the phone simulator

**User Story:** As an emergency manager, I want to send check-ins and watch replies arrive, so that I can show silence turning into a question a human follows up.

#### Acceptance Criteria

1. WHEN the Operator activates "Send check-ins" for a tract-hour whose Reach_Channel is `sms`, THE API SHALL create a Check_In_Run and send the SMS_Check_In in each household language to every Synthetic_Household in the Cape_Tract.
2. WHILE SMS_Mode is unset or holds any value other than `twilio`, THE API SHALL deliver every SMS_Check_In, reply confirmation and re-prompt through the Phone_Simulator.
3. WHERE the Twilio block of Requirement 22 is not built, THE API SHALL deliver every message through the Phone_Simulator for every SMS_Mode value.
4. THE Phone_Simulator SHALL display the outbound messages and replies for the selected Synthetic_Household and accept a typed reply from the Operator.
5. WHEN the Operator submits a reply in the Phone_Simulator, THE API SHALL process the reply as defined in Requirement 19.
6. THE API SHALL generate replies for Synthetic_Households not driven by the Operator from configured reply probabilities and a fixed random seed, and label each generated reply "Simulated".
7. WHILE a Check_In_Run is active, THE Web_App SHALL poll the API for run state every 2 seconds.
8. WHEN every Synthetic_Household in a Check_In_Run has a final status of OK, need help or silent, THE Web_App SHALL stop polling for that Check_In_Run.
9. THE Tract_Drawer SHALL display the sent, OK, need help and silent counters for the Cape_Tract and refresh the counters on each poll.
10. THE API SHALL hold Check_In_Run, reply and Escalation state in memory.

### Requirement 19: Reply parsing and escalation

**User Story:** As a resident, I want my reply understood whether I type a number or a word in my language, so that a person is sent when I ask for help.

#### Acceptance Criteria

1. THE API SHALL normalize each reply body by trimming whitespace, ignoring letter case and removing accents before classification.
2. WHEN a normalized reply equals "1" or an OK keyword from `config/languages.yaml` for any Supported_Language (en OK, YES; pt OK, SIM; es OK, SI), THE API SHALL classify the reply as OK.
3. WHEN a normalized reply equals "2" or a help keyword from `config/languages.yaml` for any Supported_Language (en HELP; pt AJUDA; es AYUDA), THE API SHALL classify the reply as need help.
4. WHEN a reply is classified as need help, THE API SHALL create an Escalation assigned to a Synthetic_Responder for the household's Cape_Town.
5. WHEN an Escalation is created, THE API SHALL send the household a short confirmation in the household language that repeats 911.
6. IF a reply matches neither class, THEN THE API SHALL send one short re-prompt in the household language and create no Escalation.
7. IF a Synthetic_Household sends a second unrecognized reply in the same Check_In_Run, THEN THE API SHALL record the reply and send no further re-prompt.
8. THE Tract_Drawer SHALL list each Escalation with the "Simulated household #N" label, household language, time created and assigned Synthetic_Responder role label.

### Requirement 20: Silence on timeout

**User Story:** As an emergency manager, I want silence counted only when phones are likely working, so that a dead network is never mistaken for a quiet household.

#### Acceptance Criteria

1. WHILE telecom(town(t),h) is 0 for the Check_In_Run tract-hour, WHEN a Synthetic_Household has not replied within Reply_Timeout seconds of the send, THE API SHALL mark the household silent and increment the silent counter.
2. WHILE telecom(town(t),h) is 1 for a tract-hour, THE API SHALL keep each Synthetic_Household of that tract in the status "awaiting door knock" and record no silence.
3. THE Tract_Drawer SHALL list silent Synthetic_Households as needing human follow-up.
4. WHEN a Synthetic_Household marked silent sends a reply, THE API SHALL replace the silent status with the reply classification and update the counters.

### Requirement 21: Demo reset

**User Story:** As the presenter, I want a one-click reset, so that I can rerun the demo from a clean state.

#### Acceptance Criteria

1. WHEN the API receives `POST /api/demo/reset`, THE API SHALL clear every Check_In_Run, reply, Escalation and counter and restore the in-memory state present at API start within 1 second.
2. THE Web_App SHALL provide a labeled reset control that calls `POST /api/demo/reset` and refreshes the displayed state.

### Requirement 22: Twilio SMS (Optional)

**User Story:** As the presenter, I want real SMS to demo phones when Twilio works, so that the audience can see a real reply, with the simulator as the safe default.

#### Acceptance Criteria

1. WHERE the Twilio block is built and SMS_Mode is `twilio`, THE API SHALL send real SMS only to Synthetic_Households mapped to numbers in `DEMO_PHONE_NUMBERS` and deliver every other message through the Phone_Simulator.
2. WHERE the Twilio block is built and SMS_Mode is `twilio`, WHEN an inbound request reaches the SMS webhook, THE API SHALL validate the Twilio request signature and pass the `From` and `Body` fields to reply processing.
3. WHERE the Twilio block is built, IF Twilio signature validation fails, THEN THE API SHALL respond with HTTP 403 and record no reply.
4. WHERE the Twilio block is built, IF a Twilio send fails, THEN THE API SHALL deliver the message through the Phone_Simulator and log the failure with a Masked_Phone_Number.

### Requirement 23: Boston Voice static view (separate block, first to cut)

**User Story:** As a Boston emergency manager, I want to see which tracts went quieter than expected on 311 during the storm, so that I can check on high-need quiet blocks.

#### Acceptance Criteria

1. WHERE the Boston Voice block is built, THE Pipeline SHALL compute the Voice layer in a separate pipeline step that writes `boston_voice.geojson`.
2. WHERE the Boston Voice block is built, THE Pipeline SHALL compute the six Need_Indicators and need_t for every Boston_Tract only within the Boston Voice pipeline step, with each Need_Indicator Percentile_Rank computed among Boston_Tracts only and the missing-indicator and emPOWER rules of Requirement 2 applied.
3. WHERE the Boston Voice block is built, THE Pipeline SHALL union the 2026 legacy and NEW SYSTEM 311 files and keep only resident-originated channels listed in `config/channels.yaml`.
4. WHERE the Boston Voice block is built, THE Pipeline SHALL drop 311 records located at the default-coordinate pile-up near 42.3594, -71.0587.
5. WHERE the Boston Voice block is built, THE Pipeline SHALL use the storm window 2026-02-22T14:00 to 2026-02-25T23:59 and the baseline 2026-01-05 to 2026-03-31, excluding the storm week, about 2026-01-24 to 2026-01-27, 2026-02-07 to 2026-02-09, holidays, and any day whose citywide storm-type count exceeds 3 times the median daily count.
6. WHERE the Boston Voice block is built, THE Pipeline SHALL compute r_t, S, lambda_t, O_t, p_t, acute_t, ratio_t, rate_pc_t, structural_t and silence_t exactly as written in the scoring steering, with `k_pseudo_days`, `acute_cap` and `silence_weights` from the Scoring_Config.
7. WHERE the Boston Voice block is built, THE Pipeline SHALL compute priority_Boston as need_t multiplied by silence_t, within [0, 1], for every Boston_Tract.
8. WHERE the Boston Voice block is built, THE Pipeline SHALL retain only timestamp, case type, channel and coordinates from 311 records, and write 311 data to `data/processed/` only as tract-level aggregates.
9. WHERE the Boston Voice block is built, THE API SHALL serve `boston_voice.geojson` from a dedicated endpoint.
10. WHERE the Boston Voice block is built, THE Boston_Voice_View SHALL render a static Boston_Tract map with the layers Priority (default), Need, Acute silence and Structural silence, labeled with the storm window and with no time slider.
11. WHERE the Boston Voice block is built, THE Boston_Voice_View SHALL show for each Boston_Tract the observed and expected request counts as text, for example "Heard 9, expected 41".
12. IF `boston_voice.geojson` is absent, THEN THE Scale_Selector SHALL show Boston as a Configuration_Preview with no scores.

### Requirement 24: Town and hazard scale selector (6 static entries required; extended catalog Optional)

**User Story:** As a state or county emergency manager, I want to see how Lifeline would run for any Massachusetts town and hazard, so that I understand the product is not limited to the Cape.

#### Acceptance Criteria

1. THE Scale_Selector SHALL list 6 static entries from `scale_catalog.json`, built by the Pipeline from `config/hazards.yaml`: Cape blizzard, Boston blizzard, and one Massachusetts town entry each for the hazards nor'easter, ice storm, flood and heat.
2. THE Scale_Selector SHALL show each entry's tier: Tier 2 for towns with open 311 data (Boston) and Tier 1 for every other town.
3. WHEN the Operator selects the Cape blizzard entry, THE Web_App SHALL show the Cape Map_View with real data.
4. WHERE the Boston Voice block is built, WHEN the Operator selects the Boston blizzard entry, THE Web_App SHALL show the Boston_Voice_View.
5. WHEN the Operator selects any other entry, THE Scale_Selector SHALL show a Configuration_Preview listing the tier and the lost-lifelines inputs for the hazard (blizzard, nor'easter and ice storm: power, phones and blocked roads; flood: flood zones, gauges and road closures; heat: power plus heat index).
6. THE Pipeline SHALL include scores in `scale_catalog.json` only for the Cape blizzard entry and the Boston Voice entry.
7. (Optional) WHERE the extended scale catalog is built, THE Scale_Selector SHALL list further Massachusetts town and hazard combinations beyond the 6 static entries, each shown as a Configuration_Preview with no scores.

### Requirement 25: Aggregate-only real data and provenance

**User Story:** As a privacy reviewer, I want real resident data kept aggregate and every source labeled, so that no real person can be identified and every number is traceable.

#### Acceptance Criteria

1. THE Pipeline SHALL write real resident data to `data/processed/` only as tract-level ACS and emPOWER aggregates, town-level outage and downed-wire counts, and tract-level 311 counts.
2. THE Pipeline SHALL record in `sources.json` the source name and URL of every curated input row used in a computation.
3. THE Web_App SHALL show the label "Modeled: assumes tower backup lasts about 8 hours" wherever a modeled telecom value appears and the source citation wherever an observed telecom event appears.
4. THE Web_App SHALL show the label "Estimated from ACS housing units." wherever a Sandwich or Chatham customer count or out_pct appears.

### Requirement 26: Secrets and phone numbers

**User Story:** As a privacy reviewer, I want secrets and phone numbers kept out of the codebase, so that nothing sensitive leaks through the repository, logs or UI.

#### Acceptance Criteria

1. THE API SHALL read secrets and demo phone numbers only from environment variables loaded from `.env`.
2. THE Pipeline SHALL read secrets only from environment variables loaded from `.env`.
3. THE Repository SHALL ignore `.env` and contain `.env.example` with empty values for `ANTHROPIC_API_KEY`, `AWS_REGION`, `CENSUS_API_KEY`, `SMS_MODE`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `DEMO_PHONE_NUMBERS` and `DEMO_REPLY_TIMEOUT_SECONDS`.
4. THE API SHALL log every phone number as a Masked_Phone_Number.
5. THE Web_App SHALL display every phone number as a Masked_Phone_Number.
6. THE Test_Suite SHALL use only the reserved fictional numbers +1 617 555 0100 to +1 617 555 0199.
7. THE Pipeline SHALL write no phone number to `data/processed/`.

### Requirement 27: Descriptive language

**User Story:** As an emergency manager, I want descriptive, non-blaming language everywhere, so that briefings and messages are accurate and respectful.

#### Acceptance Criteria

1. THE Pipeline SHALL phrase every Briefing, Why_Chip and outreach text descriptively, stating observed or modeled conditions with no claims about why the conditions occurred.
2. IF a Briefing, Why_Chip or outreach text contains a Banned_Term, THEN THE Verifier SHALL reject the text.
3. IF the Verifier rejects rendered outreach or Why_Chip text for a Banned_Term, THEN THE Pipeline SHALL stop with an error naming the item, the Supported_Language and the Banned_Term.

### Requirement 28: Local API boundaries

**User Story:** As the solo builder, I want the API limited to local precomputed data, so that the demo is predictable and its exposure is clear.

#### Acceptance Criteria

1. THE API SHALL read data only from `data/processed/` and `config/`.
2. THE API SHALL allow cross-origin requests only from the local Vite origin.
3. THE README SHALL state that the API has no authentication and is intended for local demo use only.
4. THE Web_App SHALL request data only from the API at `VITE_API_BASE`, defaulting to `http://localhost:8000`.

### Requirement 29: Accessibility

**User Story:** As an emergency manager using a keyboard or assistive technology, I want every control reachable and readable, so that I can operate Lifeline without a mouse or color vision.

#### Acceptance Criteria

1. THE Web_App SHALL make every control, including the Time_Slider, Priority_Queue rows, Tract_Drawer, Reach_Panel, Phone_Simulator, reset control and Scale_Selector, reachable and operable by keyboard.
2. THE Web_App SHALL show a visible focus indicator on the focused control.
3. THE Web_App SHALL give every icon-only button an accessible text label.
4. THE Web_App SHALL accompany every color scale with values shown as text.
5. (Optional) WHERE the contrast audit is run, THE Web_App SHALL render text with a contrast ratio of at least 4.5:1 against the dark theme background.

### Requirement 30: Required property-based tests

**User Story:** As the solo builder, I want property-based tests on the core rules, so that scoring, channel choice, verification and SMS length hold for every input.

#### Acceptance Criteria

1. THE Test_Suite SHALL include a Hypothesis property test asserting that lifelines and priority_Cape stay within [0, 1] for any out_pct, wires and need_t in [0, 1], any hours_dark of 0 or more, any telecom in {0, 1}, and any `lifelines_weights` that sum to 1.
2. THE Test_Suite SHALL include a Hypothesis property test asserting that the Reach_Channel is `sms` when telecom is 0, `door_knock` when telecom is 1, and that every tract-hour in the Priority_Queue has an AM_Radio_Script.
3. THE Test_Suite SHALL include a Hypothesis property test asserting that the Verifier rejects every claim with a missing `field` or a `value` outside tolerance and accepts every claim whose `field` exists and whose `value` matches within tolerance.
4. THE Test_Suite SHALL include a Hypothesis property test asserting that the segment counter follows the GSM-7 and UCS-2 rules of Requirement 14 for generated text, and that every cached SMS_Check_In, reply confirmation and re-prompt is within 2 segments.
5. THE Test_Suite SHALL run to completion with `pytest -q` and `npx vitest --run`, with no watch mode.

### Requirement 31: Repository and Kiro tooling

**User Story:** As the solo builder, I want the repository, hooks and docs set up from the start, so that tests and privacy checks run as I work and reviewers can see how Kiro was used.

#### Acceptance Criteria

1. THE Repository SHALL be a git repository with a `.gitignore` that excludes `.env` and `data/raw/cache/`.
2. WHEN a file under `pipeline/` is saved, THE Property_Test_Hook SHALL run the four property-based tests of Requirement 30 criteria 1 to 4.
3. IF a property-based test fails, THEN THE Property_Test_Hook SHALL report the failing test name and the failing example.
4. WHEN a file under `api/` or `data/processed/` is saved, THE Privacy_Guard_Hook SHALL scan every file under `api/` and `data/processed/` for unmasked phone numbers and street addresses.
5. IF the Privacy_Guard_Hook finds an unmasked phone number or a street address, THEN THE Privacy_Guard_Hook SHALL exit with a non-zero status and report each file path, line number and match type, without printing the matched value.
6. THE Kiro_Usage_Doc SHALL describe the Kiro steering files, the lifeline-city spec and the Kiro hooks used to build the project.
7. THE README SHALL list the run steps in order: create the Python environment with `uv venv --python 3.13`, run the Pipeline with `python -m pipeline.run`, start the API, and start the Web_App.
