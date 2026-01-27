# UI State Mapping to Engine Modes

────────────────────────────────────────
PHASE 6 — UI STATE GUARANTEES
────────────────────────────────────────

## UI States

### TRAINING Mode (EngineMode.RESEARCH)
- **Status**: "Training / Research"
- **Start button**: Enabled
- **Stop button**: Disabled
- **Equity**: Simulated (from backtests)
- **Broker**: Not connected (no broker needed)
- **Trading**: Disabled (no orders executed)

### PAPER Mode (EngineMode.PAPER)
- **Status**: "Paper Trading"
- **Start button**: Disabled
- **Stop button**: Enabled
- **Equity**: Live (from paper broker account)
- **Broker**: Alpaca Paper (or simulated paper executor)
- **Trading**: Enabled (orders executed via paper broker)
- **Live PnL**: Visible (from paper positions)

### LIVE Mode (EngineMode.LIVE)
- **Status**: "Live Trading" (future, disabled for now)
- **Start button**: Disabled
- **Stop button**: Enabled
- **Equity**: Live (from live broker account)
- **Broker**: Alpaca Live
- **Trading**: Enabled (orders executed via live broker)
- **Live PnL**: Visible (from live positions)

### PAUSED Mode (EngineMode.PAUSED)
- **Status**: "Paused"
- **Start button**: Enabled
- **Stop button**: Disabled
- **Equity**: Last known value
- **Broker**: Disconnected
- **Trading**: Disabled (all execution blocked)

### KILLED Mode (EngineMode.KILLED)
- **Status**: "Killed / Shutdown"
- **Start button**: Disabled
- **Stop button**: Disabled
- **Equity**: Frozen (last known value)
- **Broker**: Disconnected
- **Trading**: Disabled (engine loop exited)

## Emergency Kill Behavior

When Emergency Kill is triggered:
1. All open orders are cancelled immediately
2. EngineMode is set to KILLED
3. Engine loop exits (process shutdown)
4. UI shows "Killed / Shutdown" status
5. Cannot restart without full process restart

## State Transitions

### Valid Transitions:
- TRAINING → PAPER (via `/engine/start`)
- PAPER → TRAINING (via `/engine/stop`)
- PAPER → KILLED (via `/engine/kill`)
- TRAINING → KILLED (via `/engine/kill`)
- Any → KILLED (via `/engine/kill`)

### Invalid Transitions:
- KILLED → Any (requires process restart)
- LIVE → Any (LIVE mode disabled for now)

## UI Contract Guarantees

1. **Buttons MUST NOT**:
   - Start/stop threads
   - Call brokers directly
   - Touch execution directly

2. **Rork is CONTROL ONLY**:
   - Changes EngineMode only
   - Never manipulates engine internals
   - Never calls broker APIs directly

3. **Engine is AUTHORITATIVE**:
   - Engine loop controls execution
   - Engine decides when to trade
   - Engine manages broker connections

DO NOT CHANGE WITHOUT ARCHITECT REVIEW
