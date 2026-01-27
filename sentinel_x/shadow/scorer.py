"""
PHASE 5 — METRIC & SCORING ENGINE

ShadowScorer capturing comprehensive performance metrics.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import numpy as np
import threading

from sentinel_x.monitoring.logger import logger


@dataclass
class PerformanceMetrics:
    """
    Comprehensive performance metrics for a strategy.
    """
    strategy_id: str
    window_start: datetime
    window_end: datetime
    
    # PnL metrics
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    
    # Return metrics
    total_return: float = 0.0
    annualized_return: float = 0.0
    
    # Risk metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    volatility: float = 0.0
    
    # Trade metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    
    # Exposure metrics
    time_in_market: float = 0.0  # Fraction of time in market
    max_position_size: float = 0.0
    avg_position_size: float = 0.0
    
    # Latency metrics
    avg_fill_latency_ms: float = 0.0
    max_fill_latency_ms: float = 0.0
    
    # Risk-adjusted metrics
    risk_adjusted_return: float = 0.0
    calmar_ratio: float = 0.0
    
    # Regime performance (filled by RegimeAnalyzer)
    regime_performance: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "strategy_id": self.strategy_id,
            "window_start": self.window_start.isoformat() + "Z",
            "window_end": self.window_end.isoformat() + "Z",
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "volatility": self.volatility,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "expectancy": self.expectancy,
            "time_in_market": self.time_in_market,
            "max_position_size": self.max_position_size,
            "avg_position_size": self.avg_position_size,
            "avg_fill_latency_ms": self.avg_fill_latency_ms,
            "max_fill_latency_ms": self.max_fill_latency_ms,
            "risk_adjusted_return": self.risk_adjusted_return,
            "calmar_ratio": self.calmar_ratio,
            "regime_performance": self.regime_performance,
        }


class ShadowScorer:
    """
    Shadow performance scorer.
    
    Captures and computes comprehensive metrics for shadow strategies.
    """
    
    def __init__(self):
        """Initialize scorer."""
        self.metrics: Dict[str, List[PerformanceMetrics]] = {}  # strategy_id -> metrics history
        self.trade_history: Dict[str, List[Dict[str, Any]]] = {}  # strategy_id -> trades
        self.equity_curve: Dict[str, List[Tuple[datetime, float]]] = {}  # strategy_id -> (timestamp, equity)
        self._lock = threading.RLock()
        
        logger.info("ShadowScorer initialized")
    
    def record_trade(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        timestamp: datetime,
        pnl: Optional[float] = None,
    ) -> None:
        """
        Record a trade.
        
        Args:
            strategy_id: Strategy identifier
            symbol: Trading symbol
            side: Trade side ("BUY" or "SELL")
            quantity: Trade quantity
            fill_price: Fill price
            timestamp: Trade timestamp
            pnl: Optional realized PnL
        """
        with self._lock:
            if strategy_id not in self.trade_history:
                self.trade_history[strategy_id] = []
            
            trade = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "fill_price": fill_price,
                "timestamp": timestamp.isoformat() + "Z",
                "pnl": pnl,
            }
            
            self.trade_history[strategy_id].append(trade)
    
    def record_equity(
        self,
        strategy_id: str,
        timestamp: datetime,
        equity: float,
    ) -> None:
        """
        Record equity snapshot.
        
        Args:
            strategy_id: Strategy identifier
            timestamp: Snapshot timestamp
            equity: Portfolio equity
        """
        with self._lock:
            if strategy_id not in self.equity_curve:
                self.equity_curve[strategy_id] = []
            
            self.equity_curve[strategy_id].append((timestamp, equity))
            
            # Keep only last 10000 points
            if len(self.equity_curve[strategy_id]) > 10000:
                self.equity_curve[strategy_id] = self.equity_curve[strategy_id][-10000:]
    
    def compute_metrics(
        self,
        strategy_id: str,
        window_start: datetime,
        window_end: datetime,
        initial_capital: float = 100000.0,
    ) -> PerformanceMetrics:
        """
        Compute performance metrics for a time window.
        
        Args:
            strategy_id: Strategy identifier
            window_start: Window start time
            window_end: Window end time
            initial_capital: Initial capital
            
        Returns:
            PerformanceMetrics instance
        """
        with self._lock:
            # Get trades in window
            trades = self._get_trades_in_window(strategy_id, window_start, window_end)
            
            # Get equity curve in window
            equity_points = self._get_equity_in_window(strategy_id, window_start, window_end)
            
            # Compute metrics
            metrics = PerformanceMetrics(
                strategy_id=strategy_id,
                window_start=window_start,
                window_end=window_end,
            )
            
            if not trades and not equity_points:
                return metrics
            
            # PnL from equity curve
            if equity_points:
                initial_equity = equity_points[0][1] if equity_points else initial_capital
                final_equity = equity_points[-1][1] if equity_points else initial_capital
                metrics.net_pnl = final_equity - initial_equity
                metrics.total_return = metrics.net_pnl / initial_equity if initial_equity > 0 else 0.0
                
                # Annualized return
                days = (window_end - window_start).days
                if days > 0:
                    metrics.annualized_return = (1 + metrics.total_return) ** (365.0 / days) - 1
            
            # Trade statistics
            if trades:
                metrics.total_trades = len(trades)
                
                # Separate winning and losing trades
                winning = [t for t in trades if t.get("pnl", 0) > 0]
                losing = [t for t in trades if t.get("pnl", 0) < 0]
                
                metrics.winning_trades = len(winning)
                metrics.losing_trades = len(losing)
                metrics.win_rate = metrics.winning_trades / metrics.total_trades if metrics.total_trades > 0 else 0.0
                
                if winning:
                    metrics.avg_win = np.mean([t.get("pnl", 0) for t in winning])
                if losing:
                    metrics.avg_loss = np.mean([t.get("pnl", 0) for t in losing])
                
                metrics.expectancy = (
                    metrics.win_rate * metrics.avg_win +
                    (1 - metrics.win_rate) * metrics.avg_loss
                )
                
                # Gross PnL from trades
                metrics.gross_pnl = sum(t.get("pnl", 0) for t in trades)
            
            # Risk metrics from equity curve
            if len(equity_points) > 1:
                returns = []
                for i in range(1, len(equity_points)):
                    prev_equity = equity_points[i-1][1]
                    curr_equity = equity_points[i][1]
                    if prev_equity > 0:
                        ret = (curr_equity - prev_equity) / prev_equity
                        returns.append(ret)
                
                if returns:
                    returns_array = np.array(returns)
                    metrics.volatility = np.std(returns_array) * np.sqrt(252)  # Annualized
                    
                    # Sharpe ratio (assuming risk-free rate = 0)
                    if metrics.volatility > 0:
                        metrics.sharpe_ratio = metrics.annualized_return / metrics.volatility
                    
                    # Sortino ratio (downside deviation)
                    downside_returns = returns_array[returns_array < 0]
                    if len(downside_returns) > 0:
                        downside_std = np.std(downside_returns) * np.sqrt(252)
                        if downside_std > 0:
                            metrics.sortino_ratio = metrics.annualized_return / downside_std
                    
                    # Max drawdown
                    equity_values = [p[1] for p in equity_points]
                    peak = equity_values[0]
                    max_dd = 0.0
                    for equity in equity_values:
                        if equity > peak:
                            peak = equity
                        dd = (peak - equity) / peak if peak > 0 else 0.0
                        if dd > max_dd:
                            max_dd = dd
                    metrics.max_drawdown = max_dd
                    
                    # Calmar ratio
                    if metrics.max_drawdown > 0:
                        metrics.calmar_ratio = metrics.annualized_return / metrics.max_drawdown
            
            # Risk-adjusted return
            if metrics.volatility > 0:
                metrics.risk_adjusted_return = metrics.annualized_return / metrics.volatility
            
            # Store metrics
            if strategy_id not in self.metrics:
                self.metrics[strategy_id] = []
            self.metrics[strategy_id].append(metrics)
            
            # Keep only last 100 metrics per strategy
            if len(self.metrics[strategy_id]) > 100:
                self.metrics[strategy_id] = self.metrics[strategy_id][-100:]
            
            return metrics
    
    def get_latest_metrics(
        self,
        strategy_id: str,
    ) -> Optional[PerformanceMetrics]:
        """
        Get latest metrics for strategy.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            Latest PerformanceMetrics or None
        """
        with self._lock:
            if strategy_id not in self.metrics or not self.metrics[strategy_id]:
                return None
            return self.metrics[strategy_id][-1]
    
    def get_metrics_history(
        self,
        strategy_id: str,
        limit: int = 100,
    ) -> List[PerformanceMetrics]:
        """
        Get metrics history for strategy.
        
        Args:
            strategy_id: Strategy identifier
            limit: Maximum number of metrics to return
            
        Returns:
            List of PerformanceMetrics
        """
        with self._lock:
            if strategy_id not in self.metrics:
                return []
            return self.metrics[strategy_id][-limit:]
    
    def _get_trades_in_window(
        self,
        strategy_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> List[Dict[str, Any]]:
        """Get trades in time window."""
        if strategy_id not in self.trade_history:
            return []
        
        trades = []
        for trade in self.trade_history[strategy_id]:
            trade_time = datetime.fromisoformat(trade["timestamp"].replace("Z", "+00:00"))
            if window_start <= trade_time <= window_end:
                trades.append(trade)
        
        return trades
    
    def _get_equity_in_window(
        self,
        strategy_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> List[Tuple[datetime, float]]:
        """Get equity points in time window."""
        if strategy_id not in self.equity_curve:
            return []
        
        points = []
        for timestamp, equity in self.equity_curve[strategy_id]:
            if window_start <= timestamp <= window_end:
                points.append((timestamp, equity))
        
        return points


# Global scorer instance
_scorer: Optional[ShadowScorer] = None
_scorer_lock = threading.Lock()


def get_shadow_scorer() -> ShadowScorer:
    """
    Get global shadow scorer instance (singleton).
    
    Returns:
        ShadowScorer instance
    """
    global _scorer
    
    if _scorer is None:
        with _scorer_lock:
            if _scorer is None:
                _scorer = ShadowScorer()
    
    return _scorer
