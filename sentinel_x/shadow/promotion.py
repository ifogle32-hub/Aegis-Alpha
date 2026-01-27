"""
PHASE 10 — PROMOTION & GOVERNANCE LOGIC

PromotionEvaluator for strategy promotion evaluation.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.definitions import PromotionState
from sentinel_x.shadow.scorer import PerformanceMetrics, get_shadow_scorer


@dataclass
class PromotionCriteria:
    """
    Promotion evaluation criteria.
    """
    min_sample_size: int = 100  # Minimum number of trades
    min_time_days: int = 30  # Minimum time in shadow (days)
    min_sharpe: float = 1.0  # Minimum Sharpe ratio
    max_drawdown: float = 0.2  # Maximum drawdown (20%)
    min_win_rate: float = 0.5  # Minimum win rate (50%)
    min_total_return: float = 0.05  # Minimum total return (5%)
    require_stability: bool = True  # Require stability across regimes
    no_single_period_dominance: bool = True  # No single-period dominance


@dataclass
class PromotionEvaluation:
    """
    Promotion evaluation result.
    """
    strategy_id: str
    state: PromotionState
    eligible: bool
    criteria_met: Dict[str, bool]
    metrics: Optional[PerformanceMetrics] = None
    evaluation_timestamp: datetime = None
    reason: Optional[str] = None
    
    def __post_init__(self):
        """Set default timestamp."""
        if self.evaluation_timestamp is None:
            self.evaluation_timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "strategy_id": self.strategy_id,
            "state": self.state.value,
            "eligible": self.eligible,
            "criteria_met": self.criteria_met,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "evaluation_timestamp": self.evaluation_timestamp.isoformat() + "Z",
            "reason": self.reason,
        }


class PromotionEvaluator:
    """
    Strategy promotion evaluator.
    
    Features:
    - Minimum sample size check
    - Minimum time in shadow check
    - Risk threshold checks
    - Stability across regimes
    - No single-period dominance
    - Manual promotion only (no automatic live promotion)
    """
    
    def __init__(
        self,
        criteria: Optional[PromotionCriteria] = None,
    ):
        """
        Initialize promotion evaluator.
        
        Args:
            criteria: Optional promotion criteria
        """
        self.criteria = criteria or PromotionCriteria()
        self.evaluations: Dict[str, List[PromotionEvaluation]] = {}  # strategy_id -> evaluations
        self.current_states: Dict[str, PromotionState] = {}  # strategy_id -> current state
        self._lock = threading.RLock()
        
        logger.info("PromotionEvaluator initialized")
    
    def evaluate(
        self,
        strategy_id: str,
        metrics: Optional[PerformanceMetrics] = None,
        registration_time: Optional[datetime] = None,
    ) -> PromotionEvaluation:
        """
        Evaluate strategy for promotion eligibility.
        
        Args:
            strategy_id: Strategy identifier
            metrics: Optional performance metrics (will fetch if not provided)
            registration_time: Optional strategy registration time
            
        Returns:
            PromotionEvaluation instance
        """
        with self._lock:
            # Get metrics if not provided
            if metrics is None:
                scorer = get_shadow_scorer()
                metrics = scorer.get_latest_metrics(strategy_id)
            
            if metrics is None:
                # No metrics available
                evaluation = PromotionEvaluation(
                    strategy_id=strategy_id,
                    state=PromotionState.SHADOW_ONLY,
                    eligible=False,
                    criteria_met={},
                    reason="No metrics available",
                )
                self._record_evaluation(evaluation)
                return evaluation
            
            # Check criteria
            criteria_met = {}
            
            # Sample size check
            criteria_met["min_sample_size"] = metrics.total_trades >= self.criteria.min_sample_size
            
            # Time in shadow check
            if registration_time:
                days_in_shadow = (datetime.utcnow() - registration_time).days
                criteria_met["min_time_days"] = days_in_shadow >= self.criteria.min_time_days
            else:
                # Use window duration as proxy
                days_in_shadow = (metrics.window_end - metrics.window_start).days
                criteria_met["min_time_days"] = days_in_shadow >= self.criteria.min_time_days
            
            # Sharpe ratio check
            criteria_met["min_sharpe"] = metrics.sharpe_ratio >= self.criteria.min_sharpe
            
            # Drawdown check
            criteria_met["max_drawdown"] = metrics.max_drawdown <= self.criteria.max_drawdown
            
            # Win rate check
            criteria_met["min_win_rate"] = metrics.win_rate >= self.criteria.min_win_rate
            
            # Total return check
            criteria_met["min_total_return"] = metrics.total_return >= self.criteria.min_total_return
            
            # Stability check (if required)
            if self.criteria.require_stability:
                criteria_met["stability"] = self._check_stability(strategy_id)
            else:
                criteria_met["stability"] = True
            
            # Single-period dominance check
            if self.criteria.no_single_period_dominance:
                criteria_met["no_single_period_dominance"] = self._check_no_single_period_dominance(strategy_id)
            else:
                criteria_met["no_single_period_dominance"] = True
            
            # Determine eligibility
            all_met = all(criteria_met.values())
            
            # Determine state
            if all_met:
                state = PromotionState.CANDIDATE
            else:
                state = PromotionState.SHADOW_ONLY
            
            # Get current state (don't downgrade from APPROVED or LIVE_LOCKED)
            current_state = self.current_states.get(strategy_id, PromotionState.SHADOW_ONLY)
            if current_state in (PromotionState.APPROVED, PromotionState.LIVE_LOCKED):
                state = current_state
            
            evaluation = PromotionEvaluation(
                strategy_id=strategy_id,
                state=state,
                eligible=all_met,
                criteria_met=criteria_met,
                metrics=metrics,
                reason=self._generate_reason(criteria_met, all_met),
            )
            
            self._record_evaluation(evaluation)
            self.current_states[strategy_id] = state
            
            logger.info(
                f"Promotion evaluation: {strategy_id} | "
                f"state={state.value} | eligible={all_met} | "
                f"criteria_met={sum(criteria_met.values())}/{len(criteria_met)}"
            )
            
            return evaluation
    
    def _check_stability(self, strategy_id: str) -> bool:
        """
        Check stability across regimes.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            True if stable across regimes
        """
        # Get metrics history
        scorer = get_shadow_scorer()
        metrics_history = scorer.get_metrics_history(strategy_id, limit=10)
        
        if len(metrics_history) < 3:
            return False
        
        # Check if performance is consistent across windows
        returns = [m.total_return for m in metrics_history]
        if len(returns) < 2:
            return False
        
        # Check for consistency (low variance in returns)
        import numpy as np
        return_std = np.std(returns)
        return_mean = np.mean(returns)
        
        # Stable if coefficient of variation < 2.0
        if return_mean != 0:
            cv = abs(return_std / return_mean)
            return cv < 2.0
        
        return False
    
    def _check_no_single_period_dominance(self, strategy_id: str) -> bool:
        """
        Check that no single period dominates performance.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            True if no single period dominance
        """
        scorer = get_shadow_scorer()
        metrics_history = scorer.get_metrics_history(strategy_id, limit=10)
        
        if len(metrics_history) < 3:
            return False
        
        returns = [m.total_return for m in metrics_history]
        total_return = sum(returns)
        
        if total_return == 0:
            return True
        
        # Check if any single period accounts for > 50% of total return
        max_single_return = max(abs(r) for r in returns)
        if abs(total_return) > 0:
            dominance_ratio = max_single_return / abs(total_return)
            return dominance_ratio < 0.5
        
        return True
    
    def _generate_reason(
        self,
        criteria_met: Dict[str, bool],
        all_met: bool,
    ) -> str:
        """
        Generate human-readable reason.
        
        Args:
            criteria_met: Criteria met dictionary
            all_met: Whether all criteria met
            
        Returns:
            Reason string
        """
        if all_met:
            return "All promotion criteria met"
        
        failed = [k for k, v in criteria_met.items() if not v]
        return f"Failed criteria: {', '.join(failed)}"
    
    def _record_evaluation(self, evaluation: PromotionEvaluation) -> None:
        """Record evaluation."""
        strategy_id = evaluation.strategy_id
        if strategy_id not in self.evaluations:
            self.evaluations[strategy_id] = []
        self.evaluations[strategy_id].append(evaluation)
        
        # Keep only last 100 evaluations per strategy
        if len(self.evaluations[strategy_id]) > 100:
            self.evaluations[strategy_id] = self.evaluations[strategy_id][-100:]
    
    def get_current_state(self, strategy_id: str) -> PromotionState:
        """
        Get current promotion state for strategy.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            PromotionState
        """
        with self._lock:
            return self.current_states.get(strategy_id, PromotionState.SHADOW_ONLY)
    
    def set_state(
        self,
        strategy_id: str,
        state: PromotionState,
        reason: Optional[str] = None,
    ) -> None:
        """
        Manually set promotion state (for manual promotion).
        
        Args:
            strategy_id: Strategy identifier
            state: New promotion state
            reason: Optional reason for state change
        """
        with self._lock:
            old_state = self.current_states.get(strategy_id, PromotionState.SHADOW_ONLY)
            self.current_states[strategy_id] = state
            
            logger.info(
                f"Promotion state changed: {strategy_id} | "
                f"{old_state.value} -> {state.value} | reason={reason}"
            )
            
            # Log audit event
            try:
                from sentinel_x.shadow.persistence import get_shadow_persistence
                persistence = get_shadow_persistence()
                persistence.log_audit_event(
                    "PROMOTION_STATE_CHANGE",
                    strategy_id,
                    {
                        "old_state": old_state.value,
                        "new_state": state.value,
                        "reason": reason,
                    },
                )
            except Exception as e:
                logger.debug(f"Error logging promotion state change: {e}")


# Global evaluator instance
_evaluator: Optional[PromotionEvaluator] = None
_evaluator_lock = threading.Lock()


def get_promotion_evaluator(**kwargs) -> PromotionEvaluator:
    """
    Get global promotion evaluator instance (singleton).
    
    Args:
        **kwargs: Arguments for PromotionEvaluator
        
    Returns:
        PromotionEvaluator instance
    """
    global _evaluator
    
    if _evaluator is None:
        with _evaluator_lock:
            if _evaluator is None:
                _evaluator = PromotionEvaluator(**kwargs)
    
    return _evaluator
