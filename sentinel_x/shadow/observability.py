"""
PHASE 11 — OBSERVABILITY

Expose internal telemetry for shadow training:
- Shadow heartbeat
- Active strategies
- Training rate
- Error counts
- Performance summaries
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import threading
from collections import defaultdict

from sentinel_x.monitoring.logger import logger
# PHASE 3: Remove direct trainer import - use runtime instead
# from sentinel_x.shadow.trainer import get_shadow_trainer
# from sentinel_x.shadow.registry import get_strategy_registry
# from sentinel_x.shadow.scorer import get_shadow_scorer
# from sentinel_x.shadow.promotion import get_promotion_evaluator


@dataclass
class ShadowTelemetry:
    """
    Shadow training telemetry snapshot.
    """
    timestamp: datetime
    trainer_enabled: bool
    training_active: bool
    tick_counter: int
    heartbeat_age_seconds: float
    active_strategies: int
    training_rate_ticks_per_second: float
    error_count: int
    performance_summary: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "trainer_enabled": self.trainer_enabled,
            "training_active": self.training_active,
            "tick_counter": self.tick_counter,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "active_strategies": self.active_strategies,
            "training_rate_ticks_per_second": self.training_rate_ticks_per_second,
            "error_count": self.error_count,
            "performance_summary": self.performance_summary,
        }


class ShadowObservability:
    """
    Shadow training observability manager.
    
    Collects and exposes telemetry data.
    """
    
    def __init__(self):
        """Initialize observability manager."""
        self.error_counts: Dict[str, int] = defaultdict(int)  # error_type -> count
        self.performance_history: List[Dict[str, Any]] = []
        self.last_telemetry: Optional[ShadowTelemetry] = None
        self._lock = threading.RLock()
        
        logger.info("ShadowObservability initialized")
    
    def record_error(self, error_type: str) -> None:
        """
        Record error occurrence.
        
        Args:
            error_type: Error type identifier
        """
        with self._lock:
            self.error_counts[error_type] += 1
    
    def get_telemetry(self) -> ShadowTelemetry:
        """
        Get current telemetry snapshot.
        
        Returns:
            ShadowTelemetry instance
        """
        try:
            # PHASE 3: Use runtime to get trainer instead of direct import
            from sentinel_x.shadow.runtime import get_shadow_runtime
            runtime = get_shadow_runtime()
            trainer = runtime.get_trainer()
            
            if trainer is None:
                # Return default telemetry if trainer not available
                return ShadowTelemetry(
                    timestamp=datetime.utcnow(),
                    trainer_enabled=False,
                    training_active=False,
                    tick_counter=0,
                    heartbeat_age_seconds=0.0,
                    active_strategies=0,
                    training_rate_ticks_per_second=0.0,
                    error_count=0,
                    performance_summary={},
                )
            
            # PHASE 3: Lazy imports inside function
            from sentinel_x.shadow.registry import get_strategy_registry
            from sentinel_x.shadow.scorer import get_shadow_scorer
            from sentinel_x.shadow.promotion import get_promotion_evaluator
            
            registry = get_strategy_registry()
            scorer = get_shadow_scorer()
            promotion_evaluator = get_promotion_evaluator()
            
            status = trainer.get_status()
            
            # Calculate heartbeat age
            heartbeat = datetime.fromisoformat(status["heartbeat"].replace("Z", "+00:00"))
            heartbeat_age = (datetime.utcnow() - heartbeat.replace(tzinfo=None)).total_seconds()
            
            # Calculate training rate
            tick_counter = status["tick_counter"]
            if status.get("last_tick_time"):
                last_tick = datetime.fromisoformat(status["last_tick_time"].replace("Z", "+00:00"))
                time_elapsed = (datetime.utcnow() - last_tick.replace(tzinfo=None)).total_seconds()
                if time_elapsed > 0:
                    training_rate = tick_counter / time_elapsed
                else:
                    training_rate = 0.0
            else:
                training_rate = 0.0
            
            # Get active strategies
            strategies = registry.get_all_strategies()
            active_strategies = len(strategies)
            
            # Get performance summary
            performance_summary = {}
            for strategy_id in strategies.keys():
                metrics = scorer.get_latest_metrics(strategy_id)
                if metrics:
                    promotion_state = promotion_evaluator.get_current_state(strategy_id)
                    performance_summary[strategy_id] = {
                        "total_return": metrics.total_return,
                        "sharpe_ratio": metrics.sharpe_ratio,
                        "max_drawdown": metrics.max_drawdown,
                        "win_rate": metrics.win_rate,
                        "total_trades": metrics.total_trades,
                        "promotion_state": promotion_state.value,
                    }
            
            # Get error count
            with self._lock:
                error_count = sum(self.error_counts.values())
            
            telemetry = ShadowTelemetry(
                timestamp=datetime.utcnow(),
                trainer_enabled=status["enabled"],
                training_active=status["training_active"],
                tick_counter=tick_counter,
                heartbeat_age_seconds=heartbeat_age,
                active_strategies=active_strategies,
                training_rate_ticks_per_second=training_rate,
                error_count=error_count,
                performance_summary=performance_summary,
            )
            
            with self._lock:
                self.last_telemetry = telemetry
                self.performance_history.append(telemetry.to_dict())
                
                # Keep only last 1000 telemetry snapshots
                if len(self.performance_history) > 1000:
                    self.performance_history = self.performance_history[-1000:]
            
            return telemetry
        
        except Exception as e:
            logger.error(f"Error generating telemetry: {e}", exc_info=True)
            # Return minimal telemetry on error
            return ShadowTelemetry(
                timestamp=datetime.utcnow(),
                trainer_enabled=False,
                training_active=False,
                tick_counter=0,
                heartbeat_age_seconds=0.0,
                active_strategies=0,
                training_rate_ticks_per_second=0.0,
                error_count=0,
                performance_summary={},
            )
    
    def get_error_summary(self) -> Dict[str, int]:
        """
        Get error summary.
        
        Returns:
            Dict mapping error type to count
        """
        with self._lock:
            return dict(self.error_counts)
    
    def get_performance_history(
        self,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get performance history.
        
        Args:
            limit: Maximum number of snapshots to return
            
        Returns:
            List of telemetry dictionaries
        """
        with self._lock:
            return self.performance_history[-limit:]


# Global observability instance
_observability: Optional[ShadowObservability] = None
_observability_lock = threading.Lock()


def get_shadow_observability() -> ShadowObservability:
    """
    Get global shadow observability instance (singleton).
    
    Returns:
        ShadowObservability instance
    """
    global _observability
    
    if _observability is None:
        with _observability_lock:
            if _observability is None:
                _observability = ShadowObservability()
    
    return _observability
