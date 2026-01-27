# Shadow Training Architecture Hardening

## Overview

Complete refactoring of shadow training system to eliminate circular imports and enforce clean dependency architecture.

## Problem Statement

**Root Cause:**
- `sentinel_x.shadow.trainer` imported `heartbeat`
- `sentinel_x.shadow.heartbeat` imported `trainer`
- Python module initialization order broke → `ImportError: cannot import name 'get_shadow_trainer' from partially initialized module`

**Solution:**
- Architectural refactor (not hacks or lazy imports)
- One-directional dependencies enforced globally
- Clean dependency graph: controller → trainer → heartbeat

## Dependency Architecture

### Dependency Direction Rules (Non-Negotiable)

```
Controller → Trainer → Heartbeat
     ↓
  Status Provider (read-only)
```

**Rules:**
- Controllers OWN trainers
- Trainers OWN helpers (heartbeat, scorers, simulators)
- Helpers NEVER import controllers or trainers
- Status providers READ state but never construct it
- No shadow module may import another shadow module bidirectionally

### Startup Order (PHASE 7)

1. `api.main` imports routers
2. Routers import status provider
3. Status provider imports controller
4. Controller lazily constructs trainer (when `start()` called)
5. Trainer constructs heartbeat (at `__init__`)

**No cycles allowed.**

## Implementation Details

### Phase 2 — Shadow Heartbeat (Passive Component)

**File:** `sentinel_x/shadow/heartbeat.py`

**Changes:**
- Removed ALL imports of trainer or controller
- Implemented passive `ShadowHeartbeatMonitor` class
- Exposes methods: `beat(tick_count, trainer_alive, active_strategies, feed_type, error_count)`
- Stores only primitive state (timestamps, counters)
- Contains NO business logic
- Safe to instantiate multiple times

**Why passive:**
- Eliminates circular imports (heartbeat → trainer → heartbeat)
- Enables clean dependency direction: controller → trainer → heartbeat
- Allows heartbeat to be used independently if needed

### Phase 3 — Shadow Trainer (Owner of Heartbeat)

**File:** `sentinel_x/shadow/trainer.py`

**Changes:**
- Owns exactly one `ShadowHeartbeatMonitor` instance (created in `__init__`)
- Calls `heartbeat.beat()` during `on_tick` with all required parameters
- Tracks `tick_counter` locally
- Exposes `get_status()` that aggregates:
  - tick_counter
  - heartbeat status
  - error state
  - training state

**Why trainer owns heartbeat:**
- Eliminates circular imports (trainer → heartbeat, one direction)
- Heartbeat is passive - never fetches state from trainer
- Trainer provides all data to `heartbeat.beat()` method

### Phase 4 — Controller Owns Trainer (No Cross-Imports)

**File:** `sentinel_x/shadow/controller.py`

**Changes:**
- Lazily constructs the `ShadowTrainer` (only when `start()` called)
- Stores trainer as private attribute
- Never imported by trainer or heartbeat
- Uses `TYPE_CHECKING` for type hints (no runtime imports)
- Exposes lightweight `get_status()` snapshot
- Controls lifecycle: STARTING → RUNNING → ERROR → STOPPED

**Why controller owns trainer:**
- Controller is the ONLY component allowed to start/stop training
- Lazy construction prevents circular imports at module load time
- Clean separation of concerns

### Phase 5 — Status Provider (Read-Only Snapshot)

**File:** `sentinel_x/shadow/status.py`

**Changes:**
- Imports ONLY: `ShadowTrainingController`, `TrainingState` enum
- NEVER imports trainer or heartbeat directly
- Reads trainer + heartbeat state THROUGH controller references
- Produces immutable `ShadowStatusSnapshot` objects
- NEVER raises exceptions outward
- Thread-safe and lock-minimal

**Why read-only:**
- Eliminates circular imports (status → controller → trainer → heartbeat)
- Enables safe status queries without starting training
- Allows status to work even if trainer is not initialized

### Phase 6 — Shadow API Safety Guarantees

**File:** `api/shadow_routes.py`

**Endpoints:**
- `GET /shadow/status` - ShadowStatusSnapshot
- `GET /shadow/heartbeat` - Heartbeat information
- `GET /shadow/replay/progress` - Replay progress

**Guarantees:**
- Triggers no side effects
- Does not instantiate trainers
- Does not start replay
- Does not block engine loop
- Always returns valid JSON response

**Failures degrade gracefully to:**
```json
{
  "enabled": false,
  "training_active": false,
  "training_state": "ERROR"
}
```

## Testing

### Import Tests (`tests/test_shadow_imports.py`)

Tests verify:
- Importing `api.main` does NOT raise `ImportError`
- Importing `shadow.status` does NOT start training
- No circular imports exist
- All modules load correctly

### Status Tests (`tests/test_shadow_status.py`)

Tests verify:
- `/shadow/status` works before and after training starts
- Status provider is read-only
- Status provider never starts training
- Status provider handles missing trainer gracefully

## Files Modified

1. `sentinel_x/shadow/heartbeat.py` - Refactored to passive component
2. `sentinel_x/shadow/trainer.py` - Owns heartbeat instance
3. `sentinel_x/shadow/controller.py` - Lazy trainer construction
4. `sentinel_x/shadow/status.py` - Read-only status provider
5. `api/shadow_routes.py` - Unchanged API surface (already safe)
6. `tests/test_shadow_imports.py` - New import tests
7. `tests/test_shadow_status.py` - New status tests

## Quality Bar

✅ No circular imports  
✅ Deterministic behavior  
✅ Safe for long-running daemon  
✅ Shadow-only (no execution leakage)  
✅ Production-grade dependency structure  
✅ Clean startup and shutdown semantics

## Verification

```bash
# Test imports
python -c "from sentinel_x.shadow.heartbeat import ShadowHeartbeatMonitor; from sentinel_x.shadow.trainer import ShadowTrainer; from sentinel_x.shadow.controller import ShadowTrainingController; from sentinel_x.shadow.status import ShadowStatusProvider; print('All imports successful!')"

# Run tests
pytest tests/test_shadow_imports.py tests/test_shadow_status.py -v
```

## Status

**ALL PHASES COMPLETE** ✅

The shadow training system now has a clean, production-grade dependency architecture with no circular imports.
