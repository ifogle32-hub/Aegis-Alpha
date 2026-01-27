"""
Execution Router

PHASE 4 — EXECUTION ROUTER

Implements execution router that:
- Accepts ExecutionRequest
- Applies execution guard
- Routes to correct broker adapter
- Returns ExecutionResult

ABSOLUTE SAFETY:
- Execution guard MUST pass before broker call
- NO broker call if guard fails
"""

from typing import Optional
from api.execution.base import ExecutionRequest, ExecutionResult, ExecutionAdapter, ExecutionStatus
from api.execution.guard import get_execution_guard, ExecutionGuard
from api.execution.alpaca_paper import AlpacaPaperExecutor
from api.brokers import get_broker_registry, BrokerType

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class ExecutionRouter:
    """
    PHASE 4 — EXECUTION ROUTER
    
    Routes execution requests to appropriate broker adapter.
    Execution guard MUST pass before routing.
    """
    
    def __init__(self):
        self.execution_guard = get_execution_guard()
        self.broker_registry = get_broker_registry()
        self.audit_logger = self.execution_guard.audit_logger
        
        # PHASE 4: Initialize broker adapters
        self._adapters: dict[str, ExecutionAdapter] = {}
        self._initialize_adapters()
    
    def _initialize_adapters(self) -> None:
        """Initialize broker execution adapters"""
        # PHASE 4: Initialize Alpaca PAPER adapter
        try:
            alpaca_adapter = AlpacaPaperExecutor()
            if alpaca_adapter.is_available():
                self._adapters["alpaca_paper"] = alpaca_adapter
                logger.info("Alpaca PAPER execution adapter registered")
            else:
                logger.warning("Alpaca PAPER execution adapter not available")
        except Exception as e:
            logger.error(f"Failed to initialize Alpaca PAPER adapter: {e}", exc_info=True)
    
    def _select_adapter(self, request: ExecutionRequest) -> Optional[ExecutionAdapter]:
        """
        PHASE 4 — SELECT ADAPTER
        
        Select appropriate broker adapter for request.
        
        Args:
            request: Execution request
            
        Returns:
            Execution adapter or None if none available
        """
        # PHASE 4: For now, only Alpaca PAPER is supported
        # Future: Add logic to select adapter based on broker type, symbol, etc.
        
        if "alpaca_paper" in self._adapters:
            adapter = self._adapters["alpaca_paper"]
            if adapter.is_available():
                return adapter
        
        return None
    
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """
        PHASE 4 — EXECUTE ORDER
        
        Execute order request through execution router.
        
        Steps:
        1. Apply execution guard (MUST pass)
        2. Select appropriate adapter
        3. Route to adapter
        4. Return result
        
        Args:
            request: Execution request
            
        Returns:
            Execution result
        """
        # PHASE 4: Step 1 - Apply execution guard (NON-NEGOTIABLE)
        guard_result = self.execution_guard.guard_execution(request)
        
        # PHASE 4: Guard failed - return rejection result
        if guard_result is not None and not guard_result.accepted:
            # Guard already logged the rejection
            return guard_result
        
        # PHASE 4: Guard passed - proceed to execution
        # Select adapter
        adapter = self._select_adapter(request)
        if adapter is None:
            # PHASE 4: No adapter available
            result = ExecutionResult(
                accepted=False,
                request_id=request.request_id,
                status=ExecutionStatus.REJECTED,
                reason="No broker adapter available",
            )
            
            # PHASE 5: Audit rejection
            self.audit_logger.log_event(
                event_type="execution_rejected",
                actor=request.strategy_id,
                payload={
                    "request_id": request.request_id,
                    "symbol": request.symbol,
                    "reason": "No broker adapter available",
                },
                correlation_id=request.request_id
            )
            
            return result
        
        # PHASE 4: Route to adapter
        try:
            result = adapter.execute(request)
            
            # PHASE 5: Audit broker response
            if result.accepted:
                self.audit_logger.log_event(
                    event_type="execution_accepted",
                    actor=request.strategy_id,
                    payload={
                        "request_id": request.request_id,
                        "broker_order_id": result.broker_order_id,
                        "symbol": request.symbol,
                        "side": request.side.value,
                        "qty": request.qty,
                        "status": result.status.value,
                    },
                    correlation_id=request.request_id
                )
            else:
                self.audit_logger.log_event(
                    event_type="execution_rejected",
                    actor=request.strategy_id,
                    payload={
                        "request_id": request.request_id,
                        "symbol": request.symbol,
                        "reason": result.reason,
                    },
                    correlation_id=request.request_id
                )
            
            return result
            
        except Exception as e:
            # PHASE 4: Error during execution - do NOT retry
            error_msg = f"Execution error: {str(e)}"
            logger.error(f"Execution failed: {error_msg}", exc_info=True)
            
            result = ExecutionResult(
                accepted=False,
                request_id=request.request_id,
                status=ExecutionStatus.ERROR,
                reason=error_msg,
            )
            
            # PHASE 5: Audit error
            self.audit_logger.log_event(
                event_type="execution_error",
                actor=request.strategy_id,
                payload={
                    "request_id": request.request_id,
                    "symbol": request.symbol,
                    "error": error_msg,
                },
                correlation_id=request.request_id
            )
            
            return result


# Global execution router instance
_execution_router: Optional[ExecutionRouter] = None


def get_execution_router() -> ExecutionRouter:
    """Get global execution router instance"""
    global _execution_router
    if _execution_router is None:
        _execution_router = ExecutionRouter()
    return _execution_router
