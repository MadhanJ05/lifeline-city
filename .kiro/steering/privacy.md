# Privacy and Data Guardrails

These rules are non-negotiable. If a task conflicts with them, stop and flag it.

## Real data is aggregate only

- Real resident data appears only as aggregates: tract-level ACS and emPOWER, town-level outage and downed-wire counts, tract-level 311 counts.
- Never create, store, or display individual-level real data: no real names, phone numbers, addresses, medical status, or 311 case details tied to a person.
- Boston 311: keep only fields needed to count resident-originated requests per tract (timestamp, case type, channel, coordinates for the tract join). Drop free text, addresses and case IDs from anything written to `data/processed/`.
- Eversource Tab 5 downed-wire calls: aggregate to town-hour counts. Do not export street addresses or call-level rows.
- HHS emPOWER: respect masking (counts of 1 to 10 are reported as 11). Never try to unmask. State the ZIP-to-tract area-weight simplification in `docs/methods.md`.

## Synthetic records

- Households, responders, check-ins, replies and door-knock lists are synthetic.
- Every synthetic record carries `synthetic: true`, and the UI labels it "Simulated" wherever it appears (map, queue, drawer, Reach panel, phone simulator, door-knock list).
- Synthetic addresses are generated points inside a tract, rendered as "Simulated household #N" with no street address that resolves to a real home.
- Responder names are role labels (for example "Falmouth COA driver (Simulated)"), never real people.

## Provenance labels

- Town outage curves: "Reconstructed from MEMA, Eversource and public-safety reports."
- Modeled telecom flag: "Modeled: assumes tower backup lasts about 8 hours" (distinct from observed telecom events, which cite their source).
- Town customer counts from the ACS housing-unit fallback (Sandwich, Chatham): "Estimated from ACS housing units."
- Do not use the 133,000 figure from county situation report #009 (Feb 26).

## Secrets and phone numbers

- Secrets live only in `.env` (gitignored). `.env.example` has empty values.
- Demo phone numbers live only in `DEMO_PHONE_NUMBERS` in `.env`. Never write a phone number to code, config, tests, fixtures, logs, `data/processed/`, or docs. Mask them in the UI and logs (`+1 *** *** 1234`).
- Tests use reserved fictional numbers (`+1 617 555 0100` to `+1 617 555 0199`).

## Language

- Descriptive, never causal or blaming: "quieter than expected", "dark for 40 hours", "phones likely degraded". Never "neglected", "ignored", "abandoned".
- Lifeline does not replace 911. Every resident message includes 911. Every escalation ends with a human.
