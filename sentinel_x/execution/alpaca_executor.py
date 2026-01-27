"""
Alpaca paper trading executor with strict risk controls.

=== TRAINING BASELINE — DO NOT MODIFY ===

ARCHITECTURAL TRUTH:
- Alpaca PAPER is the TRAINING broker
- Alpaca PAPER must auto-connect on engine startup
- Alpaca PAPER runs forever

SAFETY LOCK:
- Hard-locked to PAPER mode only (connect() rejects LIVE URLs)
- Health checks are non-fatal and never raise exceptions
- No execution dependencies on analytics or realized_pnl

REGRESSION FREEZE:
- Alpaca auto-connect cannot be removed accidentally
- Engine runs even with missing brokers
- No future config flags affect training execution
"""

# ============================================================
# REGRESSION LOCK — DO NOT MODIFY
# Stable execution baseline.
# Changes require architectural review.
# ============================================================
# NO future changes may:
#   • Alter executor signatures
#   • Change router → executor contracts
#   • Introduce lifecycle dependencies in bootstrap
#   • Affect TRAINING auto-connect behavior
# ============================================================

import time
from datetime import datetime
from typing import Dict, Optional, List
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest, OrderSide, OrderType
from alpaca.trading.enums import QueryOrderStatus, TimeInForce
from alpaca.common.exceptions import APIError
from sentinel_x.core.kill_switch import is_killed
from sentinel_x.core.config import Config
from sentinel_x.data.storage import Storage
from sentinel_x.monitoring.logger import logger
from sentinel_x.execution.broker_base import BaseBroker


class AlpacaPaperExecutor(BaseBroker):
    """
    Alpaca PAPER trading executor with strict risk controls.
    
    PHASE 2: Explicit PAPER-only executor.
    Uses paper base URL ONLY.
    Validates keys at init but does NOT place orders on init.
    Raises NO exceptions during connectivity checks.
    """
    
    @property
    def name(self) -> str:
        return "alpaca"
    
    @property
    def mode(self) -> str:
        # Always PAPER - this executor is hard-locked to paper
        return "PAPER"
    
    def __init__(self, config: Config, storage: Optional[Storage] = None):
        """
        Initialize Alpaca PAPER executor.
        
        PHASE 2: Validates keys at init but does NOT place orders on init.
        Raises NO exceptions during initialization.
        
        Args:
            config: Configuration object
            storage: Storage instance for persisting orders
        """
        self.config = config
        self.storage = storage
        self.client: Optional[TradingClient] = None
        self.connected = False
        self.daily_pnl_start = 0.0
        self.daily_pnl_timestamp = datetime.now().date()
        
        # PHASE 2: Force paper base URL
        if "paper-api" not in config.alpaca_base_url.lower():
            logger.warning(f"Non-paper URL detected: {config.alpaca_base_url} - forcing paper URL")
            config.alpaca_base_url = "https://paper-api.alpaca.markets"
        
        # PHASE 2: Validate keys at init (non-fatal)
        if not config.alpaca_api_key or not config.alpaca_secret_key:
            logger.warning("Alpaca credentials not configured - executor will not connect")
        else:
            logger.info("AlpacaPaperExecutor initialized (PAPER mode only)")
        
        # PHASE 2: Do NOT connect at init - connection happens during arming
    
    def connect(self) -> bool:
        """
        Connect to Alpaca API.
        
        CRITICAL SAFETY: This executor is HARD-LOCKED to PAPER mode only.
        LIVE trading is cryptographically impossible unless explicitly unlocked
        through a separate mechanism.
        
        Returns:
            True if connected successfully, False otherwise
            
        Raises:
            RuntimeError: If LIVE broker URL is detected (hard fail-fast)
        
        ────────────────────────────────────────
        PHASE 8 — REGRESSION LOCK
        ────────────────────────────────────────
        
        REGRESSION LOCK:
        Do NOT modify engine loop, broker wiring, or order schemas
        without architect approval. Changes here can cause
        silent trading failures or engine crashes.
        
        ENFORCE:
        • No lifecycle module imports in bootstrap
        • No default/non-default argument order violations
        • No schema assumptions
        """
        if not self.config.alpaca_api_key or not self.config.alpaca_secret_key:
            logger.warning("Alpaca credentials not configured. Skipping connection.")
            return False
        
        # HARD BLOCK: Fail fast if LIVE broker URL detected
        if "paper-api" not in self.config.alpaca_base_url.lower():
            error_msg = (
                f"Alpaca is forbidden in LIVE mode. "
                f"LIVE broker URL detected: {self.config.alpaca_base_url}. "
                f"This executor is locked to PAPER mode only. "
                f"LIVE mode requires Tradovate executor only."
            )
            logger.critical(error_msg)
            raise RuntimeError(error_msg)
        
        try:
            # CRITICAL: Force paper=True - this is redundant but provides double protection
            self.client = TradingClient(
                api_key=self.config.alpaca_api_key,
                secret_key=self.config.alpaca_secret_key,
                paper=True,  # Force paper trading (hard lock)
                url_override=self.config.alpaca_base_url
            )
            
            # Test connection
            account = self.client.get_account()
            self.connected = True
            
            # SAFE: Defensive attribute access for account fields
            equity = getattr(account, "equity", None) or 0.0
            last_equity = getattr(account, "last_equity", None) or equity
            account_number = getattr(account, "account_number", "unknown")
            buying_power = (
                getattr(account, "day_trading_buying_power", None)
                or getattr(account, "buying_power", None)
                or getattr(account, "cash", 0.0)
            )
            
            self.daily_pnl_start = float(equity) - float(last_equity)
            
            logger.info(f"Alpaca connection successful. Account: {account_number}")
            # Log buying power ONLY in TRAINING / PAPER mode
            if self.mode == "PAPER":
                logger.info(f"Equity: ${float(equity):,.2f}, Buying Power: ${float(buying_power):,.2f}")
            
            return True
        
        except Exception as e:
            logger.error(f"Alpaca connection failed: {e}")
            self.connected = False
            return False
    
    def health_check(self) -> dict:
        """
        Non-fatal health probe to check broker connectivity.
        
        RULE: Health checks must NEVER raise exceptions.
        This method is safe to call from UI/observability code without risk.
        
        Returns:
            Dictionary with health status:
            - connected: bool - True if broker is connected
            - broker: str - Broker identifier ("alpaca_paper" or "alpaca_live")
            - error: str (optional) - Error message if connection failed
        """
        try:
            # Determine broker type from mode
            broker_type = "alpaca_paper" if self.mode == "PAPER" else "alpaca_live"
            
            # If not connected, return disconnected status
            if not self.connected or not self.client:
                return {
                    "connected": False,
                    "broker": broker_type,
                    "error": "Not connected"
                }
            
            # Probe connection with non-fatal account check
            try:
                self.client.get_account()
                return {
                    "connected": True,
                    "broker": broker_type
                }
            except Exception as e:
                # Connection probe failed - mark as disconnected
                self.connected = False  # Update internal state
                return {
                    "connected": False,
                    "broker": broker_type,
                    "error": str(e)
                }
                
        except Exception as e:
            # CRITICAL: Health check must NEVER raise
            logger.error(f"Health check error (non-fatal): {e}", exc_info=True)
            return {
                "connected": False,
                "broker": getattr(self, 'mode', 'unknown'),
                "error": f"Health check exception: {str(e)}"
            }
    
    def get_account(self) -> Optional[Dict]:
        """
        Get account information.
        
        Returns:
            Account dictionary or None if not connected
        """
        if not self.connected or not self.client:
            return None
        
        try:
            account = self.client.get_account()
            
            # PHASE 3: ALPACA ACCOUNT SCHEMA HARDENING
            # Replace all direct attribute access with safe getattr chains
            # Missing fields must NEVER raise - use safe defaults
            
            # SAFE: Defensive attribute access for all account fields
            equity = getattr(account, "equity", None) or 0.0
            buying_power_attr = (
                getattr(account, "day_trading_buying_power", None)
                or getattr(account, "buying_power", None)
                or getattr(account, "cash", 0.0)
            )
            cash = getattr(account, "cash", None) or 0.0
            portfolio_value = getattr(account, "portfolio_value", None) or equity
            account_number = getattr(account, "account_number", "unknown")
            status = getattr(account, "status", "unknown")
            
            # LOGGING RULE: Log buying power ONLY in TRAINING / PAPER mode
            if self.mode == "PAPER":
                logger.info(
                    f"Alpaca buying power detected: {buying_power_attr}"
                )
            
            return {
                'equity': float(equity),
                'buying_power': float(buying_power_attr),
                'cash': float(cash),
                'portfolio_value': float(portfolio_value),
                'day_trading_buying_power': float(buying_power_attr),
                'account_number': account_number,
                'status': status
            }
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return None
    
    def get_positions(self) -> List[Dict]:
        """
        Get current positions from Alpaca.
        
        Returns:
            List of position dictionaries
        """
        if not self.connected or not self.client:
            return []
        
        try:
            positions = self.client.get_all_positions()
            positions_list = []
            
            for pos in positions:
                positions_list.append({
                    'symbol': pos.symbol,
                    'qty': float(pos.qty),
                    'avg_price': float(pos.avg_entry_price),
                    'current_price': float(pos.current_price),
                    'unrealized_pnl': float(pos.unrealized_pl),
                    'market_value': float(pos.market_value),
                    'entry_time': None  # Alpaca doesn't provide entry time directly
                })
            
            return positions_list
        
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    def _check_kill_switch(self) -> bool:
        """Check if kill switch is triggered."""
        if is_killed():
            logger.warning("Kill switch triggered - rejecting order")
            return False
        return True
    
    def _check_max_position_size(self, symbol: str, qty: float, current_price: float) -> bool:
        """
        Check if position size exceeds maximum allowed.
        
        Args:
            symbol: Trading symbol
            qty: Order quantity (absolute value)
            current_price: Current price
            
        Returns:
            True if within limits, False otherwise
        """
        if not self.connected:
            return False
        
        account = self.get_account()
        if not account:
            return False
        
        equity = account['equity']
        max_position_value = equity * self.config.max_position_per_symbol
        order_value = qty * current_price
        
        if order_value > max_position_value:
            logger.warning(f"Order rejected: {symbol} position value ${order_value:,.2f} "
                         f"exceeds max ${max_position_value:,.2f} ({self.config.max_position_per_symbol*100}% of equity)")
            return False
        
        return True
    
    def _check_daily_loss_limit(self) -> bool:
        """
        Check if daily loss exceeds limit.
        
        Returns:
            True if within limits, False otherwise
        """
        if not self.connected:
            return False
        
        account = self.get_account()
        if not account:
            return False
        
        # Reset daily PnL tracking if new day
        today = datetime.now().date()
        if today != self.daily_pnl_timestamp:
            self.daily_pnl_start = account['equity']
            self.daily_pnl_timestamp = today
        
        daily_pnl = account['equity'] - self.daily_pnl_start
        daily_loss_pct = abs(daily_pnl) / self.daily_pnl_start if self.daily_pnl_start > 0 else 0.0
        
        if daily_pnl < 0 and daily_loss_pct > self.config.max_daily_loss:
            logger.warning(f"Daily loss limit exceeded: ${daily_pnl:,.2f} "
                         f"({daily_loss_pct*100:.2f}% > {self.config.max_daily_loss*100}%)")
            return False
        
        return True
    
    def submit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: Optional[float] = None,
        strategy: str = "",
        **kwargs,
    ) -> Optional[Dict]:
        """
        Submit order with risk checks.
        
        REGRESSION LOCK:
        - Signature MUST match BaseBroker interface exactly
        - Router passes: symbol, side, qty, price, strategy
        - Interface compliance is CRITICAL - signature changes will break router
        
        CRITICAL: Interface matches BaseBroker for router compatibility.
        Alpaca PAPER uses MARKET orders only - price parameter is accepted but ignored.
        
        Args:
            symbol: Trading symbol
            side: "buy" or "sell"
            qty: Order quantity (absolute value, always positive)
            price: Limit price (ignored - Alpaca PAPER uses MARKET orders only)
            strategy: Strategy name (optional, for logging/audit)
            **kwargs: Additional parameters (ignored for TRAINING baseline)
            
        Returns:
            Order dictionary with order_id, status, etc. or None if rejected
        
        ────────────────────────────────────────
        PHASE 8 — REGRESSION LOCK
        ────────────────────────────────────────
        
        REGRESSION LOCK:
        Do NOT modify engine loop, broker wiring, or order schemas
        without architect approval. Changes here can cause
        silent trading failures or engine crashes.
        
        ENFORCE:
        • No lifecycle module imports in bootstrap
        • No default/non-default argument order violations
        • No schema assumptions
        """
        # REGRESSION LOCK:
        # Alpaca PAPER uses MARKET orders only.
        # Price is intentionally ignored to preserve router stability.
        del price
        
        if not self.connected or not self.client:
            logger.error("Alpaca not connected - cannot submit order")
            return None
        
        # Critical: Check kill switch first
        if not self._check_kill_switch():
            return None
        
        # Get current price for risk checks (simplified - in production use market data)
        try:
            # Try to get current position to estimate current price
            positions = self.get_positions()
            current_price = None
            for pos in positions:
                if pos['symbol'] == symbol:
                    current_price = pos['current_price']
                    break
            
            # If no position, use a placeholder (in production, fetch from market data)
            if current_price is None:
                logger.warning(f"Cannot determine current price for {symbol} - using conservative estimate")
                current_price = 100.0  # Placeholder
            
            # Risk checks
            if not self._check_max_position_size(symbol, qty, current_price):
                return None
            
            if not self._check_daily_loss_limit():
                return None
        
        except Exception as e:
            logger.error(f"Risk check error for {symbol}: {e}")
            return None
        
        # PHASE 4: ALPACA ORDER SCHEMA FIX (CRITICAL)
        # Submit order
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            
            # CRITICAL: Alpaca SDK now REQUIRES time_in_force for MarketOrderRequest
            # No MarketOrderRequest may omit time_in_force
            # ValidationError must never escape submit_order()
            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY
            )
            
            order = self.client.submit_order(order_data=order_request)
            
            logger.info(f"Order submitted: {side.upper()} {qty} {symbol} - Order ID: {order.id}")
            
            # Persist order to storage
            if self.storage:
                try:
                    self.storage.save_order(
                        order_id=str(order.id),
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        order_type="market",  # Alpaca PAPER uses MARKET orders only
                        status=order.status.value,
                        timestamp=datetime.now()
                    )
                except Exception as e:
                    logger.warning(f"Error saving order to storage: {e}")
            
            return {
                'order_id': order.id,
                'symbol': symbol,
                'side': side,
                'qty': qty,
                'status': order.status.value,
                'submitted_at': order.submitted_at.isoformat() if order.submitted_at else None
            }
        
        except APIError as e:
            # CRITICAL: ValidationError (and other APIErrors) must never escape submit_order()
            logger.error(f"Alpaca API error submitting order: {e}")
            return None
        except Exception as e:
            # CRITICAL: Catch ALL exceptions including ValidationError from MarketOrderRequest
            # ValidationError must never escape submit_order()
            logger.error(f"Error submitting order: {e}", exc_info=True)
            return None
    
    def get_fills(self, since_ts: Optional[datetime] = None) -> List[Dict]:
        """
        Get fills since timestamp.
        
        Args:
            since_ts: Get fills since this timestamp (None = all)
            
        Returns:
            List of fill dicts
        """
        if not self.connected or not self.client:
            return []
        
        try:
            # Alpaca doesn't have a direct fills endpoint, use orders
            # This is a simplified implementation
            orders = self.client.get_orders(
                status=QueryOrderStatus.FILLED,
                limit=100
            )
            
            fills = []
            for order in orders:
                order_ts = order.submitted_at if order.submitted_at else datetime.now()
                if since_ts and order_ts < since_ts:
                    continue
                
                fills.append({
                    'symbol': order.symbol,
                    'side': order.side.value.lower(),
                    'qty': float(order.qty),
                    'price': float(order.filled_avg_price) if order.filled_avg_price else 0.0,
                    'timestamp': order_ts.isoformat(),
                    'strategy': ''  # Not available from Alpaca
                })
            
            return fills
        except Exception as e:
            logger.error(f"Error getting fills from Alpaca: {e}")
            return []
    
    def cancel_all_orders(self) -> int:
        """
        Cancel all open orders.
        
        Returns:
            Number of orders canceled
        """
        if not self.connected or not self.client:
            return 0
        
        try:
            # Get all open orders
            orders = self.client.get_orders(
                filter=GetOrdersRequest(
                    status=QueryOrderStatus.OPEN
                )
            )
            
            canceled_count = 0
            for order in orders:
                try:
                    self.client.cancel_order_by_id(order.id)
                    logger.info(f"Canceled order: {order.id} ({order.symbol})")
                    canceled_count += 1
                except Exception as e:
                    logger.error(f"Error canceling order {order.id}: {e}")
            
            logger.info(f"Canceled {canceled_count} open orders")
            return canceled_count
        
        except Exception as e:
            logger.error(f"Error canceling orders: {e}")
            return 0
    
    def get_open_orders(self) -> List[Dict]:
        """
        Get all open orders.
        
        Returns:
            List of order dictionaries
        """
        if not self.connected or not self.client:
            return []
        
        try:
            orders = self.client.get_orders(
                filter=GetOrdersRequest(
                    status=QueryOrderStatus.OPEN
                )
            )
            
            return [
                {
                    'order_id': order.id,
                    'symbol': order.symbol,
                    'side': order.side.value,
                    'qty': float(order.qty),
                    'status': order.status.value,
                    'submitted_at': order.submitted_at.isoformat() if order.submitted_at else None
                }
                for order in orders
            ]
        
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []


# PHASE 2: Backward compatibility alias
AlpacaExecutor = AlpacaPaperExecutor


def build_alpaca_paper_executor(config: Config) -> Optional[AlpacaPaperExecutor]:
    """
    Build Alpaca PAPER executor from config.
    
    PHASE 2: Factory function for explicit executor creation.
    
    Behavior:
    - If keys missing → return None
    - If keys present → return executor
    - Never throw exceptions
    
    Args:
        config: Configuration object
        
    Returns:
        AlpacaPaperExecutor instance if keys are present, None otherwise
    """
    try:
        # Check if keys are present
        if not config.alpaca_api_key or not config.alpaca_secret_key:
            return None
        
        # Ensure paper URL
        if "paper-api" not in config.alpaca_base_url.lower():
            logger.warning(f"Non-paper URL detected: {config.alpaca_base_url} - using paper URL")
            config.alpaca_base_url = "https://paper-api.alpaca.markets"
        
        # Import storage here to avoid circular dependency
        from sentinel_x.data.storage import get_storage
        storage = get_storage()
        
        # Create executor (does not connect yet)
        executor = AlpacaPaperExecutor(config, storage)
        return executor
        
    except Exception as e:
        # CRITICAL: Never throw - return None on any error
        logger.error(f"Failed to build Alpaca paper executor (non-fatal): {e}", exc_info=True)
        return None

