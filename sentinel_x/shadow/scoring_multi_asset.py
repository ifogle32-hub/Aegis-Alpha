"""
PHASE 9 — MULTI-ASSET SCORING & AGGREGATION

Extend shadow scoring to:
- Track per-asset PnL
- Normalize PnL via multipliers
- Aggregate portfolio-level metrics
- Track correlations across assets
- Track regime-specific performance

Metrics must be comparable across asset classes.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import numpy as np
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.scorer import ShadowScorer, PerformanceMetrics
from sentinel_x.marketdata.metadata import get_metadata_loader
from sentinel_x.shadow.assets import get_asset_registry


@dataclass
class AssetMetrics:
    """
    Performance metrics for a single asset.
    """
    symbol: str
    asset_type: str
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    pnl_usd: float
    exposure_usd: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "total_return": self.total_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "total_trades": self.total_trades,
            "pnl_usd": self.pnl_usd,
            "exposure_usd": self.exposure_usd,
        }


@dataclass
class PortfolioMetrics:
    """
    Portfolio-level aggregated metrics.
    """
    total_pnl_usd: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    volatility: float
    correlation_matrix: Dict[Tuple[str, str], float]
    asset_metrics: Dict[str, AssetMetrics]
    regime_performance: Dict[str, Dict[str, float]]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_pnl_usd": self.total_pnl_usd,
            "total_return": self.total_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "volatility": self.volatility,
            "correlation_matrix": {
                f"{k[0]}-{k[1]}": v
                for k, v in self.correlation_matrix.items()
            },
            "asset_metrics": {
                symbol: metrics.to_dict()
                for symbol, metrics in self.asset_metrics.items()
            },
            "regime_performance": self.regime_performance,
        }


class MultiAssetScorer:
    """
    Multi-asset shadow scorer.
    
    Features:
    - Per-asset PnL tracking
    - PnL normalization via multipliers
    - Portfolio-level aggregation
    - Cross-asset correlation tracking
    - Regime-specific performance
    """
    
    def __init__(self):
        """Initialize multi-asset scorer."""
        self.scorer = ShadowScorer()
        self.metadata_loader = get_metadata_loader()
        self.asset_registry = get_asset_registry()
        
        self.asset_pnl: Dict[str, List[float]] = {}  # symbol -> PnL history
        self.asset_equity: Dict[str, List[Tuple[datetime, float]]] = {}  # symbol -> equity curve
        
        self._lock = threading.RLock()
        
        logger.info("MultiAssetScorer initialized")
    
    def record_asset_trade(
        self,
        symbol: str,
        strategy_id: str,
        side: str,
        quantity: float,
        fill_price: float,
        timestamp: datetime,
        pnl: Optional[float] = None,
    ) -> None:
        """
        Record trade for specific asset.
        
        Args:
            symbol: Trading symbol
            strategy_id: Strategy identifier
            side: Trade side
            quantity: Trade quantity
            fill_price: Fill price
            timestamp: Trade timestamp
            pnl: Optional PnL
        """
        # Get contract metadata
        contract = self.metadata_loader.get_contract(symbol)
        if contract:
            # Normalize PnL via multiplier
            if pnl is not None:
                normalized_pnl = pnl * contract.multiplier
            else:
                normalized_pnl = None
        else:
            normalized_pnl = pnl
        
        # Record in base scorer
        self.scorer.record_trade(
            strategy_id=f"{strategy_id}_{symbol}",
            symbol=symbol,
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            timestamp=timestamp,
            pnl=normalized_pnl,
        )
        
        # Track per-asset PnL
        with self._lock:
            if symbol not in self.asset_pnl:
                self.asset_pnl[symbol] = []
            
            if normalized_pnl is not None:
                self.asset_pnl[symbol].append(normalized_pnl)
    
    def record_asset_equity(
        self,
        symbol: str,
        timestamp: datetime,
        equity: float,
    ) -> None:
        """
        Record equity snapshot for asset.
        
        Args:
            symbol: Trading symbol
            timestamp: Snapshot timestamp
            equity: Portfolio equity
        """
        with self._lock:
            if symbol not in self.asset_equity:
                self.asset_equity[symbol] = []
            
            self.asset_equity[symbol].append((timestamp, equity))
            
            # Keep only last 10000 points
            if len(self.asset_equity[symbol]) > 10000:
                self.asset_equity[symbol] = self.asset_equity[symbol][-10000:]
    
    def compute_asset_metrics(
        self,
        symbol: str,
        window_start: datetime,
        window_end: datetime,
        initial_capital: float = 100000.0,
    ) -> Optional[AssetMetrics]:
        """
        Compute metrics for a single asset.
        
        Args:
            symbol: Trading symbol
            window_start: Window start time
            window_end: Window end time
            initial_capital: Initial capital
            
        Returns:
            AssetMetrics or None
        """
        # Get contract metadata
        contract = self.metadata_loader.get_contract(symbol)
        if not contract:
            return None
        
        # Get equity curve for asset
        with self._lock:
            equity_points = [
                (ts, eq)
                for ts, eq in self.asset_equity.get(symbol, [])
                if window_start <= ts <= window_end
            ]
        
        if not equity_points:
            return None
        
        # Calculate metrics
        initial_equity = equity_points[0][1] if equity_points else initial_capital
        final_equity = equity_points[-1][1] if equity_points else initial_capital
        
        total_return = (final_equity - initial_equity) / initial_equity if initial_equity > 0 else 0.0
        pnl_usd = final_equity - initial_equity
        
        # Calculate returns for Sharpe and drawdown
        returns = []
        for i in range(1, len(equity_points)):
            prev_equity = equity_points[i-1][1]
            curr_equity = equity_points[i][1]
            if prev_equity > 0:
                ret = (curr_equity - prev_equity) / prev_equity
                returns.append(ret)
        
        sharpe_ratio = 0.0
        max_drawdown = 0.0
        
        if returns:
            returns_array = np.array(returns)
            volatility = np.std(returns_array) * np.sqrt(252)  # Annualized
            
            if volatility > 0:
                annualized_return = total_return * (365.0 / (window_end - window_start).days) if (window_end - window_start).days > 0 else 0.0
                sharpe_ratio = annualized_return / volatility
            
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
            max_drawdown = max_dd
        
        # Get trade statistics
        with self._lock:
            trades = self.asset_pnl.get(symbol, [])
            total_trades = len(trades)
            winning_trades = len([t for t in trades if t > 0])
            win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        # Calculate exposure (simplified)
        exposure_usd = abs(final_equity - initial_equity)  # Simplified
        
        return AssetMetrics(
            symbol=symbol,
            asset_type=contract.asset_type.value,
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            total_trades=total_trades,
            pnl_usd=pnl_usd,
            exposure_usd=exposure_usd,
        )
    
    def compute_portfolio_metrics(
        self,
        symbols: List[str],
        window_start: datetime,
        window_end: datetime,
        initial_capital: float = 100000.0,
    ) -> PortfolioMetrics:
        """
        Compute portfolio-level aggregated metrics.
        
        Args:
            symbols: List of symbols
            window_start: Window start time
            window_end: Window end time
            initial_capital: Initial capital
            
        Returns:
            PortfolioMetrics instance
        """
        # Compute per-asset metrics
        asset_metrics = {}
        for symbol in symbols:
            metrics = self.compute_asset_metrics(symbol, window_start, window_end, initial_capital)
            if metrics:
                asset_metrics[symbol] = metrics
        
        # Aggregate portfolio metrics
        total_pnl_usd = sum(m.pnl_usd for m in asset_metrics.values())
        total_return = total_pnl_usd / initial_capital if initial_capital > 0 else 0.0
        
        # Calculate portfolio volatility from asset returns
        portfolio_returns = []
        for symbol in symbols:
            with self._lock:
                equity_points = [
                    (ts, eq)
                    for ts, eq in self.asset_equity.get(symbol, [])
                    if window_start <= ts <= window_end
                ]
            
            if len(equity_points) > 1:
                for i in range(1, len(equity_points)):
                    prev_equity = equity_points[i-1][1]
                    curr_equity = equity_points[i][1]
                    if prev_equity > 0:
                        ret = (curr_equity - prev_equity) / prev_equity
                        portfolio_returns.append(ret)
        
        volatility = 0.0
        sharpe_ratio = 0.0
        max_drawdown = 0.0
        
        if portfolio_returns:
            returns_array = np.array(portfolio_returns)
            volatility = np.std(returns_array) * np.sqrt(252)  # Annualized
            
            if volatility > 0:
                annualized_return = total_return * (365.0 / (window_end - window_start).days) if (window_end - window_start).days > 0 else 0.0
                sharpe_ratio = annualized_return / volatility
        
        # Calculate correlation matrix
        correlation_matrix = {}
        for i, symbol1 in enumerate(symbols):
            for symbol2 in symbols[i+1:]:
                corr = self.asset_registry.get_correlation(symbol1, symbol2)
                correlation_matrix[(symbol1, symbol2)] = corr
        
        # Regime performance (simplified - would use RegimeAnalyzer in production)
        regime_performance = {}
        
        return PortfolioMetrics(
            total_pnl_usd=total_pnl_usd,
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            volatility=volatility,
            correlation_matrix=correlation_matrix,
            asset_metrics=asset_metrics,
            regime_performance=regime_performance,
        )


# Global multi-asset scorer instance
_multi_asset_scorer: Optional[MultiAssetScorer] = None
_multi_asset_scorer_lock = threading.Lock()


def get_multi_asset_scorer() -> MultiAssetScorer:
    """
    Get global multi-asset scorer instance (singleton).
    
    Returns:
        MultiAssetScorer instance
    """
    global _multi_asset_scorer
    
    if _multi_asset_scorer is None:
        with _multi_asset_scorer_lock:
            if _multi_asset_scorer is None:
                _multi_asset_scorer = MultiAssetScorer()
    
    return _multi_asset_scorer
