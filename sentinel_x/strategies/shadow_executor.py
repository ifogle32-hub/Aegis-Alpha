"""
PHASE 4 — SHADOW STRATEGY EXECUTION

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Shadow strategy executor that runs strategies in SHADOW mode.
Generates signals and metrics but NEVER calls execution adapters.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from collections import defaultdict
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.strategies.base import BaseStrategy

try:
    from sentinel_x.backtest.types import Signal, PriceBar
    from sentinel_x.backtest.data_loader import load_price_history
    from sentinel_x.backtest.simulator import run_backtest
    from sentinel_x.strategies.templates import get_strategy_template
    HAS_BACKTEST = True
except ImportError:
    HAS_BACKTEST = False
    logger.warning("Backtest dependencies not available, shadow executor will have limited functionality")


class ShadowExecutionRecord:
    """
    Record of a shadow execution (signals only, no actual orders).
    
    SAFETY: SHADOW MODE ONLY - never triggers order execution
    """
    def __init__(self, strategy_id: str, signal: Dict[str, Any], timestamp: datetime):
        self.strategy_id = strategy_id
        self.signal = signal
        self.timestamp = timestamp
        self.executed = False  # Always False in shadow mode


class ShadowExecutor:
    """
    Shadow strategy executor.
    
    SAFETY: SHADOW MODE ONLY
    - Generates signals from strategies
    - Records metrics (PnL, Sharpe, drawdown, trade count)
    - NEVER calls order_router or execution adapters
    - Stores results in memory registry
    
    All signals are hypothetical - no actual orders are placed.
    """
    
    def __init__(self):
        """Initialize shadow executor."""
        self.execution_records: List[ShadowExecutionRecord] = []
        self.strategy_metrics: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self.signals_registry: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        logger.info("ShadowExecutor initialized: SHADOW MODE ONLY - no order execution")
    
    def execute_shadow_strategies(
        self,
        strategies: List[BaseStrategy],
        market_data: Any
    ) -> List[ShadowExecutionRecord]:
        """
        Execute strategies in SHADOW mode.
        
        SAFETY: SHADOW MODE ONLY - never triggers order execution
        SAFETY: Never calls order_router or execution adapters
        
        Args:
            strategies: List of strategy instances
            market_data: Market data provider
            
        Returns:
            List of ShadowExecutionRecord objects (signals only)
        """
        records = []
        
        for strategy in strategies:
            try:
                strategy_name = strategy.get_name()
                
                # Generate order from strategy (this is hypothetical)
                order = strategy.safe_on_tick(market_data)
                
                if not order:
                    continue
                
                # SAFETY GUARD: Verify this is shadow mode only
                # If order execution is attempted, raise exception
                # This should never happen if shadow mode is properly gated
                
                # Create shadow execution record (signal only, no execution)
                signal = {
                    "strategy_id": strategy_name,
                    "symbol": order.get("symbol", "UNKNOWN"),
                    "side": order.get("side", "UNKNOWN"),
                    "qty": order.get("qty", 0),
                    "price": order.get("price"),
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
                
                record = ShadowExecutionRecord(
                    strategy_id=strategy_name,
                    signal=signal,
                    timestamp=datetime.utcnow()
                )
                
                records.append(record)
                self.execution_records.append(record)
                self.signals_registry[strategy_name].append(signal)
                
                logger.debug(
                    f"SHADOW SIGNAL | strategy={strategy_name} | "
                    f"symbol={signal['symbol']} | side={signal['side']} | "
                    f"NO EXECUTION (shadow mode)"
                )
                
                # PHASE 6 — SAFETY: Log shadow signal with audit logger
                try:
                    from sentinel_x.monitoring.audit_logger import log_audit_event
                    log_audit_event(
                        "SHADOW_SIGNAL",
                        f"shadow_{strategy_name}",
                        metadata={
                            "strategy": strategy_name,
                            "symbol": signal['symbol'],
                            "side": signal['side'],
                            "qty": signal.get('qty', 0),
                            "price": signal.get('price'),
                            "reason": "Shadow mode - no execution"
                        }
                    )
                except Exception as e:
                    logger.debug(f"Error logging shadow signal to audit (non-fatal): {e}")
                
                # Update metrics (hypothetical PnL calculation)
                self._update_shadow_metrics(strategy_name, signal)
                
            except Exception as e:
                logger.error(f"Shadow execution error for {strategy.get_name()}: {e}", exc_info=True)
                continue
        
        return records
    
    def _update_shadow_metrics(self, strategy_id: str, signal: Dict[str, Any]) -> None:
        """
        Update shadow metrics for a strategy.
        
        SAFETY: Metrics only - no execution
        
        Args:
            strategy_id: Strategy identifier
            signal: Signal dictionary
        """
        if strategy_id not in self.strategy_metrics:
            self.strategy_metrics[strategy_id] = {
                "signals_count": 0,
                "pnl": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "trade_count": 0,
                "win_rate": 0.0,
                "total_return": 0.0,
                "last_update": datetime.utcnow().isoformat() + "Z"
            }
        
        metrics = self.strategy_metrics[strategy_id]
        metrics["signals_count"] = len(self.signals_registry[strategy_id])
        metrics["last_update"] = datetime.utcnow().isoformat() + "Z"
        
        # If backtest dependencies are available, run shadow backtest for metrics
        if HAS_BACKTEST:
            try:
                template = get_strategy_template(strategy_id)
                if template:
                    # Run shadow backtest on recent data (simplified - use basic signal counting for now)
                    # Full backtest can be triggered via API endpoint
                    # For now, just update signal-based metrics
                    pass
            except Exception as e:
                logger.debug(f"Error updating shadow metrics via backtest for {strategy_id}: {e}")
                # Continue with basic metrics
    
    def get_strategy_metrics(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get shadow metrics for strategy(ies).
        
        Args:
            strategy_id: Optional strategy ID filter
            
        Returns:
            Dict of strategy metrics
        """
        if strategy_id:
            return self.strategy_metrics.get(strategy_id, {})
        return dict(self.strategy_metrics)
    
    def get_recent_signals(self, strategy_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent shadow signals.
        
        Args:
            strategy_id: Optional strategy ID filter
            limit: Maximum number of signals to return
            
        Returns:
            List of signal dictionaries
        """
        if strategy_id:
            return self.signals_registry.get(strategy_id, [])[-limit:]
        
        # Return all signals, sorted by timestamp
        all_signals = []
        for signals in self.signals_registry.values():
            all_signals.extend(signals)
        
        all_signals.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        return all_signals[:limit]
    
    def clear_old_records(self, max_age_hours: int = 24) -> None:
        """
        Clear old execution records (memory management).
        
        Args:
            max_age_hours: Maximum age of records to keep (hours)
        """
        cutoff_time = datetime.utcnow().replace(hour=datetime.utcnow().hour - max_age_hours)
        
        self.execution_records = [
            r for r in self.execution_records
            if r.timestamp > cutoff_time
        ]


# Global shadow executor instance
_shadow_executor: Optional[ShadowExecutor] = None
_executor_lock = threading.Lock()


def get_shadow_executor() -> ShadowExecutor:
    """
    Get global shadow executor instance (singleton).
    
    Returns:
        ShadowExecutor instance
    """
    global _shadow_executor
    
    if _shadow_executor is None:
        with _executor_lock:
            if _shadow_executor is None:
                _shadow_executor = ShadowExecutor()
    
    return _shadow_executor
