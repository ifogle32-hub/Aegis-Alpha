# PnL Visualization & Multi-Broker Implementation Summary

## Files Added/Modified

### New Files
1. **sentinel_x/execution/broker_base.py** - Base broker interface
2. **sentinel_x/execution/broker_manager.py** - Broker manager for multi-broker support
3. **sentinel_x/monitoring/pnl.py** - Real-time PnL tracking engine

### Modified Files
1. **sentinel_x/execution/paper_executor.py** - Implements BaseBroker interface
2. **sentinel_x/execution/alpaca_executor.py** - Implements BaseBroker interface
3. **sentinel_x/core/engine.py** - Integrated PnL engine, emits broker_state events
4. **sentinel_x/api/rork_server.py** - Added metrics endpoints
5. **sentinel_x/main.py** - Registers brokers with broker manager

## New Broker Interface

### BaseBroker Abstract Class
All brokers must implement:
- `name` property - Broker identifier
- `mode` property - "PAPER" or "LIVE"
- `get_account()` - Account information
- `get_positions()` - Current positions
- `submit_order()` - Submit order
- `cancel_all_orders()` - Cancel all orders
- `get_fills()` - Get fill history (optional)

### Current Implementations
- **PaperExecutor** - Simulated broker (PAPER mode)
- **AlpacaExecutor** - Alpaca API broker (PAPER or LIVE based on URL)

## New API Endpoints

### Metrics Endpoints (Read-Only)
- **GET /metrics/pnl** - Get current PnL metrics
  - Returns: total_realized, total_unrealized, total_pnl, by_strategy
  
- **GET /metrics/strategies** - Get strategy performance metrics
  - Returns: List of strategies with trades_count, win_rate, avg_return, realized_pnl, max_drawdown
  
- **GET /metrics/brokers** - Get broker information
  - Returns: List of brokers, active broker, account info, positions count

## Event Types Added

### pnl_update
```json
{
  "type": "pnl_update",
  "total_realized": 150.50,
  "total_unrealized": 25.00,
  "total_pnl": 175.50,
  "by_strategy": {
    "TestStrategy": {
      "trades_count": 5,
      "wins": 3,
      "losses": 2,
      "win_rate": 0.6,
      "avg_return": 30.10,
      "realized_pnl": 150.50,
      "max_drawdown": 10.00,
      "last_trade_ts": "2024-01-01T12:00:00Z"
    }
  },
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### strategy_metrics
```json
{
  "type": "strategy_metrics",
  "strategy": "TestStrategy",
  "trades_count": 5,
  "wins": 3,
  "losses": 2,
  "win_rate": 0.6,
  "avg_return": 30.10,
  "realized_pnl": 150.50,
  "max_drawdown": 10.00,
  "last_trade_ts": "2024-01-01T12:00:00Z",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### broker_state (enhanced)
```json
{
  "type": "broker_state",
  "broker": "alpaca",
  "mode": "PAPER",
  "cash": 50000.00,
  "equity": 100150.50,
  "positions": [...],
  "positions_count": 2,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## How to Verify PnL Accuracy

### 1. Paper Executor
- Start system in PAPER mode
- Execute test order via `/test-order`
- Check `/metrics/pnl` endpoint
- Verify:
  - Realized PnL updates when positions close
  - Unrealized PnL updates with position prices
  - Per-strategy metrics track correctly

### 2. Alpaca Paper
- Configure Alpaca PAPER credentials
- Execute trades
- Compare:
  - `/metrics/pnl` total vs Alpaca dashboard equity change
  - Position counts match
  - Broker reconciliation events show no discrepancies

### 3. Strategy Metrics
- Activate multiple strategies
- Execute trades from each
- Verify `/metrics/strategies` shows:
  - Correct trade counts per strategy
  - Win/loss ratios
  - PnL attribution

## How to Safely Add a New Broker

### Step 1: Implement BaseBroker
```python
from sentinel_x.execution.broker_base import BaseBroker

class NewBroker(BaseBroker):
    @property
    def name(self) -> str:
        return "newbroker"
    
    @property
    def mode(self) -> str:
        return "PAPER"  # or "LIVE"
    
    def get_account(self) -> Optional[Dict]:
        # Implement account retrieval
        pass
    
    def get_positions(self) -> List[Dict]:
        # Implement position retrieval
        pass
    
    def submit_order(self, symbol, side, qty, price=None, strategy=""):
        # Implement order submission
        pass
    
    def cancel_all_orders(self) -> int:
        # Implement order cancellation
        pass
    
    def get_fills(self, since_ts=None) -> List[Dict]:
        # Optional: implement fill history
        pass
```

### Step 2: Register Broker
In `main.py`:
```python
from sentinel_x.execution.broker_manager import get_broker_manager

new_broker = NewBroker(...)
broker_manager = get_broker_manager()
broker_manager.register_broker(new_broker)
```

### Step 3: Switch Active Broker
```python
# Only when idle (no open positions)
broker_manager.set_active_broker("newbroker")
```

### Step 4: Update OrderRouter (if needed)
OrderRouter automatically uses active executor based on `config.trade_mode`.
For broker switching, update router to use broker_manager.

## Paper → Live Graduation Flow

### Prerequisites
1. **Alpaca LIVE credentials configured:**
   ```bash
   export ALPACA_API_KEY="your_live_key"
   export ALPACA_SECRET_KEY="your_live_secret"
   export ALPACA_BASE_URL="https://api.alpaca.markets"  # LIVE endpoint
   ```

2. **Verify credentials:**
   ```bash
   curl -X GET "https://api.alpaca.markets/v2/account" \
     -H "APCA-API-KEY-ID: $ALPACA_API_KEY" \
     -H "APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"
   ```

### Safe Promotion Steps

1. **Start in PAPER mode** (default)
   - System boots with PAPER broker active
   - Test all strategies
   - Verify PnL tracking works

2. **Switch to LIVE mode** (requires confirmation)
   ```bash
   curl -X POST "http://localhost:8000/control/mode" \
     -H "X-API-Key: YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"mode": "LIVE", "confirm": true}'
   ```

3. **Monitor closely**
   - Watch broker_state events for reconciliation
   - Verify positions match between engine and broker
   - Check for error events

4. **Safety features**
   - LIVE mode requires explicit confirmation
   - Broker mode clearly displayed in UI
   - Kill switch stops all trading immediately
   - All orders logged and auditable

## UI Implementation Guide

### PnL Chart Component
```typescript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:8000/ws/events');

// Listen for pnl_update events
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'pnl_update') {
    updatePnLChart(data);
  }
};

// Display:
// - Line chart with total_pnl over time
// - Toggle: total / per-strategy
// - Separate realized (green) vs unrealized (yellow)
// - PAPER mode watermark
// - LIVE mode red banner
```

### Strategy Performance Table
```typescript
// Listen for strategy_metrics events
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'strategy_metrics') {
    updateStrategyTable(data);
  }
};

// Columns:
// - Strategy name
// - Trades count
// - Win % (color-coded: green > 50%, red < 50%)
// - Avg R (return per trade)
// - PnL (realized)
// - Max DD (drawdown)
// - Status (Active/Disabled badge)
```

### Broker Panel
```typescript
// Listen for broker_state events
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'broker_state') {
    updateBrokerPanel(data);
  }
};

// Display:
// - Active broker name (badge)
// - Mode: PAPER (yellow) / LIVE (red banner)
// - Cash / Equity
// - Positions count
// - Last reconciliation status
// - Broker API endpoint
```

## Testing Checklist

- [x] PnL engine tracks realized PnL from fills
- [x] PnL engine tracks unrealized PnL from positions
- [x] Per-strategy metrics update correctly
- [x] Events stream via WebSocket
- [x] Metrics endpoints return cached values
- [x] Broker manager supports multiple brokers
- [x] Paper executor implements BaseBroker
- [x] Alpaca executor implements BaseBroker
- [ ] UI components (TODO - React implementation)
- [ ] Broker reconciliation loop (TODO - Phase 3)
- [ ] Strategy metrics survive exceptions (verified in code)

## Notes

- PnL engine is in-memory (resets on restart)
- All PnL calculations are non-blocking
- Broker failures don't stop engine
- Strategy exceptions don't break metrics
- Events are JSON-serializable
- All endpoints are read-only (no mutations)
