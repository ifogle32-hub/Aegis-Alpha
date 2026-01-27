"""
Risk Engine Core

PHASE 1 — RISK ENGINE CORE

Centralized risk engine that evaluates EVERY execution request.
Risk engine approval is REQUIRED for execution.
Risk engine veto CANNOT be overridden.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum

from api.risk.types import RiskContext
from api.risk.config import RiskConfig, get_risk_config
from api.security import get_kill_switch
from api.brokers import get_broker_registry
from api.audit import get_audit_logger

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class RiskRule(Enum):
    """Risk rule identifiers"""
    KILL_SWITCH = "kill_switch"
    POSITION_SIZE = "position_size"
    NOTIONAL_VALUE = "notional_value"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MAX_OPEN_POSITIONS = "max_open_positions"
    SYMBOL_ALLOWLIST = "symbol_allowlist"
    TRADING_WINDOW = "trading_window"


@dataclass
class RiskDecision:
    """
    PHASE 1 — RISK DECISION
    
    Risk evaluation result.
    """
    approved: bool
    reason: str
    violated_rule: Optional[RiskRule] = None
    timestamp: float = field(default_factory=time.time)
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert decision to dict"""
        return {
            "approved": self.approved,
            "reason": self.reason,
            "violated_rule": self.violated_rule.value if self.violated_rule else None,
            "timestamp": self.timestamp,
            "context": self.context,
        }


class RiskEngine:
    """
    PHASE 1 — RISK ENGINE CORE
    
    Centralized risk engine with absolute veto power.
    Default behavior: Reject everything unless explicitly allowed.
    """
    
    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or get_risk_config()
        self.kill_switch = get_kill_switch()
        self.broker_registry = get_broker_registry()
        self.audit_logger = get_audit_logger()
        
        # PHASE 6: Decision history for explainability (in-memory, bounded)
        self._decision_history: List[Dict[str, Any]] = []
        self._max_history = 1000  # Keep last 1000 decisions
    
    def evaluate(self, ctx: RiskContext) -> RiskDecision:
        """
        PHASE 1 — RISK EVALUATION
        
        Evaluate risk context against all risk rules.
        
        Default behavior: Reject everything unless explicitly allowed.
        
        Args:
            ctx: Risk context (lightweight interface, no execution imports)
            
        Returns:
            Risk decision (approved or rejected)
        """
        # PHASE 1: Fail closed - reject on error
        try:
            # PHASE 4: Kill-switch check (highest priority)
            if not self.kill_switch.can_promote():
                decision = RiskDecision(
                    approved=False,
                    reason=f"Kill-switch is {self.kill_switch.status.value} - all execution blocked",
                    violated_rule=RiskRule.KILL_SWITCH,
                    context={
                        "kill_switch_status": self.kill_switch.status.value,
                        "request_id": ctx.request_id,
                        "symbol": ctx.symbol,
                    }
                )
                self._audit_and_store_decision(ctx, decision)
                return decision
            
            # PHASE 2: Core risk rules (all must pass)
            # Import rules here to avoid circular dependencies
            from api.risk.rules.position_size import check_position_size
            from api.risk.rules.notional import check_notional_value
            from api.risk.rules.pnl import check_daily_loss_limit
            from api.risk.rules.position_count import check_max_open_positions
            from api.risk.rules.allowlist import check_symbol_allowlist
            from api.risk.rules.window import check_trading_window
            
            # PHASE 2: Rule 1 - Position size
            decision = check_position_size(ctx, self.config, self.broker_registry)
            if not decision.approved:
                self._audit_and_store_decision(ctx, decision)
                return decision
            
            # PHASE 2: Rule 2 - Notional value
            decision = check_notional_value(ctx, self.config)
            if not decision.approved:
                self._audit_and_store_decision(ctx, decision)
                return decision
            
            # PHASE 2: Rule 3 - Daily loss limit
            decision = check_daily_loss_limit(ctx, self.config, self.broker_registry)
            if not decision.approved:
                self._audit_and_store_decision(ctx, decision)
                return decision
            
            # PHASE 2: Rule 4 - Max open positions
            decision = check_max_open_positions(ctx, self.config, self.broker_registry)
            if not decision.approved:
                self._audit_and_store_decision(ctx, decision)
                return decision
            
            # PHASE 2: Rule 5 - Symbol allowlist
            decision = check_symbol_allowlist(ctx, self.config)
            if not decision.approved:
                self._audit_and_store_decision(ctx, decision)
                return decision
            
            # PHASE 2: Rule 6 - Trading window
            decision = check_trading_window(ctx, self.config)
            if not decision.approved:
                self._audit_and_store_decision(ctx, decision)
                return decision
            
            # PHASE 1: All rules passed - approve
            decision = RiskDecision(
                approved=True,
                reason="All risk checks passed",
                violated_rule=None,
                context={
                    "request_id": ctx.request_id,
                    "symbol": ctx.symbol,
                    "side": ctx.side,
                    "qty": ctx.qty,
                    "order_type": ctx.order_type,
                }
            )
            self._audit_and_store_decision(ctx, decision)
            return decision
            
        except Exception as e:
            # PHASE 1: Fail closed - reject on error
            error_msg = f"Risk evaluation error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            decision = RiskDecision(
                approved=False,
                reason=error_msg,
                violated_rule=None,
                context={
                    "request_id": ctx.request_id,
                    "error": str(e),
                }
            )
            self._audit_and_store_decision(ctx, decision)
            return decision
    
    def _audit_and_store_decision(
        self,
        ctx: RiskContext,
        decision: RiskDecision
    ) -> None:
        """
        PHASE 6 — AUDIT & STORE DECISION
        
        Audit risk decision and store in history.
        """
        # PHASE 6: Audit decision
        self.audit_logger.log_event(
            event_type="risk_decision",
            actor=ctx.strategy_id,
            payload={
                "request_id": ctx.request_id,
                "approved": decision.approved,
                "reason": decision.reason,
                "violated_rule": decision.violated_rule.value if decision.violated_rule else None,
                "symbol": ctx.symbol,
                "side": ctx.side,
                "qty": ctx.qty,
                "order_type": ctx.order_type,
                "context": decision.context,
            },
            correlation_id=ctx.request_id
        )
        
        # PHASE 6: Store in history (bounded)
        decision_record = {
            "timestamp": decision.timestamp,
            "request_id": ctx.request_id,
            "decision": decision.to_dict(),
            "context": {
                "strategy_id": ctx.strategy_id,
                "symbol": ctx.symbol,
                "notional": ctx.notional,
                "side": ctx.side,
                "qty": ctx.qty,
                "order_type": ctx.order_type,
                "limit_price": ctx.limit_price,
                "confidence": ctx.confidence,
            },
        }
        
        self._decision_history.append(decision_record)
        
        # PHASE 6: Maintain bounded history
        if len(self._decision_history) > self._max_history:
            self._decision_history.pop(0)
    
    def get_decisions(
        self,
        limit: int = 100,
        approved_only: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """
        PHASE 6 — GET DECISION HISTORY
        
        Get risk decision history for explainability.
        
        Args:
            limit: Maximum number of decisions to return
            approved_only: Filter by approval status (None = all)
            
        Returns:
            List of decision records (most recent first)
        """
        decisions = self._decision_history.copy()
        
        # Filter by approval status if requested
        if approved_only is not None:
            decisions = [
                d for d in decisions
                if d["decision"]["approved"] == approved_only
            ]
        
        # Reverse to get most recent first
        decisions.reverse()
        
        # Limit results
        return decisions[:limit]
    
    def approve_strategy_promotion(self, strategy_id: str) -> Tuple[bool, str]:
        """
        PHASE 10 — STRATEGY PROMOTION APPROVAL
        
        Risk engine approval for strategy promotion from SHADOW to PAPER.
        
        Rules:
        - Default behavior: Approve if no active risk violations
        - Kill-switch check (highest priority)
        - Strategy-specific risk checks (future)
        
        Args:
            strategy_id: Strategy identifier
        
        Returns:
            (approved: bool, reason: str)
        
        SAFETY:
        - Never throws - returns failure on error
        - Fail closed (reject on error)
        """
        try:
            # PHASE 10: Kill-switch check (highest priority)
            if not self.kill_switch.can_promote():
                return False, f"Kill-switch does not allow promotion (status: {self.kill_switch.status.value})"
            
            # PHASE 10: Strategy-specific risk checks
            # For now, approve if no active risk violations
            # Future: Add strategy-specific risk scoring
            
            # PHASE 10: Default approval if all checks pass
            return True, "Risk engine approval granted"
            
        except Exception as e:
            # PHASE 10: Fail closed - reject on error
            error_msg = f"Risk approval error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def evaluate_strategy_metrics(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """
        PHASE 11 — STRATEGY METRICS EVALUATION
        
        Evaluate strategy performance metrics for auto-promotion decisions.
        
        Args:
            strategy_id: Strategy identifier
        
        Returns:
            Strategy metrics dict or None if not available
        
        SAFETY:
        - Never throws - returns None on error
        - Read-only operation
        """
        try:
            # PHASE 11: For now, return placeholder metrics
            # Future: Integrate with actual metrics computation from engine loop
            # Metrics should come from engine loop's performance tracking
            
            # TODO: Integrate with actual metrics store from engine loop
            # For now, return None to indicate metrics not available
            return None
            
        except Exception as e:
            # PHASE 11: Never throw - return None on error
            logger.error(f"Error evaluating strategy metrics for {strategy_id}: {e}", exc_info=True)
            return None


# Global risk engine instance
_risk_engine: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    """Get global risk engine instance"""
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine()
    return _risk_engine
