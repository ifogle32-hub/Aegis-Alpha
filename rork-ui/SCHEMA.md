# Sentinel X Rork UI Schema

**Production-Safe | Regulator-Safe | Regression-Proof**

This document defines the complete Rork UI schema for the Sentinel X autonomous trading system. The schema ensures that the UI acts only as a command and telemetry surface, never executing trades directly or diverging from backend engine truth.

## Table of Contents

- [Global App Contract](#global-app-contract)
- [Engine State Model](#engine-state-model)
- [Control Surface](#control-surface)
- [Telemetry Panels](#telemetry-panels)
- [Strategy Intelligence](#strategy-intelligence)
- [Shadow Comparison](#shadow-comparison)
- [Capital & Funding](#capital--funding)
- [Multi-Broker Visibility](#multi-broker-visibility)
- [Alerting & Incidents](#alerting--incidents)
- [Audit & Regulatory Exports](#audit--regulatory-exports)
- [Mobile & Investor Mode](#mobile--investor-mode)
- [UI Guarantees](#ui-guarantees)

---

## Global App Contract

```json
{
  "id": "sentinel_x",
  "name": "Sentinel X",
  "type": "autonomous_trading_system",
  "authority": "backend",
  "ui_mode": "command_and_observe",
  "always_on": true
}
```

**Key Principles:**
- Backend engine is authoritative
- UI never controls execution directly
- Sentinel X is always running
- Training & backtesting never stop

---

## Engine State Model

### Allowed States

| State | Label | Description | Trading | Training | Execution Enabled |
|-------|-------|-------------|---------|----------|-------------------|
| `RESEARCH` | Training | Research, backtests, simulations run continuously | ❌ | ✅ | ❌ |
| `PAPER` | Paper Trading | Real execution via paper broker only | ✅ | ❌ | ✅ |
| `LIVE` | Live Trading | Real capital execution (requires hardware approval) | ✅ | ❌ | ✅ |
| `PAUSED` | Paused | All execution blocked, research continues | ❌ | ✅ | ❌ |
| `KILLED` | Killed | Emergency stop, irreversible without restart | ❌ | ❌ | ❌ |

### State Invariants

1. **Training Never Stops**: Training/research continues in `RESEARCH` and `PAUSED` modes
2. **Default State**: `RESEARCH` is the default and fallback state
3. **Kill-Switch Supremacy**: `KILLED` overrides all other states

---

## Control Surface

### START Command

- **Endpoint**: `POST /engine/start`
- **Visible When**: `RESEARCH` or `PAUSED`
- **Payload**: `{ "mode": "PAPER" }`
- **Resulting State**: `PAPER`
- **Requires Auth**: ✅
- **Rate Limit**: 5 requests per minute
- **UI Behavior**: Wait for state update, poll every 1s, max wait 30s

### STOP Command

- **Endpoint**: `POST /engine/stop`
- **Visible When**: `PAPER` or `LIVE`
- **Resulting State**: `RESEARCH`
- **Requires Auth**: ✅
- **Rate Limit**: 5 requests per minute
- **UI Behavior**: Wait for state update, poll every 1s, max wait 30s

### EMERGENCY_KILL Command

- **Endpoint**: `POST /engine/kill`
- **Visible When**: Always (all states)
- **Resulting State**: `KILLED`
- **Requires Auth**: ✅
- **Confirmation Required**: ✅
- **Rate Limit**: Bypass
- **Overrides**: All other commands
- **UI Behavior**: Wait for state update, poll every 500ms, max wait 10s, show critical alert

### Control Guarantees

- ✅ UI never executes trades directly
- ✅ UI never bypasses engine
- ✅ UI never assumes command success
- ✅ UI waits for engine state updates
- ✅ Kill-switch overrides everything

---

## Telemetry Panels

All telemetry panels are **read-only** and pull data from backend metrics endpoints. No derived logic in UI.

### Available Panels

1. **Equity Curve** (`GET /dashboard/equity`)
   - Poll interval: 5s
   - Data: equity, benchmark, timestamp
   - Visualization: Line chart

2. **P&L** (`GET /dashboard/pnl`)
   - Poll interval: 5s
   - Data: daily_pnl, cumulative_pnl, realized_pnl, unrealized_pnl
   - Visualization: Bar chart

3. **Drawdown** (`GET /metrics/pnl`)
   - Poll interval: 10s
   - Data: current_drawdown, max_drawdown, drawdown_percent
   - Visualization: Area chart

4. **Open Positions** (`GET /positions`)
   - Poll interval: 3s
   - Data: positions array, count, total_pnl
   - Visualization: Table

5. **Broker Health** (`GET /dashboard/brokers`)
   - Poll interval: 10s
   - Data: active_broker, health_score, latency_ms, fill_rate, reliability_score
   - Visualization: Metrics cards

6. **Execution Latency** (`GET /execution/metrics`)
   - Poll interval: 5s
   - Data: avg_latency_ms, p50/p95/p99_latency_ms
   - Visualization: Histogram

7. **Order Fill Quality** (`GET /execution/metrics`)
   - Poll interval: 5s
   - Data: avg_slippage_bps, fill_rate, partial_fill_rate, rejection_rate
   - Visualization: Gauge chart

8. **Engine Heartbeat** (`GET /dashboard/heartbeat`)
   - Poll interval: 1s
   - Data: heartbeat_ts, uptime_seconds, is_alive
   - Visualization: Status indicator

### Telemetry Guarantees

- ✅ No derived logic in UI
- ✅ All data from backend endpoints
- ✅ UI subscribes to events only
- ✅ UI tolerates backend restarts

---

## Strategy Intelligence

- **Endpoint**: `GET /dashboard/strategies`
- **Poll Interval**: 10s
- **Read-Only**: ✅

### Strategy Fields

- `name`: Strategy name
- `status`: `ACTIVE` | `DISABLED` | `SHADOW`
- `pnl`: P&L value
- `sharpe`: Sharpe ratio
- `drawdown`: Maximum drawdown
- `expectancy`: Trade expectancy
- `health_score`: Health score (0-1)
- `auto_disabled`: Auto-disable flag
- `promotion_score`: Promotion score (if applicable)
- `paper_approved`: Paper approval status
- `live_approved`: Live approval status

### Allowed Actions

- ✅ View details (`GET /strategies/{name}`)
- ✅ View metrics (`GET /execution/metrics/{strategy_name}`)

### Disallowed Actions

- ❌ Manual enable/disable (unless backend allows)
- ❌ Direct strategy modification
- ❌ Trading logic changes

---

## Shadow Comparison

Shadow vs Live comparison panels. **UI visualizes, not decides.**

### Panels

1. **Equity Comparison** (`GET /shadow/comparison`)
   - Data: shadow_equity, paper_equity, divergence, divergence_percent
   - Visualization: Dual line chart

2. **Divergence Metrics** (`GET /shadow/comparison`)
   - Data: signal_agreement_percent, slippage_comparison, fill_rate_comparison
   - Visualization: Metrics cards

### Export

- **Endpoint**: `GET /shadow/export`
- **Formats**: CSV, JSON
- **Read-Only**: ✅

### Guarantees

- ✅ UI visualizes only
- ✅ No decision logic in UI
- ✅ Backend is authoritative

---

## Capital & Funding

Capital actions are **scheduled only, never instant**. Hardware-key protected.

### Desktop Mode

**Allowed Actions:**
- Create funding schedule (`POST /capital/funding/schedule`) - Requires hardware auth
- View funding schedule (`GET /capital/funding/schedule`)
- View withdrawal schedule (`GET /capital/withdrawal/schedule`)
- View bank connection status (`GET /capital/bank/status`)

**Constraints:**
- Requires confirmation
- Cooldown: 3600 seconds

### Mobile Mode

**Allowed Actions (Read-Only):**
- View funding schedule
- View withdrawal schedule
- View bank connection status

**Disallowed Actions:**
- ❌ Create funding schedule
- ❌ Modify schedules
- ❌ Instant transfers

### Guarantees

- ✅ Scheduled only, never instant
- ✅ Hardware-key protected
- ✅ Cooldown timers enforced
- ✅ Mobile = read-only only

---

## Multi-Broker Visibility

**ExecutionRouter is single authority.** UI only visualizes broker decisions.

- **Endpoint**: `GET /dashboard/brokers`
- **Poll Interval**: 10s
- **Read-Only**: ✅

### Data Fields

- `active_broker`: Currently active broker
- `available_brokers`: List of available brokers
- `failover_history`: History of broker failovers
- `broker_decisions`: Broker selection decisions with reasoning
- `health_scores`: Health metrics per broker
- `retry_counts`: Retry counts per broker

### Guarantees

- ✅ ExecutionRouter is authoritative
- ✅ UI never selects brokers
- ✅ UI only visualizes decisions

---

## Alerting & Incidents

**UI subscribes to events only.** No alert generation in UI.

- **Endpoint**: `GET /dashboard/alerts`
- **WebSocket**: `WS /ws/alerts`
- **Poll Interval**: 2s

### Alert Types

| Type | Severity | Channels | Auto-Dismiss |
|------|-----------|-----------|--------------|
| `kill_switch_armed` | Critical | Slack, Mobile Push | ❌ |
| `strategy_disabled` | Warning | Slack, Mobile Push | ❌ |
| `drawdown_breach` | Warning | Slack, Mobile Push | ❌ |
| `broker_failure` | Error | Slack, Mobile Push | ❌ |
| `risk_rejection` | Info | Slack | ✅ |

### Guarantees

- ✅ UI subscribes to events only
- ✅ No alert generation in UI
- ✅ Backend is source of truth

---

## Audit & Regulatory Exports

**UI cannot edit audit records.** All exports are read-only.

### Export Endpoints

1. **Executions**: `GET /audit/export?type=executions`
2. **Broker Decisions**: `GET /audit/export?type=broker_decisions`
3. **Strategy Changes**: `GET /audit/export?type=strategy_changes`
4. **Risk Rejections**: `GET /audit/export?type=risk_rejections`
5. **Capital Movements**: `GET /audit/export?type=capital_movements`

### Export Formats

- CSV
- JSON
- PDF

### Guarantees

- ✅ UI cannot edit audit records
- ✅ All exports are read-only
- ✅ Backend generates all exports

---

## Mobile & Investor Mode

### Mobile UI

**Mode**: Read-Only

**Allowed Panels:**
- Equity (`GET /dashboard/equity`)
- Daily P&L (`GET /dashboard/pnl`)
- Positions (`GET /positions`)
- Engine State (`GET /status`)

**Disallowed Features:**
- ❌ Control commands (START/STOP/KILL)
- ❌ Strategy modifications
- ❌ Capital actions
- ❌ Audit exports

### Investor View

**Mode**: Read-Only

**Allowed Panels:**
- Equity
- Daily P&L
- Engine State

**Disallowed Features:**
- ❌ All controls
- ❌ Strategy details
- ❌ Execution access
- ❌ Broker information
- ❌ Audit exports

---

## UI Guarantees

### Non-Negotiable Guarantees

1. **No Direct Execution**: UI never executes trades
2. **No Engine Bypass**: UI never bypasses engine
3. **Training Never Stops**: Training never stops
4. **Engine State Authority**: Engine state is source of truth
5. **Kill-Switch Supremacy**: Kill-switch overrides UI
6. **ExecutionRouter Authority**: ExecutionRouter is authoritative
7. **Backend Restart Tolerance**: UI tolerates backend restarts without desync
8. **No UI Logic Divergence**: No UI logic may diverge from engine truth

### Enforcement

- Schema validation
- Backend authority
- Polling with validation
- Read-only visualization
- Exponential backoff polling
- Schema validation and testing

---

## API Contract

### Authentication

- **Type**: API Key
- **Header**: `X-API-Key`
- **Required For**: POST, PUT, DELETE

### Rate Limiting

- **Control Endpoints**: 5 requests per minute
- **Read Endpoints**: 60 requests per minute
- **Kill Endpoint**: Bypass

### Timeouts

- **Control Endpoints**: 10 seconds
- **Read Endpoints**: 5 seconds
- **Kill Endpoint**: 5 seconds

### Error Handling

- **Retry Strategy**: Exponential backoff
- **Max Retries**: 3
- **Backoff Multiplier**: 2

### State Sync

- **Poll Interval**: 1000ms
- **Max Wait**: 30 seconds
- **Never Assume Success**: ✅

---

## Future Extensibility

The schema supports future extensions without changes:

- **Brokers**: Dynamic broker list from backend
- **Strategies**: Dynamic strategy list from backend
- **Agents**: Dynamic agent list from backend

---

## Regulatory Compliance

### Features

- ✅ All actions are logged and auditable
- ✅ No instant capital movements
- ✅ Hardware-key protection for sensitive operations
- ✅ Read-only investor view
- ✅ Complete audit trail
- ✅ No UI-side trading logic
- ✅ Backend is authoritative for all decisions

---

## Schema Files

- `schema.json`: Complete JSON schema definition
- `schema.types.ts`: TypeScript type definitions
- `SCHEMA.md`: This documentation

---

**Last Updated**: 2024-01-07  
**Version**: 1.0.0  
**Status**: Production-Ready
