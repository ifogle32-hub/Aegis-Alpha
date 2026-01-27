"""
PHASE 1 — SHADOW BACKTESTING MODULE

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Shadow backtesting simulator for strategy evaluation.
"""

from sentinel_x.backtest.types import PriceBar, Signal
from sentinel_x.backtest.data_loader import load_price_history, load_price_history_dict
from sentinel_x.backtest.simulator import ShadowBacktestSimulator, BacktestResult, run_backtest

__all__ = [
    'PriceBar',
    'Signal',
    'load_price_history',
    'load_price_history_dict',
    'ShadowBacktestSimulator',
    'BacktestResult',
    'run_backtest'
]
