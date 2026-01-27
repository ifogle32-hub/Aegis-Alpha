# PHASE 8 — CURSOR VERIFICATION CHECKLIST

## Startup & Import Verification

### ✔ python -m api.main boots cleanly
```bash
python -m api.main
```
**Expected:**
- No ImportError
- No NameError
- No circular import warnings
- Server starts on port 8000
- Logs show: "Aegis Alpha Control Plane - Starting"

### ✔ No circular import warnings
**Check:**
- No warnings about circular imports in logs
- trainer.py does NOT import heartbeat at module level
- heartbeat.py does NOT import trainer at all

### ✔ No NameError / ImportError
**Check:**
- rork.py has `import threading`
- All imports resolve correctly
- No missing module errors

### ✔ curl /status returns JSON
```bash
curl http://localhost:8000/status
```
**Expected:**
- Returns 200 OK
- Returns valid JSON
- Contains: engine, shadow, kill_switch, brokers fields
- Never blocks or hangs

### ✔ curl /shadow/status returns JSON
```bash
curl http://localhost:8000/shadow/status
```
**Expected:**
- Returns 200 OK
- Returns valid JSON
- Contains: enabled, training_active, training_state fields
- Works even when shadow is disabled
- Never blocks or hangs

### ✔ Port 8000 bound once
**Check:**
- Only one process listening on port 8000
- No "port already in use" errors
- If port conflict: use `scripts/kill_dev_ports.sh`

### ✔ ShadowRuntime lifecycle logs visible
**Check logs for:**
- "Shadow runtime started (SHADOW mode)" OR
- "Shadow runtime disabled (LIVE/ARMED mode)"
- "Shadow runtime stopped" on shutdown

## Mode Separation Verification

### ✔ SHADOW MODE
**When system_mode != ARMED:**
- Engine loop NOT started
- Shadow runtime started
- Logs: "Engine loop NOT started (SHADOW mode)"
- Logs: "Shadow runtime started (SHADOW mode)"

### ✔ LIVE MODE
**When system_mode == ARMED:**
- Engine loop started
- Shadow runtime NOT started
- Logs: "Engine loop started (LIVE mode)"
- Logs: "Shadow runtime disabled (LIVE/ARMED mode)"

## Lifespan Handler Verification

### ✔ FastAPI lifespan works
**Check:**
- No @app.on_event("startup") or @app.on_event("shutdown")
- Uses lifespan context manager
- Startup logic in lifespan startup
- Shutdown logic in lifespan shutdown

## Port Safety Verification

### ✔ Port conflict detection
**Test:**
1. Start first instance: `python -m api.main`
2. Try to start second instance
3. Should exit with error: "Port 8000 is already in use"

### ✔ kill_dev_ports.sh works
```bash
./scripts/kill_dev_ports.sh
```
**Expected:**
- Kills processes on ports 8000, 8001
- Kills uvicorn, gunicorn processes
- Kills python api.main processes

## Logging Verification

### ✔ Startup logs
**Check for:**
- "Aegis Alpha Control Plane - Starting"
- PID, Mode, Shadow Enabled
- "Port 8000 is available" or error if in use
- Configuration loaded message
- Shadow runtime start/disable message
- Engine loop start/disable message

### ✔ Shutdown logs
**Check for:**
- "Aegis Alpha Control Plane - Shutting down"
- "Shadow runtime stopped"
- "Engine loop stopped"
- "Shutdown complete"

## Regression Tests

### Run tests
```bash
pytest tests/test_shadow_imports.py -v
pytest tests/test_shadow_status.py -v
```

**Expected:**
- All tests pass
- No circular import errors
- No NameError errors
- Status endpoints work

## What Was Broken

### Root Causes Fixed:

1. **Circular Import**: trainer.py imported heartbeat at module level
   - **Fix**: Lazy import inside __init__ method

2. **NameError**: rork.py used threading.Lock() without import
   - **Fix**: Added `import threading` at top

3. **Deprecated FastAPI Events**: Used @app.on_event("startup")
   - **Fix**: Replaced with lifespan context manager

4. **Port Conflicts**: No detection of existing listeners
   - **Fix**: Added port check in lifespan startup

5. **Mode Confusion**: Engine and shadow both starting
   - **Fix**: Conditional startup based on system mode

6. **No Shutdown Logic**: No cleanup on FastAPI shutdown
   - **Fix**: Added shutdown logic in lifespan

7. **Missing Logging**: Silent failures on startup
   - **Fix**: Added comprehensive startup/shutdown logging

## Verification Commands

```bash
# 1. Clean start
./scripts/kill_dev_ports.sh
python -m api.main

# 2. Check status endpoints
curl http://localhost:8000/status | jq
curl http://localhost:8000/shadow/status | jq

# 3. Check logs
tail -f logs/*.log | grep -E "(Starting|Shutting|Shadow|Engine)"

# 4. Verify port binding
lsof -i:8000

# 5. Run tests
pytest tests/test_shadow_imports.py tests/test_shadow_status.py -v
```
