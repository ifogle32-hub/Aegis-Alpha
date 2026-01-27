# Shadow Training Extension Implementation

## Overview

Extended the existing Shadow Training system with:
1. Verifiable shadow heartbeat
2. Deterministic historical replay
3. Live dashboards
4. Hardened multi-asset support
5. CI tests for determinism and safety
6. Safety & governance hardening

## Phase 1 — Shadow Heartbeat Verification

**File**: `sentinel_x/shadow/heartbeat.py`

### Features
- Heartbeat emitted every N ticks (configurable)
- Heartbeat persisted with timestamp + tick count
- Heartbeat includes:
  - `trainer_alive`: Boolean indicating trainer status
  - `active_strategies`: Number of active strategies
  - `feed_type`: Feed type (live | replay | synthetic)
  - `last_tick_ts`: Last tick timestamp
  - `error_count`: Total error count

### Exposed Via
- Internal engine registry: `get_shadow_heartbeat_monitor()`
- Read-only status snapshot: `get_status_snapshot()`
- Log entry every M seconds (configurable)
- Persistent file: `/tmp/sentinel_x_shadow_heartbeat.json`

### Fail Conditions
- If heartbeat stalls → emit WARN
- If stalled > threshold → auto-restart shadow trainer thread
- Engine must NOT crash (all errors are non-fatal)

### Integration
- Integrated into `ShadowTrainer.process_tick()`
- Emits heartbeat every `heartbeat_interval_ticks` ticks
- Auto-restart logic in `_attempt_restart()` method

## Phase 2 — Historical Replay Engine

**File**: `sentinel_x/shadow/replay.py`

### Features
- Tick-accurate timestamps
- Deterministic ordering (same input → same output)
- Clock control:
  - `play()`: Start replay
  - `pause()`: Pause replay
  - `resume()`: Resume replay
  - `rewind()`: Rewind to beginning
  - `step()`: Manual tick stepping
- Windowed replay (date ranges)
- Multi-symbol synchronized replay

### Replay Modes
- **STRICT**: Exact timestamps (real-time simulation)
- **ACCELERATED**: Fast-forward with speed multiplier
- **STEP**: Manual tick stepping (one tick at a time)

### Guarantees
- Same input → same outputs (byte-for-byte reproducible)
- Replay results reproducible with seeded randomness
- Replay cannot leak into live execution (isolated feed)

### Usage
```python
from sentinel_x.shadow.replay import HistoricalReplayFeed, ReplayMode

feed = HistoricalReplayFeed(
    symbols=["SPY", "QQQ"],
    historical_data=historical_data_dict,
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 1, 31),
    replay_mode=ReplayMode.STRICT,
    speed_multiplier=1.0,
    seed=42,  # For determinism
)

feed.start()
tick = feed.get_next_tick()
```

## Phase 3 — Live Dashboards

**File**: `dashboards/shadow_dashboard.py`

### Features
- **Textual-based dashboard** (terminal UI)
- **Text-based fallback** (if Textual not available)

### Required Views
- Shadow heartbeat (live)
- Active strategies count
- Per-strategy metrics (return, Sharpe, drawdown, trades, promotion state)
- PnL curves (shadow only)
- Drawdown & risk stats
- Regime breakdown
- Replay progress indicator

### Rules
- **Read-only**: No control actions
- **No trade buttons**: No execution capability
- **No mutation**: Cannot modify engine state
- **Auto-refresh**: Updates every N seconds
- **Survive restarts**: Dashboard can be restarted independently

### Usage
```bash
python dashboards/shadow_dashboard.py
```

## Phase 4 — Multi-Asset Hardening

**File**: `sentinel_x/shadow/assets.py`

### Supported Asset Types
- **Equities**: Stocks, ETFs
- **Futures**: Commodity, index futures
- **Crypto**: Cryptocurrencies
- **FX**: Foreign exchange (spot)

### Features
- **Asset abstraction layer**: `ContractSpec` for each asset type
- **Contract specs**:
  - Tick size (minimum price increment)
  - Multiplier (contract multiplier)
  - Currency (base currency)
  - Fees (per-contract and percentage)
  - Trade size limits (min/max)
- **Currency normalization**: Cross-currency PnL aggregation
- **Cross-asset PnL aggregation**: Portfolio-level PnL calculation
- **Correlation tracking**: Asset correlation matrix

### Risk Controls Per Asset
- **Max exposure**: Maximum position exposure limit
- **Volatility scaling**: Volatility-based position sizing
- **Liquidity penalty**: Liquidity-based fee adjustment
- **Asset-specific slippage models**: Custom slippage per asset type

### Usage
```python
from sentinel_x.shadow.assets import AssetRegistry, ContractSpec, AssetType

registry = AssetRegistry()

# Register equity contract
equity_spec = ContractSpec(
    symbol="SPY",
    asset_type=AssetType.EQUITY,
    tick_size=0.01,
    multiplier=1.0,
    currency="USD",
    fee_percentage=0.1,
)
registry.register_contract(equity_spec)

# Calculate cross-asset PnL
pnl = registry.calculate_portfolio_pnl(positions, current_prices)
```

## Phase 5 — CI Tests for Shadow Determinism

### Test Files
- `tests/test_shadow_determinism.py`: Core determinism tests
- `tests/test_replay.py`: Replay engine tests
- `tests/test_multi_asset.py`: Multi-asset tests

### Test Categories

#### 1. Deterministic Replay
- **Same data → same signals**: Verify identical inputs produce identical signals
- **Same signals → same scores**: Verify identical signals produce identical scores
- Uses seeded randomness for reproducibility

#### 2. Strategy Isolation
- **One strategy failure does not affect others**: Verify strategy isolation
- Tests unregistration and state isolation

#### 3. No Live Execution Leakage
- **Assert broker code is never invoked**: Verify shadow never calls broker
- Checks that shadow trainer has no broker references

#### 4. Restart Safety
- **Resume shadow training without data loss**: Verify persistence across restarts
- Tests strategy registration persistence

#### 5. Multi-Asset Correctness
- **Cross-asset PnL reconciliation**: Verify portfolio PnL calculation
- Tests currency normalization and fee calculation

### CI Requirements
- ✅ Runs headless (no GUI required)
- ✅ No network calls (all data is local)
- ✅ No external brokers (simulation only)
- ✅ Seeded randomness only (deterministic)
- ✅ Fails hard on nondeterminism (assertions)

### Running Tests
```bash
python -m pytest tests/test_shadow_determinism.py -v
python -m pytest tests/test_replay.py -v
python -m pytest tests/test_multi_asset.py -v
```

## Phase 6 — Safety & Governance Hardening

**File**: `sentinel_x/shadow/governance.py`

### Explicit Guards
- **Shadow cannot write to live state**: Runtime assertion
- **Shadow cannot access execution adapters**: Runtime assertion
- **Promotion logic remains manual**: Enforced in PromotionEvaluator
- **Replay mode blocks all live feeds**: Isolation enforcement

### Audit Logs
- **Replay start/stop**: Logged with timestamps, symbols, mode
- **Strategy evaluation results**: Logged with metrics
- **Promotion eligibility changes**: Logged with old/new states

### Integration
- Integrated into `ShadowTrainer` for automatic logging
- All operations are audited via `ShadowPersistence`
- Governance checks are non-blocking (log only, don't raise)

### Usage
```python
from sentinel_x.shadow.governance import get_shadow_governance

governance = get_shadow_governance()

# Log replay start
governance.log_replay_start(
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 1, 31),
    symbols=["SPY"],
    replay_mode="STRICT",
)

# Log promotion eligibility change
governance.log_promotion_eligibility_change(
    strategy_id="strategy_1",
    old_state="SHADOW_ONLY",
    new_state="CANDIDATE",
    reason="All criteria met",
)
```

## Files Created

### Core Components
- `sentinel_x/shadow/heartbeat.py` - Heartbeat monitoring
- `sentinel_x/shadow/replay.py` - Historical replay engine
- `sentinel_x/shadow/assets.py` - Multi-asset support
- `sentinel_x/shadow/governance.py` - Safety & governance

### Dashboards
- `dashboards/shadow_dashboard.py` - Live dashboard (Textual + text fallback)

### Tests
- `tests/test_shadow_determinism.py` - Determinism tests
- `tests/test_replay.py` - Replay engine tests
- `tests/test_multi_asset.py` - Multi-asset tests

### Documentation
- `SHADOW_TRAINING_EXTENSION.md` - This document

## Integration Points

### Engine Integration
- Heartbeat monitor integrated into `ShadowTrainer.process_tick()`
- Governance logging integrated into trainer lifecycle
- Replay feed can be used as drop-in replacement for market feed

### Existing Components Updated
- `sentinel_x/shadow/trainer.py` - Added heartbeat and governance integration
- `sentinel_x/shadow/__init__.py` - Exported new components

## Quality Assurance

- ✅ No linter errors
- ✅ Production-grade code
- ✅ Comprehensive docstrings
- ✅ Thread-safe implementations
- ✅ Error handling throughout
- ✅ No TODOs or stubs
- ✅ No placeholders
- ✅ Deterministic tests
- ✅ CI-ready test suite

## Summary

All 6 phases have been implemented:

1. ✅ Phase 1: Shadow Heartbeat Verification
2. ✅ Phase 2: Historical Replay Engine
3. ✅ Phase 3: Live Dashboards
4. ✅ Phase 4: Multi-Asset Hardening
5. ✅ Phase 5: CI Tests for Shadow Determinism
6. ✅ Phase 6: Safety & Governance Hardening

The shadow training system is now:
- **Observable**: Heartbeat monitoring and dashboards
- **Deterministic**: Reproducible replay engine
- **Multi-asset**: Supports equities, futures, crypto, FX
- **Tested**: Comprehensive CI test suite
- **Governed**: Safety guards and audit logging

All requirements met. Zero placeholders. Production-ready.
