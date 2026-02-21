# Sentinel X v0.1

Lean, shadow-only, adaptive engine. Single asset NVDA. No real trading.

## Run

**Terminal 1 — Engine (learning loop):**
```bash
python -m sentinel_x_v01.main
```

**Terminal 2 — Monitor API (Rork):**
```bash
uvicorn sentinel_x_v01.monitor_api:app --host 0.0.0.0 --port 8000
```

## Env (optional)

- `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` — Alpaca keys for bar data (paper).
- `SENTINEL_SYMBOL` — default `NVDA`
- `SENTINEL_INITIAL_CAPITAL` — default `100000`
- `SENTINEL_LEARNING_RATE` — default `0.01`
- `SENTINEL_LOOP_SLEEP` — seconds between loops, default `60`

## API (read-only)

- `GET /status` — engine status
- `GET /heartbeat` — heartbeat
- `GET /portfolio` — capital, position, PnL
- `GET /metrics` — metrics
- `GET /strategy` — strategy/learner state

All return JSON. No write endpoints.
