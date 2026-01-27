"""
Alpaca PAPER Execution Adapter

PHASE 3 — PAPER EXECUTION ADAPTER (ALPACA PAPER)

Implements Alpaca PAPER execution adapter using official alpaca-py SDK.
submit_order() ONLY reachable through execution guard.

ABSOLUTE SAFETY RULES:
- Uses official alpaca-py SDK
- Supports market and limit orders only
- No advanced order types
- No leverage logic
- On failure: Do NOT retry automatically
"""

import os
import threading
from typing import Optional
from api.execution.base import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionAdapter,
    ExecutionStatus,
    OrderSide,
    OrderType,
)

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide as AlpacaOrderSide, OrderStatus
    from alpaca.common.exceptions import APIError as AlpacaAPIError
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    TradingClient = None
    MarketOrderRequest = None
    LimitOrderRequest = None
    AlpacaOrderSide = None
    OrderStatus = None
    AlpacaAPIError = None

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class AlpacaPaperExecutor(ExecutionAdapter):
    """
    PHASE 3 — ALPACA PAPER EXECUTION ADAPTER
    
    Alpaca PAPER execution adapter.
    submit_order() ONLY reachable through execution guard.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._client: Optional[TradingClient] = None
        self._connected: bool = False
        self._broker_name = "alpaca_paper"
        
        # PHASE 3: Read credentials from environment
        self.api_key_id = os.getenv("ALPACA_API_KEY_ID")
        self.api_secret = os.getenv("ALPACA_API_SECRET")
        
        # PHASE 3: Alpaca PAPER base URL
        self.base_url = "https://paper-api.alpaca.markets"
        
        # PHASE 3: Initialize client if credentials available
        if ALPACA_AVAILABLE and self.api_key_id and self.api_secret:
            try:
                self._client = TradingClient(
                    api_key=self.api_key_id,
                    secret_key=self.api_secret,
                    paper=True,  # PHASE 3: Always paper
                    url_override=self.base_url,
                )
                self._connected = True
                logger.info("Alpaca PAPER execution adapter initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Alpaca PAPER client: {e}", exc_info=True)
                self._connected = False
        else:
            if not ALPACA_AVAILABLE:
                logger.warning("alpaca-py SDK not available - Alpaca PAPER execution disabled")
            else:
                logger.warning("Alpaca credentials not found - Alpaca PAPER execution disabled")
            self._connected = False
    
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """
        PHASE 3 — EXECUTE ORDER
        
        Execute order request through Alpaca PAPER.
        This method is ONLY reachable through execution guard.
        
        Args:
            request: Execution request
            
        Returns:
            Execution result
        """
        # PHASE 3: Check if connected
        if not self._connected or not self._client:
            return ExecutionResult(
                accepted=False,
                request_id=request.request_id,
                status=ExecutionStatus.REJECTED,
                reason="Alpaca PAPER client not connected",
            )
        
        try:
            # PHASE 3: Convert OrderSide to Alpaca OrderSide
            if request.side == OrderSide.BUY:
                alpaca_side = AlpacaOrderSide.BUY
            else:
                alpaca_side = AlpacaOrderSide.SELL
            
            # PHASE 3: Create order request based on order type
            if request.order_type == OrderType.MARKET:
                # PHASE 3: Market order
                order_request = MarketOrderRequest(
                    symbol=request.symbol,
                    qty=request.qty,
                    side=alpaca_side,
                )
            elif request.order_type == OrderType.LIMIT:
                # PHASE 3: Limit order (requires limit_price)
                if request.limit_price is None:
                    return ExecutionResult(
                        accepted=False,
                        request_id=request.request_id,
                        status=ExecutionStatus.REJECTED,
                        reason="Limit price required for limit orders",
                    )
                
                order_request = LimitOrderRequest(
                    symbol=request.symbol,
                    qty=request.qty,
                    side=alpaca_side,
                    limit_price=request.limit_price,
                )
            else:
                # PHASE 3: Unsupported order type
                return ExecutionResult(
                    accepted=False,
                    request_id=request.request_id,
                    status=ExecutionStatus.REJECTED,
                    reason=f"Unsupported order type: {request.order_type.value}",
                )
            
            # PHASE 3: Submit order to Alpaca
            with self._lock:
                try:
                    order = self._client.submit_order(order_request)
                    
                    # PHASE 3: Map Alpaca order status to ExecutionStatus
                    if order.status == OrderStatus.ACCEPTED or order.status == OrderStatus.NEW:
                        status = ExecutionStatus.ACCEPTED
                    elif order.status == OrderStatus.FILLED:
                        status = ExecutionStatus.FILLED
                    elif order.status == OrderStatus.PARTIALLY_FILLED:
                        status = ExecutionStatus.PARTIALLY_FILLED
                    elif order.status == OrderStatus.CANCELLED:
                        status = ExecutionStatus.CANCELLED
                    else:
                        status = ExecutionStatus.PENDING
                    
                    # PHASE 3: Success - return result with broker_order_id
                    return ExecutionResult(
                        accepted=True,
                        request_id=request.request_id,
                        broker_order_id=order.id,
                        status=status,
                        reason="Order submitted successfully",
                    )
                    
                except AlpacaAPIError as e:
                    # PHASE 3: Alpaca API error - do NOT retry automatically
                    error_msg = f"Alpaca API error: {str(e)}"
                    logger.error(f"Order submission failed: {error_msg}")
                    
                    return ExecutionResult(
                        accepted=False,
                        request_id=request.request_id,
                        status=ExecutionStatus.REJECTED,
                        reason=error_msg,
                    )
                except Exception as e:
                    # PHASE 3: Unexpected error - do NOT retry automatically
                    error_msg = f"Unexpected error: {str(e)}"
                    logger.error(f"Order submission failed: {error_msg}", exc_info=True)
                    
                    return ExecutionResult(
                        accepted=False,
                        request_id=request.request_id,
                        status=ExecutionStatus.ERROR,
                        reason=error_msg,
                    )
                    
        except Exception as e:
            # PHASE 3: Error during order creation - do NOT retry automatically
            error_msg = f"Order creation failed: {str(e)}"
            logger.error(f"Order creation failed: {error_msg}", exc_info=True)
            
            return ExecutionResult(
                accepted=False,
                request_id=request.request_id,
                status=ExecutionStatus.ERROR,
                reason=error_msg,
            )
    
    def is_available(self) -> bool:
        """Check if adapter is available/connected"""
        with self._lock:
            return self._connected and self._client is not None
    
    def get_broker_name(self) -> str:
        """Get broker name/identifier"""
        return self._broker_name
