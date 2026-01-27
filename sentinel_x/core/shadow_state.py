"""
PHASE 1 — SHADOW STATE MODEL (SOURCE OF TRUTH)

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Thread-safe SHADOW state management for runtime enablement.
Works alongside existing EngineMode system.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional
from sentinel_x.monitoring.logger import logger


class ShadowMode(str, Enum):
    """
    Shadow operation modes.
    
    MONITOR: Default mode - no shadow operations
    SHADOW: Shadow mode enabled - signals and metrics only
    """
    MONITOR = "MONITOR"
    SHADOW = "SHADOW"


@dataclass
class ShadowState:
    """
    Shadow state management.
    
    SAFETY: Thread-safe state transitions
    SAFETY: Prevents unsafe transitions (e.g., ARMED → SHADOW)
    SAFETY: All transitions are auditable
    """
    shadow_enabled: bool = False
    mode: ShadowMode = ShadowMode.MONITOR
    trading_window: str = "CLOSED"
    last_transition: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: Optional[str] = None
    transition_history: list = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    
    def transition(self, *, enable_shadow: bool, reason: str) -> None:
        """
        Transition shadow state with validation.
        
        SAFETY: Thread-safe
        SAFETY: Prevents unsafe transitions
        SAFETY: Logs all transitions
        
        Args:
            enable_shadow: True to enable SHADOW mode, False to disable
            reason: Human-readable reason for transition (audit trail)
        """
        with self._lock:
            old_enabled = self.shadow_enabled
            old_mode = self.mode
            
            # Check for unsafe transitions
            # SHADOW cannot be enabled if engine is in LIVE mode (ARMED equivalent)
            if enable_shadow:
                try:
                    from sentinel_x.core.engine_mode import get_engine_mode, EngineMode
                    current_engine_mode = get_engine_mode()
                    
                    # LIVE mode is equivalent to ARMED - block SHADOW
                    if current_engine_mode == EngineMode.LIVE:
                        error_msg = f"Cannot enable SHADOW while engine is in LIVE mode (ARMED)"
                        logger.critical(error_msg)
                        raise RuntimeError(error_msg)
                except Exception as e:
                    logger.error(f"Error checking engine mode for shadow transition: {e}", exc_info=True)
                    raise
            
            # Perform transition
            self.shadow_enabled = enable_shadow
            self.mode = ShadowMode.SHADOW if enable_shadow else ShadowMode.MONITOR
            self.last_transition = datetime.now(timezone.utc)
            self.reason = reason
            
            # Record transition history
            self.transition_history.append({
                "from_enabled": old_enabled,
                "to_enabled": enable_shadow,
                "from_mode": old_mode.value,
                "to_mode": self.mode.value,
                "reason": reason,
                "timestamp": self.last_transition.isoformat() + "Z"
            })
            
            # Keep history limited to last 100 transitions
            if len(self.transition_history) > 100:
                self.transition_history = self.transition_history[-100:]
            
            # Log transition
            logger.info(
                f"Shadow state transition: {old_mode.value} -> {self.mode.value} "
                f"(enabled={enable_shadow}) | reason: {reason}"
            )
            
            # Audit log for critical transitions
            if enable_shadow:
                try:
                    from sentinel_x.monitoring.audit_logger import log_audit_event
                    log_audit_event(
                        "SHADOW_ENABLED",
                        None,
                        metadata={
                            "reason": reason,
                            "mode": self.mode.value
                        }
                    )
                except Exception:
                    pass  # Non-fatal if audit logging fails
    
    def get_state(self) -> dict:
        """
        Get current shadow state snapshot.
        
        SAFETY: Thread-safe, read-only
        
        Returns:
            Dict with current shadow state
        """
        with self._lock:
            return {
                "shadow_enabled": self.shadow_enabled,
                "mode": self.mode.value,
                "trading_window": self.trading_window,
                "last_transition": self.last_transition.isoformat() + "Z",
                "reason": self.reason,
                "transition_count": len(self.transition_history)
            }
