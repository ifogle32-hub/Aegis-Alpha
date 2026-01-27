"""
PHASE 1 — SHADOW STATE CORE

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Shadow mode state management for Sentinel X.
Thread-safe singleton controller for enabling/disabling shadow mode.
"""

from enum import Enum
from threading import Lock
from datetime import datetime
from typing import Dict, Any, Optional

from sentinel_x.monitoring.logger import logger


class ShadowState(Enum):
    """Shadow mode state enum."""
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"


class ShadowController:
    """
    Thread-safe singleton controller for shadow mode state.
    
    SAFETY: SHADOW MODE ONLY
    - Never triggers order execution
    - State changes are instantaneous
    - Engine continues running during state changes
    
    Default state: DISABLED
    """
    
    def __init__(self):
        """Initialize shadow controller (private - use get_shadow_controller())."""
        self._state: ShadowState = ShadowState.DISABLED
        self._lock: Lock = Lock()
        self._last_transition: Optional[datetime] = None
        self._transition_reason: Optional[str] = None
        self._trading_window: str = "UNKNOWN"  # For status reporting
        
        logger.info("ShadowController initialized: state=DISABLED")
    
    def get_state(self) -> ShadowState:
        """
        Get current shadow state.
        
        SAFETY: Thread-safe read-only operation
        
        Returns:
            ShadowState enum value (DISABLED or ENABLED)
        """
        with self._lock:
            return self._state
    
    def is_enabled(self) -> bool:
        """
        Check if shadow mode is enabled.
        
        Returns:
            True if enabled, False otherwise
        """
        return self.get_state() == ShadowState.ENABLED
    
    def enable(self, reason: Optional[str] = None) -> None:
        """
        Enable shadow mode.
        
        SAFETY: SHADOW MODE ONLY - never triggers order execution
        SAFETY: Non-blocking, engine continues running
        
        Args:
            reason: Optional reason for enabling (for audit logging)
        """
        with self._lock:
            if self._state == ShadowState.ENABLED:
                logger.debug("Shadow mode already enabled")
                return
            
            self._state = ShadowState.ENABLED
            self._last_transition = datetime.utcnow()
            self._transition_reason = reason or "API enable request"
            
            logger.info(
                f"SHADOW MODE ENABLED | "
                f"reason={self._transition_reason} | "
                f"timestamp={self._last_transition.isoformat()}Z"
            )
    
    def disable(self, reason: Optional[str] = None) -> None:
        """
        Disable shadow mode.
        
        SAFETY: Non-blocking, engine continues running
        
        Args:
            reason: Optional reason for disabling (for audit logging)
        """
        with self._lock:
            if self._state == ShadowState.DISABLED:
                logger.debug("Shadow mode already disabled")
                return
            
            self._state = ShadowState.DISABLED
            self._last_transition = datetime.utcnow()
            self._transition_reason = reason or "API disable request"
            
            logger.info(
                f"SHADOW MODE DISABLED | "
                f"reason={self._transition_reason} | "
                f"timestamp={self._last_transition.isoformat()}Z"
            )
    
    def get_state_dict(self) -> Dict[str, Any]:
        """
        Get shadow state as dictionary (for status endpoint).
        
        Returns:
            Dict with shadow state information
        """
        with self._lock:
            return {
                "shadow_enabled": self._state == ShadowState.ENABLED,
                "mode": self._state.value,
                "trading_window": self._trading_window,
                "last_transition": self._last_transition.isoformat() + "Z" if self._last_transition else None,
                "reason": self._transition_reason
            }
    
    def update_trading_window(self, window: str) -> None:
        """
        Update trading window status (for observability).
        
        Args:
            window: Trading window status (e.g., "OPEN", "CLOSED", "UNKNOWN")
        """
        with self._lock:
            self._trading_window = window
            logger.debug(f"Shadow trading window updated: {window}")


# Global singleton instance
_shadow_controller: Optional[ShadowController] = None
_controller_lock: Lock = Lock()


def get_shadow_controller() -> ShadowController:
    """
    Get global shadow controller instance (singleton).
    
    SAFETY: Thread-safe singleton pattern
    
    Returns:
        ShadowController instance
    """
    global _shadow_controller
    
    if _shadow_controller is None:
        with _controller_lock:
            if _shadow_controller is None:
                _shadow_controller = ShadowController()
    
    return _shadow_controller


def get_shadow_state() -> ShadowController:
    """
    Alias for get_shadow_controller() for compatibility.
    
    NOTE: This function is kept for backward compatibility with existing code
    that expects get_shadow_state() to return a ShadowController.
    
    Returns:
        ShadowController instance
    """
    return get_shadow_controller()
