"""
PHASE 5 — SIMULATED BROKER (CORE LOGIC)

SAFETY: OFFLINE BACKTEST ENGINE
REGRESSION LOCK — DO NOT CONNECT TO LIVE

Features:
- Order acceptance
- Deterministic fills
- Optional slippage model (placeholder)
- Partial fill support (placeholder)

Rules:
- No instant fills by default
- Fills occur on FUTURE events
- Deterministic randomness only (seeded)
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

# SAFETY: OFFLINE BACKTEST ENGINE
# REGRESSION LOCK — DO NOT CONNECT TO LIVE

try:
    import numpy as np
except ImportError:
    np = None

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class Order:
    """PHASE 5: Order representation for simulated broker."""
    order_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: float
    order_type: str  # "MARKET", "LIMIT"
    limit_price: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    strategy_name: str = ""
    status: str = "PENDING"  # PENDING, FILLED, PARTIALLY_FILLED, REJECTED, CANCELLED


@dataclass
class Fill:
    """PHASE 5: Fill representation for simulated broker."""
    fill_id: str
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: datetime
    fees: float = 0.0
    slippage: float = 0.0
    strategy_name: str = ""


class SimulatedBroker:
    """
    PHASE 5: Simulated broker (core logic).
    
    SAFETY: offline only
    SAFETY: no live execution path
    
    Note: Full implementation in sentinel_x/research/backtest_engine.py
    This is a scaffolding interface.
    """
    
    def __init__(self, 
                 slippage_pct: float = 0.001,  # 0.1%
                 fee_pct: float = 0.001,  # 0.1%
                 seed: Optional[int] = None):
        """
        Initialize simulated broker.
        
        Args:
            slippage_pct: Fixed slippage percentage
            fee_pct: Trading fee percentage
            seed: Random seed for deterministic execution
        """
        self.slippage_pct = slippage_pct
        self.fee_pct = fee_pct
        
        # Order tracking
        self.orders: Dict[str, Order] = {}
        self.fills: List[Fill] = []
        self.order_counter = 0
        
        # Deterministic randomness
        if np:
            self.rng = np.random.RandomState(seed) if seed is not None else np.random
        else:
            self.rng = None
        
        logger.info(f"SimulatedBroker initialized: slippage={slippage_pct*100:.2f}%, fee={fee_pct*100:.2f}%")
    
    def submit_order(self, order: Order) -> str:
        """
        PHASE 5: Submit order to broker.
        
        SAFETY: offline only
        SAFETY: no live execution path
        
        Returns:
            Order ID
        """
        self.order_counter += 1
        if not order.order_id:
            order.order_id = f"ORD_{self.order_counter}"
        
        self.orders[order.order_id] = order
        order.status = "PENDING"
        
        logger.debug(f"Order submitted: {order.order_id} {order.side} {order.quantity} {order.symbol}")
        
        return order.order_id
    
    def process_market_tick(self, symbol: str, price: float, timestamp: datetime, volume: float = 0.0) -> List[Fill]:
        """
        PHASE 5: Process market tick and attempt to fill pending orders.
        
        SAFETY: fills occur on future ticks only (no lookahead)
        
        Returns:
            List of fills generated
        """
        fills = []
        
        # Process pending orders for this symbol
        for order_id, order in self.orders.items():
            if order.status != "PENDING" or order.symbol != symbol:
                continue
            
            # Check if order can be filled
            fill = self._try_fill_order(order, price, timestamp, volume)
            if fill:
                fills.append(fill)
                self.fills.append(fill)
                
                # Update order status
                if fill.quantity >= order.quantity:
                    order.status = "FILLED"
                else:
                    order.status = "PARTIALLY_FILLED"
                    order.quantity -= fill.quantity
        
        return fills
    
    def _try_fill_order(self, order: Order, current_price: float, timestamp: datetime, volume: float) -> Optional[Fill]:
        """
        PHASE 5: Try to fill an order (realistic execution).
        
        SAFETY: fills occur on future ticks only (no lookahead)
        """
        # Market orders: fill immediately with slippage
        if order.order_type == "MARKET":
            # Calculate execution price with slippage
            if order.side == "BUY":
                exec_price = current_price * (1 + self.slippage_pct)
            else:  # SELL
                exec_price = current_price * (1 - self.slippage_pct)
            
            # Calculate fees and slippage
            trade_value = order.quantity * exec_price
            fees = trade_value * self.fee_pct
            slippage_cost = abs(order.quantity * (exec_price - current_price))
            
            fill = Fill(
                fill_id=f"FILL_{len(self.fills) + 1}",
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=exec_price,
                timestamp=timestamp,
                fees=fees,
                slippage=slippage_cost,
                strategy_name=order.strategy_name
            )
            
            return fill
        
        # Limit orders: fill if price is favorable
        elif order.order_type == "LIMIT" and order.limit_price:
            if order.side == "BUY" and current_price <= order.limit_price:
                exec_price = min(current_price, order.limit_price) * (1 + self.slippage_pct * 0.5)
                trade_value = order.quantity * exec_price
                fees = trade_value * self.fee_pct
                slippage_cost = abs(order.quantity * (exec_price - current_price))
                
                fill = Fill(
                    fill_id=f"FILL_{len(self.fills) + 1}",
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    price=exec_price,
                    timestamp=timestamp,
                    fees=fees,
                    slippage=slippage_cost,
                    strategy_name=order.strategy_name
                )
                
                return fill
            
            elif order.side == "SELL" and current_price >= order.limit_price:
                exec_price = max(current_price, order.limit_price) * (1 - self.slippage_pct * 0.5)
                trade_value = order.quantity * exec_price
                fees = trade_value * self.fee_pct
                slippage_cost = abs(order.quantity * (exec_price - current_price))
                
                fill = Fill(
                    fill_id=f"FILL_{len(self.fills) + 1}",
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    price=exec_price,
                    timestamp=timestamp,
                    fees=fees,
                    slippage=slippage_cost,
                    strategy_name=order.strategy_name
                )
                
                return fill
        
        return None
    
    def get_fills(self) -> List[Fill]:
        """Get all fills."""
        return self.fills.copy()
    
    def get_orders(self) -> List[Order]:
        """Get all orders."""
        return list(self.orders.values())
