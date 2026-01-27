"""
PHASE 2: Equity Curve & Benchmark Engine

Compute equity curve from realized + unrealized PnL.
Support benchmark comparison (SPY default, configurable).
Track cumulative return, drawdown, max drawdown, relative performance.

Emit events:
{
  type: "equity_update",
  equity,
  benchmark_equity,
  drawdown,
  relative_alpha,
  timestamp
}

Rules:
- Equity updates in real time
- Benchmark never blocks trading
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from collections import deque
from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.event_bus import get_event_bus
from sentinel_x.data.market_data import get_market_data
from sentinel_x.utils import safe_emit


class EquityEngine:
    """
    Equity curve and benchmark comparison engine.
    
    Tracks:
    - Equity curve (realized + unrealized PnL + initial capital)
    - Benchmark equity (SPY or configurable)
    - Drawdown tracking
    - Relative alpha vs benchmark
    """
    
    def __init__(self, initial_capital: float = 100000.0, 
                 benchmark_symbol: str = "SPY",
                 market_data=None):
        """
        Initialize equity engine.
        
        Args:
            initial_capital: Starting capital
            benchmark_symbol: Benchmark symbol (default: SPY)
            market_data: Market data provider (optional)
        """
        self.initial_capital = initial_capital
        self.benchmark_symbol = benchmark_symbol
        self.market_data = market_data
        
        # Equity tracking
        self.equity_history: deque = deque(maxlen=10000)  # Last 10k points
        self.benchmark_history: deque = deque(maxlen=10000)
        self.timestamps: deque = deque(maxlen=10000)
        
        # Current values
        self.current_equity: float = initial_capital
        self.current_benchmark_price: Optional[float] = None
        self.benchmark_start_price: Optional[float] = None
        
        # Drawdown tracking
        self.peak_equity: float = initial_capital
        self.max_drawdown: float = 0.0
        self.current_drawdown: float = 0.0
        
        # Benchmark tracking
        self.benchmark_start_time: Optional[datetime] = None
        
        self.event_bus = get_event_bus()
        
        logger.info(f"EquityEngine initialized: capital=${initial_capital:,.2f}, benchmark={benchmark_symbol}")
    
    def update_equity(self, realized_pnl: float | None = None, unrealized_pnl: float | None = None, 
                     equity: Optional[float] = None) -> None:
        """
        Update equity from PnL (non-blocking).
        
        PHASE 1: SAFE SIGNATURE - realized_pnl and unrealized_pnl are optional.
        Analytics layers infer PnL if needed. Execution never depends on it.
        
        Args:
            realized_pnl: Total realized PnL (optional, defaults to 0.0)
            unrealized_pnl: Total unrealized PnL (optional, defaults to 0.0)
            equity: Optional explicit equity value (if provided, used directly)
        """
        try:
            # PHASE 1: Safe defaults - never require realized_pnl
            realized = realized_pnl if realized_pnl is not None else 0.0
            unrealized = unrealized_pnl if unrealized_pnl is not None else 0.0
            
            if equity is not None:
                self.current_equity = equity
            else:
                self.current_equity = self.initial_capital + realized + unrealized
            
            # Update peak and drawdown
            if self.current_equity > self.peak_equity:
                self.peak_equity = self.current_equity
            
            self.current_drawdown = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
            
            if self.current_drawdown > self.max_drawdown:
                self.max_drawdown = self.current_drawdown
            
            # Record history
            now = datetime.utcnow()
            self.equity_history.append(self.current_equity)
            self.timestamps.append(now)
            
            # Update benchmark (non-blocking, never fails)
            self._update_benchmark_async()
            
            # Emit event (non-blocking)
            self._emit_equity_update()
        
        except Exception as e:
            logger.error(f"Error updating equity: {e}", exc_info=True)
    
    def _update_benchmark_async(self) -> None:
        """
        Update benchmark price asynchronously (never blocks).
        """
        try:
            # Schedule async update (fire-and-forget)
            safe_emit(self._fetch_benchmark_price())
        except Exception as e:
            logger.debug(f"Error scheduling benchmark update: {e}")
    
    async def _fetch_benchmark_price(self) -> None:
        """
        Fetch benchmark price (async, never blocks trading).
        """
        try:
            if not self.market_data:
                # Try to get market data if not provided
                try:
                    from sentinel_x.data.market_data import get_market_data
                    # This might fail if market_data not initialized, that's OK
                    market_data = get_market_data([self.benchmark_symbol])
                    if market_data:
                        self.market_data = market_data
                except Exception:
                    pass
            
            if self.market_data:
                # Fetch latest benchmark price
                price = self.market_data.fetch_latest(self.benchmark_symbol)
                if price and price > 0:
                    self.current_benchmark_price = price
                    
                    # Initialize benchmark start price if first fetch
                    if self.benchmark_start_price is None:
                        self.benchmark_start_price = price
                        self.benchmark_start_time = datetime.utcnow()
                    
                    # Record benchmark history
                    self.benchmark_history.append(price)
        
        except Exception as e:
            logger.debug(f"Error fetching benchmark price: {e}")
            # Never block - benchmark is optional
    
    def get_equity_curve(self, limit: int = 1000) -> List[Dict]:
        """
        Get equity curve data.
        
        Args:
            limit: Maximum number of points to return
            
        Returns:
            List of dicts with timestamp, equity, benchmark_equity, drawdown
        """
        try:
            result = []
            n = min(len(self.equity_history), limit)
            
            for i in range(len(self.equity_history) - n, len(self.equity_history)):
                if i < 0:
                    continue
                
                timestamp = self.timestamps[i] if i < len(self.timestamps) else datetime.utcnow()
                equity = self.equity_history[i]
                
                # Get corresponding benchmark value
                benchmark_equity = None
                if i < len(self.benchmark_history) and self.benchmark_start_price:
                    benchmark_price = self.benchmark_history[i]
                    # Calculate benchmark equity (normalized to start at initial_capital)
                    benchmark_equity = self.initial_capital * (benchmark_price / self.benchmark_start_price)
                
                # Calculate drawdown at this point
                peak = max(self.equity_history[max(0, i-1000):i+1]) if i > 0 else equity
                drawdown = (peak - equity) / peak if peak > 0 else 0.0
                
                result.append({
                    'timestamp': timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),
                    'equity': equity,
                    'benchmark_equity': benchmark_equity,
                    'drawdown': drawdown
                })
            
            return result
        
        except Exception as e:
            logger.error(f"Error getting equity curve: {e}", exc_info=True)
            return []
    
    def get_current_metrics(self) -> Dict:
        """
        Get current equity metrics.
        
        Returns:
            Dict with equity, benchmark_equity, drawdown, max_drawdown, relative_alpha, cumulative_return
        """
        try:
            # Calculate cumulative return
            cumulative_return = (self.current_equity - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0.0
            
            # Calculate benchmark return
            benchmark_return = 0.0
            benchmark_equity = None
            if self.current_benchmark_price and self.benchmark_start_price:
                benchmark_return = (self.current_benchmark_price - self.benchmark_start_price) / self.benchmark_start_price
                benchmark_equity = self.initial_capital * (1 + benchmark_return)
            
            # Calculate relative alpha
            relative_alpha = cumulative_return - benchmark_return if benchmark_return else None
            
            return {
                'equity': self.current_equity,
                'benchmark_equity': benchmark_equity,
                'drawdown': self.current_drawdown,
                'max_drawdown': self.max_drawdown,
                'relative_alpha': relative_alpha,
                'cumulative_return': cumulative_return,
                'benchmark_return': benchmark_return if benchmark_return else None,
                'initial_capital': self.initial_capital
            }
        
        except Exception as e:
            logger.error(f"Error getting current metrics: {e}", exc_info=True)
            return {
                'equity': self.current_equity,
                'benchmark_equity': None,
                'drawdown': 0.0,
                'max_drawdown': 0.0,
                'relative_alpha': None,
                'cumulative_return': 0.0,
                'benchmark_return': None,
                'initial_capital': self.initial_capital
            }
    
    def _emit_equity_update(self) -> None:
        """Emit equity update event (non-blocking)."""
        try:
            from sentinel_x.core.state import get_state
            
            metrics = self.get_current_metrics()
            current_state = get_state()
            
            # PHASE 1: Event must include type, timestamp, engine_state, payload
            event = {
                'type': 'equity_update',
                'timestamp': datetime.utcnow().isoformat() + "Z",
                'engine_state': current_state.value,
                'payload': {
                    'equity': metrics['equity'],
                    'benchmark_equity': metrics['benchmark_equity'],
                    'drawdown': metrics['drawdown'],
                    'max_drawdown': metrics['max_drawdown'],
                    'relative_alpha': metrics['relative_alpha'],
                    'cumulative_return': metrics['cumulative_return'],
                    'benchmark_return': metrics['benchmark_return'],
                }
            }
            
            # Non-blocking publish
            safe_emit(self.event_bus.publish(event))
            
            # PHASE 2: Persist equity snapshot
            try:
                from sentinel_x.monitoring.metrics_store import get_metrics_store, EquitySnapshot
                metrics_store = get_metrics_store()
                snapshot = EquitySnapshot(
                    timestamp=datetime.utcnow(),
                    equity=metrics['equity'],
                    benchmark_equity=metrics.get('benchmark_equity'),
                    drawdown=metrics['drawdown'],
                    max_drawdown=metrics['max_drawdown'],
                    cumulative_return=metrics['cumulative_return'],
                    benchmark_return=metrics.get('benchmark_return'),
                    relative_alpha=metrics.get('relative_alpha')
                )
                metrics_store.record_equity_snapshot(snapshot)
            except Exception as e:
                logger.debug(f"Error persisting equity snapshot: {e}")
        
        except Exception as e:
            logger.error(f"Error emitting equity update: {e}", exc_info=True)
    
    def reset(self) -> None:
        """Reset equity tracking (for restart)."""
        self.current_equity = self.initial_capital
        self.peak_equity = self.initial_capital
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        self.equity_history.clear()
        self.benchmark_history.clear()
        self.timestamps.clear()
        self.benchmark_start_price = None
        self.benchmark_start_time = None
        logger.info("EquityEngine reset")


# Global equity engine instance
_equity_engine: Optional[EquityEngine] = None


def get_equity_engine(initial_capital: float = 100000.0,
                     benchmark_symbol: str = "SPY",
                     market_data=None) -> EquityEngine:
    """Get global equity engine instance."""
    global _equity_engine
    if _equity_engine is None:
        _equity_engine = EquityEngine(initial_capital, benchmark_symbol, market_data)
    return _equity_engine
