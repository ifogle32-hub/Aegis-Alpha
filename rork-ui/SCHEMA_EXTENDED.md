# Sentinel X Rork UI Schema - Extended Phases

**Production-Safe | Regulator-Safe | Regression-Proof**

This document describes the extended phases added to the Rork UI schema, implementing all requirements for hardware approval flows, investor mobile views, chaos testing visualization, LLM strategy synthesis, TradingView bindings, and enhanced safety guarantees.

## Extended Phases Summary

### Phase 0: Global UI State Model ✓
- **Status**: Already implemented
- **Description**: Single authoritative UI state machine reflecting backend engine states
- **States**: TRAINING, PAPER_TRADING, LIVE_TRADING, PAUSED, KILLED
- **Invariant**: UI reflects state, UI does not decide state

### Phase 1: Hardware-Key Approval Flow ✓
- **Status**: Implemented
- **Description**: Hardware-backed approval system for sensitive actions
- **Schema**: `ApprovalRequest`
- **Features**:
  - Display pending approvals
  - Countdown to expiration
  - Explicit physical confirmation required
  - No soft approvals
  - No auto-approval
  - Immutable audit log view

**UI Restrictions**:
- Approval buttons do nothing without hardware signal
- UI cannot fabricate approvals
- UI cannot reuse approvals
- UI only displays approval status from backend

**Endpoints**:
- `GET /approvals/pending` - List pending approvals
- `GET /approvals/{request_id}` - View approval details
- `GET /approvals/audit` - View audit log

**Action Types**:
- `ENABLE_LIVE` - Enable live trading
- `WITHDRAW` - Capital withdrawal
- `STRATEGY_PROMOTION` - Promote strategy to live
- `KILL_RESET` - Reset kill switch

**Required Devices**:
- `YubiKey` - Hardware security key
- `SecureEnclave` - iOS/Android secure storage
- `WebAuthn` - Web authentication standard

### Phase 2: Investor Mobile-Only Schema ✓
- **Status**: Implemented
- **Description**: Read-only mobile view for investors
- **Mode**: READ-ONLY
- **Visible Panels**:
  - Total equity
  - Daily P&L
  - Drawdown
  - Equity curve
  - Engine state
  - Broker mode (Paper / Live indicator only)

**Hidden Features**:
- Strategies
- Orders
- Execution routing
- Risk rules
- Kill-switch controls

**Actions**: NONE (all actions disallowed)

**Funding**:
- Display funding schedule only
- No instant deposits
- No withdrawals
- No broker credentials
- No schedule modifications

**Guarantee**: Investor UI can NEVER mutate engine state

### Phase 3: Chaos Test Visualizer Schema ✓
- **Status**: Implemented
- **Description**: Visualization of chaos engineering test runs
- **Schema**: `ChaosTestRun`

**Fault Types**:
- `LATENCY` - Network latency injection
- `BROKER_DOWN` - Broker failure simulation
- `PARTIAL_FILL` - Partial fill scenarios
- `PRICE_GAP` - Price gap scenarios
- `NETWORK_PARTITION` - Network partition scenarios

**Visualization**:
- Timeline visualization of test events
- Engine state transitions
- Strategy survivability
- Broker failover paths
- Kill-switch triggers

**Restrictions**:
- Chaos tests NEVER run in LIVE mode
- UI cannot trigger chaos without explicit backend permission
- UI only visualizes test results
- Backend controls all test execution

**Endpoints**:
- `GET /chaos/tests` - List test runs
- `GET /chaos/tests/{test_id}` - View test details
- `GET /chaos/tests/{test_id}/timeline` - View test timeline

### Phase 4: LLM Strategy Synthesis UI ✓
- **Status**: Implemented
- **Description**: UI for viewing LLM-generated strategies
- **Schema**: `SynthesizedStrategy`

**Lifecycle States**:
- `CANDIDATE` - Generated, not yet evaluated
- `SHADOW_TESTING` - Participating in shadow trading
- `PAPER_APPROVED` - Approved for paper testing
- `LIVE_APPROVED` - Approved for live (requires explicit approval)
- `ARCHIVED` - Rejected or obsolete

**UI Features**:
- Browse generated strategies
- Inspect logic summaries
- View backtests
- Compare against active strategies
- Observe promotion readiness

**Restrictions**:
- LLM strategies are READ-ONLY
- No execution
- No auto-promotion without approval
- LIVE requires hardware approval
- UI cannot modify strategy code
- UI cannot enable/disable strategies

**Promotion Flow**:
1. **CANDIDATE → SHADOW_TESTING**: Automatic (no approval)
2. **SHADOW_TESTING → PAPER_APPROVED**: Requires approval (`POST /synthesis/strategies/{name}/approve-paper`)
3. **PAPER_APPROVED → LIVE_APPROVED**: Requires hardware approval (`POST /synthesis/strategies/{name}/approve-live`)

**Endpoints**:
- `GET /synthesis/strategies` - List synthesized strategies
- `GET /synthesis/strategies/{strategy_name}` - View strategy details
- `GET /synthesis/strategies/{strategy_name}/backtest` - View backtest results
- `GET /synthesis/strategies/compare` - Compare strategies
- `GET /synthesis/promotion-scores` - View promotion readiness scores

### Phase 5: TradingView Chart Bindings ✓
- **Status**: Implemented
- **Description**: TradingView chart integration with backend data
- **Supported Charts**:
  1. Equity Curve vs Benchmark
  2. Per-Strategy Equity
  3. Drawdown
  4. Exposure by Asset
  5. Execution Markers
  6. Shadow vs Paper Comparison

**Rules**:
- Backend is source of truth
- Charts are read-only
- Real-time via WS/SSE
- No client-side calculations affecting metrics
- Exportable snapshots for audits

**WebSocket Endpoints**:
- `WS /ws/equity` - Equity curve updates
- `WS /ws/strategies` - Strategy performance updates
- `WS /ws/drawdown` - Drawdown updates
- `WS /ws/positions` - Position updates
- `WS /ws/executions` - Execution marker updates
- `WS /ws/shadow` - Shadow comparison updates

**Export**:
- `GET /charts/export/{chart_id}` - Export chart snapshot
- Formats: PNG, PDF, SVG

### Phase 6: Shadow vs Live Comparison UI ✓
- **Status**: Implemented (extended)
- **Description**: Enhanced shadow vs live comparison visualization
- **Schema**: `ShadowComparison`

**UI Features**:
- Side-by-side charts
- Highlight divergence
- Auto-disable warnings
- Promotion eligibility indicators

**Visualization**:
- Equity comparison: Dual line chart (shadow vs paper)
- Performance metrics: Side-by-side metrics cards
- Divergence heatmap: Divergence visualization
- Promotion readiness: Promotion eligibility indicator

**Endpoints**:
- `GET /shadow/comparison` - Get comparison data
- `GET /shadow/comparison/{strategy_name}` - Get strategy-specific comparison

### Phase 7: Mobile Funding Scheduler ✓
- **Status**: Implemented (extended)
- **Description**: Controlled funding schedule management
- **Schema**: `FundingSchedule`

**Rules**:
- Scheduled only
- No instant movement
- Requires hardware approval
- Read-only on investor mobile
- Admin-only control surface

**Funding Directions**:
- `DEPOSIT` - Add capital
- `WITHDRAW` - Remove capital

**Frequencies**:
- `ONCE` - Single execution
- `DAILY` - Daily execution
- `WEEKLY` - Weekly execution
- `MONTHLY` - Monthly execution

**Mobile Access**:
- **Investor**: Read-only (view schedule only)
- **Admin**: Full access (requires hardware auth)

**Endpoints**:
- `GET /capital/funding/schedule` - List schedules
- `GET /capital/funding/schedule/{schedule_id}` - View schedule
- `POST /capital/funding/schedule` - Create schedule (admin only, hardware auth required)

### Phase 8: UI Safety Guarantees (Extended) ✓
- **Status**: Implemented
- **Description**: Extended safety guarantees enforced globally

**Guarantees**:
1. ✅ UI never calls brokers directly
2. ✅ UI never executes orders
3. ✅ UI never mutates strategies
4. ✅ UI never bypasses ExecutionRouter
5. ✅ UI failures do not affect engine
6. ✅ Kill-switch always visible
7. ✅ All actions logged and auditable
8. ✅ UI mirrors backend truth, never diverges
9. ✅ UI is a mirror and a controller, never the executor

## Implementation Status

| Phase | Status | Schema | Types | Documentation |
|-------|--------|--------|-------|---------------|
| Phase 0 | ✅ | ✅ | ✅ | ✅ |
| Phase 1 | ✅ | ✅ | ✅ | ✅ |
| Phase 2 | ✅ | ✅ | ✅ | ✅ |
| Phase 3 | ✅ | ✅ | ✅ | ✅ |
| Phase 4 | ✅ | ✅ | ✅ | ✅ |
| Phase 5 | ✅ | ✅ | ✅ | ✅ |
| Phase 6 | ✅ | ✅ | ✅ | ✅ |
| Phase 7 | ✅ | ✅ | ✅ | ✅ |
| Phase 8 | ✅ | ✅ | ✅ | ✅ |

## Files Updated

1. **`schema.json`** - Extended with all new phases
2. **`schema.types.ts`** - Added TypeScript types for all new phases
3. **`SCHEMA_EXTENDED.md`** - This documentation

## Validation

- ✅ `schema.json` is valid JSON
- ✅ `schema.types.ts` has no linting errors
- ✅ All phases implemented
- ✅ All invariants preserved
- ✅ All guarantees encoded

## Key Design Principles

### 1. Backend Authority
- ✅ Backend engine is authoritative for all decisions
- ✅ UI never executes trades directly
- ✅ UI never bypasses engine
- ✅ Engine state is source of truth

### 2. Hardware Approval
- ✅ Sensitive actions require hardware approval
- ✅ UI cannot fabricate approvals
- ✅ UI only displays approval status
- ✅ Backend validates all approvals

### 3. Read-Only Investor View
- ✅ Investor UI can NEVER mutate engine state
- ✅ Minimal information display
- ✅ No control capabilities
- ✅ Funding schedule view only

### 4. Chaos Testing Safety
- ✅ Chaos tests NEVER run in LIVE mode
- ✅ UI cannot trigger tests
- ✅ UI only visualizes results
- ✅ Backend controls execution

### 5. Strategy Synthesis Safety
- ✅ LLM strategies are READ-ONLY
- ✅ No auto-promotion
- ✅ LIVE requires hardware approval
- ✅ UI cannot modify strategies

### 6. Chart Bindings
- ✅ Backend is source of truth
- ✅ Charts are read-only
- ✅ Real-time via WS/SSE
- ✅ Exportable for audits

## Usage

### For UI Developers

1. Import types from `schema.types.ts`
2. Use `schema.json` for validation
3. Follow phase-specific documentation
4. Never add UI-side trading logic
5. Always wait for engine state updates
6. Never assume command success
7. Respect hardware approval requirements
8. Implement read-only investor view

### For Backend Developers

1. Ensure API endpoints match schema definitions
2. Maintain engine state authority
3. Enforce hardware approval requirements
4. Prevent chaos tests in LIVE mode
5. Control all strategy promotions
6. Provide real-time data via WebSockets
7. Log all actions for audit trail

---

**Version**: 2.0.0  
**Last Updated**: 2024-01-07  
**Status**: Complete - All Phases Implemented
