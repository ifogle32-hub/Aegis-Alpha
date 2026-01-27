"""
PHASE 0 — SHADOW MODE DEFINITIONS & GUARANTEES

Defines shadow mode semantics, guarantees, and safety contracts.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


class ShadowMode(str, Enum):
    """
    Shadow operation modes.
    
    LIVE: Real-time market data feed (websocket/polling)
    HISTORICAL: Replay historical data with timestamp accuracy
    SYNTHETIC: Monte Carlo / regime simulation
    """
    LIVE = "live"
    HISTORICAL = "historical"
    SYNTHETIC = "synthetic"


class PromotionState(str, Enum):
    """
    Strategy promotion states.
    
    SHADOW_ONLY: Only running in shadow, not eligible for promotion
    CANDIDATE: Meets minimum criteria, under evaluation
    APPROVED: Approved for live trading (manual promotion required)
    LIVE_LOCKED: Currently live (manual only, no automatic promotion)
    """
    SHADOW_ONLY = "SHADOW_ONLY"
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    LIVE_LOCKED = "LIVE_LOCKED"


@dataclass
class ShadowGuarantees:
    """
    Shadow mode safety guarantees.
    
    These guarantees are enforced at multiple layers to ensure
    shadow operations can never affect live trading.
    """
    
    # Core guarantees
    cannot_execute_trades: bool = True
    cannot_mutate_live_positions: bool = True
    can_be_paused_resumed: bool = True
    failures_cannot_crash_engine: bool = True
    
    # Operational guarantees
    deterministic_simulation: bool = True
    no_broker_connectivity: bool = True
    full_metric_capture: bool = True
    promotion_requires_explicit_gate: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert guarantees to dictionary."""
        return {
            "cannot_execute_trades": self.cannot_execute_trades,
            "cannot_mutate_live_positions": self.cannot_mutate_live_positions,
            "can_be_paused_resumed": self.can_be_paused_resumed,
            "failures_cannot_crash_engine": self.failures_cannot_crash_engine,
            "deterministic_simulation": self.deterministic_simulation,
            "no_broker_connectivity": self.no_broker_connectivity,
            "full_metric_capture": self.full_metric_capture,
            "promotion_requires_explicit_gate": self.promotion_requires_explicit_gate,
        }


# Global shadow guarantees (immutable)
SHADOW_GUARANTEES = ShadowGuarantees()


def assert_shadow_guarantees() -> None:
    """
    Assert that shadow guarantees are in place.
    
    This is a documentation/contract check, not a runtime guard.
    Actual guards are enforced in ShadowTrainer and SimulationEngine.
    
    Raises:
        AssertionError: If guarantees are violated (should never happen)
    """
    assert SHADOW_GUARANTEES.cannot_execute_trades, "Shadow must never execute trades"
    assert SHADOW_GUARANTEES.cannot_mutate_live_positions, "Shadow must never mutate live positions"
    assert SHADOW_GUARANTEES.failures_cannot_crash_engine, "Shadow failures must not crash engine"
