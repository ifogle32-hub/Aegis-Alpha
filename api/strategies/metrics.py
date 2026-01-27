"""
Strategy Metrics Model

PHASE 11 — STRATEGY METRICS CONTRACT

Read-only metrics model for strategy performance evaluation.
Metrics are computed by the engine loop and consumed by auto-promotion engine.
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class StrategyMetrics:
    """
    PHASE 11 — STRATEGY METRICS
    
    Performance metrics for a strategy over a rolling window.
    All metrics are read-only inputs from the engine loop.
    """
    strategy_id: str
    pnl_rolling_30d: float = 0.0  # Rolling 30-day PnL
    sharpe_rolling_30d: float = 0.0  # Rolling 30-day Sharpe ratio
    max_drawdown_30d: float = 0.0  # Maximum drawdown over 30 days (positive value)
    trade_count: int = 0  # Total trade count
    last_updated: float = 0.0  # Timestamp of last update
    
    def to_dict(self) -> dict:
        """Convert to dict for API responses"""
        return {
            "strategy_id": self.strategy_id,
            "pnl_rolling_30d": self.pnl_rolling_30d,
            "sharpe_rolling_30d": self.sharpe_rolling_30d,
            "max_drawdown_30d": self.max_drawdown_30d,
            "trade_count": self.trade_count,
            "last_updated": self.last_updated,
        }
    
    def is_valid(self) -> bool:
        """Check if metrics are valid (not stale)"""
        # Metrics older than 24 hours are considered stale
        import time
        age_hours = (time.time() - self.last_updated) / 3600.0
        return age_hours < 24.0
