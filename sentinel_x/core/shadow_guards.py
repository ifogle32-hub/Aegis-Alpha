"""
PHASE 3 — SHADOW GUARDS (MANDATORY)

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Global guards for shadow operations.
All shadow-related code must check these guards.
"""

from sentinel_x.core.shadow_registry import get_shadow_state
from sentinel_x.monitoring.logger import logger


def assert_shadow_enabled() -> None:
    """
    Assert that shadow mode is enabled.
    
    Raises RuntimeError if shadow mode is disabled.
    
    SAFETY: Use this guard before any shadow operation
    SAFETY: Fail-fast on disabled shadow mode
    
    Raises:
        RuntimeError: If shadow mode is disabled
    """
    state = get_shadow_state()
    if not state.shadow_enabled:
        raise RuntimeError(
            "Shadow mode is disabled at engine level. "
            "Enable shadow mode via /engine/shadow endpoint before performing shadow operations."
        )


def can_emit_shadow_signals() -> bool:
    """
    Check if shadow signals can be emitted.
    
    SAFETY: Non-blocking check
    
    Returns:
        True if shadow mode is enabled, False otherwise
    """
    return is_shadow_enabled()


def require_shadow_for_promotion() -> None:
    """
    Require shadow mode for promotion evaluation.
    
    Raises RuntimeError if shadow mode is disabled.
    
    SAFETY: Use this guard before promotion operations
    
    Raises:
        RuntimeError: If shadow mode is disabled
    """
    assert_shadow_enabled()


def is_shadow_enabled() -> bool:
    """
    Check if shadow mode is currently enabled.
    
    SAFETY: Non-blocking, never raises
    
    Returns:
        True if shadow enabled, False otherwise
    """
    try:
        state = get_shadow_state()
        return state.shadow_enabled
    except Exception as e:
        logger.debug(f"Error checking shadow enabled state: {e}")
        return False
