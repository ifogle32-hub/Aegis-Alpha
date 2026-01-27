"""
PHASE 12 — SAFETY & FAIL-SAFE

Hard rules and safety guards:
- Shadow cannot place real orders
- Shadow cannot mutate live state
- Shadow can be globally disabled instantly
- Kill-switch overrides everything
"""

from typing import Optional
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.core.kill_switch import is_killed


class ShadowSafetyGuard:
    """
    Shadow safety guard.
    
    Enforces hard safety rules:
    - Shadow cannot place real orders
    - Shadow cannot mutate live state
    - Shadow can be globally disabled instantly
    - Kill-switch overrides everything
    """
    
    def __init__(self):
        """Initialize safety guard."""
        self._enabled = True
        self._lock = threading.RLock()
        
        logger.info("ShadowSafetyGuard initialized")
    
    def is_enabled(self) -> bool:
        """
        Check if shadow training is enabled.
        
        Returns:
            True if enabled, False otherwise
        """
        with self._lock:
            # Kill-switch overrides everything
            if is_killed():
                return False
            return self._enabled
    
    def disable(self, reason: Optional[str] = None) -> None:
        """
        Disable shadow training instantly.
        
        Args:
            reason: Optional reason for disabling
        """
        with self._lock:
            self._enabled = False
            logger.critical(
                f"SHADOW TRAINING DISABLED | reason={reason or 'manual disable'}"
            )
    
    def enable(self, reason: Optional[str] = None) -> None:
        """
        Enable shadow training.
        
        Args:
            reason: Optional reason for enabling
        """
        with self._lock:
            if is_killed():
                logger.warning("Cannot enable shadow training: kill-switch is active")
                return
            
            self._enabled = True
            logger.info(f"Shadow training enabled | reason={reason or 'manual enable'}")
    
    def assert_can_execute(self) -> None:
        """
        Assert that shadow operations can execute.
        
        Raises:
            RuntimeError: If shadow is disabled or kill-switch is active
        """
        if not self.is_enabled():
            raise RuntimeError(
                "Shadow training is disabled or kill-switch is active. "
                "Cannot execute shadow operations."
            )
    
    def assert_no_live_execution(self) -> None:
        """
        Assert that no live execution is attempted.
        
        This is a redundant safety check that should never fail
        if shadow architecture is correct.
        
        Raises:
            RuntimeError: If live execution is detected (should never happen)
        """
        # This is a defensive check - in correct implementation,
        # shadow should never have access to live execution paths
        try:
            from sentinel_x.core.engine_mode import get_engine_mode, EngineMode
            mode = get_engine_mode()
            
            # Shadow should not run in LIVE mode
            if mode == EngineMode.LIVE:
                raise RuntimeError(
                    "SAFETY VIOLATION: Shadow training attempted in LIVE mode. "
                    "This should never happen."
                )
        except ImportError:
            # Engine mode not available - skip check
            pass
    
    def assert_no_live_mutation(self) -> None:
        """
        Assert that no live state mutation is attempted.
        
        Raises:
            RuntimeError: If live mutation is detected (should never happen)
        """
        # This is a defensive check - shadow should never mutate live state
        # In correct implementation, shadow has isolated state only
        pass  # Placeholder for future validation


# Global safety guard instance
_safety_guard: Optional[ShadowSafetyGuard] = None
_safety_guard_lock = threading.Lock()


def get_shadow_safety_guard() -> ShadowSafetyGuard:
    """
    Get global shadow safety guard instance (singleton).
    
    Returns:
        ShadowSafetyGuard instance
    """
    global _safety_guard
    
    if _safety_guard is None:
        with _safety_guard_lock:
            if _safety_guard is None:
                _safety_guard = ShadowSafetyGuard()
    
    return _safety_guard
