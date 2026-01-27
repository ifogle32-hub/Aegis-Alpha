"""
Execution Interface (Abstraction)

PHASE 1 — EXECUTION INTERFACE (ABSTRACTION)

Defines broker-agnostic execution interfaces for order submission.
NO broker-specific logic here.
"""

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum


class OrderSide(Enum):
    """Order side"""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type"""
    MARKET = "market"
    LIMIT = "limit"


class ExecutionStatus(Enum):
    """Execution status"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class ExecutionRequest:
    """
    PHASE 1 — EXECUTION REQUEST
    
    Broker-agnostic execution request.
    """
    symbol: str
    side: OrderSide
    qty: float
    order_type: OrderType
    limit_price: Optional[float] = None
    strategy_id: str = "unknown"
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert request to dict"""
        return {
            "request_id": self.request_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "order_type": self.order_type.value,
            "limit_price": self.limit_price,
            "strategy_id": self.strategy_id,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionRequest":
        """Create request from dict"""
        return cls(
            request_id=data.get("request_id", str(uuid.uuid4())),
            symbol=data["symbol"],
            side=OrderSide(data["side"]),
            qty=float(data["qty"]),
            order_type=OrderType(data["order_type"]),
            limit_price=data.get("limit_price"),
            strategy_id=data.get("strategy_id", "unknown"),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class ExecutionResult:
    """
    PHASE 1 — EXECUTION RESULT
    
    Result of execution attempt.
    """
    accepted: bool
    request_id: str
    broker_order_id: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    reason: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dict"""
        return {
            "accepted": self.accepted,
            "request_id": self.request_id,
            "broker_order_id": self.broker_order_id,
            "status": self.status.value,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class ExecutionAdapter(ABC):
    """
    PHASE 1 — EXECUTION ADAPTER INTERFACE
    
    Abstract base class for broker-specific execution adapters.
    """
    
    @abstractmethod
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """
        Execute an order request.
        
        Args:
            request: Execution request
            
        Returns:
            Execution result
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if adapter is available/connected.
        
        Returns:
            True if available, False otherwise
        """
        pass
    
    @abstractmethod
    def get_broker_name(self) -> str:
        """
        Get broker name/identifier.
        
        Returns:
            Broker name
        """
        pass
