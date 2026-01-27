"""
SHADOW Trading - Signals Only

PHASE 1 — SHADOW TRADING (SIGNALS ONLY)

Implements SHADOW trading mode where:
- Strategies compute signals
- Signals are recorded
- NO broker interaction occurs
- NO order execution

ABSOLUTE SAFETY:
- Signals stored in memory/local store
- Never routed to brokers
- Visible via API only
"""

import time
import threading
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque


@dataclass
class ShadowSignal:
    """
    SHADOW trading signal model - computational only.
    
    Signals represent strategy intentions but are NEVER executed.
    """
    strategy_id: str
    symbol: str
    side: str  # "buy" | "sell"
    confidence: float  # 0.0-1.0
    timestamp: float
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert signal to dict for API responses"""
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat() + "Z",
            "reason": self.reason,
            "metadata": self.metadata,
        }


class ShadowSignalRegistry:
    """
    Registry for SHADOW trading signals.
    
    PHASE 1: Stores signals in memory (bounded)
    PHASE 7: Thread-safe, non-blocking
    """
    
    def __init__(self, max_signals: int = 1000):
        self._signals: deque = deque(maxlen=max_signals)
        self._lock = threading.Lock()
        self._enabled: bool = False  # Only enabled when engine state == SHADOW
    
    def is_enabled(self) -> bool:
        """Check if shadow signal generation is enabled"""
        with self._lock:
            return self._enabled
    
    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable shadow signal generation"""
        with self._lock:
            self._enabled = enabled
    
    def record_signal(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        confidence: float,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[ShadowSignal]:
        """
        Record a SHADOW trading signal.
        
        PHASE 1: Signal is recorded but NEVER executed
        PHASE 3: Only records if shadow enabled and kill-switch safe
        
        Returns:
            ShadowSignal if recorded, None if disabled
        """
        # PHASE 3: Check if shadow is enabled (kill-switch will disable this)
        if not self.is_enabled():
            return None
        
        # PHASE 3: Check kill-switch (HARD_KILL blocks shadow signals)
        try:
            from api.security import get_kill_switch
            kill_switch = get_kill_switch()
            if not kill_switch.is_shadow_allowed():
                return None
        except Exception:
            # If kill-switch check fails, don't record signal (fail-safe)
            return None
        
        # Validate inputs
        if side not in ["buy", "sell"]:
            return None
        
        if not 0.0 <= confidence <= 1.0:
            confidence = max(0.0, min(1.0, confidence))
        
        signal = ShadowSignal(
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            confidence=confidence,
            timestamp=time.time(),
            reason=reason,
            metadata=metadata or {},
        )
        
        with self._lock:
            self._signals.append(signal)
        
        return signal
    
    def get_signals(self, limit: int = 100, strategy_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get recent SHADOW signals.
        
        Args:
            limit: Maximum number of signals to return
            strategy_id: Optional filter by strategy
        
        Returns:
            List of signal dicts, most recent first
        """
        with self._lock:
            signals = list(self._signals)
        
        # Filter by strategy if specified
        if strategy_id:
            signals = [s for s in signals if s.strategy_id == strategy_id]
        
        # Sort by timestamp (most recent first)
        signals.sort(key=lambda s: s.timestamp, reverse=True)
        
        # Limit results
        signals = signals[:limit]
        
        return [signal.to_dict() for signal in signals]
    
    def clear(self) -> None:
        """Clear all signals (for testing/reset)"""
        with self._lock:
            self._signals.clear()


# Global shadow signal registry instance
_shadow_registry: Optional[ShadowSignalRegistry] = None


def get_shadow_registry() -> ShadowSignalRegistry:
    """Get global shadow signal registry instance"""
    global _shadow_registry
    if _shadow_registry is None:
        _shadow_registry = ShadowSignalRegistry()
    return _shadow_registry
