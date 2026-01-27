# SHADOW MODE IMPLEMENTATION

## Overview

Production-grade, runtime-toggleable SHADOW mode system for Sentinel X / Aegis Alpha. Enables shadow trading observability (signals, metrics, backtests, UI dashboards) without allowing execution and without requiring engine restarts.

## SAFETY GUARANTEES

- **SHADOW MODE ONLY**: Read-only operations, no execution paths
- **NO ORDER SUBMISSION**: Shadow operations never trigger order placement
- **NO BROKER INTERACTION**: Shadow mode does not interact with brokers
- **RUNTIME TOGGLE**: Enable/disable without engine restart
- **UNSAFE TRANSITION BLOCKING**: Cannot enable SHADOW while engine is LIVE (ARMED equivalent)
- **THREAD-SAFE**: All state transitions are thread-safe
- **AUDITABLE**: All transitions are logged and auditable

## Architecture

### Core Components

1. **`sentinel_x/core/shadow_state.py`** - Shadow state model (source of truth)
   - `ShadowState` dataclass with thread-safe transitions
   - `ShadowMode` enum (MONITOR, SHADOW)
   - Transition history tracking
   - Blocks unsafe transitions (LIVE → SHADOW)

2. **`sentinel_x/core/shadow_registry.py`** - Singleton registry
   - Global `get_shadow_state()` accessor
   - Thread-safe initialization

3. **`sentinel_x/core/shadow_guards.py`** - Mandatory guards
   - `assert_shadow_enabled()` - Fail-fast guard
   - `can_emit_shadow_signals()` - Non-blocking check
   - `require_shadow_for_promotion()` - Promotion guard
   - `is_shadow_enabled()` - Safe check (never raises)

4. **`sentinel_x/api/shadow_control.py`** - Runtime API
   - `POST /engine/shadow` - Toggle shadow mode
   - `GET /engine/shadow` - Get current shadow state
   - Blocks unsafe transitions with HTTP 409

5. **`sentinel_x/api/shadow_endpoints.py`** - Shadow endpoints (updated)
   - `GET /shadow/strategies/{id}/signals` - Get shadow signals (guarded)
   - `GET /shadow/overview` - Get shadow overview (guarded)
   - `WebSocket /shadow/ws/shadow` - Real-time shadow feed (returns disabled state if gate is off)

6. **`sentinel_x/strategies/guards.py`** - Strategy guards (re-export)
7. **`sentinel_x/intelligence/promotion_guards.py`** - Promotion guards (re-export)

### Integration Points

- **Status Endpoint** (`/status`) - Exposes `shadow_mode` and `shadow_state`
- **Strategy Promotion** - Checks shadow gate before using backtest metrics
- **Shadow Endpoints** - All endpoints check shadow gate and return disabled state if off
- **WebSocket Feed** - Returns `disabled: true` when shadow mode is off

## Usage

### Enable SHADOW Mode

```bash
curl -X POST http://localhost:8000/engine/shadow \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "reason": "Operator enabled shadow testing"
  }'
```

**Response:**
```json
{
  "shadow_enabled": true,
  "mode": "SHADOW",
  "trading_window": "CLOSED",
  "last_transition": "2024-01-01T12:00:00Z",
  "reason": "Operator enabled shadow testing",
  "transition_count": 1
}
```

### Disable SHADOW Mode

```bash
curl -X POST http://localhost:8000/engine/shadow \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": false,
    "reason": "Shadow testing complete"
  }'
```

### Check SHADOW State

```bash
curl http://localhost:8000/engine/shadow
```

### Verify via Status Endpoint

```bash
curl http://localhost:8000/status | jq '.shadow_mode'
```

Expected: `true` or `false`

## Safe Operation Rules

### Transitions

- ✅ **MONITOR → SHADOW**: Allowed (when engine is not LIVE)
- ✅ **SHADOW → MONITOR**: Allowed (always)
- ❌ **LIVE → SHADOW**: Blocked (HTTP 409 Conflict)
- ❌ **ARMED → SHADOW**: Blocked (LIVE mode is equivalent to ARMED)

### Behavior

- **SHADOW enabled**: Signals, metrics, and backtests are generated and exposed
- **SHADOW disabled**: All shadow endpoints return `disabled: true`, WebSocket feeds are empty
- **UI reflects engine truth**: Status endpoint always shows actual shadow state

## Guards Implementation

### Engine Level

- Shadow state checked before any shadow operation
- RuntimeError raised if shadow disabled when required

### Strategy Level

- `can_emit_shadow_signals()` checks before signal generation
- Returns `disabled: true` in API responses if shadow is off

### Promotion Level

- Backtest metrics only used for promotion if shadow is enabled
- `require_shadow_for_promotion()` can be used for strict enforcement

### WebSocket Level

- `collect_shadow_realtime()` checks shadow gate
- Returns `disabled: true` message when shadow is off
- UI must render disabled state

## Status Endpoint Schema

```json
{
  "engine_status": "RUNNING",
  "engine_mode": "TRAINING",
  "shadow_mode": true,
  "shadow_state": {
    "mode": "SHADOW",
    "trading_window": "CLOSED",
    "last_transition": "2024-01-01T12:00:00Z",
    "reason": "Operator enabled shadow testing"
  },
  "shadow_backtest": {
    "nvda_momentum": {
      "strategy_id": "nvda_momentum",
      "pnl": 1234.56,
      "sharpe": 1.23,
      "max_drawdown": 0.15,
      "trade_count": 42
    }
  }
}
```

## WebSocket Response Schema

### When SHADOW Enabled

```json
{
  "disabled": false,
  "timestamp": "2024-01-01T12:00:00Z",
  "signals": [...],
  "metrics": {...},
  "mode": "SHADOW"
}
```

### When SHADOW Disabled

```json
{
  "disabled": true,
  "reason": "Shadow mode disabled. Enable via /engine/shadow endpoint.",
  "mode": "MONITOR",
  "shadow_enabled": false,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## Error Handling

- All shadow operations fail gracefully if shadow is disabled
- API endpoints return appropriate HTTP status codes:
  - `403 Forbidden` - Shadow mode disabled (for guarded endpoints)
  - `409 Conflict` - Unsafe transition attempted (e.g., LIVE → SHADOW)
  - `200 OK` - Successful operation or disabled state (with `disabled: true`)

## Thread Safety

- All state transitions use `Lock` for thread safety
- Guards are non-blocking where possible
- State snapshot methods are read-only and thread-safe

## Audit Trail

- All transitions are logged with timestamp, reason, and mode change
- Transition history maintained (last 100 transitions)
- Audit events logged for critical transitions
- Request IDs tracked for all API calls

## Testing

Run the test suite:

```bash
cd /Users/ins/Aegis\ Alpha
pytest tests/backtest/test_simulator.py -v
```

## Implementation Status

✅ All phases completed:
- ✅ PHASE 1: Engine state model
- ✅ PHASE 2: Registry singleton
- ✅ PHASE 3: Global guards
- ✅ PHASE 4: Runtime toggle API
- ✅ PHASE 5: Status endpoint integration
- ✅ PHASE 6: Strategy + promotion guards
- ✅ PHASE 7: WebSocket gating
- ✅ PHASE 8: Safe operation rules (enforced by design)
- ✅ PHASE 9: Operator flow (documented)

## Next Steps

1. **UI Integration**: Update Shadow Dashboard to check `disabled` field and display appropriate message
2. **Monitoring**: Add alerts when shadow mode is disabled but expected to be enabled
3. **Metrics**: Track shadow mode uptime and transition frequency
4. **Documentation**: Update API docs with shadow mode requirements
