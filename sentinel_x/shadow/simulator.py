"""
PHASE 4 — SHADOW EXECUTION SIMULATOR

SimulationEngine for deterministic shadow execution with:
- No broker code allowed
- Deterministic fills
- Configurable slippage/spread models
- Latency simulation
- Partial fills
- Order rejection simulation
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading
import numpy as np

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.feed import MarketTick


class OrderType(str, Enum):
    """Order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderSide(str, Enum):
    """Order sides."""
    BUY = "BUY"
    SELL = "SELL"


class FillStatus(str, Enum):
    """Fill status."""
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


@dataclass
class SimulatedOrder:
    """
    Simulated order.
    """
    order_id: str
    strategy_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None  # For limit orders
    stop_price: Optional[float] = None  # For stop orders
    timestamp: datetime = field(default_factory=datetime.utcnow)
    status: FillStatus = FillStatus.PENDING
    filled_quantity: float = 0.0
    fill_price: Optional[float] = None
    fill_timestamp: Optional[datetime] = None
    rejection_reason: Optional[str] = None


@dataclass
class SlippageModel:
    """
    Slippage model configuration.
    """
    base_slippage_bps: float = 5.0  # 5 basis points base slippage
    volatility_multiplier: float = 1.0  # Multiply by volatility
    size_impact: float = 0.0001  # Impact per unit of size
    
    def calculate_slippage(
        self,
        base_price: float,
        quantity: float,
        volatility: float = 0.02,
    ) -> float:
        """
        Calculate slippage in price units.
        
        Args:
            base_price: Base price
            quantity: Order quantity
            volatility: Market volatility
            
        Returns:
            Slippage in price units
        """
        base = base_price * (self.base_slippage_bps / 10000)
        vol_component = base_price * volatility * self.volatility_multiplier
        size_component = base_price * abs(quantity) * self.size_impact
        
        return base + vol_component + size_component


@dataclass
class SpreadModel:
    """
    Spread model configuration.
    """
    base_spread_bps: float = 10.0  # 10 basis points base spread
    volatility_multiplier: float = 1.5  # Spread widens with volatility
    
    def calculate_spread(
        self,
        mid_price: float,
        volatility: float = 0.02,
    ) -> Tuple[float, float]:
        """
        Calculate bid/ask spread.
        
        Args:
            mid_price: Mid price
            volatility: Market volatility
            
        Returns:
            Tuple of (bid, ask)
        """
        spread_bps = self.base_spread_bps * (1 + volatility * self.volatility_multiplier)
        spread = mid_price * (spread_bps / 10000)
        
        bid = mid_price - spread / 2
        ask = mid_price + spread / 2
        
        return bid, ask


@dataclass
class LatencyModel:
    """
    Latency simulation model.
    """
    mean_ms: float = 50.0  # Mean latency in milliseconds
    std_ms: float = 10.0  # Standard deviation
    
    def simulate_latency(self) -> float:
        """
        Simulate order latency.
        
        Returns:
            Latency in seconds
        """
        latency_ms = max(0, np.random.normal(self.mean_ms, self.std_ms))
        return latency_ms / 1000.0


class SimulationEngine:
    """
    Shadow execution simulator.
    
    SAFETY: No broker code allowed. All execution is simulated.
    
    Features:
    - Deterministic fills (with configurable randomness)
    - Slippage and spread models
    - Latency simulation
    - Partial fills
    - Order rejection simulation
    - Position lifecycle tracking
    """
    
    def __init__(
        self,
        initial_capital: float = 100000.0,
        slippage_model: Optional[SlippageModel] = None,
        spread_model: Optional[SpreadModel] = None,
        latency_model: Optional[LatencyModel] = None,
    ):
        """
        Initialize simulation engine.
        
        Args:
            initial_capital: Starting capital
            slippage_model: Optional slippage model
            spread_model: Optional spread model
            latency_model: Optional latency model
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position data
        self.orders: Dict[str, SimulatedOrder] = {}
        self.order_history: List[SimulatedOrder] = []
        
        self.slippage_model = slippage_model or SlippageModel()
        self.spread_model = spread_model or SpreadModel()
        self.latency_model = latency_model or LatencyModel()
        
        self._lock = threading.RLock()
        self._order_counter = 0
        
        logger.info(f"SimulationEngine initialized with capital: ${initial_capital:,.2f}")
    
    def submit_order(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> SimulatedOrder:
        """
        Submit order for simulation.
        
        Args:
            strategy_id: Strategy identifier
            symbol: Trading symbol
            side: Order side ("BUY" or "SELL")
            quantity: Order quantity
            order_type: Order type ("MARKET", "LIMIT", "STOP")
            price: Limit price (for limit orders)
            stop_price: Stop price (for stop orders)
            
        Returns:
            SimulatedOrder instance
        """
        with self._lock:
            self._order_counter += 1
            order_id = f"SHADOW_{self._order_counter}"
            
            order = SimulatedOrder(
                order_id=order_id,
                strategy_id=strategy_id,
                symbol=symbol,
                side=OrderSide(side.upper()),
                order_type=OrderType(order_type.upper()),
                quantity=abs(quantity),
                price=price,
                stop_price=stop_price,
            )
            
            self.orders[order_id] = order
            
            logger.debug(
                f"Shadow order submitted: {order_id} | "
                f"strategy={strategy_id} | symbol={symbol} | "
                f"side={side} | qty={quantity} | type={order_type}"
            )
            
            return order
    
    def process_tick(self, tick: MarketTick) -> List[SimulatedOrder]:
        """
        Process market tick and fill eligible orders.
        
        Args:
            tick: Market tick
            
        Returns:
            List of filled orders
        """
        with self._lock:
            filled_orders = []
            
            # Process pending orders for this symbol
            for order_id, order in list(self.orders.items()):
                if order.symbol != tick.symbol:
                    continue
                
                if order.status != FillStatus.PENDING:
                    continue
                
                # Check if order should be filled
                fill_result = self._check_order_fill(order, tick)
                
                if fill_result:
                    fill_price, fill_qty, rejection_reason = fill_result
                    
                    if rejection_reason:
                        order.status = FillStatus.REJECTED
                        order.rejection_reason = rejection_reason
                        logger.debug(f"Shadow order rejected: {order_id} | reason={rejection_reason}")
                    else:
                        # Fill order
                        order.status = FillStatus.FILLED if fill_qty == order.quantity else FillStatus.PARTIAL
                        order.filled_quantity = fill_qty
                        order.fill_price = fill_price
                        order.fill_timestamp = tick.timestamp
                        
                        # Update position
                        self._update_position(order, fill_price, fill_qty)
                        
                        filled_orders.append(order)
                        logger.debug(
                            f"Shadow order filled: {order_id} | "
                            f"qty={fill_qty}/{order.quantity} | price={fill_price:.2f}"
                        )
                    
                    # Move to history
                    self.order_history.append(order)
                    del self.orders[order_id]
            
            return filled_orders
    
    def _check_order_fill(
        self,
        order: SimulatedOrder,
        tick: MarketTick,
    ) -> Optional[Tuple[float, float, Optional[str]]]:
        """
        Check if order should be filled.
        
        Returns:
            Tuple of (fill_price, fill_quantity, rejection_reason) or None
        """
        # Simulate latency
        if self.latency_model:
            latency = self.latency_model.simulate_latency()
            # In real implementation, would delay fill by latency
        
        # Check order type
        if order.order_type == OrderType.MARKET:
            return self._fill_market_order(order, tick)
        elif order.order_type == OrderType.LIMIT:
            return self._fill_limit_order(order, tick)
        elif order.order_type == OrderType.STOP:
            return self._fill_stop_order(order, tick)
        else:
            return None, 0.0, f"Unknown order type: {order.order_type}"
    
    def _fill_market_order(
        self,
        order: SimulatedOrder,
        tick: MarketTick,
    ) -> Tuple[float, float, Optional[str]]:
        """Fill market order."""
        # Calculate slippage
        base_price = tick.bid if order.side == OrderSide.BUY else tick.ask
        if base_price is None:
            base_price = tick.price
        
        slippage = self.slippage_model.calculate_slippage(
            base_price,
            order.quantity,
            volatility=0.02,  # Could use tick volatility if available
        )
        
        # Apply slippage
        if order.side == OrderSide.BUY:
            fill_price = base_price + slippage
        else:
            fill_price = base_price - slippage
        
        # Check if we have enough cash (for buys)
        if order.side == OrderSide.BUY:
            required_cash = fill_price * order.quantity
            if required_cash > self.cash:
                # Partial fill
                fill_qty = self.cash / fill_price
                if fill_qty < 0.01:  # Minimum fill size
                    return None, 0.0, "Insufficient capital"
                return fill_price, fill_qty, None
        
        return fill_price, order.quantity, None
    
    def _fill_limit_order(
        self,
        order: SimulatedOrder,
        tick: MarketTick,
    ) -> Tuple[float, float, Optional[str]]:
        """Fill limit order."""
        if order.price is None:
            return None, 0.0, "Limit price not set"
        
        # Check if limit price is hit
        if order.side == OrderSide.BUY:
            # Buy limit: fill if ask <= limit price
            if tick.ask and tick.ask <= order.price:
                return order.price, order.quantity, None
            elif tick.price <= order.price:
                return order.price, order.quantity, None
        else:
            # Sell limit: fill if bid >= limit price
            if tick.bid and tick.bid >= order.price:
                return order.price, order.quantity, None
            elif tick.price >= order.price:
                return order.price, order.quantity, None
        
        # Not filled
        return None, 0.0, None
    
    def _fill_stop_order(
        self,
        order: SimulatedOrder,
        tick: MarketTick,
    ) -> Tuple[float, float, Optional[str]]:
        """Fill stop order."""
        if order.stop_price is None:
            return None, 0.0, "Stop price not set"
        
        # Check if stop price is hit
        if order.side == OrderSide.BUY:
            # Buy stop: fill if price >= stop price
            if tick.price >= order.stop_price:
                return self._fill_market_order(order, tick)[:2] + (None,)
        else:
            # Sell stop: fill if price <= stop price
            if tick.price <= order.stop_price:
                return self._fill_market_order(order, tick)[:2] + (None,)
        
        # Not filled
        return None, 0.0, None
    
    def _update_position(
        self,
        order: SimulatedOrder,
        fill_price: float,
        fill_qty: float,
    ) -> None:
        """Update position after fill."""
        symbol = order.symbol
        
        if symbol not in self.positions:
            self.positions[symbol] = {
                "quantity": 0.0,
                "avg_price": 0.0,
                "unrealized_pnl": 0.0,
            }
        
        pos = self.positions[symbol]
        
        if order.side == OrderSide.BUY:
            # Buying
            total_cost = pos["quantity"] * pos["avg_price"] + fill_price * fill_qty
            pos["quantity"] += fill_qty
            if pos["quantity"] > 0:
                pos["avg_price"] = total_cost / pos["quantity"]
            
            # Update cash
            self.cash -= fill_price * fill_qty
        else:
            # Selling
            if pos["quantity"] < fill_qty:
                # Short sale (not fully covered)
                fill_qty = pos["quantity"]
            
            pos["quantity"] -= fill_qty
            
            # Update cash
            self.cash += fill_price * fill_qty
            
            # Update average price if still holding
            if pos["quantity"] > 0:
                # Keep same avg_price
                pass
    
    def get_position(self, symbol: str) -> Dict[str, Any]:
        """
        Get position for symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Position dictionary
        """
        with self._lock:
            return self.positions.get(symbol, {
                "quantity": 0.0,
                "avg_price": 0.0,
                "unrealized_pnl": 0.0,
            }).copy()
    
    def get_portfolio_value(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total portfolio value.
        
        Args:
            current_prices: Dict mapping symbol to current price
            
        Returns:
            Total portfolio value
        """
        with self._lock:
            value = self.cash
            
            for symbol, pos in self.positions.items():
                if symbol in current_prices:
                    value += pos["quantity"] * current_prices[symbol]
            
            return value
    
    def reset(self) -> None:
        """Reset simulator to initial state."""
        with self._lock:
            self.cash = self.initial_capital
            self.positions = {}
            self.orders = {}
            self.order_history = []
            self._order_counter = 0
            logger.info("SimulationEngine reset")


# Global simulator instance
_simulator: Optional[SimulationEngine] = None
_simulator_lock = threading.Lock()


def get_simulation_engine(
    initial_capital: float = 100000.0,
    **kwargs
) -> SimulationEngine:
    """
    Get global simulation engine instance (singleton).
    
    Args:
        initial_capital: Starting capital
        **kwargs: Additional arguments for SimulationEngine
        
    Returns:
        SimulationEngine instance
    """
    global _simulator
    
    if _simulator is None:
        with _simulator_lock:
            if _simulator is None:
                _simulator = SimulationEngine(initial_capital, **kwargs)
    
    return _simulator
