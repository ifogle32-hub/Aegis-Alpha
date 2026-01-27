"""
PHASE 2 — SHADOW HEARTBEAT (PASSIVE COMPONENT)

ShadowHeartbeatMonitor: Passive heartbeat tracking component.

DEPENDENCY RULES:
- Heartbeat is PASSIVE - never imports trainer or controller
- Heartbeat stores only primitive state (timestamps, counters)
- Heartbeat contains NO business logic
- Heartbeat is safe to instantiate multiple times
- Trainer OWNS heartbeat and calls beat() method

Why passive:
- Eliminates circular imports (heartbeat → trainer → heartbeat)
- Enables clean dependency direction: controller → trainer → heartbeat
- Allows heartbeat to be used independently if needed
"""

from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import threading
import time
import json
import os
from pathlib import Path

from sentinel_x.monitoring.logger import logger


@dataclass
class ShadowHeartbeat:
    """
    Shadow training heartbeat data (immutable snapshot).
    """
    timestamp: datetime
    tick_count: int
    trainer_alive: bool
    active_strategies: int
    feed_type: str  # "live" | "replay" | "synthetic" | "unknown"
    last_tick_ts: Optional[datetime]
    error_count: int
    heartbeat_age_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert heartbeat to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "tick_count": self.tick_count,
            "trainer_alive": self.trainer_alive,
            "active_strategies": self.active_strategies,
            "feed_type": self.feed_type,
            "last_tick_ts": self.last_tick_ts.isoformat() + "Z" if self.last_tick_ts else None,
            "error_count": self.error_count,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
        }


class ShadowHeartbeatMonitor:
    """
    Passive shadow heartbeat monitor.
    
    DEPENDENCY RULES:
    - NEVER imports trainer, controller, or any shadow business logic
    - Stores only primitive state (timestamps, counters)
    - Contains NO business logic
    - Safe to instantiate multiple times
    
    Usage:
    - Trainer creates instance: heartbeat = ShadowHeartbeatMonitor()
    - Trainer calls: heartbeat.beat(tick_count, trainer_alive, active_strategies, feed_type, error_count)
    - Status provider reads: heartbeat.get_status()
    """
    
    def __init__(
        self,
        heartbeat_interval_ticks: int = 10,
        log_interval_seconds: float = 30.0,
    ):
        """
        Initialize heartbeat monitor.
        
        Args:
            heartbeat_interval_ticks: Emit heartbeat every N ticks (for callers to check)
            log_interval_seconds: Log heartbeat every M seconds
        """
        self.heartbeat_interval_ticks = heartbeat_interval_ticks
        self.log_interval_seconds = log_interval_seconds
        
        # State (primitive types only)
        self.last_heartbeat: Optional[ShadowHeartbeat] = None
        self.heartbeat_history: list[ShadowHeartbeat] = []
        self.last_log_time: float = 0.0
        self.last_tick_ts: Optional[float] = None
        
        self._lock = threading.RLock()
        self._heartbeat_file = Path("/tmp/sentinel_x_shadow_heartbeat.json")
        
        logger.info("ShadowHeartbeatMonitor initialized (passive component)")
    
    def tick(self) -> None:
        """Update last tick timestamp."""
        self.last_tick_ts = time.time()
    
    def beat(
        self,
        tick_count: int,
        trainer_alive: bool,
        active_strategies: int,
        feed_type: str,
        error_count: int,
        last_tick_ts: Optional[datetime] = None,
    ) -> ShadowHeartbeat:
        """
        Record heartbeat beat.
        
        Called by trainer during tick processing.
        
        Args:
            tick_count: Current tick count
            trainer_alive: Whether trainer is active
            active_strategies: Number of active strategies
            feed_type: Feed type ("live" | "replay" | "synthetic" | "unknown")
            error_count: Current error count
            last_tick_ts: Last tick timestamp (optional)
        
        Returns:
            ShadowHeartbeat instance
        """
        try:
            # Calculate heartbeat age
            heartbeat_age = 0.0
            if self.last_heartbeat:
                age_delta = (datetime.utcnow() - self.last_heartbeat.timestamp).total_seconds()
                heartbeat_age = age_delta
            
            heartbeat = ShadowHeartbeat(
                timestamp=datetime.utcnow(),
                tick_count=tick_count,
                trainer_alive=trainer_alive,
                active_strategies=active_strategies,
                feed_type=feed_type,
                last_tick_ts=last_tick_ts,
                error_count=error_count,
                heartbeat_age_seconds=heartbeat_age,
            )
            
            with self._lock:
                self.last_heartbeat = heartbeat
                self.heartbeat_history.append(heartbeat)
                
                # Keep only last 1000 heartbeats
                if len(self.heartbeat_history) > 1000:
                    self.heartbeat_history = self.heartbeat_history[-1000:]
                
                # Persist heartbeat
                self._persist_heartbeat(heartbeat)
                
                # Log periodically
                current_time = time.time()
                if current_time - self.last_log_time >= self.log_interval_seconds:
                    logger.info(
                        f"Shadow heartbeat | "
                        f"tick_count={tick_count} | "
                        f"trainer_alive={trainer_alive} | "
                        f"active_strategies={active_strategies} | "
                        f"feed_type={feed_type} | "
                        f"error_count={error_count}"
                    )
                    self.last_log_time = current_time
            
            return heartbeat
        
        except Exception as e:
            # SAFETY: Engine must NOT crash
            logger.error(f"Error recording heartbeat (non-fatal): {e}", exc_info=True)
            # Return minimal heartbeat
            return ShadowHeartbeat(
                timestamp=datetime.utcnow(),
                tick_count=tick_count,
                trainer_alive=False,
                active_strategies=0,
                feed_type="unknown",
                last_tick_ts=None,
                error_count=0,
            )
    
    def _persist_heartbeat(self, heartbeat: ShadowHeartbeat) -> None:
        """
        Persist heartbeat to file.
        
        Args:
            heartbeat: Heartbeat instance
        """
        try:
            heartbeat_data = heartbeat.to_dict()
            heartbeat_data["pid"] = os.getpid()
            
            with open(self._heartbeat_file, 'w') as f:
                json.dump(heartbeat_data, f, indent=2)
        
        except Exception as e:
            logger.debug(f"Error persisting heartbeat (non-fatal): {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get read-only status snapshot.
        
        Returns:
            Status dictionary
        """
        with self._lock:
            if self.last_heartbeat:
                return self.last_heartbeat.to_dict()
            return {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "tick_count": 0,
                "trainer_alive": False,
                "active_strategies": 0,
                "feed_type": "unknown",
                "last_tick_ts": None,
                "error_count": 0,
                "heartbeat_age_seconds": 0.0,
            }
    
    def get_heartbeat(self) -> Optional[ShadowHeartbeat]:
        """
        Get latest heartbeat.
        
        Returns:
            Latest ShadowHeartbeat or None
        """
        with self._lock:
            return self.last_heartbeat
    
    def get_heartbeat_history(self, limit: int = 100) -> list[ShadowHeartbeat]:
        """
        Get heartbeat history.
        
        Args:
            limit: Maximum number of heartbeats to return
        
        Returns:
            List of ShadowHeartbeat instances
        """
        with self._lock:
            return self.heartbeat_history[-limit:]


# Global heartbeat monitor instance (for backward compatibility)
# NOTE: This is NOT recommended - trainer should own its heartbeat instance
# This exists only for legacy code that may call get_shadow_heartbeat_monitor()
_heartbeat_monitor: Optional[ShadowHeartbeatMonitor] = None
# PHASE 7: Lock created lazily to avoid import-time side effects
_heartbeat_monitor_lock: Optional[threading.Lock] = None


def get_shadow_heartbeat_monitor(**kwargs) -> ShadowHeartbeatMonitor:
    """
    Get global shadow heartbeat monitor instance (singleton).
    
    DEPRECATED: Trainers should create their own heartbeat instances.
    This function exists for backward compatibility only.
    
    PHASE 7: Lock created lazily on first call to avoid import-time side effects.
    
    Args:
        **kwargs: Arguments for ShadowHeartbeatMonitor
    
    Returns:
        ShadowHeartbeatMonitor instance
    """
    global _heartbeat_monitor, _heartbeat_monitor_lock
    
    if _heartbeat_monitor_lock is None:
        _heartbeat_monitor_lock = threading.Lock()
    
    if _heartbeat_monitor is None:
        with _heartbeat_monitor_lock:
            if _heartbeat_monitor is None:
                _heartbeat_monitor = ShadowHeartbeatMonitor(**kwargs)
    
    return _heartbeat_monitor
