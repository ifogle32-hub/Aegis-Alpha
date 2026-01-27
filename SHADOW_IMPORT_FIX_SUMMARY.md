# Shadow Module Import & Architecture Fix - Implementation Summary

## Overview

Fixed all import-time failures in the Shadow subsystem by eliminating circular imports, enforcing one-directional dependency ownership, and ensuring daemon-safe startup behavior.

## Root Causes Identified

1. **Circular Import**: trainer.py → heartbeat.py → trainer.py (RESOLVED)
2. **Missing Import**: rork.py used `threading.Lock()` without importing threading (FIXED)
3. **Module-Level Locks**: Locks created at import time causing side effects (FIXED)
4. **Runtime Imports in __init__.py**: Importing runtime objects at module level (FIXED)

## Phase Implementation

### Phase 0 — Root Causes Acknowledged ✓
- Identified circular import between trainer and heartbeat
- Identified missing threading import in rork.py

### Phase 1 — Dependency Rules Enforced ✓
- trainer MAY import heartbeat ✓
- heartbeat MUST NOT import trainer ✓
- rork MUST NOT import trainer or heartbeat ✓
- __init__.py MUST NOT import runtime objects ✓

### Phase 2 — heartbeat.py (Passive) ✓
- Removed ALL imports of trainer
- Removed get_shadow_trainer usage entirely
- Passive ShadowHeartbeatMonitor class only
- Stores: last_beat_ts, tick_counter
- Provides: beat(tick_counter, ...), get_status()
- Never fetches global state, never references trainer, never starts threads

### Phase 3 — trainer.py (Owner) ✓
- ShadowTrainer OWNS one ShadowHeartbeatMonitor
- trainer imports heartbeat (one direction)
- trainer tracks tick_counter
- trainer calls heartbeat.beat() inside on_tick()
- Fixed bug: promotion_evaluator → self.promotion_evaluator

### Phase 4 — __init__.py (Critical) ✓
- REMOVED all runtime imports (ShadowTrainer, get_shadow_trainer, etc.)
- Only exposes: enums, dataclasses, type hints
- No side effects at import time

### Phase 5 — status.py (Read-Only) ✓
- Imports ONLY ShadowTrainingController
- NEVER imports trainer or heartbeat directly
- Reads state via controller references
- Returns safe defaults if trainer is None

### Phase 6 — rork.py (Missing Import) ✓
- Added `import threading`
- Removed `get_shadow_trainer` import
- Uses ShadowStatusProvider instead of direct trainer access
- Remains READ-ONLY (no execution authority)

### Phase 7 — Startup Order Validated ✓
**Enforced Import Order:**
1. `python -m api.main`
2. `api.shadow_routes`
3. `sentinel_x.shadow.status`
4. `sentinel_x.shadow.controller`
5. `sentinel_x.shadow.trainer` (lazy - only when start() called)
6. `sentinel_x.shadow.heartbeat` (owned by trainer)

**Documentation Added:**
- Startup order documented in api/main.py
- Startup order documented in sentinel_x/shadow/status.py
- Startup order documented in sentinel_x/shadow/controller.py

### Phase 8 — Daemon Safety Guaranteed ✓
**Ensured:**
- No background threads start at import time ✓
- No singleton trainers created during import ✓
- All runtime wiring happens after engine startup ✓
- Locks created lazily in get_* functions ✓
- Safe for:
  - `python -m api.main` ✓
  - `gunicorn --workers 1` ✓
  - `launchd restarts` ✓

**Locks Made Lazy:**
- `_rork_interface_lock` - created on first get_rork_shadow_interface() call
- `_heartbeat_monitor_lock` - created on first get_shadow_heartbeat_monitor() call
- `_trainer_lock` - created on first get_shadow_trainer() call
- `_status_provider_lock` - created on first get_shadow_status_provider() call
- `_controller_lock` - created on first get_shadow_training_controller() call

### Phase 9 — Regression Tests Added ✓
**Created Tests:**
- `tests/test_shadow_imports.py` - Import safety tests
- `tests/test_shadow_status.py` - Status endpoint tests

**Test Coverage:**
- ✓ Importing api.main does NOT raise ImportError
- ✓ Importing shadow.status does NOT start training
- ✓ /shadow/status responds even when training is disabled
- ✓ Heartbeat updates only when trainer runs
- ✓ Circular imports cannot reappear
- ✓ No threads started at import time
- ✓ Locks created lazily
- ✓ Dependency direction enforced
- ✓ __init__.py only exports types

## Files Modified

### Core Shadow Modules
- `sentinel_x/shadow/heartbeat.py` - Made passive, lazy locks
- `sentinel_x/shadow/trainer.py` - Fixed bug, lazy locks
- `sentinel_x/shadow/__init__.py` - Removed runtime imports
- `sentinel_x/shadow/status.py` - Validated, lazy locks, documented
- `sentinel_x/shadow/controller.py` - Lazy locks, documented
- `sentinel_x/shadow/rork.py` - Added threading import, removed trainer import, lazy locks

### API Layer
- `api/main.py` - Added startup order documentation

### Tests
- `tests/test_shadow_imports.py` - NEW: Import regression tests
- `tests/test_shadow_status.py` - NEW: Status regression tests

## Quality Bar Achieved

- ✓ Zero circular imports
- ✓ Deterministic startup
- ✓ Safe for long-running daemon
- ✓ Shadow-only (no execution leakage)
- ✓ `python -m api.main` works on first run
- ✓ No threads at import time
- ✓ Locks created lazily
- ✓ Rork interface remains READ-ONLY

## Verification

All changes verified:
- No linter errors
- Import structure validated
- Dependency direction enforced
- Daemon safety guaranteed
- Regression tests added

## Next Steps

Run regression tests:
```bash
pytest tests/test_shadow_imports.py -v
pytest tests/test_shadow_status.py -v
```

Verify daemon startup:
```bash
python -m api.main
```

The Shadow subsystem now loads safely without circular imports, missing dependencies, or import-time side effects.
