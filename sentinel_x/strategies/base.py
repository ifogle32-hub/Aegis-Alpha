# sentinel_x/strategies/base.py

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from collections import deque
import time
from sentinel_x.monitoring.logger import logger


class BaseStrategy(ABC):
    """
    Base class for all strategies.
    Strategies return an order dict or None on each tick.
    
    PHASE 1: Strategy metrics canonical state
    - PnL tracking fields added for observability
    - Allocation weight for promotion engine
    - Trade statistics for promotion evaluation
    """

    name: str = "BaseStrategy"

    def __init__(self, name: str = None) -> None:
        # Initialize name (use provided name or derive from class)
        if name:
            self.name = name
        elif not hasattr(self, 'name') or self.name == "BaseStrategy":
            self.name = self.__class__.__name__
        
        self.enabled: bool = True
        self.allocation_weight: float = 1.0
        
        # PHASE 1: PnL tracking fields (canonical state)
        self.pnl_realized: float = 0.0
        self.pnl_unrealized: float = 0.0
        self.trades: int = 0
        self.wins: int = 0
        self.losses: int = 0
        
        # PHASE 1: Last update timestamp for age calculation
        self.last_update_ts: float | None = None
        
        # ============================================================
        # PHASE 1 — MOBILE VISUALIZATION: STRATEGY TIME-SERIES STATE
        # ============================================================
        # REGRESSION LOCK — mobile charts are read-only
        # REGRESSION LOCK — no persistence
        # Memory-only time-series buffer for mobile performance charts
        # Stores (timestamp, pnl_total) tuples, max 1000 points
        # SAFETY: Read-only tracking, no trading logic, no execution paths
        # SAFETY: Memory bounded, non-blocking, backward-compatible
        # ============================================================
        self.pnl_timeseries: deque = deque(maxlen=1000)  # (ts, pnl_total) tuples
        
        # ============================================================
        # PHASE 1 — STRATEGY RISK STATE (CAPITAL ALLOCATION)
        # ============================================================
        # Risk metrics for capital allocation engine (Kelly + Risk Parity)
        # These fields are used by the capital allocator to compute
        # optimal allocation weights across strategies.
        # 
        # SAFETY: Read-only tracking fields only
        # - No broker calls
        # - No position sizing logic changes
        # - No leverage assumptions
        # - Deterministic math only
        # ============================================================
        self.returns: list[float] = []  # Historical returns for volatility/expected return calculation
        self.max_drawdown: float = 0.0  # Maximum drawdown observed (for risk parity allocation)
        self.volatility: float | None = None  # Calculated volatility (standard deviation of returns)
        self.expected_return: float | None = None  # Expected return (mean of returns or Kelly estimate)

    def get_name(self) -> str:
        """Get strategy name."""
        return getattr(self, "name", self.__class__.__name__)

    @abstractmethod
    def on_tick(self, market_data) -> Optional[Dict[str, Any]]:
        """
        Return an order dict or None.
        """
        pass

    def safe_on_tick(self, market_data) -> Optional[Dict[str, Any]]:
        """
        Safe wrapper for on_tick() that never throws.
        Any exception is caught, logged, and returns None.
        
        PHASE 1: Enhanced safety - tracks failures for auto-disable.
        """
        try:
            return self.on_tick(market_data)
        except Exception as e:
            strategy_name = self.get_name()
            logger.exception(
                f"Strategy {strategy_name} failed safely",
                extra={"strategy": strategy_name, "error": str(e)}
            )
            # Track failure for auto-disable (if strategy manager available)
            try:
                from sentinel_x.intelligence.strategy_manager import get_strategy_manager
                strategy_manager = get_strategy_manager()
                if strategy_manager:
                    # Increment failure count (will auto-disable if threshold exceeded)
                    if not hasattr(self, '_failure_count'):
                        self._failure_count = 0
                    self._failure_count += 1
                    
                    # Auto-disable after 5 consecutive failures
                    if self._failure_count >= 5:
                        logger.warning(f"Strategy {strategy_name} failed {self._failure_count} times, auto-disabling")
                        try:
                            from sentinel_x.intelligence.strategy_manager import StrategyStatus
                            strategy_manager.status[strategy_name] = StrategyStatus.DISABLED
                            self.enabled = False
                        except Exception:
                            pass  # Fail silently if disable fails
            except Exception:
                pass  # Fail silently if tracking fails
            return None
    
    def update_pnl_timeseries(self) -> None:
        """
        Update PnL time-series for mobile visualization.
        
        PHASE 1 — MOBILE VISUALIZATION: Strategy Time-Series Update
        REGRESSION LOCK — mobile charts are read-only
        REGRESSION LOCK — no persistence
        
        SAFETY:
        - Read-only tracking only
        - Non-blocking (deque append is O(1))
        - Memory bounded (maxlen=1000)
        - No trading logic
        - No execution paths
        - Safe to call frequently (called when collecting performance snapshots)
        
        Updates timeseries with current timestamp and total PnL.
        Called by strategy_manager when collecting performance data.
        """
        try:
            ts = time.time()
            total_pnl = self.pnl_realized + self.pnl_unrealized
            self.pnl_timeseries.append((ts, total_pnl))
        except Exception as e:
            # SAFETY: Never raise - timeseries update must not affect strategy execution
            logger.debug(f"Error updating PnL timeseries for {self.get_name()}: {e}")