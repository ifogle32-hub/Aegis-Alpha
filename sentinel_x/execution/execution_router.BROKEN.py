"""
EXECUTION-CRITICAL FILE - Import Safe

SINGLE authority for all order execution.
Engine MUST call execute(intent).

SAFETY RULES:
• NEVER raises to engine
• ALWAYS returns ExecutionRecord
• EXACTLY ONE try/finally per execution
• NO early returns inside try blocks
• Kill-switch overrides everything
• Broker routing is deterministic
• Paper trading always works
"""

from datetime import datetime
import threading
from typing import Dict, Optional

from sentinel_x.monitoring.logger import logger
from sentinel_x.core.kill_switch import is_killed
from sentinel_x.core.engine_mode import EngineMode, get_engine_mode
from sentinel_x.core.config import Config

from sentinel_x.execution.order_intent import OrderIntent
from sentinel_x.execution.models import ExecutionRecord, ExecutionStatus
from sentinel_x.execution.broker_base import BaseBroker
from sentinel_x.execution.paper_executor import PaperExecutor
from sentinel_x.execution.alpaca_executor import AlpacaExecutor
from sentinel_x.execution.broker_health import get_broker_health_model
from sentinel_x.execution.risk_engine import get_risk_gate


class ExecutionRouter:
    """
    SINGLE authority for all execution.
    Engine MUST call execute(intent).
    """

    def __init__(
        self,
        config: Config,
        paper_executor: Optional[PaperExecutor] = None,
        alpaca_executor: Optional[AlpacaExecutor] = None,
        execution_timeout_seconds: float = 60.0,
    ):
        """
        Initialize execution router.
        
        Args:
            config: Configuration object
            paper_executor: Paper trading executor (optional)
            alpaca_executor: Alpaca executor (optional)
            execution_timeout_seconds: Execution timeout in seconds
        """
        self.config = config
        self.paper_executor = paper_executor
        self.alpaca_executor = alpaca_executor
        self.execution_timeout_seconds = execution_timeout_seconds

        self.broker_health = get_broker_health_model()
        self.risk_gate = get_risk_gate()

        self._lock = threading.Lock()
        self.execution_records: Dict[str, ExecutionRecord] = {}

        logger.info("ExecutionRouter initialized")

    def execute(self, intent: OrderIntent) -> ExecutionRecord:
        """
        ONLY public method.
        NEVER raises.
        ALWAYS returns ExecutionRecord.
        """
        try:
            return self._route_execution(intent)
        except Exception as e:
            logger.critical(
                f"ExecutionRouter crash prevented | intent_id={getattr(intent, 'intent_id', 'unknown')} | error={str(e)}",
                exc_info=True,
            )
            intent_id = getattr(intent, "intent_id", "unknown")
            client_order_id = getattr(intent, "client_order_id", None) or f"sentinel_{intent_id[:8] if len(intent_id) >= 8 else 'unknown'}"
            record = ExecutionRecord.failed(
                intent_id=intent_id,
                client_order_id=client_order_id,
                reason=f"router_exception:{str(e)}",
            )
            self._store(record)
            return record

    def _route_execution(self, intent: OrderIntent) -> ExecutionRecord:
        """
        Internal execution routing.
        
        CANONICAL STRUCTURE:
        - Kill-switch check (before try)
        - Risk gate check (before try)
        - Single try/finally wrapping execution
        - No early returns inside try
        - Single return at end
        """
        # Extract intent fields safely
        intent_id = getattr(intent, "intent_id", "unknown")
        client_order_id = getattr(intent, "client_order_id", None) or f"sentinel_{intent_id[:8] if len(intent_id) >= 8 else 'unknown'}"
        qty = getattr(intent, "qty", 0.0)
        symbol = getattr(intent, "symbol", "UNKNOWN")
        side = getattr(intent, "side", "BUY")

        # Create execution record
        record = ExecutionRecord(
            intent_id=intent_id,
            client_order_id=client_order_id,
            status=ExecutionStatus.PENDING,
            requested_qty=qty,
        )
        self._store(record)

        # Kill-switch supremacy - check first
        if is_killed():
            record.status = ExecutionStatus.KILLED
            record.rejection_reason = "kill_switch"
            record.updated_at = datetime.utcnow()
            self._store(record)
            return record

        # Risk gate check - before try block
        risk_passed = False
        risk_reason = None
        try:
            risk_result = self.risk_gate.check(intent)
            risk_passed = getattr(risk_result, "passed", False)
            risk_reason = getattr(risk_result, "reason", "risk_check_failed")
        except Exception as e:
            logger.error(f"Risk gate check error: {e}", exc_info=True)
            risk_passed = False
            risk_reason = f"risk_gate_error:{str(e)}"

        if not risk_passed:
            record.status = ExecutionStatus.RISK_REJECTED
            record.rejection_reason = risk_reason
            record.updated_at = datetime.utcnow()
            self._store(record)
            return record

        # Kill-switch re-check before execution
        if is_killed():
            record.status = ExecutionStatus.KILLED
            record.rejection_reason = "kill_switch_mid_execution"
            record.updated_at = datetime.utcnow()
            self._store(record)
            return record

        # EXACTLY ONE try/finally per execution
        executor: Optional[BaseBroker] = None
        broker_result: Optional[Dict] = None
        execution_error: Optional[str] = None

        try:
            # Select executor (deterministic, with fallback)
            executor = self._select_executor(intent)
            if executor is None:
                execution_error = "no_executor_available"
            else:
                record.status = ExecutionStatus.SUBMITTED
                record.submitted_at = datetime.utcnow()

                # Kill-switch check before broker call
                if is_killed():
                    record.status = ExecutionStatus.KILLED
                    record.rejection_reason = "kill_switch_before_broker_call"
                    # Don't set execution_error, let finally handle it
                else:
                    # Submit to broker
                    try:
                        broker_result = executor.submit_order(
                            symbol=symbol,
                            side=side,
                            qty=qty,
                            price=getattr(intent, "limit_price", None),
                            strategy=getattr(intent, "strategy", ""),
                        )
                    except Exception as broker_ex:
                        logger.error(f"Broker submission error: {broker_ex}", exc_info=True)
                        execution_error = f"broker_error:{str(broker_ex)}"
                        broker_result = None

                    # Process broker result
                    if broker_result is None:
                        if execution_error is None:
                            execution_error = "broker_rejected"
                    else:
                        # Extract order details
                        record.broker_order_id = broker_result.get("order_id")
                        record.filled_qty = broker_result.get("filled_qty", 0.0) or broker_result.get("qty", 0.0)
                        record.avg_fill_price = broker_result.get("price", 0.0) or broker_result.get("fill_price", 0.0)

                        # Determine fill status
                        if record.filled_qty >= record.requested_qty:
                            record.status = ExecutionStatus.FILLED
                        elif record.filled_qty > 0:
                            record.status = ExecutionStatus.PARTIALLY_FILLED
                        else:
                            record.status = ExecutionStatus.SUBMITTED

        except Exception as e:
            logger.error(f"Execution failure: {e}", exc_info=True)
            execution_error = f"execution_error:{str(e)}"

        finally:
            # Update record status if there was an error
            if execution_error is not None:
                if record.status == ExecutionStatus.PENDING or record.status == ExecutionStatus.SUBMITTED:
                    record.status = ExecutionStatus.REJECTED
                    record.rejection_reason = execution_error

            # Always update timestamp and store
            record.updated_at = datetime.utcnow()
            self._store(record)

        # Single return at end - no mutation after return
        return record

    def _select_executor(self, intent: OrderIntent) -> Optional[BaseBroker]:
        """
        Select executor deterministically.
        
        Rules:
        - PAPER mode: prefer paper_executor, fallback to alpaca if paper-api
        - LIVE mode: use alpaca_executor only
        - Always fallback to paper_executor if available (safety)
        - Never raises - returns None if no executor available
        """
        mode = get_engine_mode()

        # PAPER mode: prefer paper executor
        if mode == EngineMode.PAPER:
            if self.paper_executor is not None:
                return self.paper_executor
            # Fallback: check if alpaca is in paper mode
            if self.alpaca_executor is not None:
                try:
                    alpaca_mode = getattr(self.alpaca_executor, "mode", None)
                    if alpaca_mode == "PAPER":
                        return self.alpaca_executor
                except Exception:
                    pass
            # Final fallback: use paper executor if available (safety)
            if self.paper_executor is not None:
                return self.paper_executor

        # LIVE mode: use alpaca executor only
        if mode == EngineMode.LIVE:
            if self.alpaca_executor is not None:
                try:
                    alpaca_mode = getattr(self.alpaca_executor, "mode", None)
                    if alpaca_mode == "LIVE":
                        return self.alpaca_executor
                except Exception:
                    pass

        # RESEARCH/PAUSED mode: no execution, but return paper executor for safety
        # (This should not be reached in normal flow, but ensures paper always works)
        if self.paper_executor is not None:
            logger.warning(f"Mode {mode.value} - using paper executor as fallback")
            return self.paper_executor

        # No executor available
        logger.error("No executor available for execution")
        return None

    def _store(self, record: ExecutionRecord) -> None:
        """Store execution record thread-safely."""
        try:
            with self._lock:
                self.execution_records[record.intent_id] = record
        except Exception as e:
            logger.error(f"Error storing execution record: {e}", exc_info=True)

    def cancel_all_orders(self) -> int:
        """
        Cancel all open orders.
        
        Returns:
            Number of orders cancelled
        """
        count = 0
        try:
            if self.paper_executor is not None:
                try:
                    cancelled = self.paper_executor.cancel_all_orders()
                    count += cancelled or 0
                except Exception as e:
                    logger.error(f"Error cancelling paper orders: {e}", exc_info=True)

            if self.alpaca_executor is not None:
                try:
                    cancelled = self.alpaca_executor.cancel_all_orders()
                    count += cancelled or 0
                except Exception as e:
                    logger.error(f"Error cancelling alpaca orders: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error in cancel_all_orders: {e}", exc_info=True)

        return count
