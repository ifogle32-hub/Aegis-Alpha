"""
PHASE 6 — SIMULATED PORTFOLIO

SAFETY: OFFLINE BACKTEST ENGINE
REGRESSION LOCK — DO NOT CONNECT TO LIVE

Tracks:
- Cash
- Positions
- Realized PnL
- Unrealized PnL
- Drawdown
- Exposure

Supports:
- Per-strategy attribution
- Portfolio-level aggregation

NO margin or leverage shortcuts yet.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict

# SAFETY: OFFLINE BACKTEST ENGINE
# REGRESSION LOCK — DO NOT CONNECT TO LIVE

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class Position:
    """PHASE 6: Position representation."""
    symbol: str
    quantity: float  # Positive for long, negative for short
    avg_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class SimulatedPortfolio:
    """
    PHASE 6: Simulated portfolio for backtesting.
    
    SAFETY: offline only
    SAFETY: no live execution path
    
    Note: Full implementation in sentinel_x/research/backtest_engine.py
    This is a scaffolding interface.
    """
    
    def __init__(self, initial_capital: float = 100000.0):
        """
        Initialize simulated portfolio.
        
        Args:
            initial_capital: Starting capital
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}  # symbol -> Position
        self.trades: List[Dict] = []  # Trade history
        
        # PnL tracking
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.total_pnl = 0.0
        
        # Equity curve
        self.equity_curve: List[Dict] = []
        
        # Strategy-level attribution
        self.strategy_pnl: Dict[str, float] = defaultdict(float)
        self.strategy_trades: Dict[str, List[Dict]] = defaultdict(list)
        
        logger.info(f"SimulatedPortfolio initialized: initial_capital=${initial_capital:,.2f}")
    
    def update_position(self, symbol: str, quantity: float, price: float, fees: float, strategy_name: str = ""):
        """
        PHASE 6: Update position after fill.
        
        SAFETY: offline only
        """
        # Simplified position update (full implementation in research/backtest_engine.py)
        if symbol not in self.positions:
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=0.0,
                avg_price=0.0,
                current_price=price
            )
        
        position = self.positions[symbol]
        
        # Update position (simplified)
        if quantity > 0:  # Buying
            if position.quantity <= 0:
                # Opening long or closing short
                position.quantity = quantity
                position.avg_price = price
                self.cash -= (quantity * price + fees)
            else:
                # Adding to long
                total_value = position.quantity * position.avg_price + quantity * price
                position.quantity += quantity
                position.avg_price = total_value / position.quantity
                self.cash -= (quantity * price + fees)
        else:  # Selling
            if position.quantity > 0:
                # Closing long or opening short
                realized_pnl = abs(quantity) * (price - position.avg_price) - fees
                self.realized_pnl += realized_pnl
                self.strategy_pnl[strategy_name] += realized_pnl
                position.quantity += quantity
                if position.quantity == 0:
                    position.avg_price = 0.0
                self.cash += (abs(quantity) * price - fees)
        
        # Record trade
        trade = {
            'symbol': symbol,
            'quantity': quantity,
            'price': price,
            'fees': fees,
            'strategy_name': strategy_name,
            'timestamp': datetime.now()
        }
        self.trades.append(trade)
        self.strategy_trades[strategy_name].append(trade)
    
    def update_prices(self, prices: Dict[str, float]):
        """
        PHASE 6: Update current prices and recalculate unrealized PnL.
        
        SAFETY: offline only
        """
        self.unrealized_pnl = 0.0
        
        for symbol, position in self.positions.items():
            if symbol in prices:
                position.current_price = prices[symbol]
                position.unrealized_pnl = position.quantity * (position.current_price - position.avg_price)
                self.unrealized_pnl += position.unrealized_pnl
        
        self.total_pnl = self.realized_pnl + self.unrealized_pnl
    
    def get_equity(self) -> float:
        """PHASE 6: Get current equity (cash + positions value)."""
        return self.cash + sum(pos.quantity * pos.current_price for pos in self.positions.values())
    
    def get_exposure(self) -> float:
        """PHASE 6: Get total exposure (absolute value of positions)."""
        return sum(abs(pos.quantity * pos.current_price) for pos in self.positions.values())
    
    def get_drawdown(self) -> float:
        """PHASE 6: Get current drawdown from peak equity."""
        if not self.equity_curve:
            return 0.0
        
        current_equity = self.get_equity()
        peak_equity = max(eq.get('equity', self.initial_capital) for eq in self.equity_curve) if self.equity_curve else self.initial_capital
        peak_equity = max(peak_equity, self.initial_capital)
        
        if peak_equity == 0:
            return 0.0
        
        return (peak_equity - current_equity) / peak_equity
    
    def snapshot(self, timestamp: datetime):
        """PHASE 6: Take equity curve snapshot."""
        equity = self.get_equity()
        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': equity,
            'cash': self.cash,
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': self.unrealized_pnl,
            'total_pnl': self.total_pnl,
            'exposure': self.get_exposure(),
            'drawdown': self.get_drawdown()
        })
