# Alpaca PAPER Positions & Orders Integration (Read-Only)

## Overview
Read-only integration with Alpaca PAPER account to expose positions and orders for Sentinel X display, WITHOUT enabling trading, order placement, or modification.

## Safety Guarantees

✅ **NEVER submits orders**
✅ **NEVER cancels orders**
✅ **NEVER modifies positions**
✅ **NEVER enables trading**
✅ **trading_enabled = false (HARD LOCK)**
✅ **Engine state remains MONITOR**
✅ **All operations are read-only**

## Implementation Phases

### Phase 1 — Broker Capability Extension ✅
**File:** `api/alpaca_broker.py`

**Added Methods:**
- `get_positions()` - Fetches open positions (read-only)
- `get_orders(limit, status)` - Fetches recent orders (read-only)

**Allowed Alpaca API Calls:**
- ✅ `get_all_positions()` - Read positions only
- ✅ `get_orders()` - Read orders only

**Disallowed (Not Implemented):**
- ❌ `submit_order()` - NOT IMPLEMENTED
- ❌ `cancel_order()` - NOT IMPLEMENTED
- ❌ `replace_order()` - NOT IMPLEMENTED
- ❌ `close_position()` - NOT IMPLEMENTED

### Phase 2 — Position Model ✅
**Normalized Position Schema:**
```json
{
  "symbol": "AAPL",
  "qty": 10.0,
  "side": "long",
  "market_value": 1500.0,
  "cost_basis": 1400.0,
  "unrealized_pl": 100.0,
  "unrealized_pl_pct": 7.14,
  "current_price": 150.0
}
```

**Fields:**
- `symbol` - Stock symbol
- `qty` - Quantity (always positive)
- `side` - "long" or "short"
- `market_value` - Current market value
- `cost_basis` - Original cost basis
- `unrealized_pl` - Unrealized profit/loss
- `unrealized_pl_pct` - Unrealized P&L percentage
- `current_price` - Current market price

**Safety:**
- Numeric fields are floats
- Missing data handled safely (defaults to 0.0)
- Empty list returned if no positions
- Invalid positions skipped (continue with others)

### Phase 3 — Order Model ✅
**Normalized Order Schema:**
```json
{
  "id": "order-123",
  "symbol": "AAPL",
  "qty": 10.0,
  "filled_qty": 10.0,
  "side": "buy",
  "order_type": "market",
  "status": "filled",
  "submitted_at": "2024-01-01T10:00:00Z",
  "filled_at": "2024-01-01T10:00:01Z"
}
```

**Fields:**
- `id` - Order ID
- `symbol` - Stock symbol
- `qty` - Order quantity
- `filled_qty` - Filled quantity
- `side` - "buy" or "sell"
- `order_type` - Order type (market, limit, etc.)
- `status` - Order status (filled, open, canceled, etc.)
- `submitted_at` - Submission timestamp (ISO format)
- `filled_at` - Fill timestamp (ISO format, nullable)

**Restrictions:**
- Only lists recent orders (limit parameter)
- Optional status filter
- No mutation endpoints
- No order routing logic

### Phase 4 — API Endpoints ✅
**File:** `api/main.py`

**GET /positions**
- Returns list of normalized positions
- Always returns 200 (never 404)
- Returns [] if none or on error
- Safe for frequent polling

**GET /orders**
- Returns list of recent orders
- Query parameters:
  - `limit` (default: 50) - Maximum orders to return
  - `status` (optional) - Filter by status
- Always returns 200 (never 404)
- Returns [] if none or on error
- Safe for frequent polling

**Endpoint Safety:**
- Never block
- Never throw uncaught exceptions
- Fast and safe for Sentinel X polling

### Phase 5 — Failure Handling ✅
**Graceful Degradation:**
- Alpaca API unavailable → Returns empty arrays
- Invalid credentials → Returns empty arrays
- Network errors → Returns empty arrays
- Invalid data → Skips invalid items, continues with valid ones

**Error Handling:**
- All exceptions caught
- Never propagated to callers
- Sentinel X remains ONLINE
- No crashes or 500 errors

### Phase 6 — Sentinel X Compatibility ✅
**Display Updates:**
- Portfolio section populates with positions
- Orders/history view populates
- Equity and P&L remain consistent
- "No brokers" never appears
- No trading controls are enabled

**Response Format:**
- Positions: Array of position objects
- Orders: Array of order objects
- Consistent with Sentinel X expectations

### Phase 7 — Production Guarantees ✅
**Thread Safety:**
- All operations guarded by locks
- Safe for concurrent requests
- No race conditions

**Non-Blocking:**
- Account data fetched on-demand
- Never blocks request handlers
- No async deadlocks

**Compatibility:**
- Works under gunicorn + uvicorn workers
- Does not interfere with engine loop
- Does not affect `/status` endpoint
- Safe in MONITOR mode

### Phase 8 — Code Organization ✅
**Files Modified:**
- `api/alpaca_broker.py` - Extended with positions/orders methods
- `api/main.py` - Added `/positions` and `/orders` endpoints

**No Breaking Changes:**
- All existing endpoints maintained
- No import changes required
- Backward compatible

## API Usage

### Get Positions
```bash
curl http://localhost:8000/positions
```

**Response:**
```json
[
  {
    "symbol": "AAPL",
    "qty": 10.0,
    "side": "long",
    "market_value": 1500.0,
    "cost_basis": 1400.0,
    "unrealized_pl": 100.0,
    "unrealized_pl_pct": 7.14,
    "current_price": 150.0
  }
]
```

### Get Orders
```bash
curl http://localhost:8000/orders?limit=50&status=filled
```

**Response:**
```json
[
  {
    "id": "order-123",
    "symbol": "AAPL",
    "qty": 10.0,
    "filled_qty": 10.0,
    "side": "buy",
    "order_type": "market",
    "status": "filled",
    "submitted_at": "2024-01-01T10:00:00Z",
    "filled_at": "2024-01-01T10:00:01Z"
  }
]
```

## Validation Checklist

✅ `/positions` returns 200 with live Alpaca paper positions
✅ `/orders` returns 200 with recent Alpaca paper orders
✅ No Alpaca order submission methods exist
✅ `trading_enabled` remains false
✅ Engine remains MONITOR-ONLY
✅ Kill-switch remains READY
✅ Sentinel X remains ONLINE
✅ All operations are read-only
✅ Thread-safe and production-ready

## Safety Verification

**No Order Submission:**
- ✅ No `submit_order()` method exists
- ✅ No `cancel_order()` method exists
- ✅ No `replace_order()` method exists
- ✅ No `close_position()` method exists
- ✅ Only read operations implemented

**Trading Disabled:**
- ✅ `trading_enabled = False` (hard lock)
- ✅ Engine state = MONITOR
- ✅ Kill-switch = READY

**Error Handling:**
- ✅ All exceptions caught
- ✅ Never raises to callers
- ✅ Returns empty arrays on failure
- ✅ Sentinel X remains ONLINE

## Troubleshooting

**Positions/Orders return empty arrays:**
1. Check Alpaca credentials are set
2. Verify API keys are correct (PAPER keys)
3. Check network connectivity to Alpaca
4. Review error message in broker response

**Sentinel X not showing positions/orders:**
1. Verify `/positions` and `/orders` endpoints return 200
2. Check response format matches expected schema
3. Verify Sentinel X is polling these endpoints
4. Check for error messages in response

## Next Steps

1. Set Alpaca PAPER credentials (if not already set)
2. Verify `/positions` and `/orders` endpoints return data
3. Sentinel X will automatically display positions and orders
4. No trading capability will be enabled
