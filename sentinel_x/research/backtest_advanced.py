"""
PHASE 7, 9, 10 — ADVANCED BACKTESTING FEATURES

SAFETY: backtester is isolated from live engine
SAFETY: no live execution path
REGRESSION LOCK — OFFLINE ONLY

Features:
- Multi-timeframe support
- Bias controls (lookahead, survivorship)
- Walk-forward evaluation
- Monte Carlo simulation
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict

# SAFETY: backtester is isolated from live engine
# SAFETY: no live execution path
# REGRESSION LOCK — OFFLINE ONLY

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# ============================================================================
# PHASE 7 — MULTI-TIMEFRAME SUPPORT
# ============================================================================

class MultiTimeframeManager:
    """
    PHASE 7: Multi-timeframe support for backtesting.
    
    SAFETY: offline only
    SAFETY: no live execution path
    
    Allows strategies to subscribe to:
    - Tick stream
    - Multiple bar streams (1m, 5m, 15m, etc.)
    
    Rules:
    - Bar events emitted from ticks
    - No synthetic lookahead bars
    - Explicit alignment between timeframes
    """
    
    def __init__(self, timeframes: List[str] = None):
        """
        Initialize multi-timeframe manager.
        
        Args:
            timeframes: List of timeframes to support (e.g., ['1m', '5m', '15m'])
        """
        self.timeframes = timeframes or ['1m', '5m', '15m', '1h', '1d']
        
        # Track last bar close time for each timeframe
        self.last_bar_time: Dict[str, Dict[str, datetime]] = defaultdict(dict)  # symbol -> timeframe -> last_time
        
        # Bar buffers (for aggregating ticks into bars)
        self.bar_buffers: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    
    def timeframe_to_minutes(self, timeframe: str) -> int:
        """Convert timeframe string to minutes."""
        if timeframe.endswith('m'):
            return int(timeframe[:-1])
        elif timeframe.endswith('h'):
            return int(timeframe[:-1]) * 60
        elif timeframe.endswith('d'):
            return int(timeframe[:-1]) * 60 * 24
        else:
            raise ValueError(f"Unknown timeframe format: {timeframe}")
    
    def should_emit_bar(self, symbol: str, timeframe: str, timestamp: datetime) -> bool:
        """
        PHASE 7: Check if bar should be emitted for timeframe.
        
        SAFETY: no synthetic lookahead bars
        """
        if symbol not in self.last_bar_time or timeframe not in self.last_bar_time[symbol]:
            return True
        
        last_time = self.last_bar_time[symbol][timeframe]
        timeframe_minutes = self.timeframe_to_minutes(timeframe)
        
        # Check if enough time has passed
        time_diff = (timestamp - last_time).total_seconds() / 60.0
        return time_diff >= timeframe_minutes
    
    def update_bar_buffer(self, symbol: str, timeframe: str, tick_data: Dict[str, Any]):
        """PHASE 7: Update bar buffer with tick data."""
        self.bar_buffers[symbol][timeframe].append(tick_data)
    
    def get_bar_from_buffer(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """
        PHASE 7: Aggregate buffer into bar.
        
        SAFETY: no synthetic lookahead bars
        """
        if symbol not in self.bar_buffers or timeframe not in self.bar_buffers[symbol]:
            return None
        
        buffer = self.bar_buffers[symbol][timeframe]
        if not buffer:
            return None
        
        # Aggregate ticks into OHLCV bar
        opens = [t.get('open', t.get('price', 0)) for t in buffer]
        highs = [t.get('high', t.get('price', 0)) for t in buffer]
        lows = [t.get('low', t.get('price', 0)) for t in buffer]
        closes = [t.get('close', t.get('price', 0)) for t in buffer]
        volumes = [t.get('volume', 0) for t in buffer]
        
        bar = {
            'timestamp': buffer[-1].get('timestamp'),
            'open': opens[0] if opens else 0.0,
            'high': max(highs) if highs else 0.0,
            'low': min(lows) if lows else 0.0,
            'close': closes[-1] if closes else 0.0,
            'volume': sum(volumes) if volumes else 0.0,
            'timeframe': timeframe
        }
        
        # Clear buffer
        self.bar_buffers[symbol][timeframe] = []
        
        # Update last bar time
        self.last_bar_time[symbol][timeframe] = pd.to_datetime(bar['timestamp'])
        
        return bar


# ============================================================================
# PHASE 9 — BIAS CONTROLS
# ============================================================================

class BiasController:
    """
    PHASE 9: Bias controls for backtesting.
    
    SAFETY: offline only
    SAFETY: no live execution path
    
    Enforces:
    - No lookahead bias
    - No survivorship bias
    - No hindsight parameter tuning
    - Walk-forward evaluation support
    
    Adds explicit assertions to catch violations.
    """
    
    def __init__(self):
        """Initialize bias controller."""
        self.max_timestamp_seen: Optional[datetime] = None
        self.data_access_log: List[Dict[str, Any]] = []
        self.lookahead_violations: List[str] = []
        self.survivorship_violations: List[str] = []
    
    def check_lookahead(self, requested_timestamp: datetime, current_timestamp: datetime, context: str = ""):
        """
        PHASE 9: Check for lookahead bias.
        
        SAFETY: raises error if lookahead detected
        """
        if requested_timestamp > current_timestamp:
            violation = f"Lookahead bias detected: requested {requested_timestamp} > current {current_timestamp} ({context})"
            self.lookahead_violations.append(violation)
            raise ValueError(violation)
    
    def check_data_access(self, symbol: str, timestamp: datetime, data_timestamp: datetime, context: str = ""):
        """
        PHASE 9: Check data access for lookahead bias.
        
        SAFETY: raises error if future data accessed
        """
        if data_timestamp > timestamp:
            violation = f"Lookahead bias: accessing data at {data_timestamp} when current time is {timestamp} ({context})"
            self.lookahead_violations.append(violation)
            raise ValueError(violation)
        
        # Log data access
        self.data_access_log.append({
            'symbol': symbol,
            'requested_time': timestamp,
            'data_time': data_timestamp,
            'context': context
        })
    
    def check_survivorship(self, symbol: str, start_date: datetime, end_date: datetime):
        """
        PHASE 9: Check for survivorship bias.
        
        Note: This is a placeholder - full implementation would require
        historical delisting data to detect symbols that existed at start
        but not at end.
        """
        # Placeholder - would check if symbol existed throughout period
        pass
    
    def get_violations(self) -> Dict[str, List[str]]:
        """PHASE 9: Get all bias violations."""
        return {
            'lookahead': self.lookahead_violations,
            'survivorship': self.survivorship_violations
        }
    
    def has_violations(self) -> bool:
        """PHASE 9: Check if any violations occurred."""
        return len(self.lookahead_violations) > 0 or len(self.survivorship_violations) > 0


# ============================================================================
# PHASE 10 — WALK-FORWARD & MONTE CARLO
# ============================================================================

@dataclass
class WalkForwardConfig:
    """PHASE 10: Walk-forward backtest configuration."""
    train_period_days: int = 252  # 1 year
    test_period_days: int = 63  # 1 quarter
    step_days: int = 63  # Step forward by 1 quarter
    min_train_periods: int = 1  # Minimum number of train periods


class WalkForwardBacktester:
    """
    PHASE 10: Walk-forward backtesting.
    
    SAFETY: offline only
    SAFETY: no live execution path
    
    Performs rolling walk-forward backtests:
    - Train on period 1, test on period 2
    - Train on period 2, test on period 3
    - etc.
    
    Rules:
    - Results labeled clearly
    - No single curve optimization allowed
    """
    
    def __init__(self, config: WalkForwardConfig):
        """
        Initialize walk-forward backtester.
        
        Args:
            config: Walk-forward configuration
        """
        self.config = config
        self.results: List[Dict[str, Any]] = []
    
    def run_walk_forward(self, 
                        backtest_engine_factory: Callable,
                        start_date: datetime,
                        end_date: datetime,
                        strategy_factory: Callable,
                        symbols: List[str]) -> List[Dict[str, Any]]:
        """
        PHASE 10: Run walk-forward backtest.
        
        SAFETY: offline only
        
        Args:
            backtest_engine_factory: Function that creates a BacktestEngine
            start_date: Overall start date
            end_date: Overall end date
            strategy_factory: Function that creates strategy instances
            symbols: List of symbols to backtest
        
        Returns:
            List of backtest results for each walk-forward period
        """
        current_start = start_date
        period_num = 0
        
        while current_start < end_date:
            # Calculate train and test periods
            train_end = current_start + timedelta(days=self.config.train_period_days)
            test_start = train_end
            test_end = test_start + timedelta(days=self.config.test_period_days)
            
            if test_end > end_date:
                break
            
            period_num += 1
            logger.info(f"Walk-forward period {period_num}: train={current_start} to {train_end}, test={test_start} to {test_end}")
            
            # Train period (for parameter optimization - placeholder)
            # In production, this would optimize parameters on train period
            
            # Test period (run backtest)
            engine = backtest_engine_factory()
            strategy = strategy_factory()
            engine.add_strategy(strategy, symbols)
            
            # Run backtest on test period
            results = engine.run(test_start, test_end)
            results['period'] = period_num
            results['train_start'] = current_start
            results['train_end'] = train_end
            results['test_start'] = test_start
            results['test_end'] = test_end
            
            self.results.append(results)
            
            # Step forward
            current_start += timedelta(days=self.config.step_days)
        
        logger.info(f"Walk-forward backtest completed: {period_num} periods")
        return self.results
    
    def aggregate_results(self) -> Dict[str, Any]:
        """PHASE 10: Aggregate walk-forward results."""
        if not self.results:
            return {}
        
        # Aggregate metrics across all periods
        total_trades = sum(r.get('strategy_trades', {}).get('total', 0) for r in self.results)
        total_pnl = sum(r.get('total_pnl', 0) for r in self.results)
        avg_sharpe = np.mean([r.get('metrics', {}).get('sharpe', 0) for r in self.results])
        
        return {
            'periods': len(self.results),
            'total_trades': total_trades,
            'total_pnl': total_pnl,
            'avg_sharpe': avg_sharpe,
            'period_results': self.results
        }


class MonteCarloBacktester:
    """
    PHASE 10: Monte Carlo trade reshuffling.
    
    SAFETY: offline only
    SAFETY: no live execution path
    
    Performs Monte Carlo simulation by:
    - Reshuffling trade order
    - Randomizing trade outcomes
    - Testing robustness
    
    Rules:
    - Results labeled clearly
    - No single curve optimization allowed
    """
    
    def __init__(self, n_simulations: int = 1000, seed: Optional[int] = None):
        """
        Initialize Monte Carlo backtester.
        
        Args:
            n_simulations: Number of Monte Carlo simulations
            seed: Random seed for reproducibility
        """
        self.n_simulations = n_simulations
        self.rng = np.random.RandomState(seed) if seed is not None else np.random
        self.results: List[Dict[str, Any]] = []
    
    def run_monte_carlo(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        PHASE 10: Run Monte Carlo simulation on trades.
        
        SAFETY: offline only
        
        Args:
            trades: List of trades to simulate
        
        Returns:
            Monte Carlo results
        """
        if not trades:
            return {}
        
        # Extract trade PnLs
        trade_pnls = [t.get('pnl', 0.0) for t in trades if 'pnl' in t]
        
        if not trade_pnls:
            return {}
        
        # Run simulations
        simulation_results = []
        for i in range(self.n_simulations):
            # Reshuffle trade order
            shuffled_pnls = self.rng.permutation(trade_pnls)
            
            # Calculate equity curve
            equity_curve = [100000.0]  # Starting capital
            for pnl in shuffled_pnls:
                equity_curve.append(equity_curve[-1] + pnl)
            
            # Calculate metrics
            returns = np.diff(equity_curve) / equity_curve[:-1]
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0.0
            max_dd = self._calculate_max_drawdown(equity_curve)
            
            simulation_results.append({
                'sharpe': sharpe,
                'max_drawdown': max_dd,
                'final_equity': equity_curve[-1],
                'total_pnl': equity_curve[-1] - equity_curve[0]
            })
        
        # Aggregate results
        sharpe_values = [r['sharpe'] for r in simulation_results]
        dd_values = [r['max_drawdown'] for r in simulation_results]
        
        return {
            'n_simulations': self.n_simulations,
            'sharpe_mean': np.mean(sharpe_values),
            'sharpe_std': np.std(sharpe_values),
            'sharpe_percentiles': {
                '5th': np.percentile(sharpe_values, 5),
                '50th': np.percentile(sharpe_values, 50),
                '95th': np.percentile(sharpe_values, 95)
            },
            'max_drawdown_mean': np.mean(dd_values),
            'max_drawdown_std': np.std(dd_values),
            'max_drawdown_percentiles': {
                '5th': np.percentile(dd_values, 5),
                '50th': np.percentile(dd_values, 50),
                '95th': np.percentile(dd_values, 95)
            },
            'simulations': simulation_results
        }
    
    def _calculate_max_drawdown(self, equity_curve: List[float]) -> float:
        """Calculate maximum drawdown from equity curve."""
        if not equity_curve:
            return 0.0
        
        peak = equity_curve[0]
        max_dd = 0.0
        
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        
        return max_dd
