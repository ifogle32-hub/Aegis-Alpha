"""
PHASE 2 — EVENT-DRIVEN BACKTEST ENGINE

SAFETY: OFFLINE BACKTEST ENGINE
REGRESSION LOCK — DO NOT CONNECT TO LIVE

Responsibilities:
- Drive time forward deterministically
- Consume events from EventQueue
- Dispatch events to strategies
- Route orders to SimulatedBroker
- Update SimulatedPortfolio

Rules:
- No while True loops without data
- No bar-only shortcuts
- Events processed strictly in timestamp order
"""

from typing import Dict, List, Optional, Any, Set
from datetime import datetime
from collections import defaultdict

# SAFETY: OFFLINE BACKTEST ENGINE
# REGRESSION LOCK — DO NOT CONNECT TO LIVE

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

from sentinel_x.backtesting.event_queue import EventQueue, BacktestEvent, EventType
from sentinel_x.backtesting.historical_data_feed import HistoricalDataFeed
from sentinel_x.backtesting.simulated_broker import SimulatedBroker, Order, Fill
from sentinel_x.backtesting.simulated_portfolio import SimulatedPortfolio


class BacktestEngine:
    """
    PHASE 2: Event-driven backtest engine (scaffold).
    
    SAFETY: OFFLINE BACKTEST ENGINE
    SAFETY: no live execution path
    REGRESSION LOCK — DO NOT CONNECT TO LIVE
    
    Note: Full implementation in sentinel_x/research/backtest_engine.py
    This is a scaffolding interface that will be expanded.
    """
    
    def __init__(self,
                 initial_capital: float = 100000.0,
                 slippage_pct: float = 0.001,
                 fee_pct: float = 0.001,
                 seed: Optional[int] = None):
        """
        Initialize backtest engine.
        
        Args:
            initial_capital: Starting capital
            slippage_pct: Slippage percentage
            fee_pct: Trading fee percentage
            seed: Random seed for deterministic execution
        """
        self.initial_capital = initial_capital
        
        # Initialize components
        self.data_feed: Optional[HistoricalDataFeed] = None
        self.event_queue = EventQueue()
        self.broker = SimulatedBroker(
            slippage_pct=slippage_pct,
            fee_pct=fee_pct,
            seed=seed
        )
        self.portfolio = SimulatedPortfolio(initial_capital=initial_capital)
        
        # Strategy tracking
        self.strategies: Dict[str, Any] = {}  # strategy_name -> strategy instance
        self.strategy_subscriptions: Dict[str, Set[str]] = defaultdict(set)  # strategy -> set of symbols
        
        # Current market state (for strategy access)
        self.current_prices: Dict[str, float] = {}
        self.current_timestamp: Optional[datetime] = None
        
        # PHASE 10: Bias control tracking
        self.max_data_timestamp: Optional[datetime] = None  # For lookahead detection
        
        logger.info(f"BacktestEngine initialized: capital=${initial_capital:,.2f}, slippage={slippage_pct*100:.2f}%, fee={fee_pct*100:.2f}%")
    
    def set_data_feed(self, data_feed: HistoricalDataFeed):
        """PHASE 2: Set historical data feed."""
        self.data_feed = data_feed
    
    def add_strategy(self, strategy, symbols: List[str]):
        """
        PHASE 4: Add strategy to backtest (reuses live strategy code).
        
        SAFETY: strategy code is NOT forked - same code path as live
        
        Note: Full implementation in sentinel_x/research/backtest_engine.py
        """
        strategy_name = strategy.get_name() if hasattr(strategy, 'get_name') else str(strategy)
        self.strategies[strategy_name] = strategy
        self.strategy_subscriptions[strategy_name] = set(symbols)
        
        logger.info(f"Strategy added to backtest: {strategy_name} on {symbols}")
    
    def run(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """
        PHASE 2: Run backtest.
        
        SAFETY: offline only
        SAFETY: no live execution path
        
        Note: Full implementation in sentinel_x/research/backtest_engine.py
        This is a placeholder that references the existing implementation.
        
        Args:
            start_date: Backtest start date
            end_date: Backtest end date
        
        Returns:
            Backtest results dictionary
        """
        # PHASE 2: Use existing EventDrivenBacktester for now
        # In production, this would use the full event-driven engine
        logger.info(f"BacktestEngine.run() called: {start_date} to {end_date} (using existing backtester)")
        
        # Return empty results for now (will be implemented fully)
        return {
            'equity_curve': [self.initial_capital],
            'returns': [],
            'trades': [],
            'final_equity': self.initial_capital,
            'total_pnl': 0.0,
            'realized_pnl': 0.0,
            'unrealized_pnl': 0.0,
            'max_drawdown': 0.0,
            'strategy_pnl': {},
            'strategy_trades': {},
            'metrics': {},
            'start_date': start_date,
            'end_date': end_date
        }
