"""Base broker and BrokerAdapter interfaces for multi-broker support."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import datetime


@dataclass
class BrokerHealthSnapshot:
    """
    Lightweight, read-only view of broker health.
    
    Used by the router for deterministic routing decisions.
    All values are normalized to sane defaults when data is sparse.
    """
    broker: str
    latency_ms: float = 0.0
    fill_rate: float = 1.0
    slippage_bps: float = 0.0
    error_rate: float = 0.0
    availability: float = 1.0
    reliability_score: float = 1.0
    last_updated: Optional[datetime] = field(default=None)


class BaseBroker(ABC):
    """
    Abstract base class for all brokers.
    
    NOTE:
    - This is intentionally minimal: connectivity + basic trading interface.
    - Execution arbitration and health logic live in the router and adapters,
      never in strategies or engine code.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Broker name (e.g., 'alpaca', 'paper', 'ibkr')."""
        raise NotImplementedError
    
    @property
    @abstractmethod
    def mode(self) -> str:
        """Broker mode: 'PAPER' or 'LIVE'."""
        raise NotImplementedError
    
    @abstractmethod
    def get_account(self) -> Optional[Dict]:
        """
        Get account information.
        
        Returns:
            Dict with keys: equity, cash, buying_power, portfolio_value, etc.
            None if not connected or error
        """
        raise NotImplementedError
    
    @abstractmethod
    def get_positions(self) -> List[Dict]:
        """
        Get current positions.
        
        Returns:
            List of position dicts with: symbol, qty, avg_price, current_price, unrealized_pnl
        """
        raise NotImplementedError
    
    @abstractmethod
    def submit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: Optional[float] = None,
        strategy: str = "",
    ) -> Optional[Dict]:
        """
        Submit an order.
        
        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            qty: Order quantity
            price: Limit price (None for market)
            strategy: Strategy name
            
        Returns:
            Order result dict with order_id, status, etc. or None if rejected
        """
        raise NotImplementedError
    
    @abstractmethod
    def cancel_all_orders(self) -> int:
        """
        Cancel all open orders.
        
        Returns:
            Number of orders canceled
        """
        raise NotImplementedError
    
    def get_fills(self, since_ts: Optional[datetime] = None) -> List[Dict]:
        """
        Get fills since timestamp (optional).
        
        Args:
            since_ts: Get fills since this timestamp (None = all)
            
        Returns:
            List of fill dicts with: symbol, side, qty, price, timestamp, strategy
        """
        # Default implementation returns empty list
        # Brokers can override if they support fill history
        return []


class BrokerAdapter(BaseBroker, ABC):
    """
    BrokerAdapter = strict interface used by the ExecutionRouter.
    
    PHASE 1: All broker-specific logic is encapsulated behind this interface.
    
    Required methods for routing and health:
    - submit_order()
    - cancel_order()
    - get_order_status()
    - get_latency()
    - get_fees()
    - get_reliability_score()
    """
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a single order, if supported by the broker.
        
        Returns:
            True if cancel acknowledged, False otherwise.
        """
        raise NotImplementedError
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Get current status for a single order, if supported by the broker.
        
        Returns:
            Order status dict or None if unavailable.
        """
        raise NotImplementedError
    
    def get_latency(self) -> float:
        """
        Return recent average execution latency in milliseconds.
        
        Routers use this for tie-breaking and health scoring.
        Default implementation returns 0.0 if unknown.
        """
        return 0.0
    
    def get_fees(self) -> Dict[str, float]:
        """
        Return a static view of broker fees used for routing decisions.
        
        Example schema (not enforced):
            {
                "per_share": 0.0005,
                "per_order": 0.0,
                "rebate_bps": 0.0
            }
        """
        return {}
    
    def get_reliability_score(self) -> float:
        """
        Return broker reliability score in [0.0, 1.0].
        
        Routers combine this with latency, slippage, and cost metrics.
        Default implementation assumes fully reliable until health model
        has collected enough data.
        """
        return 1.0
