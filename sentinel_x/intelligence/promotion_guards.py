"""
PHASE 6 — PROMOTION SHADOW GUARDS

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Guards for promotion evaluation using shadow data.
"""

from sentinel_x.core.shadow_guards import require_shadow_for_promotion, assert_shadow_enabled, is_shadow_enabled

# Re-export guards for promotion module
__all__ = ['require_shadow_for_promotion', 'assert_shadow_enabled', 'is_shadow_enabled']
