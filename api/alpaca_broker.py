"""
Alpaca PAPER Broker Adapter (Read-Only)

PHASE 3 — BROKER ADAPTER (READ-ONLY)

Connects to Alpaca PAPER account for account information only.
NEVER places orders or modifies account state.

ABSOLUTE SAFETY RULES:
- NEVER place orders
- NEVER enable trading
- trading_enabled MUST remain false (HARD LOCK)
- On failure: Return DISCONNECTED status, do NOT raise exceptions
"""

import os
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetAccountRequest
    from alpaca.trading.enums import AccountStatus
    from alpaca.common.exceptions import APIError as AlpacaAPIError
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    TradingClient = None

from api.brokers import Broker, BrokerType, BrokerStatus


class AlpacaPaperBroker:
    """
    Alpaca PAPER broker adapter - read-only account information.
    
    PHASE 3: Fetches account information only
    PHASE 4: Never submits orders
    PHASE 6: Thread-safe, non-blocking
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._client: Optional[TradingClient] = None
        self._last_error: Optional[str] = None
        self._last_update: Optional[datetime] = None
        
        # PHASE 2: Read credentials from environment
        self.api_key_id = os.getenv("ALPACA_API_KEY_ID")
        self.api_secret_key = os.getenv("ALPACA_API_SECRET_KEY")
        self.base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        
        # PHASE 3: HARD LOCK - trading_enabled always false
        self.trading_enabled = False
    
    def _create_client(self) -> Optional[TradingClient]:
        """Create Alpaca client - returns None if credentials missing or unavailable"""
        if not ALPACA_AVAILABLE:
            return None
        
        if not self.api_key_id or not self.api_secret_key:
            return None
        
        try:
            return TradingClient(
                api_key=self.api_key_id,
                secret_key=self.api_secret_key,
                base_url=self.base_url,
                paper=True,  # PHASE 2: Always paper
            )
        except Exception:
            return None
    
    def _fetch_account(self) -> Optional[Dict[str, Any]]:
        """
        Fetch account information from Alpaca.
        
        PHASE 3: Read-only operation
        Returns None on failure, never raises.
        """
        if not ALPACA_AVAILABLE:
            return None
        
        try:
            client = self._create_client()
            if client is None:
                return None
            
            # PHASE 3: Fetch account only - no orders, no modifications
            account = client.get_account()
            
            return {
                "equity": float(account.equity or 0.0),
                "cash": float(account.cash or 0.0),
                "buying_power": float(account.buying_power or 0.0),
                "currency": account.currency or "USD",
                "status": account.status.value if account.status else "ACTIVE",
            }
        except AlpacaAPIError as e:
            # PHASE 3: Log error but don't raise
            self._last_error = f"Alpaca API error: {str(e)}"
            return None
        except Exception as e:
            # PHASE 3: Catch all exceptions, never raise
            self._last_error = f"Connection error: {str(e)}"
            return None
    
    def get_broker(self) -> Broker:
        """
        Get broker representation with current account data.
        
        PHASE 3: Returns DISCONNECTED status on failure
        PHASE 6: Thread-safe
        """
        with self._lock:
            account_data = self._fetch_account()
            
            if account_data is None:
                # PHASE 3: Return DISCONNECTED status, include error message
                return Broker(
                    id="alpaca-paper",
                    type=BrokerType.PAPER,
                    status=BrokerStatus.DISCONNECTED,
                    trading_enabled=False,  # PHASE 3: HARD LOCK - always false
                    equity=0.0,
                    currency="USD",
                )
            
            # PHASE 3: Success - return broker with account data
            self._last_error = None
            self._last_update = datetime.now()
            
            return Broker(
                id="alpaca-paper",
                type=BrokerType.PAPER,
                status=BrokerStatus.CONNECTED,
                trading_enabled=False,  # PHASE 3: HARD LOCK - always false
                equity=account_data["equity"],
                currency=account_data["currency"],
                # Additional fields for Sentinel X compatibility
                cash=account_data["cash"],
                buying_power=account_data["buying_power"],
            )
    
    def get_error(self) -> Optional[str]:
        """Get last error message - for debugging"""
        with self._lock:
            return self._last_error
    
    def is_available(self) -> bool:
        """Check if Alpaca SDK is available and credentials are configured"""
        return ALPACA_AVAILABLE and self.api_key_id is not None and self.api_secret_key is not None
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """
        PHASE 1: Fetch open positions from Alpaca PAPER (read-only)
        PHASE 2: Normalize positions into broker-agnostic schema
        
        Returns:
            List of normalized position dicts, empty list on failure
        """
        if not ALPACA_AVAILABLE:
            return []
        
        try:
            client = self._create_client()
            if client is None:
                return []
            
            # PHASE 1: Read-only - get_all_positions() only
            positions = client.get_all_positions()
            
            # PHASE 2: Normalize positions
            normalized = []
            for pos in positions:
                try:
                    qty = float(pos.qty or 0.0)
                    side = "long" if qty > 0 else "short" if qty < 0 else "long"
                    
                    normalized.append({
                        "symbol": pos.symbol or "",
                        "qty": abs(qty),  # Always positive, side indicates direction
                        "side": side,
                        "market_value": float(pos.market_value or 0.0),
                        "cost_basis": float(pos.cost_basis or 0.0),
                        "unrealized_pl": float(pos.unrealized_pl or 0.0),
                        "unrealized_pl_pct": float(pos.unrealized_plpc or 0.0) if hasattr(pos, 'unrealized_plpc') else 0.0,
                        "current_price": float(pos.current_price or 0.0) if hasattr(pos, 'current_price') else 0.0,
                    })
                except Exception:
                    # PHASE 5: Skip invalid positions, continue with others
                    continue
            
            return normalized
        except AlpacaAPIError as e:
            # PHASE 5: Return empty list on API error
            self._last_error = f"Alpaca positions API error: {str(e)}"
            return []
        except Exception as e:
            # PHASE 5: Return empty list on any error
            self._last_error = f"Positions fetch error: {str(e)}"
            return []
    
    def get_orders(self, limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        PHASE 1: Fetch recent orders from Alpaca PAPER (read-only)
        PHASE 3: Normalize orders into read-only schema
        
        Args:
            limit: Maximum number of orders to return (default 50)
            status: Optional order status filter
        
        Returns:
            List of normalized order dicts, empty list on failure
        """
        if not ALPACA_AVAILABLE:
            return []
        
        try:
            client = self._create_client()
            if client is None:
                return []
            
            # PHASE 1: Read-only - get_orders() only
            # PHASE 3: Fetch recent orders with optional status filter
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import OrderStatus
            
            request_params = {
                "limit": limit,
                "nested": False,  # Don't include nested orders
            }
            
            # PHASE 3: Apply status filter if provided
            if status:
                try:
                    # Map string status to enum if valid
                    status_enum = OrderStatus[status.upper()] if hasattr(OrderStatus, status.upper()) else None
                    if status_enum:
                        request_params["status"] = status_enum
                except Exception:
                    # Invalid status - ignore filter
                    pass
            
            orders = client.get_orders(GetOrdersRequest(**request_params))
            
            # PHASE 3: Normalize orders
            normalized = []
            for order in orders:
                try:
                    normalized.append({
                        "id": str(order.id or ""),
                        "symbol": order.symbol or "",
                        "qty": float(order.qty or 0.0),
                        "filled_qty": float(order.filled_qty or 0.0),
                        "side": order.side.value.lower() if hasattr(order.side, 'value') else str(order.side).lower(),
                        "order_type": order.order_type.value if hasattr(order.order_type, 'value') else str(order.order_type),
                        "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                        "submitted_at": order.submitted_at.isoformat() if hasattr(order.submitted_at, 'isoformat') and order.submitted_at else None,
                        "filled_at": order.filled_at.isoformat() if hasattr(order.filled_at, 'isoformat') and order.filled_at else None,
                    })
                except Exception:
                    # PHASE 5: Skip invalid orders, continue with others
                    continue
            
            return normalized
        except AlpacaAPIError as e:
            # PHASE 5: Return empty list on API error
            self._last_error = f"Alpaca orders API error: {str(e)}"
            return []
        except Exception as e:
            # PHASE 5: Return empty list on any error
            self._last_error = f"Orders fetch error: {str(e)}"
            return []


# Global Alpaca broker instance
_alpaca_broker: Optional[AlpacaPaperBroker] = None


def get_alpaca_broker() -> Optional[AlpacaPaperBroker]:
    """Get global Alpaca broker instance"""
    global _alpaca_broker
    if _alpaca_broker is None:
        _alpaca_broker = AlpacaPaperBroker()
    return _alpaca_broker
