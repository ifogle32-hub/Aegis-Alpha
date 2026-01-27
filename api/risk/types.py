"""
PHASE 1 — RISK TYPES

Lightweight interface for risk evaluation.
Avoids circular dependencies by not importing execution types.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskContext:
    """
    Risk evaluation context.
    
    Lightweight interface that avoids circular dependencies.
    Risk engine evaluates data, not execution objects.
    """
    strategy_id: str
    symbol: str
    notional: float  # Calculated notional value (qty * price)
    side: str  # "buy" or "sell" (matches OrderSide enum values)
    qty: float  # Order quantity
    order_type: str  # "market" or "limit" (matches OrderType enum values)
    request_id: str  # Request identifier
    limit_price: Optional[float] = None  # Limit price for limit orders
    confidence: Optional[float] = None  # Optional confidence score
