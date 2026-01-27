"""
PHASE 1: Order Intent Model - Immutable, Append-Only

OrderIntent represents the immutable intent to execute an order.
All execution MUST flow through OrderIntent - no implicit orders allowed.

SAFETY: OrderIntent is created BEFORE broker submission and is append-only.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Optional
from sentinel_x.core.engine_mode import EngineMode


class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(Enum):
    """Time in force enumeration."""
    DAY = "DAY"  # Day order (default)
    GTC = "GTC"  # Good till canceled
    IOC = "IOC"  # Immediate or cancel
    FOK = "FOK"  # Fill or kill


@dataclass(frozen=True)
class OrderIntent:
    """
    Immutable Order Intent - represents intent to execute before broker submission.
    
    SAFETY: This object is frozen (immutable) and append-only.
    All fields are required except limit_price (nullable for market orders).
    """
    intent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    strategy: str = ""
    symbol: str = ""
    side: str = ""  # "BUY" or "SELL"
    qty: float = 0.0
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None  # Required for LIMIT orders
    time_in_force: TimeInForce = TimeInForce.DAY
    engine_mode: EngineMode = EngineMode.RESEARCH  # Mode when intent was created
    risk_checks_passed: bool = False  # Set by risk engine
    created_at: datetime = field(default_factory=datetime.utcnow)
    client_order_id: Optional[str] = None  # Generated from intent_id for idempotency
    
    def __post_init__(self):
        """
        Validate OrderIntent after creation.
        Raises ValueError if invalid.
        """
        # Use object.__setattr__ for frozen dataclass validation
        object.__setattr__(self, '_validated', True)
        
        if not self.strategy:
            raise ValueError("OrderIntent requires strategy")
        if not self.symbol:
            raise ValueError("OrderIntent requires symbol")
        if self.side.upper() not in ("BUY", "SELL"):
            raise ValueError(f"OrderIntent requires side='BUY' or 'SELL', got: {self.side}")
        if self.qty <= 0:
            raise ValueError(f"OrderIntent requires qty > 0, got: {self.qty}")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("OrderIntent LIMIT order requires limit_price")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("OrderIntent MARKET order must not have limit_price")
    
    def with_risk_check(self, passed: bool) -> "OrderIntent":
        """
        Create a new OrderIntent with risk check result.
        This is the only way to update risk_checks_passed.
        """
        # Use dataclasses.replace() for frozen dataclass
        client_order_id = self.client_order_id or f"sentinel_{self.intent_id[:8]}"
        return replace(
            self,
            risk_checks_passed=passed,
            client_order_id=client_order_id
        )
    
    def to_dict(self) -> dict:
        """Convert OrderIntent to dictionary for serialization."""
        return {
            "intent_id": self.intent_id,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "order_type": self.order_type.value,
            "limit_price": self.limit_price,
            "time_in_force": self.time_in_force.value,
            "engine_mode": self.engine_mode.value,
            "risk_checks_passed": self.risk_checks_passed,
            "created_at": self.created_at.isoformat() + "Z",
            "client_order_id": self.client_order_id
        }
    
    @classmethod
    def from_strategy_order(cls, order_dict: dict, engine_mode: EngineMode | None = None):
        """
        Create OrderIntent from strategy order dictionary.
        
        Args:
            order_dict: Order dict from strategy.on_tick() with keys:
                - symbol: str
                - side: str ("buy" or "sell")
                - qty: float
                - price: Optional[float] (for limit orders)
                - strategy: str
            engine_mode: Current engine mode (optional, defaults to current mode)
            
        Returns:
            OrderIntent instance
        """
        from sentinel_x.core.engine_mode import get_engine_mode
        
        if engine_mode is None:
            engine_mode = get_engine_mode()
        
        side = order_dict.get("side", "buy").upper()
        if side not in ("BUY", "SELL"):
            # Normalize "buy" -> "BUY", "sell" -> "SELL"
            side = "BUY" if side.lower() == "buy" else "SELL"
        
        price = order_dict.get("price")
        order_type = OrderType.LIMIT if price is not None else OrderType.MARKET
        
        return cls(
            strategy=order_dict.get("strategy", "UnknownStrategy"),
            symbol=order_dict.get("symbol", ""),
            side=side,
            qty=abs(float(order_dict.get("qty", 0))),  # Always positive
            order_type=order_type,
            limit_price=float(price) if price is not None else None,
            time_in_force=TimeInForce.DAY,  # Default
            engine_mode=engine_mode,
            risk_checks_passed=False,  # Set by risk engine
            client_order_id=None  # Generated later
        )
