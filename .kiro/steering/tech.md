# Tech Stack

```
pipeline (Python)  ->  data/processed/*.json, *.geojson  ->  API (FastAPI)  ->  web (Vite + React + TS + MapLibre)
                                                            ^
                                     Twilio webhook (optional) | web polls the API
```

## Pipeline

- Python 3.13 via `uv` (`uv venv --python 3.13`; 3.11 is not installed). pandas, geopandas, shapely, numpy, scipy, requests, pyyaml, openpyxl (Eversource xlsx).
- Runs offline, before the demo. Reads `data/raw/`, writes directly to `data/processed/`, then runs the privacy guard and exits non-zero on findings. Every step is idempotent and re-runnable.
- Network fetches (ACS, HHS emPOWER, TIGER tracts, MA town boundaries, Boston 311) cache raw responses under `data/raw/cache/` (gitignored) and skip the fetch when the cache exists.
- CRS: store outputs in EPSG:4326. Compute areas, centroids and area-weighted overlays in EPSG:26986 (MA State Plane, meters).
- Time: all timestamps are `America/New_York` local, ISO 8601. Cape timeline is hourly from 2026-02-23T01:00 to 2026-02-27T23:00 inclusive (119 hours).
- Census: newest ACS 5-year vintage that responds, fall back one year. Barnstable County = state 25, county 001. Boston = Suffolk, state 25, county 025, clipped to the City of Boston boundary.
- Scoring weights and thresholds come from `config/scoring.yaml`, never hard-coded. Formulas are in `scoring.md` steering.
- LLM use is limited to operator briefings at `key_demo_hours`, generated in the pipeline with the Anthropic API: model `claude-opus-5-5`, no `temperature` parameter (rejected since 2026-10-21), `output_config` effort `low`, structured outputs for the briefing JSON, `max_tokens` 4000. A `stop_reason` of `refusal` or `max_tokens`, a failed call, a missing key, or a verifier rejection after one retry falls back to the template briefing. Resident outreach (SMS, doorstep, radio) uses hand-written templates only. Everything is cached to `data/processed/`; the demo never calls an LLM.

## API

- FastAPI + uvicorn. Serves precomputed files from `data/processed/` and holds check-in state in memory. `POST /api/demo/reset` restores a clean state.
- Live updates by **polling** (web polls every 2 s while a check-in run is active). No SSE, no websockets.
- SMS: phone simulator is the default channel. Twilio is optional behind `SMS_MODE=simulator|twilio`; if Twilio does not work within 20 minutes of trying, stay on the simulator.
- CORS limited to the local Vite origin. No auth (local demo only); note this in the README.

## Web

- Node 25 and npm 11 (installed). Vite + React 18 + TypeScript (strict) + Tailwind CSS + MapLibre GL JS. Recharts for sparklines and bars.
- Free dark basemap that needs no token. If tiles fail, render tract polygons on a plain background.
- Single page. Talks only to the local API (`VITE_API_BASE`, default `http://localhost:8000`).
- Accessible by default: keyboard-reachable controls, visible focus, labels on icon buttons, color scales that also show values as text, WCAG AA contrast on the dark theme.

## Testing

- Python: pytest + Hypothesis (property-based tests for scoring, curve reconstruction, channel choice, verifier, SMS length).
- Web: Vitest + fast-check for pure logic (formatting, queue sorting). Keep UI tests minimal.
- Never run watchers in automation. Use `pytest -q`, `vitest --run`, `npm run build`.

## Commands

```
python -m pipeline.run            # full pipeline -> data/processed/
pytest -q                         # pipeline + api tests
uvicorn api.main:app --port 8000  # API (run manually)
cd web && npm run dev             # web (run manually)
cd web && npx vitest --run && npm run build
```

## Dependencies and secrets

- Pin exact versions in `requirements.txt` and `web/package.json`. No new libraries without a reason.
- Secrets and demo phone numbers live only in `.env` (gitignored). Commit `.env.example` with empty values: `ANTHROPIC_API_KEY`, `AWS_REGION`, `CENSUS_API_KEY`, `SMS_MODE`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `DEMO_PHONE_NUMBERS`, `DEMO_REPLY_TIMEOUT_SECONDS`.
