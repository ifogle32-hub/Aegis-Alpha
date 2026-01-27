"""
PHASE 1: Shadow module __init__.py

RULE: MUST NOT import trainer or heartbeat at module level.
Only runtime accessor is allowed.
"""

# PHASE 1: Only import runtime accessor - NO trainer or heartbeat
from sentinel_x.shadow.runtime import get_shadow_runtime

# Core enums and constants (no heavy deps, safe to import)
from sentinel_x.shadow.definitions import ShadowMode, PromotionState, SHADOW_GUARANTEES
from sentinel_x.shadow.controller import TrainingState

__all__ = [
    # Runtime accessor (safe - no side effects)
    "get_shadow_runtime",
    # Enums and constants (safe to import - no heavy deps)
    "ShadowMode",
    "PromotionState",
    "SHADOW_GUARANTEES",
    "TrainingState",
]
