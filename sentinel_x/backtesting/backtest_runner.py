"""
PHASE 1-8 — BACKTEST RUNNER

SAFETY: OFFLINE BACKTEST ENGINE
REGRESSION LOCK — DO NOT CONNECT TO LIVE

High-level interface for running backtests and integrating results
with promotion/demotion logic.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field

# SAFETY: OFFLINE BACKTEST ENGINE
# REGRESSION LOCK — DO NOT CONNECT TO LIVE

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

# PHASE 4: Import strategy factory and config (shared code)
try:
    from sentinel_x.intelligence.strategy_factory import get_strategy_factory
    from sentinel_x.intelligence.models import StrategyConfig
except Exception:
    get_strategy_factory = None
    StrategyConfig = None


@dataclass
class BacktestConfig:
    """PHASE 1: Backtest configuration."""
    initial_capital: float = 100000.0
    slippage_pct: float = 0.001  # 0.1%
    fee_pct: float = 0.001  # 0.1%
    seed: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    symbols: List[str] = field(default_factory=list)


@dataclass
class BacktestResult:
    """
    PHASE 7: Backtest result (immutable, read-only).
    
    SAFETY: backtest results are advisory only
    """
    strategy_name: str
    trades_count: int
    realized_pnl: float
    win_rate: float
    expectancy: float
    sharpe: Optional[float] = None
    max_drawdown: float = 0.0
    total_return: float = 0.0
    volatility: Optional[float] = None
    equity_curve: List[float] = field(default_factory=list)
    drawdown_curve: List[float] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'strategy_name': self.strategy_name,
            'trades_count': self.trades_count,
            'realized_pnl': self.realized_pnl,
            'win_rate': self.win_rate,
            'expectancy': self.expectancy,
            'sharpe': self.sharpe,
            'max_drawdown': self.max_drawdown,
            'total_return': self.total_return,
            'volatility': self.volatility,
            'timestamp': self.timestamp.isoformat()
        }


class BacktestRunner:
    """
    PHASE 1-8: High-level backtest runner.
    
    SAFETY: OFFLINE BACKTEST ENGINE
    SAFETY: promotion logic remains training-only
    REGRESSION LOCK — DO NOT CONNECT TO LIVE
    
    Responsibilities:
    - Run backtest on strategy
    - Produce BacktestResult
    - Integrate results with promotion/demotion logic (PHASE 8)
    """
    
    def __init__(self, config: Optional[BacktestConfig] = None):
        """
        Initialize backtest runner.
        
        Args:
            config: Backtest configuration
        """
        self.config = config or BacktestConfig()
    
    def run_backtest(self, 
                    strategy_name: str,
                    strategy_config: Dict[str, Any],
                    historical_data: Dict[str, Any]) -> BacktestResult:
        """
        PHASE 1-7: Run backtest on a strategy.
        
        SAFETY: offline only
        SAFETY: no live execution path
        
        Args:
            strategy_name: Strategy name
            strategy_config: Strategy configuration (from StrategyFactory)
            historical_data: Historical data (symbol -> DataFrame)
        
        Returns:
            BacktestResult
        """
        # PHASE 4: Use StrategyFactory to create strategy (shared code, no forking)
        try:
            if not get_strategy_factory:
                raise ValueError("StrategyFactory not available")
            
            factory = get_strategy_factory()
            strategy = factory.create_strategy(strategy_config)
            
            if not strategy:
                raise ValueError(f"Failed to create strategy {strategy_name}")
            
            # PHASE 4: Assert strategy uses same code path
            if not hasattr(strategy, 'on_tick'):
                raise AssertionError(f"Strategy {strategy_name} missing on_tick() - cannot verify same code path")
            
            logger.info(f"Backtest runner: Using StrategyFactory for {strategy_name} (same code path as live)")
            
        except Exception as e:
            logger.error(f"Error creating strategy via factory: {e}", exc_info=True)
            raise
        
        # PHASE 2-6: Run backtest using existing backtest engine (from research package)
        # Note: In production, this would use the new backtesting package,
        # but for now we'll use the existing EventDrivenBacktester as scaffolding
        try:
            from sentinel_x.research.backtester import EventDrivenBacktester
            
            backtester = EventDrivenBacktester(
                initial_capital=self.config.initial_capital,
                slippage_pct=self.config.slippage_pct,
                fee_pct=self.config.fee_pct
            )
            
            # Get first symbol's data
            symbol = list(historical_data.keys())[0] if historical_data else None
            if not symbol:
                raise ValueError("No historical data provided")
            
            data = historical_data[symbol]
            
            # Run backtest
            results = backtester.backtest(strategy, symbol, data)
            
            # PHASE 7: Convert to BacktestResult
            trades = results.get('trades', [])
            returns = results.get('returns', [])
            equity_curve = results.get('equity_curve', [])
            
            # Calculate metrics
            trades_count = len(trades)
            realized_pnl = results.get('final_capital', self.config.initial_capital) - self.config.initial_capital
            
            # Calculate win rate
            wins = sum(1 for t in trades if hasattr(t, 'pnl') and t.pnl and t.pnl > 0)
            win_rate = wins / trades_count if trades_count > 0 else 0.0
            
            # Calculate expectancy
            if trades_count > 0:
                total_pnl = sum(t.pnl for t in trades if hasattr(t, 'pnl') and t.pnl)
                expectancy = total_pnl / trades_count
            else:
                expectancy = 0.0
            
            # Calculate Sharpe (if sufficient data)
            sharpe = None
            if len(returns) > 1:
                try:
                    import numpy as np
                    returns_array = np.array(returns)
                    if returns_array.std() > 0:
                        sharpe = (returns_array.mean() / returns_array.std()) * (252 ** 0.5)  # Annualized
                except Exception:
                    pass
            
            # Calculate max drawdown
            max_drawdown = 0.0
            if equity_curve:
                peak = equity_curve[0]
                for equity in equity_curve:
                    if equity > peak:
                        peak = equity
                    dd = (peak - equity) / peak if peak > 0 else 0.0
                    if dd > max_drawdown:
                        max_drawdown = dd
            
            # Calculate total return
            total_return = realized_pnl / self.config.initial_capital if self.config.initial_capital > 0 else 0.0
            
            # Calculate volatility
            volatility = None
            if len(returns) > 1:
                try:
                    import numpy as np
                    returns_array = np.array(returns)
                    volatility = returns_array.std() * (252 ** 0.5)  # Annualized
                except Exception:
                    pass
            
            result = BacktestResult(
                strategy_name=strategy_name,
                trades_count=trades_count,
                realized_pnl=realized_pnl,
                win_rate=win_rate,
                expectancy=expectancy,
                sharpe=sharpe,
                max_drawdown=max_drawdown,
                total_return=total_return,
                volatility=volatility,
                equity_curve=list(equity_curve) if equity_curve is not None else [],
                drawdown_curve=[],  # TODO: Calculate drawdown curve
                timestamp=datetime.now()
            )
            
            logger.info(f"Backtest completed for {strategy_name}: "
                       f"trades={trades_count}, pnl=${realized_pnl:,.2f}, "
                       f"win_rate={win_rate:.2%}, sharpe={sharpe:.2f if sharpe else 'N/A'}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error running backtest for {strategy_name}: {e}", exc_info=True)
            raise
    
    def run_and_integrate(self,
                         strategy_name: str,
                         strategy_config: Dict[str, Any],
                         historical_data: Dict[str, Any]) -> BacktestResult:
        """
        PHASE 8: Run backtest and integrate results with promotion/demotion logic.
        
        SAFETY: offline backtesting only
        SAFETY: promotion logic remains training-only
        REGRESSION LOCK — BACKTEST GOVERNANCE BRIDGE
        
        Rules:
        - Backtest results are ADVISORY
        - Live training metrics still required
        - Promotion requires BOTH backtest + live scores >= thresholds
        
        Args:
            strategy_name: Strategy name
            strategy_config: Strategy configuration
            historical_data: Historical data
        
        Returns:
            BacktestResult
        """
        # Run backtest
        result = self.run_backtest(strategy_name, strategy_config, historical_data)
        
        # PHASE 8: Integrate with promotion/demotion logic (advisory only)
        try:
            from sentinel_x.intelligence.strategy_manager import get_strategy_manager
            
            strategy_manager = get_strategy_manager()
            if strategy_manager:
                # Record backtest metrics (advisory only, offline)
                strategy_manager.record_backtest_metrics(strategy_name, result.to_dict())
                
                logger.info(f"Backtest results integrated with promotion logic for {strategy_name} (advisory only)")
        except Exception as e:
            logger.debug(f"Error integrating backtest results (non-fatal): {e}")
        
        return result
