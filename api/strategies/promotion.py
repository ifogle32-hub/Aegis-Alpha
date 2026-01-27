"""
Strategy Promotion Engine

PHASE 1-9 — STRATEGY LIFECYCLE GOVERNANCE SYSTEM

Safely manages strategy lifecycle transitions between SHADOW and PAPER modes,
integrated with engine, risk, audit, and kill-switch systems.

SAFETY RULES:
- No strategy may place orders unless explicitly in PAPER mode
- SHADOW mode produces signals only
- Strategy promotion/demotion must NEVER crash the engine
- Engine loop MUST NOT be restarted
- All state changes must be audit-logged
- Kill-switch overrides all strategy states
"""

import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from threading import Lock

from api.strategies.registry import StrategyMode, get_strategy_registry
from api.engine import get_engine_runtime, EngineState
from api.security import get_kill_switch, KillSwitchStatus
from api.audit import get_audit_logger
from api.risk.engine import get_risk_engine
from api.shadow import get_shadow_registry

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class PromotionReason(str, Enum):
    """Reasons for strategy promotion or demotion"""
    MANUAL = "manual"
    PERFORMANCE = "performance"
    RISK_CLEAR = "risk_clear"
    SYSTEM = "system"


@dataclass
class PromotionDecision:
    """
    PHASE 1 — PROMOTION DECISION
    
    Result of a promotion or demotion attempt.
    """
    strategy_id: str
    from_mode: str
    to_mode: str
    approved: bool
    reason: str
    timestamp: float = field(default_factory=time.time)
    actor: str = "system"
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API responses"""
        return {
            "strategy_id": self.strategy_id,
            "from_mode": self.from_mode,
            "to_mode": self.to_mode,
            "approved": self.approved,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "correlation_id": self.correlation_id,
        }


class StrategyPromotionEngine:
    """
    PHASE 2 — STRATEGY PROMOTION ENGINE
    
    Thread-safe promotion engine that safely manages strategy lifecycle transitions.
    All methods are deterministic and non-throwing.
    """
    
    def __init__(self):
        self.strategy_registry = get_strategy_registry()
        self.engine_runtime = get_engine_runtime()
        self.kill_switch = get_kill_switch()
        self.audit_logger = get_audit_logger()
        self.risk_engine = get_risk_engine()
        self.shadow_registry = get_shadow_registry()
        
        # PHASE 4: In-memory promotion history (bounded)
        self._promotion_history: List[PromotionDecision] = []
        self._max_history = 1000
        self._lock = Lock()
    
    def promote(
        self,
        strategy_id: str,
        actor: str = "api",
        reason: str = PromotionReason.MANUAL.value,
        correlation_id: Optional[str] = None
    ) -> PromotionDecision:
        """
        PHASE 2 — PROMOTE STRATEGY
        
        Promote strategy from SHADOW to PAPER.
        
        Rules:
        - SHADOW → PAPER allowed ONLY if:
          - engine.state == ARMED
          - kill-switch == READY
          - risk engine approves
        - DISABLED blocks all promotion
        
        Args:
            strategy_id: Strategy identifier
            actor: Actor performing the promotion
            reason: Reason for promotion
            correlation_id: Optional correlation ID (e.g., approval request ID)
        
        Returns:
            PromotionDecision (never raises)
        """
        with self._lock:
            try:
                # Get current strategy mode
                current_mode = self.strategy_registry.get_strategy_mode(strategy_id)
                if current_mode is None:
                    # Strategy not found - check if it exists at all
                    strategy = self.strategy_registry.get_strategy(strategy_id)
                    if not strategy:
                        decision = PromotionDecision(
                            strategy_id=strategy_id,
                            from_mode="UNKNOWN",
                            to_mode=StrategyMode.PAPER.value,
                            approved=False,
                            reason=f"Strategy not found: {strategy_id}",
                            actor=actor,
                            correlation_id=correlation_id,
                        )
                        self._audit_and_store(decision)
                        return decision
                    # Strategy exists but has invalid mode - default to SHADOW
                    current_mode = StrategyMode.SHADOW
                
                current_mode_str = current_mode.value
                
                # Check if already in target mode
                if current_mode == StrategyMode.PAPER:
                    decision = PromotionDecision(
                        strategy_id=strategy_id,
                        from_mode=current_mode_str,
                        to_mode=StrategyMode.PAPER.value,
                        approved=True,
                        reason="Strategy already in PAPER mode",
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                    self._audit_and_store(decision)
                    return decision
                
                # DISABLED blocks all promotion
                if current_mode == StrategyMode.DISABLED:
                    decision = PromotionDecision(
                        strategy_id=strategy_id,
                        from_mode=current_mode_str,
                        to_mode=StrategyMode.PAPER.value,
                        approved=False,
                        reason="Cannot promote DISABLED strategy",
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                    self._audit_and_store(decision)
                    return decision
                
                # Only SHADOW → PAPER allowed via promote()
                if current_mode != StrategyMode.SHADOW:
                    decision = PromotionDecision(
                        strategy_id=strategy_id,
                        from_mode=current_mode_str,
                        to_mode=StrategyMode.PAPER.value,
                        approved=False,
                        reason=f"Cannot promote from {current_mode_str} to PAPER (only SHADOW → PAPER allowed)",
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                    self._audit_and_store(decision)
                    return decision
                
                # Check engine state (must be ARMED)
                engine_state = self.engine_runtime.get_state_dict()
                if engine_state.get("state") != EngineState.ARMED.value:
                    decision = PromotionDecision(
                        strategy_id=strategy_id,
                        from_mode=current_mode_str,
                        to_mode=StrategyMode.PAPER.value,
                        approved=False,
                        reason=f"Engine state must be ARMED (current: {engine_state.get('state')})",
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                    self._audit_and_store(decision)
                    return decision
                
                # Check kill-switch (must be READY)
                if not self.kill_switch.can_promote():
                    decision = PromotionDecision(
                        strategy_id=strategy_id,
                        from_mode=current_mode_str,
                        to_mode=StrategyMode.PAPER.value,
                        approved=False,
                        reason=f"Kill-switch does not allow promotion (status: {self.kill_switch.status.value})",
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                    self._audit_and_store(decision)
                    return decision
                
                # PHASE 10: Risk engine approval (REQUIRED)
                # Risk engine has veto power - rejection blocks promotion
                risk_approved, risk_reason = self.risk_engine.approve_strategy_promotion(strategy_id)
                
                if not risk_approved:
                    decision = PromotionDecision(
                        strategy_id=strategy_id,
                        from_mode=current_mode_str,
                        to_mode=StrategyMode.PAPER.value,
                        approved=False,
                        reason=f"Risk engine rejection: {risk_reason}",
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                    
                    # PHASE 10: Audit risk rejection
                    try:
                        self.audit_logger.log_event(
                            event_type="strategy_promotion_rejected",
                            actor=actor,
                            payload={
                                "strategy_id": strategy_id,
                                "from_mode": current_mode_str,
                                "to_mode": StrategyMode.PAPER.value,
                                "reason": f"risk_rejected: {risk_reason}",
                            },
                            correlation_id=correlation_id
                        )
                    except Exception as e:
                        # Audit failures must not block execution
                        logger.error(f"Audit logging failed (non-fatal): {e}", exc_info=True)
                    
                    self._audit_and_store(decision)
                    return decision
                
                # All checks passed - perform promotion
                updated = self.strategy_registry.set_mode(strategy_id, StrategyMode.PAPER)
                
                if updated:
                    decision = PromotionDecision(
                        strategy_id=strategy_id,
                        from_mode=current_mode_str,
                        to_mode=StrategyMode.PAPER.value,
                        approved=True,
                        reason=f"Strategy promoted to PAPER mode ({reason})",
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                else:
                    decision = PromotionDecision(
                        strategy_id=strategy_id,
                        from_mode=current_mode_str,
                        to_mode=StrategyMode.PAPER.value,
                        approved=False,
                        reason="Failed to update strategy mode",
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                
                self._audit_and_store(decision)
                return decision
                
            except Exception as e:
                # PHASE 2: Non-throwing - return failure decision
                logger.error(f"Error promoting strategy {strategy_id}: {e}", exc_info=True)
                decision = PromotionDecision(
                    strategy_id=strategy_id,
                    from_mode="UNKNOWN",
                    to_mode=StrategyMode.PAPER.value,
                    approved=False,
                    reason=f"Promotion error: {str(e)}",
                    actor=actor,
                    correlation_id=correlation_id,
                )
                self._audit_and_store(decision)
                return decision
    
    def demote(
        self,
        strategy_id: str,
        actor: str = "api",
        reason: str = PromotionReason.MANUAL.value,
        correlation_id: Optional[str] = None
    ) -> PromotionDecision:
        """
        PHASE 2 — DEMOTE STRATEGY
        
        Demote strategy from PAPER to SHADOW.
        
        Rules:
        - PAPER → SHADOW allowed ALWAYS (safe demotion)
        - Other transitions handled appropriately
        
        Args:
            strategy_id: Strategy identifier
            actor: Actor performing the demotion
            reason: Reason for demotion
            correlation_id: Optional correlation ID
        
        Returns:
            PromotionDecision (never raises)
        """
        with self._lock:
            try:
                # Get current strategy mode
                current_mode = self.strategy_registry.get_strategy_mode(strategy_id)
                if current_mode is None:
                    # Strategy not found - check if it exists at all
                    strategy = self.strategy_registry.get_strategy(strategy_id)
                    if not strategy:
                        decision = PromotionDecision(
                            strategy_id=strategy_id,
                            from_mode="UNKNOWN",
                            to_mode=StrategyMode.SHADOW.value,
                            approved=False,
                            reason=f"Strategy not found: {strategy_id}",
                            actor=actor,
                            correlation_id=correlation_id,
                        )
                        self._audit_and_store(decision)
                        return decision
                    # Strategy exists but has invalid mode - default to SHADOW
                    current_mode = StrategyMode.SHADOW
                
                current_mode_str = current_mode.value
                
                # Check if already in target mode
                if current_mode == StrategyMode.SHADOW:
                    decision = PromotionDecision(
                        strategy_id=strategy_id,
                        from_mode=current_mode_str,
                        to_mode=StrategyMode.SHADOW.value,
                        approved=True,
                        reason="Strategy already in SHADOW mode",
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                    self._audit_and_store(decision)
                    return decision
                
                # PHASE 2: PAPER → SHADOW always allowed (safe demotion)
                if current_mode == StrategyMode.PAPER:
                    updated = self.strategy_registry.set_mode(strategy_id, StrategyMode.SHADOW)
                    
                    if updated:
                        decision = PromotionDecision(
                            strategy_id=strategy_id,
                            from_mode=current_mode_str,
                            to_mode=StrategyMode.SHADOW.value,
                            approved=True,
                            reason=f"Strategy demoted to SHADOW mode ({reason})",
                            actor=actor,
                            correlation_id=correlation_id,
                        )
                    else:
                        decision = PromotionDecision(
                            strategy_id=strategy_id,
                            from_mode=current_mode_str,
                            to_mode=StrategyMode.SHADOW.value,
                            approved=False,
                            reason="Failed to update strategy mode",
                            actor=actor,
                            correlation_id=correlation_id,
                        )
                    
                    self._audit_and_store(decision)
                    return decision
                
                # DISABLED → SHADOW also allowed (re-enable)
                if current_mode == StrategyMode.DISABLED:
                    updated = self.strategy_registry.set_mode(strategy_id, StrategyMode.SHADOW)
                    
                    if updated:
                        decision = PromotionDecision(
                            strategy_id=strategy_id,
                            from_mode=current_mode_str,
                            to_mode=StrategyMode.SHADOW.value,
                            approved=True,
                            reason=f"Strategy re-enabled to SHADOW mode ({reason})",
                            actor=actor,
                            correlation_id=correlation_id,
                        )
                    else:
                        decision = PromotionDecision(
                            strategy_id=strategy_id,
                            from_mode=current_mode_str,
                            to_mode=StrategyMode.SHADOW.value,
                            approved=False,
                            reason="Failed to update strategy mode",
                            actor=actor,
                            correlation_id=correlation_id,
                        )
                    
                    self._audit_and_store(decision)
                    return decision
                
                # Other transitions not supported
                decision = PromotionDecision(
                    strategy_id=strategy_id,
                    from_mode=current_mode_str,
                    to_mode=StrategyMode.SHADOW.value,
                    approved=False,
                    reason=f"Demotion from {current_mode_str} not supported",
                    actor=actor,
                    correlation_id=correlation_id,
                )
                self._audit_and_store(decision)
                return decision
                
            except Exception as e:
                # PHASE 2: Non-throwing - return failure decision
                logger.error(f"Error demoting strategy {strategy_id}: {e}", exc_info=True)
                decision = PromotionDecision(
                    strategy_id=strategy_id,
                    from_mode="UNKNOWN",
                    to_mode=StrategyMode.SHADOW.value,
                    approved=False,
                    reason=f"Demotion error: {str(e)}",
                    actor=actor,
                    correlation_id=correlation_id,
                )
                self._audit_and_store(decision)
                return decision
    
    def demote_all_to_shadow(
        self,
        actor: str = "system",
        reason: str = PromotionReason.SYSTEM.value,
        correlation_id: Optional[str] = None,
        explicit_reason: Optional[str] = None
    ) -> int:
        """
        PHASE 3 — DEMOTE ALL STRATEGIES
        
        Demote all PAPER strategies to SHADOW.
        Called when ARMED expires or kill-switch triggers.
        
        Args:
            actor: Actor performing the demotion
            reason: Reason for demotion
            correlation_id: Optional correlation ID
        
        Returns:
            Number of strategies demoted (never raises)
        """
        with self._lock:
            try:
                strategies = self.strategy_registry.list()
                demoted_count = 0
                
                for strategy in strategies:
                    strategy_id = strategy.get("id")
                    if not strategy_id:
                        continue
                    
                    current_mode = self.strategy_registry.get_strategy_mode(strategy_id)
                    
                    # Only demote PAPER strategies
                    if current_mode == StrategyMode.PAPER:
                        # PHASE 16: Use explicit reason if provided, otherwise use default
                        demote_reason = explicit_reason if explicit_reason else reason
                        decision = self.demote(
                            strategy_id=strategy_id,
                            actor=actor,
                            reason=demote_reason,
                            correlation_id=correlation_id
                        )
                        if decision.approved:
                            demoted_count += 1
                
                logger.info(f"Demoted {demoted_count} strategies to SHADOW (actor: {actor}, reason: {reason})")
                return demoted_count
                
            except Exception as e:
                # PHASE 3: Non-throwing - log and return 0
                logger.error(f"Error demoting all strategies: {e}", exc_info=True)
                return 0
    
    def _audit_and_store(self, decision: PromotionDecision, metrics_snapshot: Optional[Dict[str, Any]] = None, rule_snapshot: Optional[Dict[str, Any]] = None) -> None:
        """
        PHASE 5, 17 — AUDIT AND STORE DECISION
        
        Audit promotion decision and store in history.
        Audit failures must not block execution.
        
        Args:
            decision: Promotion decision
            metrics_snapshot: Optional metrics snapshot for audit
            rule_snapshot: Optional rule snapshot for audit
        """
        try:
            # PHASE 5: Determine event type
            event_type = "strategy_promotion" if decision.approved and decision.to_mode == StrategyMode.PAPER.value else "strategy_demotion"
            
            # PHASE 17: Audit payload with all required fields
            payload = {
                "strategy_id": decision.strategy_id,
                "actor": decision.actor,
                "from_mode": decision.from_mode,
                "to_mode": decision.to_mode,
                "approved": decision.approved,
                "reason": decision.reason,
                "promotion_reason": decision.reason,
                "timestamp": decision.timestamp,
            }
            
            # PHASE 17: Add metrics snapshot if available
            if metrics_snapshot:
                payload["metrics_snapshot"] = metrics_snapshot
            
            # PHASE 17: Add rule snapshot if available
            if rule_snapshot:
                payload["rule_snapshot"] = rule_snapshot
            
            # PHASE 5: Audit decision
            self.audit_logger.log_event(
                event_type=event_type,
                actor=decision.actor,
                payload=payload,
                correlation_id=decision.correlation_id
            )
        except Exception as e:
            # PHASE 5: Audit failures must not block execution
            logger.error(f"Audit logging failed (non-fatal): {e}", exc_info=True)
        
        try:
            # PHASE 4: Store in history (bounded)
            self._promotion_history.append(decision)
            
            if len(self._promotion_history) > self._max_history:
                self._promotion_history.pop(0)
        except Exception as e:
            # Storage failures must not block execution
            logger.error(f"History storage failed (non-fatal): {e}", exc_info=True)
    
    def get_promotions(
        self,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        PHASE 4 — GET PROMOTION HISTORY
        
        Get recent promotion decisions.
        
        Args:
            limit: Maximum number of decisions to return
        
        Returns:
            List of promotion decisions (most recent first)
        """
        with self._lock:
            # Return most recent decisions
            decisions = self._promotion_history[-limit:]
            decisions.reverse()  # Most recent first
            return [d.to_dict() for d in decisions]


# Global promotion engine instance
_promotion_engine: Optional[StrategyPromotionEngine] = None


def get_strategy_promotion() -> StrategyPromotionEngine:
    """Get global strategy promotion engine instance"""
    global _promotion_engine
    if _promotion_engine is None:
        _promotion_engine = StrategyPromotionEngine()
    return _promotion_engine
