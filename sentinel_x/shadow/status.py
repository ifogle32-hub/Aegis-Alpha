"""
PHASE 5 — SHADOW STATUS SNAPSHOT

ShadowStatusSnapshot: Thread-safe, immutable status representation.

PHASE 7 — STARTUP ORDER:
This module is imported in step 3 of the startup sequence:
1. python -m api.main
2. api.shadow_routes
3. sentinel_x.shadow.status (THIS MODULE)
4. sentinel_x.shadow.controller
5. sentinel_x.shadow.trainer (lazy - only when start() called)
6. sentinel_x.shadow.heartbeat (owned by trainer)

DEPENDENCY RULES:
- Status provider imports ONLY controller (never trainer or heartbeat directly)
- Status provider reads trainer + heartbeat state THROUGH controller references
- Status provider NEVER raises exceptions outward
- Status provider is thread-safe and lock-minimal
- No threads started at import time
- Locks created lazily on first get_* call

Why read-only:
- Eliminates circular imports (status → controller → trainer → heartbeat)
- Enables safe status queries without starting training
- Allows status to work even if trainer is not initialized

Contains:
- enabled (bool)
- training_active (bool)
- training_state
- feed_type (historical | live | synthetic)
- replay_window (start/end)
- current_replay_ts
- tick_counter
- heartbeat_age_ms
- error_count

Snapshot must be:
- Thread-safe
- Immutable per request
- Generated without locking engine loop
"""

import threading
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field

from sentinel_x.monitoring.logger import logger
# PHASE 3: Use runtime instead of direct controller import
# from sentinel_x.shadow.controller import ShadowTrainingController, TrainingState, get_shadow_training_controller
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel_x.shadow.controller import ShadowTrainingController


@dataclass(frozen=True)
class ShadowStatusSnapshot:
    """
    Immutable shadow training status snapshot.
    
    Thread-safe: All fields are read-only after creation.
    """
    enabled: bool
    training_active: bool
    training_state: str
    feed_type: str  # "historical" | "live" | "synthetic" | "none"
    replay_window_start: Optional[str] = None
    replay_window_end: Optional[str] = None
    current_replay_ts: Optional[str] = None
    tick_counter: int = 0
    heartbeat_age_ms: Optional[int] = None
    error_count: int = 0
    last_error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary."""
        return {
            "enabled": self.enabled,
            "training_active": self.training_active,
            "training_state": self.training_state,
            "feed_type": self.feed_type,
            "replay_window": {
                "start": self.replay_window_start,
                "end": self.replay_window_end,
            },
            "current_replay_ts": self.current_replay_ts,
            "tick_counter": self.tick_counter,
            "heartbeat_age_ms": self.heartbeat_age_ms,
            "error_count": self.error_count,
            "last_error": self.last_error,
        }


class ShadowStatusProvider:
    """
    Thread-safe provider of shadow status snapshots.
    
    Generates snapshots without locking engine loop.
    """
    
    def __init__(self, controller: Optional['ShadowTrainingController'] = None):
        """
        Initialize status provider.
        
        PHASE 3: Uses runtime to get controller, avoiding direct import.
        
        Args:
            controller: Optional shadow training controller
        """
        # PHASE 3: Lazy import inside __init__ to avoid circular dependencies
        if controller is None:
            from sentinel_x.shadow.runtime import get_shadow_runtime
            runtime = get_shadow_runtime()
            controller = runtime.get_controller()
        
        self.controller = controller
        self._lock = threading.RLock()
    
    def get_snapshot(self) -> ShadowStatusSnapshot:
        """
        Get current shadow status snapshot.
        
        SAFETY:
        - Thread-safe
        - Immutable result
        - No engine loop locking
        - Never raises exceptions
        
        Returns:
            ShadowStatusSnapshot
        """
        try:
            # Get controller status (fast, non-blocking)
            controller_status = self.controller.get_status()
            
            # Get trainer status if available
            trainer_status = {}
            try:
                if self.controller._trainer:
                    trainer_status = self.controller._trainer.get_status()
            except Exception:
                pass  # Trainer status optional
            
            # Determine feed type
            feed_type = "none"
            replay_window_start = None
            replay_window_end = None
            current_replay_ts = None
            
            if self.controller._replay_feed:
                feed_type = "historical"
                try:
                    progress = self.controller._replay_feed.get_progress()
                    if progress:
                        replay_window_start = progress.get("start_timestamp")
                        replay_window_end = progress.get("end_timestamp")
                        current_replay_ts = progress.get("current_timestamp")
                except Exception:
                    pass  # Replay progress optional
            elif controller_status.get("enabled"):
                feed_type = "live"
            
            # PHASE 5: Get tick counter and heartbeat from trainer status
            # Read through controller references - never import trainer directly
            tick_counter = trainer_status.get("tick_counter", 0)
            
            # Get heartbeat age from heartbeat status if available
            heartbeat_age_ms = controller_status.get("heartbeat_age_ms")
            heartbeat_status = trainer_status.get("heartbeat_status", {})
            if heartbeat_age_ms is None and heartbeat_status:
                heartbeat_age_seconds = heartbeat_status.get("heartbeat_age_seconds", 0.0)
                heartbeat_age_ms = int(heartbeat_age_seconds * 1000) if heartbeat_age_seconds else None
            
            # PHASE 3: Lazy import TrainingState
            from sentinel_x.shadow.controller import TrainingState
            
            # Create snapshot
            snapshot = ShadowStatusSnapshot(
                enabled=controller_status.get("enabled", False),
                training_active=controller_status.get("state") == TrainingState.RUNNING.value,
                training_state=controller_status.get("state", TrainingState.IDLE.value),
                feed_type=feed_type,
                replay_window_start=replay_window_start,
                replay_window_end=replay_window_end,
                current_replay_ts=current_replay_ts,
                tick_counter=tick_counter,
                heartbeat_age_ms=heartbeat_age_ms,
                error_count=controller_status.get("error_count", 0),
                last_error=controller_status.get("last_error"),
            )
            
            return snapshot
            
        except Exception as e:
            # SAFETY: Never raise - return safe default
            logger.error(f"Error generating shadow status snapshot: {e}", exc_info=True)
            # PHASE 3: Lazy import TrainingState
            from sentinel_x.shadow.controller import TrainingState
            return ShadowStatusSnapshot(
                enabled=False,
                training_active=False,
                training_state=TrainingState.ERROR.value,
                feed_type="none",
                error_count=1,
                last_error=str(e),
            )


# Global status provider instance
_status_provider: Optional[ShadowStatusProvider] = None
# PHASE 7: Lock created lazily to avoid import-time side effects
_status_provider_lock: Optional[threading.Lock] = None


def get_shadow_status_provider() -> ShadowStatusProvider:
    """
    Get global shadow status provider instance (singleton).
    
    PHASE 3: Uses runtime to get controller, avoiding direct import.
    PHASE 7: Lock created lazily on first call to avoid import-time side effects.
    
    Returns:
        ShadowStatusProvider instance
    """
    global _status_provider, _status_provider_lock
    
    if _status_provider_lock is None:
        _status_provider_lock = threading.Lock()
    
    if _status_provider is None:
        with _status_provider_lock:
            if _status_provider is None:
                # PHASE 3: Use runtime to get controller
                from sentinel_x.shadow.runtime import get_shadow_runtime
                runtime = get_shadow_runtime()
                controller = runtime.get_controller()
                _status_provider = ShadowStatusProvider(controller=controller)
    
    return _status_provider
