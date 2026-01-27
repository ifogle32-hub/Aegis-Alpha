# Alpaca PAPER Broker Integration

## Overview
Read-only integration with Alpaca PAPER trading account for account information display in Sentinel X, WITHOUT enabling trading or order execution.

## Safety Guarantees

✅ **NEVER places orders**
✅ **NEVER enables trading**
✅ **trading_enabled = false (HARD LOCK)**
✅ **Engine state remains MONITOR**
✅ **No breaking changes to existing endpoints**
✅ **No secrets hard-coded**

## Implementation Phases

### Phase 1 — Dependency Installation ✅
- `alpaca-py>=0.20.0` already in `sentinel_x/requirements.txt`
- Compatible with Python 3.12+

### Phase 2 — Environment Configuration ✅
Reads credentials from environment variables:
- `ALPACA_API_KEY_ID` - Alpaca API key
- `ALPACA_API_SECRET_KEY` - Alpaca secret key
- `ALPACA_BASE_URL` - Defaults to `https://paper-api.alpaca.markets`

**Safety:**
- No secrets logged
- Always uses PAPER endpoint
- Never uses live trading keys

### Phase 3 — Broker Adapter (Read-Only) ✅
**File:** `api/alpaca_broker.py`

**Features:**
- Connects to Alpaca PAPER account
- Fetches account information only (equity, cash, buying_power)
- Never submits orders
- Never modifies account state
- Thread-safe implementation

**Broker Fields:**
- `id`: "alpaca-paper"
- `type`: "paper"
- `status`: CONNECTED / DISCONNECTED
- `trading_enabled`: **false (HARD LOCK)**
- `equity`: Account equity
- `cash`: Available cash
- `buying_power`: Buying power
- `currency`: USD

**Error Handling:**
- Returns DISCONNECTED status on failure
- Includes error message (never raises exceptions)
- Sentinel X remains ONLINE even if Alpaca fails

### Phase 4 — API Integration ✅
**File:** `api/brokers.py` + `api/main.py`

**Integration:**
- Alpaca broker registered in `BrokerRegistry`
- `/brokers` endpoint returns Alpaca broker data
- Updates account data on each API call (non-blocking)
- Thread-safe broker registry

**Endpoint Behavior:**
- Always returns 200 (never 404)
- Never throws uncaught exceptions
- Fast and safe for frequent polling
- Alpaca unavailable does not break endpoint

### Phase 5 — Sentinel X Compatibility ✅
**Broker Response Format:**
```json
{
  "id": "alpaca-paper",
  "type": "paper",
  "status": "CONNECTED",
  "trading_enabled": false,
  "equity": 100000.0,
  "cash": 50000.0,
  "buying_power": 200000.0,
  "currency": "USD"
}
```

**Sentinel X Display:**
- "No brokers" state disappears
- Equity and portfolio sections populate
- Kill-switch remains READY
- Mode remains MONITOR
- No trading controls become available

### Phase 6 — Production Guarantees ✅
**Thread Safety:**
- All broker operations guarded by locks
- Non-blocking account data fetching
- Safe for concurrent requests

**Non-Blocking:**
- Account data fetched on-demand
- Never blocks request handlers
- No async deadlocks

**Compatibility:**
- Works under gunicorn + uvicorn workers
- Does not interfere with engine loop
- Does not affect `/status` endpoint

### Phase 7 — Code Organization ✅
**Files Modified:**
- `api/alpaca_broker.py` - NEW: Alpaca broker adapter
- `api/brokers.py` - UPDATED: Broker registry with Alpaca integration
- `api/main.py` - UPDATED: Endpoint documentation

**No Breaking Changes:**
- All existing endpoints maintained
- No import changes required
- Backward compatible

## Configuration

### Environment Variables
Set these in your environment or `.env` file:
```bash
export ALPACA_API_KEY_ID="your_paper_api_key"
export ALPACA_API_SECRET_KEY="your_paper_secret_key"
export ALPACA_BASE_URL="https://paper-api.alpaca.markets"  # Optional, defaults to paper
```

### Verification
1. Check broker availability:
   ```bash
   curl http://localhost:8000/brokers
   ```

2. Expected response (with Alpaca configured):
   ```json
   [
     {
       "id": "paper-sim",
       "type": "simulated",
       "status": "CONNECTED",
       "trading_enabled": false,
       "equity": 100000.0,
       "currency": "USD",
       "cash": 0.0,
       "buying_power": 0.0
     },
     {
       "id": "alpaca-paper",
       "type": "paper",
       "status": "CONNECTED",
       "trading_enabled": false,
       "equity": 100000.0,
       "cash": 50000.0,
       "buying_power": 200000.0,
       "currency": "USD"
     }
   ]
   ```

3. If Alpaca unavailable:
   ```json
   [
     {
       "id": "paper-sim",
       "type": "simulated",
       "status": "CONNECTED",
       "trading_enabled": false,
       "equity": 100000.0,
       "currency": "USD",
       "cash": 0.0,
       "buying_power": 0.0
     },
     {
       "id": "alpaca-paper",
       "type": "paper",
       "status": "DISCONNECTED",
       "trading_enabled": false,
       "equity": 0.0,
       "currency": "USD",
       "cash": 0.0,
       "buying_power": 0.0
     }
   ]
   ```

## Validation Checklist

✅ `/brokers` returns 200
✅ Sentinel X shows Alpaca Paper instead of "No brokers"
✅ Equity and buying power match Alpaca paper account
✅ No orders can be placed (trading_enabled = false)
✅ Kill-switch remains READY
✅ Engine remains MONITOR-ONLY
✅ No breaking changes to existing endpoints
✅ Thread-safe and production-ready

## Troubleshooting

**Alpaca shows DISCONNECTED:**
1. Check environment variables are set
2. Verify API keys are correct (PAPER keys, not LIVE)
3. Check network connectivity to Alpaca
4. Review error message in broker response

**Broker not appearing:**
1. Verify `alpaca-py` is installed
2. Check environment variables
3. Review application logs

**Sentinel X still shows "No brokers":**
1. Verify `/brokers` endpoint returns 200
2. Check broker response format matches expected schema
3. Verify Sentinel X is polling `/brokers` endpoint

## Safety Verification

All safety rules enforced:
- ✅ `trading_enabled` is hard-coded to `False` in `AlpacaPaperBroker`
- ✅ No order placement methods exist
- ✅ Engine state never changes from MONITOR
- ✅ Kill-switch remains READY
- ✅ All operations are read-only
