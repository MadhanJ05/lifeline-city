# Lifeline City

Lifeline helps emergency managers find residents who go quiet during a disaster, then routes a human to check on them. The demo is a case study of Cape Cod (Barnstable County) in the Blizzard of 2026. It covers Tier 1, which works for any Massachusetts town: **Need** (tract-level ACS and HHS emPOWER), **Lost lifelines** (town-hour power outage, hours dark, downed wires, modeled phone outage) and **Reach** (SMS check-ins, door-knock lists or an AM radio script, chosen per tract-hour). Boston Voice (Tier 2, 311 silence) is an optional later block and is not built yet. `--skip-boston` is implied until it exists.

Data flow: `pipeline/` (offline) writes `data/processed/`. The FastAPI app in `api/` serves those files, and the Vite + React app in `web/` talks only to the API. The demo never calls an LLM.

## Setup

Requires Python 3.13 (via `uv`) and Node 25 / npm 11.

```sh
uv venv --python 3.13
source .venv/bin/activate          # or call .venv/bin/python directly
uv pip install -r requirements.txt
cp .env.example .env               # fill in locally; .env is gitignored
cd web && npm ci && cd ..          # or npm install
```

In `.env`:

- `CENSUS_API_KEY` is needed only when `data/raw/cache/` is empty. Cached fetches are reused.
- `ANTHROPIC_API_KEY` is needed only to regenerate operator briefings. Cached LLM responses in `data/processed/llm_cache/` are reused, and template briefings are the fallback.
- `SMS_MODE` can be left empty (simulator). `DEMO_REPLY_TIMEOUT_SECONDS` defaults to 30.

## Run

Run these in order:

```sh
python -m pipeline.run                              # full pipeline -> data/processed/
python -m pipeline.run --no-llm                     # same, no Anthropic calls (llm_cache hits only)
uvicorn api.main:app --host 127.0.0.1 --port 8000   # API
cd web && npm run dev                               # web -> http://localhost:5173
```

The pipeline ends with the privacy guard and exits non-zero on any finding. The API loads `.env` on its own (`api/sms.py` calls `load_dotenv`, and real environment variables take precedence), so you don't need `--env-file`. If `data/processed/` is missing, the API refuses to start and tells you to run the pipeline. The web app reads `VITE_API_BASE` and defaults to `http://localhost:8000`.

## Tests

```sh
pytest -q                                    # pipeline + API
pytest -q -m required_pbt                    # required property-based tests only
cd web && npx vitest --run && npm run build  # web logic tests + typecheck/build
python -m pipeline.privacy_guard api data/processed README.md   # phone/address scan
```

## Demo walkthrough

1. Set the time slider to **Tue Feb 24, 9 AM** (a key demo hour with a verified briefing).
2. Open the Falmouth tract at **rank 1**. Phones are likely degraded, so Reach shows a **door-knock list** for simulated responders, with an access-hazard note where downed wires apply.
3. Open the Barnstable tract `25001015300` at **rank 7**. Its channel is **SMS**. Click **Send check-ins**.
4. In the phone simulator, pick **Simulated household #1** (Português) and reply `AJUDA`. An escalation is routed to a simulated responder, and the household gets a confirmation that repeats 911. Wait about 30 s, and households with no reply are marked silent (only on SMS tract-hours).
5. Click **Reset demo** to clear check-in state.

You can also try **Mon Feb 23, 5 PM**, where both channels appear in the queue. Falmouth flips to door-knock at 6 PM because of the modeled 8-hour tower-backup rule.

## Security and privacy

- **The API has no authentication.** It's for localhost demo use only. Bind it to `127.0.0.1` and never expose it publicly. CORS allows only the local Vite origin (`localhost:5173`).
- Real data is aggregate only: tract-level ACS and emPOWER (masking respected), and town-hour outage and downed-wire counts. No individual-level real data is stored or shown.
- **All households and responders are synthetic** (`synthetic: true`) and labeled "Simulated" in the UI. There are no real addresses, names or contacts.
- Demo phone numbers live only in `DEMO_PHONE_NUMBERS` in `.env`. They're masked in the UI and logs, and they never appear in code, data or docs.
- **SMS defaults to the in-app phone simulator.** Twilio is not built, so every `SMS_MODE` value uses the simulator.
- Lifeline does not replace 911. Every resident message includes 911 and 2-1-1, and every escalation ends with a human.

## Data labels

- Town outage curves: "Reconstructed from MEMA, Eversource and public-safety reports."
- Chatham outage share: "Estimated from the Cape-wide share (no town reports)"
- Sandwich and Chatham customer counts: "Estimated from ACS housing units."
- Modeled telecom flag: "Modeled: assumes tower backup lasts about 8 hours". Observed telecom events are map pins and briefing context, each with its source.

## More

- [docs/methods.md](docs/methods.md): data sources, formulas, assumptions and simplifications
- [docs/kiro-usage.md](docs/kiro-usage.md): how Kiro specs, steering and hooks were used
