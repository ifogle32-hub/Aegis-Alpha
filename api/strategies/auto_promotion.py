"""
Auto-Promotion Rules Engine

PHASE 12 — AUTO-PROMOTION RULES ENGINE

Automatically promotes and demotes strategies based on performance metrics
and configurable rules. Runs during engine loop evaluation cycle.

SAFETY RULES:
- Auto-promotion NEVER bypasses risk checks
- Auto-promotion blocked if engine.state != ARMED
- Auto-promotion blocked if kill-switch != READY
- Auto-promotion blocked during CLOSED trading window
- All transitions must be audited
- Fail closed: default to SHADOW
"""

import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from threading import Lock

from api.strategies.registry import StrategyMode, get_strategy_registry
from api.strategies.promotion import get_strategy_promotion, PromotionReason
from api.strategies.metrics import StrategyMetrics as StrategyMetricsModel
from api.engine import get_engine_runtime, EngineState
from api.security import get_kill_switch
from api.audit import get_audit_logger
from api.risk.engine import get_risk_engine

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class AutoPromotionRule:
    """
    PHASE 12 — AUTO-PROMOTION RULE
    
    Rules for automatic strategy promotion/demotion.
    """
    min_pnl: float = 0.0  # Minimum PnL for promotion (positive)
    min_sharpe: float = 1.5  # Minimum Sharpe ratio
    max_drawdown: float = 10.0  # Maximum drawdown percentage (positive)
    min_trades: int = 20  # Minimum trade count
    lookback_days: int = 30  # Rolling window days
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API responses"""
        return {
            "min_pnl": self.min_pnl,
            "min_sharpe": self.min_sharpe,
            "max_drawdown": self.max_drawdown,
            "min_trades": self.min_trades,
            "lookback_days": self.lookback_days,
        }
    
    def evaluate(self, metrics: StrategyMetricsModel) -> Tuple[bool, str]:
        """
        Evaluate metrics against promotion rules.
        
        Args:
            metrics: Strategy metrics
        
        Returns:
            (passes: bool, reason: str)
        """
        # Check if metrics are valid
        if not metrics.is_valid():
            return False, "Metrics are stale (older than 24 hours)"
        
        # Check minimum trades
        if metrics.trade_count < self.min_trades:
            return False, f"Insufficient trades: {metrics.trade_count} < {self.min_trades}"
        
        # Check minimum PnL
        if metrics.pnl_rolling_30d <= self.min_pnl:
            return False, f"PnL too low: {metrics.pnl_rolling_30d:.2f} <= {self.min_pnl:.2f}"
        
        # Check minimum Sharpe
        if metrics.sharpe_rolling_30d < self.min_sharpe:
            return False, f"Sharpe too low: {metrics.sharpe_rolling_30d:.2f} < {self.min_sharpe:.2f}"
        
        # Check maximum drawdown (drawdown is positive value, so we check if it exceeds threshold)
        if metrics.max_drawdown_30d > self.max_drawdown:
            return False, f"Drawdown too high: {metrics.max_drawdown_30d:.2f}% > {self.max_drawdown:.2f}%"
        
        # All rules passed
        return True, "All promotion rules passed"


@dataclass
class StrategyAutoPromotionState:
    """
    PHASE 12 — STRATEGY AUTO-PROMOTION STATE
    
    Per-strategy auto-promotion configuration and state.
    """
    strategy_id: str
    auto_promotion_enabled: bool = False
    last_decision: Optional[str] = None  # "promote" | "demote" | "none"
    last_decision_reason: Optional[str] = None
    last_decision_timestamp: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API responses"""
        return {
            "strategy_id": self.strategy_id,
            "auto_promotion_enabled": self.auto_promotion_enabled,
            "last_decision": self.last_decision,
            "last_decision_reason": self.last_decision_reason,
            "last_decision_timestamp": self.last_decision_timestamp,
        }


class AutoPromotionEngine:
    """
    PHASE 12 — AUTO-PROMOTION ENGINE
    
    Evaluates strategies against promotion rules and triggers promotions/demotions.
    Runs during engine loop evaluation cycle (non-blocking, hard timeout enforced).
    """
    
    def __init__(self):
        self.strategy_registry = get_strategy_registry()
        self.promotion_engine = get_strategy_promotion()
        self.engine_runtime = get_engine_runtime()
        self.kill_switch = get_kill_switch()
        self.audit_logger = get_audit_logger()
        self.risk_engine = get_risk_engine()
        
        # PHASE 12: Global promotion rules (default)
        self.promotion_rule = AutoPromotionRule(
            min_pnl=0.0,
            min_sharpe=1.5,
            max_drawdown=10.0,
            min_trades=20,
            lookback_days=30,
        )
        
        # PHASE 12: Per-strategy auto-promotion state
        self._strategy_states: Dict[str, StrategyAutoPromotionState] = {}
        self._metrics_cache: Dict[str, StrategyMetricsModel] = {}
        self._lock = Lock()
    
    def evaluate_cycle(self, timeout_seconds: float = 5.0) -> Dict[str, Any]:
        """
        PHASE 13 — EVALUATION CYCLE
        
        Evaluate all strategies for auto-promotion/demotion.
        Called once per engine loop evaluation cycle.
        
        Args:
            timeout_seconds: Hard timeout for evaluation (default 5.0s)
        
        Returns:
            Evaluation summary dict
        
        SAFETY:
        - Non-blocking
        - Hard timeout enforced
        - Failures logged but ignored
        - Never throws
        """
        start_time = time.time()
        summary = {
            "evaluated": 0,
            "promoted": 0,
            "demoted": 0,
            "errors": 0,
            "duration_ms": 0.0,
        }
        
        try:
            # PHASE 13: Pre-flight checks (must pass before evaluation)
            engine_state = self.engine_runtime.get_state_dict()
            
            # Check engine state (must be ARMED)
            if engine_state.get("state") != EngineState.ARMED.value:
                # Auto-promotion only runs when ARMED
                return summary
            
            # Check kill-switch (must be READY)
            if not self.kill_switch.can_promote():
                # Auto-promotion blocked by kill-switch
                return summary
            
            # Check trading window (must be OPEN)
            if engine_state.get("trading_window") == "CLOSED":
                # Auto-promotion blocked during CLOSED window
                return summary
            
            # PHASE 13: Evaluate strategies (with timeout protection)
            strategies = self.strategy_registry.list()
            
            for strategy in strategies:
                # Check timeout
                if time.time() - start_time > timeout_seconds:
                    logger.warning(f"Auto-promotion evaluation timeout after {timeout_seconds}s")
                    break
                
                strategy_id = strategy.get("id")
                if not strategy_id:
                    continue
                
                try:
                    result = self._evaluate_strategy(strategy_id)
                    summary["evaluated"] += 1
                    if result.get("promoted"):
                        summary["promoted"] += 1
                    if result.get("demoted"):
                        summary["demoted"] += 1
                    if result.get("error"):
                        summary["errors"] += 1
                except Exception as e:
                    # PHASE 13: Strategy evaluation errors must not block cycle
                    logger.error(f"Error evaluating strategy {strategy_id} (non-fatal): {e}", exc_info=True)
                    summary["errors"] += 1
            
        except Exception as e:
            # PHASE 13: Evaluation cycle errors must not crash engine
            logger.error(f"Auto-promotion evaluation cycle error (non-fatal): {e}", exc_info=True)
        
        finally:
            summary["duration_ms"] = (time.time() - start_time) * 1000.0
        
        return summary
    
    def _evaluate_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """
        PHASE 12 — EVALUATE STRATEGY
        
        Evaluate single strategy for promotion/demotion.
        
        Args:
            strategy_id: Strategy identifier
        
        Returns:
            Evaluation result dict
        
        SAFETY:
        - Never throws
        """
        try:
            with self._lock:
                # Get strategy state
                strategy_state = self._strategy_states.get(strategy_id)
                if not strategy_state:
                    strategy_state = StrategyAutoPromotionState(strategy_id=strategy_id)
                    self._strategy_states[strategy_id] = strategy_state
                
                # Skip if auto-promotion disabled
                if not strategy_state.auto_promotion_enabled:
                    return {"promoted": False, "demoted": False, "error": False}
                
                # Get current strategy mode
                current_mode = self.strategy_registry.get_strategy_mode(strategy_id)
                if current_mode is None:
                    return {"promoted": False, "demoted": False, "error": False}
                
                # PHASE 12: Get strategy metrics
                metrics = self._get_strategy_metrics(strategy_id)
                if metrics is None:
                    # Metrics not available - cannot evaluate
                    return {"promoted": False, "demoted": False, "error": False}
                
                # PHASE 12: Evaluate promotion rules
                rules_pass, rules_reason = self.promotion_rule.evaluate(metrics)
                
                # PHASE 12: Handle SHADOW strategies (promotion candidate)
                if current_mode == StrategyMode.SHADOW:
                    if rules_pass:
                        # PHASE 17: Prepare metrics and rule snapshots for audit
                        metrics_snapshot = metrics.to_dict() if metrics else None
                        rule_snapshot = self.promotion_rule.to_dict()
                        
                        # Attempt promotion
                        decision = self.promotion_engine.promote(
                            strategy_id=strategy_id,
                            actor="system",
                            reason=PromotionReason.PERFORMANCE.value,
                            correlation_id=None
                        )
                        
                        # PHASE 17: Audit promotion attempt with snapshots
                        try:
                            self.audit_logger.log_event(
                                event_type="auto_promotion_attempt",
                                actor="system",
                                payload={
                                    "strategy_id": strategy_id,
                                    "approved": decision.approved,
                                    "reason": decision.reason,
                                    "metrics_snapshot": metrics_snapshot,
                                    "rule_snapshot": rule_snapshot,
                                },
                                correlation_id=None
                            )
                        except Exception as e:
                            # Audit failures must not block execution
                            logger.error(f"Audit logging failed (non-fatal): {e}", exc_info=True)
                        
                        if decision.approved:
                            strategy_state.last_decision = "promote"
                            strategy_state.last_decision_reason = f"Metrics passed: {rules_reason}"
                            strategy_state.last_decision_timestamp = time.time()
                            return {"promoted": True, "demoted": False, "error": False}
                        else:
                            strategy_state.last_decision = "none"
                            strategy_state.last_decision_reason = f"Promotion blocked: {decision.reason}"
                            strategy_state.last_decision_timestamp = time.time()
                            return {"promoted": False, "demoted": False, "error": False}
                    else:
                        # Rules failed - no promotion
                        strategy_state.last_decision = "none"
                        strategy_state.last_decision_reason = f"Metrics failed: {rules_reason}"
                        strategy_state.last_decision_timestamp = time.time()
                        return {"promoted": False, "demoted": False, "error": False}
                
                # PHASE 16: Handle PAPER strategies (demotion candidate)
                if current_mode == StrategyMode.PAPER:
                    # PHASE 16: Check for drawdown breach (explicit demotion reason)
                    if metrics.max_drawdown_30d > self.promotion_rule.max_drawdown:
                        # PHASE 17: Prepare metrics and rule snapshots for audit
                        metrics_snapshot = metrics.to_dict() if metrics else None
                        rule_snapshot = self.promotion_rule.to_dict()
                        
                        # Explicit drawdown breach demotion
                        decision = self.promotion_engine.demote(
                            strategy_id=strategy_id,
                            actor="system",
                            reason="drawdown_exceeded",
                            correlation_id=None
                        )
                        
                        # PHASE 17: Audit auto-demotion with snapshots
                        try:
                            self.audit_logger.log_event(
                                event_type="auto_demotion_breach",
                                actor="system",
                                payload={
                                    "strategy_id": strategy_id,
                                    "reason": "drawdown_exceeded",
                                    "approved": decision.approved,
                                    "metrics_snapshot": metrics_snapshot,
                                    "rule_snapshot": rule_snapshot,
                                },
                                correlation_id=None
                            )
                        except Exception as e:
                            # Audit failures must not block execution
                            logger.error(f"Audit logging failed (non-fatal): {e}", exc_info=True)
                        
                        if decision.approved:
                            strategy_state.last_decision = "demote"
                            strategy_state.last_decision_reason = f"Drawdown exceeded: {metrics.max_drawdown_30d:.2f}% > {self.promotion_rule.max_drawdown:.2f}%"
                            strategy_state.last_decision_timestamp = time.time()
                            return {"promoted": False, "demoted": True, "error": False}
                    
                    # PHASE 16: Check risk engine for breach
                    risk_approved, risk_reason = self.risk_engine.approve_strategy_promotion(strategy_id)
                    if not risk_approved:
                        # PHASE 17: Prepare metrics and rule snapshots for audit
                        metrics_snapshot = metrics.to_dict() if metrics else None
                        rule_snapshot = self.promotion_rule.to_dict()
                        
                        # Explicit risk breach demotion
                        decision = self.promotion_engine.demote(
                            strategy_id=strategy_id,
                            actor="system",
                            reason="risk_breach",
                            correlation_id=None
                        )
                        
                        # PHASE 17: Audit risk breach demotion with snapshots
                        try:
                            self.audit_logger.log_event(
                                event_type="auto_demotion_breach",
                                actor="system",
                                payload={
                                    "strategy_id": strategy_id,
                                    "reason": "risk_breach",
                                    "risk_reason": risk_reason,
                                    "approved": decision.approved,
                                    "metrics_snapshot": metrics_snapshot,
                                    "rule_snapshot": rule_snapshot,
                                },
                                correlation_id=None
                            )
                        except Exception as e:
                            # Audit failures must not block execution
                            logger.error(f"Audit logging failed (non-fatal): {e}", exc_info=True)
                        
                        if decision.approved:
                            strategy_state.last_decision = "demote"
                            strategy_state.last_decision_reason = f"Risk breach: {risk_reason}"
                            strategy_state.last_decision_timestamp = time.time()
                            return {"promoted": False, "demoted": True, "error": False}
                    
                    if not rules_pass:
                        # PHASE 17: Prepare metrics and rule snapshots for audit
                        metrics_snapshot = metrics.to_dict() if metrics else None
                        rule_snapshot = self.promotion_rule.to_dict()
                        
                        # Auto-demote on rule failure (performance degradation)
                        decision = self.promotion_engine.demote(
                            strategy_id=strategy_id,
                            actor="system",
                            reason=f"performance_degraded: {rules_reason}",
                            correlation_id=None
                        )
                        
                        # PHASE 17: Audit auto-demotion with snapshots
                        try:
                            self.audit_logger.log_event(
                                event_type="auto_demotion_performance",
                                actor="system",
                                payload={
                                    "strategy_id": strategy_id,
                                    "reason": "performance_degraded",
                                    "rules_reason": rules_reason,
                                    "approved": decision.approved,
                                    "metrics_snapshot": metrics_snapshot,
                                    "rule_snapshot": rule_snapshot,
                                },
                                correlation_id=None
                            )
                        except Exception as e:
                            # Audit failures must not block execution
                            logger.error(f"Audit logging failed (non-fatal): {e}", exc_info=True)
                        
                        if decision.approved:
                            strategy_state.last_decision = "demote"
                            strategy_state.last_decision_reason = f"Metrics failed: {rules_reason}"
                            strategy_state.last_decision_timestamp = time.time()
                            return {"promoted": False, "demoted": True, "error": False}
                        else:
                            strategy_state.last_decision = "none"
                            strategy_state.last_decision_reason = f"Demotion failed: {decision.reason}"
                            strategy_state.last_decision_timestamp = time.time()
                            return {"promoted": False, "demoted": False, "error": False}
                    else:
                        # Rules pass - keep in PAPER
                        strategy_state.last_decision = "none"
                        strategy_state.last_decision_reason = "Metrics passing - no change"
                        strategy_state.last_decision_timestamp = time.time()
                        return {"promoted": False, "demoted": False, "error": False}
                
                # Other modes - no evaluation
                return {"promoted": False, "demoted": False, "error": False}
                
        except Exception as e:
            # PHASE 12: Never throw - return error result
            logger.error(f"Error evaluating strategy {strategy_id} (non-fatal): {e}", exc_info=True)
            return {"promoted": False, "demoted": False, "error": True}
    
    def _get_strategy_metrics(self, strategy_id: str) -> Optional[StrategyMetricsModel]:
        """
        PHASE 11 — GET STRATEGY METRICS
        
        Get strategy metrics from risk engine or cache.
        
        Args:
            strategy_id: Strategy identifier
        
        Returns:
            StrategyMetrics or None if not available
        """
        try:
            # PHASE 11: Try to get metrics from risk engine
            metrics_dict = self.risk_engine.evaluate_strategy_metrics(strategy_id)
            
            if metrics_dict:
                # Convert dict to StrategyMetricsModel
                metrics = StrategyMetricsModel(
                    strategy_id=strategy_id,
                    pnl_rolling_30d=metrics_dict.get("pnl_rolling_30d", 0.0),
                    sharpe_rolling_30d=metrics_dict.get("sharpe_rolling_30d", 0.0),
                    max_drawdown_30d=metrics_dict.get("max_drawdown_30d", 0.0),
                    trade_count=metrics_dict.get("trade_count", 0),
                    last_updated=metrics_dict.get("last_updated", time.time()),
                )
                
                # Cache metrics
                with self._lock:
                    self._metrics_cache[strategy_id] = metrics
                
                return metrics
            
            # Try cache if risk engine doesn't have metrics
            with self._lock:
                cached_metrics = self._metrics_cache.get(strategy_id)
                if cached_metrics and cached_metrics.is_valid():
                    return cached_metrics
            
            # No metrics available
            return None
            
        except Exception as e:
            logger.error(f"Error getting metrics for {strategy_id} (non-fatal): {e}", exc_info=True)
            return None
    
    def set_auto_promotion_enabled(self, strategy_id: str, enabled: bool, actor: str = "api") -> bool:
        """
        PHASE 15 — ENABLE/DISABLE AUTO-PROMOTION
        
        Enable or disable auto-promotion for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            enabled: Enable flag
            actor: Actor performing the change
        
        Returns:
            True if set, False if strategy not found
        """
        try:
            with self._lock:
                strategy_state = self._strategy_states.get(strategy_id)
                if not strategy_state:
                    # Check if strategy exists
                    strategy = self.strategy_registry.get_strategy(strategy_id)
                    if not strategy:
                        return False
                    
                    strategy_state = StrategyAutoPromotionState(strategy_id=strategy_id)
                    self._strategy_states[strategy_id] = strategy_state
                
                strategy_state.auto_promotion_enabled = enabled
                
                # PHASE 17: Audit enable/disable
                try:
                    self.audit_logger.log_event(
                        event_type="auto_promotion_toggle",
                        actor=actor,
                        payload={
                            "strategy_id": strategy_id,
                            "enabled": enabled,
                        },
                        correlation_id=None
                    )
                except Exception as e:
                    # Audit failures must not block execution
                    logger.error(f"Audit logging failed (non-fatal): {e}", exc_info=True)
                
                return True
                
        except Exception as e:
            logger.error(f"Error setting auto-promotion enabled (non-fatal): {e}", exc_info=True)
            return False
    
    def get_strategy_state(self, strategy_id: str) -> Optional[StrategyAutoPromotionState]:
        """Get auto-promotion state for a strategy"""
        with self._lock:
            return self._strategy_states.get(strategy_id)
    
    def get_promotion_rule(self) -> AutoPromotionRule:
        """Get global promotion rule"""
        return self.promotion_rule
    
    def is_eligible_for_promotion(self, strategy_id: str) -> bool:
        """
        PHASE 14 — CHECK PROMOTION ELIGIBILITY
        
        Check if strategy is eligible for promotion based on metrics.
        
        Args:
            strategy_id: Strategy identifier
        
        Returns:
            True if eligible, False otherwise
        """
        try:
            # Get metrics
            metrics = self._get_strategy_metrics(strategy_id)
            if metrics is None:
                return False
            
            # Check rules
            rules_pass, _ = self.promotion_rule.evaluate(metrics)
            return rules_pass
            
        except Exception as e:
            logger.error(f"Error checking promotion eligibility (non-fatal): {e}", exc_info=True)
            return False


# Global auto-promotion engine instance
_auto_promotion_engine: Optional[AutoPromotionEngine] = None


def get_auto_promotion_engine() -> AutoPromotionEngine:
    """Get global auto-promotion engine instance"""
    global _auto_promotion_engine
    if _auto_promotion_engine is None:
        _auto_promotion_engine = AutoPromotionEngine()
    return _auto_promotion_engine
