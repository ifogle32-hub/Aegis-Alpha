"""Paper trading executor (no real money)."""
from typing import Dict, Optional, List, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
from sentinel_x.monitoring.logger import logger
from sentinel_x.execution.broker_base import BaseBroker

if TYPE_CHECKING:
    from sentinel_x.intelligence.strategy_manager import StrategyManager
    from sentinel_x.strategies.base import BaseStrategy


@dataclass
class Position:
    """Represents a trading position."""
    symbol: str
    size: float  # Positive for long, negative for short
    entry_price: float
    entry_time: datetime
    current_price: float = 0.0
    
    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized P&L."""
        return self.size * (self.current_price - self.entry_price)
    
    @property
    def notional_value(self) -> float:
        """Calculate current notional value."""
        return abs(self.size) * self.current_price


@dataclass
class Fill:
    """Represents a trade fill."""
    symbol: str
    side: str  # "BUY" or "SELL"
    size: float
    price: float
    timestamp: datetime
    strategy: str = ""


class PaperExecutor(BaseBroker):
    """Paper trading executor that simulates order execution."""
    
    @property
    def name(self) -> str:
        return "paper"
    
    @property
    def mode(self) -> str:
        return "PAPER"
    
    def __init__(self, initial_capital: float = 100000.0, 
                 strategy_manager: Optional['StrategyManager'] = None):
        """
        Initialize paper executor.
        
        Args:
            initial_capital: Starting capital in USD
            strategy_manager: Strategy manager to check strategy status
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.fills: List[Fill] = []
        self.total_pnl = 0.0
        self.strategy_manager = strategy_manager
        
        logger.info(f"PaperExecutor initialized with ${initial_capital:,.2f} capital")
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol."""
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Position]:
        """Get all current positions."""
        return self.positions.copy()
    
    def get_account(self) -> Optional[Dict]:
        """Get account information."""
        return {
            'equity': self.get_portfolio_value(),
            'cash': self.cash,
            'buying_power': self.cash,
            'portfolio_value': self.get_portfolio_value(),
        }
    
    def get_positions(self) -> List[Dict]:
        """
        Get all positions as list of dictionaries for API (read-only).
        
        Returns:
            List of position dictionaries with symbol, qty, avg_price, current_price, unrealized_pnl, entry_time
        """
        positions_list = []
        for symbol, position in self.positions.items():
            positions_list.append({
                'symbol': symbol,
                'qty': position.size,
                'avg_price': position.entry_price,
                'current_price': position.current_price,
                'unrealized_pnl': position.unrealized_pnl,
                'entry_time': position.entry_time
            })
        return positions_list
    
    def get_portfolio_value(self) -> float:
        """Calculate total portfolio value (cash + positions)."""
        total = self.cash
        
        for position in self.positions.values():
            total += position.notional_value
            total += position.unrealized_pnl
        
        return total
    
    def update_prices(self, prices: Dict[str, float]) -> None:
        """Update current prices for all positions."""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].current_price = price
    
    def submit_order(self, symbol: str, side: str, qty: float, 
                     price: Optional[float] = None, strategy: str = "") -> Optional[Dict]:
        """
        Submit order (matches router interface).
        
        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            qty: Order quantity (always positive)
            price: Execution price (required)
            strategy: Strategy name
            
        Returns:
            Fill object or None if order rejected
        """
        if price is None:
            logger.warning(f"Price required for order on {symbol}")
            return None
        
        # Convert side and qty to size (positive for BUY, negative for SELL)
        size = qty if side.upper() == "BUY" else -qty
        return self.execute_order(symbol, size, price, strategy)
    
    def execute_order(self, symbol: str, size: float, price: float, 
                     strategy: str = "", strategy_instance: Optional['BaseStrategy'] = None) -> Optional[Fill]:
        """
        Execute an order (simulated).
        
        Args:
            symbol: Trading symbol
            size: Position size (positive for long, negative for short)
            price: Execution price
            strategy: Strategy name that generated the order
            strategy_instance: Strategy instance (to check if active)
            
        Returns:
            Fill object or None if order rejected
        """
        # Check if strategy is active (if strategy_manager available)
        if self.strategy_manager and strategy_instance:
            if not self.strategy_manager.is_active(strategy_instance):
                logger.debug(f"Ignoring order from DISABLED strategy: {strategy}")
                return None
        
        # Get current position
        current_position = self.positions.get(symbol)
        current_size = current_position.size if current_position else 0.0
        
        # Calculate new position size
        new_size = current_size + size
        
        # Calculate order cost
        order_cost = abs(size) * price
        
        # Check if we have enough cash for long positions
        if new_size > 0 and order_cost > self.cash:
            logger.warning(f"Insufficient cash for {symbol} order: need ${order_cost:.2f}, have ${self.cash:.2f}")
            return None
        
        # Execute the order
        side = "BUY" if size > 0 else "SELL"
        
        fill = Fill(
            symbol=symbol,
            side=side,
            size=abs(size),
            price=price,
            timestamp=datetime.now(),
            strategy=strategy
        )
        
        # Update position
        if new_size == 0:
            # Closing position
            if symbol in self.positions:
                old_position = self.positions[symbol]
                realized_pnl = old_position.size * (price - old_position.entry_price)
                self.total_pnl += realized_pnl
                self.cash += old_position.notional_value + realized_pnl
                del self.positions[symbol]
                logger.info(f"Closed {symbol} position. Realized P&L: ${realized_pnl:.2f}")
        else:
            # Opening or adjusting position
            if current_position:
                # Update existing position (simple average price)
                total_value = current_position.size * current_position.entry_price + size * price
                new_entry_price = total_value / new_size
                self.positions[symbol] = Position(
                    symbol=symbol,
                    size=new_size,
                    entry_price=new_entry_price,
                    entry_time=current_position.entry_time,
                    current_price=price
                )
            else:
                # New position
                self.positions[symbol] = Position(
                    symbol=symbol,
                    size=new_size,
                    entry_price=price,
                    entry_time=datetime.now(),
                    current_price=price
                )
            
            # Update cash
            if size > 0:
                # Buying: reduce cash
                self.cash -= order_cost
            else:
                # Selling: increase cash
                self.cash += order_cost
        
        self.fills.append(fill)
        logger.info(f"Fill: {side} {abs(size):.4f} {symbol} @ ${price:.2f} (Strategy: {strategy})")
        
        # Return as dict for broker interface
        return {
            'order_id': f"paper_{len(self.fills)}",
            'symbol': symbol,
            'side': side,
            'qty': abs(size),
            'price': price,
            'status': 'filled',
            'strategy': strategy,
            'timestamp': fill.timestamp.isoformat()
        }
    
    def get_total_pnl(self) -> float:
        """Get total realized P&L."""
        return self.total_pnl
    
    def get_unrealized_pnl(self) -> float:
        """Get total unrealized P&L."""
        return sum(pos.unrealized_pnl for pos in self.positions.values())
    
    def get_fills(self, since_ts: Optional[datetime] = None) -> List[Dict]:
        """Get fills since timestamp."""
        fills = self.fills.copy()
        if since_ts:
            fills = [f for f in fills if f.timestamp >= since_ts]
        
        return [
            {
                'symbol': f.symbol,
                'side': f.side,
                'qty': f.size,
                'price': f.price,
                'timestamp': f.timestamp.isoformat(),
                'strategy': f.strategy
            }
            for f in fills
        ]
    
    def cancel_all_orders(self) -> int:
        logger.info("PaperExecutor: cancel_all_orders (noop)")
        return 0
    
    def health_check(self) -> dict:
        """
        Non-fatal health probe for simulated paper executor.
        
        RULE: Health checks must NEVER raise exceptions.
        Paper executor is always "connected" since it's simulated.
        
        Returns:
            Dictionary with health status:
            - connected: bool - Always True for paper executor
            - broker: str - Always "paper_simulated"
        """
        try:
            return {
                "connected": True,
                "broker": "paper_simulated"
            }
        except Exception as e:
            # CRITICAL: Health check must NEVER raise (defensive)
            logger.error(f"Paper executor health check error (should never happen): {e}", exc_info=True)
            return {
                "connected": False,
                "broker": "paper_simulated",
                "error": f"Health check exception: {str(e)}"
            }


# Global executor instance
_executor = None


def get_executor(initial_capital: float = 100000.0, 
                 strategy_manager: Optional['StrategyManager'] = None) -> PaperExecutor:
    """Get global paper executor instance."""
    global _executor
    if _executor is None:
        _executor = PaperExecutor(initial_capital, strategy_manager)
    elif strategy_manager and _executor.strategy_manager is None:
        # Update strategy manager if not set
        _executor.strategy_manager = strategy_manager
    return _executor

