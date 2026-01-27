"""
PHASE 1 — BACKTESTER CORE PACKAGE

SAFETY: OFFLINE BACKTEST ENGINE
REGRESSION LOCK — DO NOT CONNECT TO LIVE

This package provides offline backtesting capabilities:
- Event-driven backtesting engine
- Historical data feed
- Simulated broker and portfolio
- Strategy reuse (no forking)
- Bias controls
- Integration with promotion/demotion logic

NO live execution paths
NO live broker imports
NO engine loop dependencies
"""

# SAFETY: OFFLINE BACKTEST ENGINE
# REGRESSION LOCK — DO NOT CONNECT TO LIVE

# PHASE 1: Core components (scaffold + implementation)
from sentinel_x.backtesting.event_queue import EventQueue, BacktestEvent, EventType
from sentinel_x.backtesting.historical_data_feed import HistoricalDataFeed
from sentinel_x.backtesting.simulated_broker import SimulatedBroker, Order, Fill
from sentinel_x.backtesting.simulated_portfolio import SimulatedPortfolio, Position
from sentinel_x.backtesting.backtest_engine import BacktestEngine

# PHASE 8: Governance bridge (backtest → promotion)
from sentinel_x.backtesting.governance_bridge import (
    PromotionEvaluator, BacktestMetrics, LiveTrainingMetrics, 
    MergedPromotionScore, get_promotion_evaluator
)

# PHASE 7: Backtest runner and results
from sentinel_x.backtesting.backtest_runner import (
    BacktestRunner, BacktestConfig, BacktestResult
)

__all__ = [
    # Event queue
    'EventQueue',
    'BacktestEvent',
    'EventType',
    # Historical data feed
    'HistoricalDataFeed',
    # Simulated broker
    'SimulatedBroker',
    'Order',
    'Fill',
    # Simulated portfolio
    'SimulatedPortfolio',
    'Position',
    # Backtest engine
    'BacktestEngine',
    # Governance bridge
    'PromotionEvaluator',
    'BacktestMetrics',
    'LiveTrainingMetrics',
    'MergedPromotionScore',
    'get_promotion_evaluator',
    # Backtest runner
    'BacktestRunner',
    'BacktestConfig',
    'BacktestResult'
]
