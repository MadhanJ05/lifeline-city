# Repo Structure

Repo root is this workspace. Module names have no numeric prefixes so tests can import them; `pipeline/run.py` fixes the order.

```
.kiro/
  steering/        product tech structure privacy outreach-style scoring
  specs/lifeline-city/  requirements.md design.md tasks.md
  hooks/
config/
  scoring.yaml     weights, caps, thresholds (scoring.md)
  languages.yaml   en, pt, es; reply keywords per language
  hazards.yaml     hazard -> lost-lifelines inputs (scale selector)
  responders.yaml  simulated responder types per Cape town
  channels.yaml    Boston 311 channel keep/drop list
  storm_types.yaml Boston 311 storm-type tags
data/
  raw/             inputs; code never edits files here (curated CSVs, Eversource, reports); fetched API caches go in data/raw/cache/ (gitignored)
  processed/       everything the API serves; pipeline is the only writer
    cape_tracts.geojson    tract geometry, town, Need + components
    cape_towns.geojson     town boundaries
    cape_timeline.json     town-hour lifelines components; tract-hour priority and channel
    telecom_events.json    observed telecom pins with sources
    boston_voice.geojson   static Voice view (Need, silence, priority per tract)
    content.json           cached verified briefings, SMS, door-knock notes, radio scripts
    households.json        synthetic households (synthetic: true)
    responders.json        synthetic responders (synthetic: true)
    scale_catalog.json     town/hazard selector entries
    sources.json           provenance labels and citations
    verifier_log.json      briefing verifier pass/fail record
pipeline/
  run.py common.py fetch.py need.py tracts_towns.py outage_curves.py wires.py
  telecom.py lifelines.py voice_boston.py synthetic.py content.py verifier.py
  scale_catalog.py export.py
api/
  main.py data.py state.py reach.py sms.py
collector/         live outage snapshots (docs/live-data.md)
  run.py sources.py geo.py
web/
  src/App.tsx src/api.ts src/types.ts
  src/components/  MapView TimeSlider Queue TractDrawer WhyFlagged ReachPanel
                   PhoneSimulator BostonVoiceView ScaleSelector SourceBadges
tests/
  pipeline/ api/ collector/
docs/
  methods.md kiro-usage.md live-data.md
.env.example
```

## Rules

- Pipeline reads `data/raw/` and `config/`, writes only `data/processed/`. API reads only `data/processed/` and `config/`. Web reads only the API.
- Collector writes only `data/live/` (gitignored) and appends there; nothing reads it yet.
- Shared helpers (percentile rank, hourly time grid, paths, provenance labels) live in `pipeline/common.py`. Do not duplicate them.
- Each `data/processed/` file has a matching TypeScript type in `web/src/types.ts` and a pydantic model in `api/data.py`.
- Tests mirror source paths: `pipeline/lifelines.py` -> `tests/pipeline/test_lifelines.py`.
