"""
PHASE 13 — RORK READINESS (NO DEPENDENCY)

Prepare (do not require) hooks for:
- Shadow status read-only
- Strategy score viewing
- Promotion approvals
- Kill switch

No mobile authority over execution.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import threading

from sentinel_x.monitoring.logger import logger
# PHASE 3: Use runtime instead of direct imports
# from sentinel_x.shadow.registry import get_strategy_registry
# from sentinel_x.shadow.scorer import get_shadow_scorer
# from sentinel_x.shadow.promotion import get_promotion_evaluator, PromotionState
# from sentinel_x.shadow.observability import get_shadow_observability
# from sentinel_x.shadow.safety import get_shadow_safety_guard
# from sentinel_x.shadow.status import get_shadow_status_provider


@dataclass
class ShadowStatus:
    """
    Shadow status for Rork (read-only).
    """
    enabled: bool
    training_active: bool
    active_strategies: int
    heartbeat_age_seconds: float
    telemetry: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "training_active": self.training_active,
            "active_strategies": self.active_strategies,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "telemetry": self.telemetry,
        }


@dataclass
class StrategyScore:
    """
    Strategy score for Rork (read-only).
    """
    strategy_id: str
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    promotion_state: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "strategy_id": self.strategy_id,
            "total_return": self.total_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "total_trades": self.total_trades,
            "promotion_state": self.promotion_state,
        }


class RorkShadowInterface:
    """
    Rork (mobile) interface for shadow training.
    
    READ-ONLY operations only. No execution authority.
    """
    
    def get_shadow_status(self) -> ShadowStatus:
        """
        Get shadow status (read-only).
        
        PHASE 3: Uses runtime instead of direct imports to eliminate circular dependencies.
        
        Returns:
            ShadowStatus instance
        """
        try:
            # PHASE 3: Use runtime to get status
            from sentinel_x.shadow.runtime import get_shadow_runtime
            runtime = get_shadow_runtime()
            
            # Get status via runtime
            runtime_status = runtime.get_status()
            
            # Lazy imports inside function
            from sentinel_x.shadow.registry import get_strategy_registry
            from sentinel_x.shadow.observability import get_shadow_observability
            from sentinel_x.shadow.status import get_shadow_status_provider
            
            registry = get_strategy_registry()
            observability = get_shadow_observability()
            status_provider = get_shadow_status_provider()
            
            # Get status snapshot (read-only, thread-safe)
            snapshot = status_provider.get_snapshot()
            telemetry = observability.get_telemetry()
            
            # Convert heartbeat_age_ms to seconds
            heartbeat_age_seconds = (snapshot.heartbeat_age_ms / 1000.0) if snapshot.heartbeat_age_ms else 0.0
            
            return ShadowStatus(
                enabled=runtime_status.get("enabled", False),
                training_active=runtime_status.get("trainer_active", False),
                active_strategies=len(registry.get_all_strategies()),
                heartbeat_age_seconds=heartbeat_age_seconds,
                telemetry=telemetry.to_dict(),
            )
        
        except Exception as e:
            logger.error(f"Error getting shadow status: {e}", exc_info=True)
            return ShadowStatus(
                enabled=False,
                training_active=False,
                active_strategies=0,
                heartbeat_age_seconds=0.0,
                telemetry={},
            )
    
    def get_strategy_scores(self) -> List[StrategyScore]:
        """
        Get strategy scores (read-only).
        
        PHASE 3: Uses lazy imports inside function to avoid circular dependencies.
        
        Returns:
            List of StrategyScore instances
        """
        try:
            # PHASE 3: Lazy imports inside function
            from sentinel_x.shadow.registry import get_strategy_registry
            from sentinel_x.shadow.scorer import get_shadow_scorer
            from sentinel_x.shadow.promotion import get_promotion_evaluator, PromotionState
            
            registry = get_strategy_registry()
            scorer = get_shadow_scorer()
            promotion_evaluator = get_promotion_evaluator()
            
            scores = []
            strategies = registry.get_all_strategies()
            
            for strategy_id in strategies.keys():
                metrics = scorer.get_latest_metrics(strategy_id)
                if metrics:
                    promotion_state = promotion_evaluator.get_current_state(strategy_id)
                    scores.append(StrategyScore(
                        strategy_id=strategy_id,
                        total_return=metrics.total_return,
                        sharpe_ratio=metrics.sharpe_ratio,
                        max_drawdown=metrics.max_drawdown,
                        win_rate=metrics.win_rate,
                        total_trades=metrics.total_trades,
                        promotion_state=promotion_state.value,
                    ))
            
            return scores
        
        except Exception as e:
            logger.error(f"Error getting strategy scores: {e}", exc_info=True)
            return []
    
    def get_promotion_candidates(self) -> List[Dict[str, Any]]:
        """
        Get promotion candidates (read-only).
        
        PHASE 3: Uses lazy imports inside function.
        
        Returns:
            List of candidate dictionaries
        """
        try:
            # PHASE 3: Lazy imports inside function
            from sentinel_x.shadow.registry import get_strategy_registry
            from sentinel_x.shadow.promotion import get_promotion_evaluator, PromotionState
            
            registry = get_strategy_registry()
            promotion_evaluator = get_promotion_evaluator()
            
            candidates = []
            strategies = registry.get_all_strategies()
            
            for strategy_id in strategies.keys():
                state = promotion_evaluator.get_current_state(strategy_id)
                if state == PromotionState.CANDIDATE:
                    metadata = registry.get_metadata(strategy_id)
                    candidates.append({
                        "strategy_id": strategy_id,
                        "name": metadata.name if metadata else strategy_id,
                        "state": state.value,
                    })
            
            return candidates
        
        except Exception as e:
            logger.error(f"Error getting promotion candidates: {e}", exc_info=True)
            return []
    
    def approve_promotion(
        self,
        strategy_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Approve strategy promotion (manual only).
        
        SAFETY: This is a manual approval gate. No automatic promotion.
        
        PHASE 3: Uses lazy imports inside function.
        
        Args:
            strategy_id: Strategy identifier
            reason: Optional reason for approval
            
        Returns:
            True if approved, False otherwise
        """
        try:
            # PHASE 3: Lazy imports inside function
            from sentinel_x.shadow.promotion import get_promotion_evaluator, PromotionState
            
            promotion_evaluator = get_promotion_evaluator()
            
            # Check current state
            current_state = promotion_evaluator.get_current_state(strategy_id)
            if current_state not in (PromotionState.CANDIDATE, PromotionState.SHADOW_ONLY):
                logger.warning(
                    f"Cannot approve promotion for {strategy_id}: "
                    f"current state is {current_state.value}"
                )
                return False
            
            # Set to APPROVED (manual promotion)
            promotion_evaluator.set_state(
                strategy_id=strategy_id,
                state=PromotionState.APPROVED,
                reason=reason or "Manual approval via Rork",
            )
            
            logger.info(f"Strategy {strategy_id} approved for promotion (manual)")
            return True
        
        except Exception as e:
            logger.error(f"Error approving promotion: {e}", exc_info=True)
            return False
    
    def get_kill_switch_status(self) -> Dict[str, Any]:
        """
        Get kill-switch status (read-only).
        
        PHASE 3: Uses lazy imports inside function.
        
        Returns:
            Kill-switch status dictionary
        """
        try:
            from sentinel_x.core.kill_switch import is_killed
            # PHASE 3: Lazy import inside function
            from sentinel_x.shadow.safety import get_shadow_safety_guard
            
            safety_guard = get_shadow_safety_guard()
            
            return {
                "killed": is_killed(),
                "shadow_enabled": safety_guard.is_enabled(),
            }
        
        except Exception as e:
            logger.error(f"Error getting kill-switch status: {e}", exc_info=True)
            return {
                "killed": False,
                "shadow_enabled": False,
            }


# Global Rork interface instance
_rork_interface: Optional[RorkShadowInterface] = None
# PHASE 7: Lock created lazily to avoid import-time side effects
_rork_interface_lock: Optional[threading.Lock] = None


def get_rork_shadow_interface() -> RorkShadowInterface:
    """
    Get global Rork shadow interface instance (singleton).
    
    PHASE 7: Lock created lazily on first call to avoid import-time side effects.
    
    Returns:
        RorkShadowInterface instance
    """
    global _rork_interface, _rork_interface_lock
    
    if _rork_interface_lock is None:
        _rork_interface_lock = threading.Lock()
    
    if _rork_interface is None:
        with _rork_interface_lock:
            if _rork_interface is None:
                _rork_interface = RorkShadowInterface()
    
    return _rork_interface
