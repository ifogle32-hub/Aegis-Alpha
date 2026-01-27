"""
Execution Guard (Non-Negotiable)

PHASE 2 — EXECUTION GUARD (NON-NEGOTIABLE)

Centralized execution guard that enforces ALL safety conditions before ANY execution attempt.
This guard MUST be centralized and impossible to bypass.

ABSOLUTE SAFETY RULES:
- Execution MUST be impossible unless engine.state == ARMED
- Execution MUST be blocked if kill-switch != READY
- Execution MUST be blocked if ARMED is expired
- Execution MUST be blocked on restart (default = MONITOR)
- Every execution attempt MUST be audited
"""

import time
from typing import Tuple, Optional
from api.execution.base import ExecutionRequest, ExecutionResult, ExecutionStatus
from api.engine import get_engine_runtime, check_execution_guardrails
from api.security import get_kill_switch
from api.brokers import get_broker_registry
from api.audit import get_audit_logger
from api.risk.engine import get_risk_engine
from api.risk.types import RiskContext
from api.strategies.registry import get_strategy_registry, StrategyMode

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class ExecutionGuard:
    """
    PHASE 2 — EXECUTION GUARD
    
    Centralized guard that checks ALL safety conditions before execution.
    This is the SINGLE POINT OF ENTRY for all execution attempts.
    """
    
    def __init__(self):
        self.engine_runtime = get_engine_runtime()
        self.kill_switch = get_kill_switch()
        self.broker_registry = get_broker_registry()
        self.audit_logger = get_audit_logger()
        self.risk_engine = get_risk_engine()  # PHASE 7: Risk engine integration
        self.strategy_registry = get_strategy_registry()  # PHASE 4: Strategy registry
    
    def check_execution_allowed(self, request: ExecutionRequest) -> Tuple[bool, Optional[str]]:
        """
        PHASE 2 — EXECUTION GUARD CHECK
        
        Check if execution is allowed. This is the SINGLE POINT OF ENTRY.
        
        Returns:
            (allowed: bool, reason: str | None)
            
        Safety Checks (ALL must pass):
        1. engine.state == ARMED
        2. current_time < armed_expires_at
        3. kill_switch.state == READY
        4. broker.trading_enabled == true
        5. Risk engine approval (future - currently always True)
        """
        # PHASE 2: Use centralized guardrails from engine
        allowed, reason = check_execution_guardrails()
        if not allowed:
            return False, reason
        
        # PHASE 2: Check broker trading enabled
        if not self.broker_registry.has_trading_enabled():
            return False, "No broker has trading enabled"
        
        # PHASE 7: Risk engine approval (REQUIRED)
        # Risk engine veto CANNOT be overridden
        # This check is done in guard_execution() to get full context
        
        # All checks passed
        return True, None
    
    def guard_execution(self, request: ExecutionRequest) -> ExecutionResult:
        """
        PHASE 2 — EXECUTION GUARD (GUARDED ENTRY POINT)
        
        Guarded entry point for ALL execution attempts.
        This method MUST be called before ANY broker execution.
        
        If guard fails:
        - HARD REJECT
        - NO broker call
        - Audit the rejection
        
        Args:
            request: Execution request
            
        Returns:
            Execution result (rejected if guard fails)
        """
        # PHASE 2: Check if execution is allowed
        allowed, reason = self.check_execution_allowed(request)
        
        if not allowed:
            # PHASE 2: HARD REJECT - NO broker call
            result = ExecutionResult(
                accepted=False,
                request_id=request.request_id,
                status=ExecutionStatus.REJECTED,
                reason=reason or "Execution guard check failed",
            )
            
            # PHASE 5: Audit the rejection
            self.audit_logger.log_event(
                event_type="execution_rejected",
                actor=request.strategy_id,
                payload={
                    "request_id": request.request_id,
                    "symbol": request.symbol,
                    "side": request.side.value,
                    "qty": request.qty,
                    "order_type": request.order_type.value,
                    "reason": reason or "Execution guard check failed",
                },
                correlation_id=request.request_id
            )
            
            return result
        
        # PHASE 4: Strategy mode check (REQUIRED)
        # Execution is allowed ONLY if strategy_mode == PAPER
        strategy_mode = self.strategy_registry.get_strategy_mode(request.strategy_id)
        
        if strategy_mode != StrategyMode.PAPER:
            # PHASE 4: Strategy not in PAPER mode - reject execution
            mode_str = strategy_mode.value if strategy_mode else "UNKNOWN"
            result = ExecutionResult(
                accepted=False,
                request_id=request.request_id,
                status=ExecutionStatus.REJECTED,
                reason=f"Strategy execution blocked - strategy mode is {mode_str}, must be PAPER",
            )
            
            # PHASE 6: Audit rejection
            self.audit_logger.log_event(
                event_type="execution_rejected_strategy_mode",
                actor=request.strategy_id,
                payload={
                    "request_id": request.request_id,
                    "strategy_id": request.strategy_id,
                    "symbol": request.symbol,
                    "strategy_mode": mode_str,
                    "reason": f"Strategy mode is {mode_str}, must be PAPER",
                },
                correlation_id=request.request_id
            )
            
            return result
        
        # PHASE 7: Risk engine evaluation (REQUIRED)
        # Risk engine has absolute veto power
        # Convert ExecutionRequest to RiskContext to avoid circular imports
        # STEP 2: Risk now evaluates data, not execution objects
        
        # Calculate notional value (qty * price)
        # For limit orders: use limit_price
        # For market orders: notional will be 0 (risk rule will handle rejection)
        if request.order_type.value == "limit" and request.limit_price:
            notional = request.qty * request.limit_price
        else:
            # Market order: risk rule will reject if no price estimation
            notional = 0.0
        
        risk_ctx = RiskContext(
            strategy_id=request.strategy_id,
            symbol=request.symbol,
            notional=notional,
            side=request.side.value,  # Convert enum to string ("buy" or "sell")
            qty=request.qty,
            order_type=request.order_type.value,  # Convert enum to string ("market" or "limit")
            request_id=request.request_id,
            limit_price=request.limit_price,
            confidence=None  # Not in ExecutionRequest currently
        )
        
        risk_decision = self.risk_engine.evaluate(risk_ctx)
        
        if not risk_decision.approved:
            # PHASE 7: Risk engine veto - CANNOT be overridden
            result = ExecutionResult(
                accepted=False,
                request_id=request.request_id,
                status=ExecutionStatus.REJECTED,
                reason=f"Risk engine rejection: {risk_decision.reason}",
            )
            
            # PHASE 5: Audit rejection (already logged by risk engine)
            # Additional guard-level audit
            self.audit_logger.log_event(
                event_type="execution_rejected_by_risk",
                actor=request.strategy_id,
                payload={
                    "request_id": request.request_id,
                    "symbol": request.symbol,
                    "side": request.side.value,
                    "qty": request.qty,
                    "order_type": request.order_type.value,
                    "risk_reason": risk_decision.reason,
                    "violated_rule": risk_decision.violated_rule.value if risk_decision.violated_rule else None,
                },
                correlation_id=request.request_id
            )
            
            return result
        
        # PHASE 2: Guard passed - execution can proceed
        # Note: This method only validates conditions
        # Actual execution happens in ExecutionRouter after guard passes
        
        # PHASE 5: Audit execution attempt
        self.audit_logger.log_event(
            event_type="execution_attempted",
            actor=request.strategy_id,
            payload={
                "request_id": request.request_id,
                "symbol": request.symbol,
                "side": request.side.value,
                "qty": request.qty,
                "order_type": request.order_type.value,
                "risk_approved": True,
            },
            correlation_id=request.request_id
        )
        
        # Guard passed - return success indicator
        # Router will handle actual execution
        return ExecutionResult(
            accepted=True,
            request_id=request.request_id,
            status=ExecutionStatus.PENDING,
            reason="Guard and risk checks passed - proceeding to broker execution",
        )


# Global execution guard instance
_execution_guard: Optional[ExecutionGuard] = None


def get_execution_guard() -> ExecutionGuard:
    """Get global execution guard instance"""
    global _execution_guard
    if _execution_guard is None:
        _execution_guard = ExecutionGuard()
    return _execution_guard
