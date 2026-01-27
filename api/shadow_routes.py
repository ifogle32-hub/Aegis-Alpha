"""
PHASE 4 — READ-ONLY SHADOW STATUS API

Expose read-only shadow status endpoints:
- GET /shadow/status
- GET /shadow/heartbeat
- GET /shadow/replay/progress

Rules:
- GET-only
- No side effects
- No parameters that mutate state
- Safe for mobile polling
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.status import get_shadow_status_provider
from sentinel_x.shadow.replay_bridge import get_replay_bridge

router = APIRouter(prefix="/shadow", tags=["shadow"])


@router.get("/status")
def get_shadow_status() -> Dict[str, Any]:
    """
    PHASE 6 — GET SHADOW STATUS (READ-ONLY, ALWAYS WORKS)
    
    Get current shadow training status snapshot.
    
    Returns:
        ShadowStatusSnapshot as dictionary
    
    SAFETY:
    - Always returns 200
    - Read-only operation
    - No side effects
    - Never triggers imports that start loops
    - Only reads runtime state
    - Never blocks
    - Never raises exceptions (returns safe defaults)
    - Works even when shadow is disabled
    """
    try:
        # PHASE 6: Use runtime to check if shadow is enabled
        from sentinel_x.shadow.runtime import get_shadow_runtime
        runtime = get_shadow_runtime()
        
        if not runtime.is_started():
            # PHASE 6: Shadow disabled - return safe default
            return {
                "enabled": False,
                "training_active": False,
                "training_state": "IDLE",
                "feed_type": "none",
                "replay_window": {
                    "start": None,
                    "end": None,
                },
                "current_replay_ts": None,
                "tick_counter": 0,
                "heartbeat_age_ms": None,
                "error_count": 0,
                "reason": "shadow not started",
            }
        
        status_provider = get_shadow_status_provider()
        snapshot = status_provider.get_snapshot()
        return snapshot.to_dict()
    except Exception as e:
        logger.error(f"Error getting shadow status: {e}", exc_info=True)
        # Return safe default on error
        return {
            "enabled": False,
            "training_active": False,
            "training_state": "ERROR",
            "feed_type": "none",
            "replay_window": {
                "start": None,
                "end": None,
            },
            "current_replay_ts": None,
            "tick_counter": 0,
            "heartbeat_age_ms": None,
            "error_count": 1,
            "last_error": str(e),
            "reason": "error getting status",
        }


@router.get("/metrics")
def shadow_metrics():
    """
    Read-only Shadow runtime metrics.
    """
    try:
        from sentinel_x.shadow.runtime import get_shadow_runtime
        runtime = get_shadow_runtime()

        if not runtime.is_started():
            return {
                "started": False,
                "idle": True,
                "threads": [],
                "heartbeat": None,
                "trainer": None,
                "cpu_safe": True,
            }

        metrics = runtime.metrics()
        return {
            "started": True,
            "idle": metrics.get("idle", False),
            "threads": metrics.get("threads", []),
            "heartbeat": {
                "last_tick_ms": metrics.get("heartbeat_last_tick_ms"),
                "age_ms": metrics.get("heartbeat_age_ms"),
            },
            "trainer": {
                "last_step_ms": metrics.get("trainer_last_step_ms"),
                "lag_ms": metrics.get("trainer_lag_ms"),
            },
            "cpu_safe": metrics.get("cpu_safe", True),
        }
    except Exception as e:
        return {
            "started": False,
            "error": str(e),
            "cpu_safe": True,
        }


@router.get("/heartbeat")
def get_shadow_heartbeat() -> Dict[str, Any]:
    """
    PHASE 4 — GET SHADOW HEARTBEAT (READ-ONLY)
    
    Get shadow training heartbeat information.
    
    Returns:
        Heartbeat dictionary with:
        - alive: bool
        - heartbeat_age_ms: int | None
        - training_active: bool
        - last_tick_time: str | None
    
    SAFETY:
    - Read-only operation
    - No side effects
    - Safe for frequent polling
    """
    try:
        status_provider = get_shadow_status_provider()
        snapshot = status_provider.get_snapshot()
        
        # Determine if alive (heartbeat age < 60 seconds)
        alive = True
        if snapshot.heartbeat_age_ms is not None:
            alive = snapshot.heartbeat_age_ms < 60000
        
        return {
            "alive": alive,
            "heartbeat_age_ms": snapshot.heartbeat_age_ms,
            "training_active": snapshot.training_active,
            "training_state": snapshot.training_state,
            "tick_counter": snapshot.tick_counter,
        }
    except Exception as e:
        logger.error(f"Error getting shadow heartbeat: {e}", exc_info=True)
        return {
            "alive": False,
            "heartbeat_age_ms": None,
            "training_active": False,
            "training_state": "ERROR",
            "tick_counter": 0,
            "error": str(e),
        }


@router.get("/replay/progress")
def get_replay_progress() -> Dict[str, Any]:
    """
    PHASE 4 — GET REPLAY PROGRESS (READ-ONLY)
    
    Get historical replay progress.
    
    Returns:
        Replay progress dictionary with:
        - replay_active: bool
        - progress: dict with current_tick, total_ticks, progress_pct, etc.
    
    SAFETY:
    - Read-only operation
    - No side effects
    - Safe for frequent polling
    """
    try:
        replay_bridge = get_replay_bridge()
        progress = replay_bridge.get_replay_progress()
        return progress
    except Exception as e:
        logger.error(f"Error getting replay progress: {e}", exc_info=True)
        return {
            "replay_active": False,
            "progress": None,
            "error": str(e),
        }
