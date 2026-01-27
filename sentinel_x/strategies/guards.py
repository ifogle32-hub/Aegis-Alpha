"""
PHASE 6 — STRATEGY SHADOW GUARDS

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Guards for strategy shadow signal emission.
"""

from sentinel_x.core.shadow_guards import can_emit_shadow_signals, assert_shadow_enabled, is_shadow_enabled

# Re-export guards for strategies module
__all__ = ['can_emit_shadow_signals', 'assert_shadow_enabled', 'is_shadow_enabled']
