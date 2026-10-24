# Outreach Style

Applies to SMS check-ins, phone simulator messages, door-knock lists, AM radio scripts and operator briefings. All of it is pre-generated in the pipeline, cached in `data/processed/content.json`, and checked by tests. Resident outreach (SMS, doorstep, radio) uses hand-written templates in en, pt and es only, never LLM drafts. The LLM writes only operator briefings at `key_demo_hours`, checked by the verifier.

## Languages

- English (`en`), Portuguese (`pt`), Spanish (`es`). No others.
- Each synthetic household has one language, sampled from the tract mix in `config/languages.yaml`.
- Write each language natively, not word-for-word. Back-translate `pt` and `es` to English and check that intent matches the English version; record the result.

## Every resident-facing message

1. **Carbon monoxide safety first.** Never run a generator, grill or stove indoors or in a garage. Fresh air and 911 if dizzy or headache.
2. Then the ask or the information.
3. **Always include 911 and the regional help line** (`help_line` per region in `config/languages.yaml`). Cape: "911 for emergencies, 2-1-1 for shelters and help" (statewide Mass 211; MEMA directed residents there during the storm). Boston: "911 for emergencies, 311 for city help".

- Plain language, about grade 6. Short sentences. No jargon or acronyms other than 911, 2-1-1 and 311.
- Calm and respectful. No fear language, no blame, no exclamation points, no promised response times.
- Descriptive only ("power is out in parts of Falmouth"), never causal.
- Every message offers a path to a human.

## SMS check-in (phones working, `telecom = 0`)

- Order: CO safety line, then "Reply 1 if OK, 2 if you need help.", then 911 and the help line.
- **At most 2 SMS segments.** Count with the real encoding: GSM-7 is 160 chars single or 153 per segment (max 306); any character outside GSM-7 (for example a, o with tilde, or a, i, o, u with acute accents) switches to UCS-2 at 70 single or 67 per segment (max 134). **SMS bodies only** are written without accents in Portuguese and Spanish so they stay in GSM-7 (for example "fogareiro", "tontura ou mal-estar"). Doorstep scripts, radio scripts and UI text keep accents.
- The "Simulated" label and sender name are shown by the phone simulator UI, not inside the message body.

## Replies

- Accept `1` / `2` and words, case-insensitive, trimmed, accents optional: en `OK`, `YES`, `HELP`; pt `OK`, `SIM`, `AJUDA`; es `OK`, `SI`, `AYUDA`. Keywords live in `config/languages.yaml`.
- `2` or a help word creates an escalation routed to a human (simulated responder) and sends a short confirmation in the household language that repeats 911.
- Unrecognized reply: one short re-prompt, no escalation.
- No reply within `DEMO_REPLY_TIMEOUT_SECONDS` counts as "silent" **only when `telecom = 0`**. When `telecom = 1`, never send SMS and never infer silence from a missing reply.

## Door-knock list (phones degraded, `telecom = 1`)

- Routed to responders that actually exist on the Cape, all synthetic and labeled "Simulated": police/fire wellness checks, Council on Aging, Elder Services, Meals on Wheels drivers.
- Each entry: simulated household, language to use, the tract-level reasons it was flagged, and an **access hazard** note when the town downed-wire percentile is at or above the threshold in `config/scoring.yaml` ("Downed wires reported nearby. Treat every wire as live.").
- Doorstep script in the household language: CO safety, "Are you OK? Do you need help?", 911 and the help line.

## AM radio script (every priority area)

- For the county AM station (the after-action report found it was never used). One fixed template per language, filled per town-hour, about 30 seconds read aloud.
- Order: what is happening (descriptive, name towns not tracts), CO safety, check on neighbors who live alone, how to get help (911 and the help line), when the next update airs.
- Only use numbers present in the area metrics.

## Operator briefings (tract drawer)

- Audience is the emergency manager, not residents. Short headline, 2 to 4 claims, one recommended action that matches the Reach channel.
- Every number in a briefing must come from that tract-hour metrics and carry the field it came from. The verifier rejects any claim whose field is missing or whose value does not match within tolerance; regenerate once, then fall back to a template briefing.
- Same descriptive-language rule: "dark for 40 hours", "phones likely degraded", never "neglected".
