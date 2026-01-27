"""
PHASE 2: Execution Models - Shared Data Structures

Eliminates circular imports by centralizing execution-related models.
All execution code imports from this module, not from each other.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class ExecutionStatus(Enum):
    """Execution status enumeration."""
    PENDING = "PENDING"
    RISK_REJECTED = "RISK_REJECTED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    KILLED = "KILLED"


@dataclass
class ExecutionRecord:
    """Execution record - tracks order execution state."""
    intent_id: str
    client_order_id: str
    broker_order_id: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    submitted_at: Optional[datetime] = None
    filled_qty: float = 0.0
    requested_qty: float = 0.0
    avg_fill_price: float = 0.0
    execution_latency_ms: float = 0.0
    slippage_bps: float = 0.0
    rejection_reason: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def failed(cls, intent_id: str, client_order_id: str, reason: str) -> "ExecutionRecord":
        """
        Factory for a failed execution record.

        Used by safe wrappers to downgrade router failures to FAILED state
        without crashing the engine.
        """
        return cls(
            intent_id=intent_id,
            client_order_id=client_order_id,
            status=ExecutionStatus.REJECTED,
            requested_qty=0.0,
            rejection_reason=reason,
        )


@dataclass
class BrokerDecision:
    """
    Broker selection decision with reasoning.
    
    PHASE 3: Every routing decision logs this for audit.
    """
    intent_id: str
    selected_broker: str
    health_score: float
    latency_ms: float
    fill_rate: float
    slippage_bps: float
    reliability_score: float
    reasoning: str
    alternatives_considered: list[str]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    selected_broker_instance: Optional[Any] = field(default=None, repr=False)  # Broker instance (not serialized)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/audit."""
        return {
            'intent_id': self.intent_id,
            'selected_broker': self.selected_broker,
            'health_score': self.health_score,
            'latency_ms': self.latency_ms,
            'fill_rate': self.fill_rate,
            'slippage_bps': self.slippage_bps,
            'reliability_score': self.reliability_score,
            'reasoning': self.reasoning,
            'alternatives_considered': self.alternatives_considered,
            'timestamp': self.timestamp.isoformat() + "Z"
        }
