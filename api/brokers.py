"""
Broker Abstraction Layer

PHASE 2 — BROKER ABSTRACTION (PAPER-SAFE)

Creates a broker interface with:
- id
- type (simulated | paper | live)
- status (CONNECTED / DISCONNECTED)
- trading_enabled (false by default)
- equity
- currency

SAFETY:
- NO ORDER ROUTING (only observation)
- Default trading_enabled = false
- Do NOT connect to real brokers
"""

from typing import List, Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass
import threading


class BrokerType(Enum):
    """Broker type enum"""
    SIMULATED = "simulated"
    PAPER = "paper"
    LIVE = "live"


class BrokerStatus(Enum):
    """Broker connection status"""
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"


@dataclass
class Broker:
    """
    Broker representation - read-only for control plane.
    
    SAFETY: No order routing methods - observation only.
    
    PHASE 5: Extended fields for Sentinel X compatibility (cash, buying_power)
    """
    id: str
    type: BrokerType
    status: BrokerStatus
    trading_enabled: bool = False  # PHASE 2: Default false - no trading
    equity: float = 0.0
    currency: str = "USD"
    cash: float = 0.0  # PHASE 5: Cash balance for Sentinel X
    buying_power: float = 0.0  # PHASE 5: Buying power for Sentinel X
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API responses"""
        result = {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "trading_enabled": self.trading_enabled,
            "equity": self.equity,
            "currency": self.currency,
        }
        # PHASE 5: Include additional fields for Sentinel X compatibility
        result["cash"] = self.cash
        result["buying_power"] = self.buying_power
        return result


class BrokerRegistry:
    """
    Broker registry - manages broker instances.
    
    PHASE 2: Default simulated broker
    PHASE 4: Alpaca PAPER broker integration (read-only)
    """
    
    def __init__(self):
        self._brokers: Dict[str, Broker] = {}
        self._lock = threading.Lock()
        self._initialize_default()
        self._initialize_alpaca()
    
    def _initialize_default(self) -> None:
        """Initialize default simulated broker"""
        default_broker = Broker(
            id="paper-sim",
            type=BrokerType.SIMULATED,
            status=BrokerStatus.CONNECTED,
            trading_enabled=False,  # PHASE 2: Never enabled by default
            equity=100000.0,
            currency="USD",
        )
        self._brokers[default_broker.id] = default_broker
    
    def _initialize_alpaca(self) -> None:
        """
        PHASE 4: Initialize Alpaca PAPER broker (read-only)
        Safe to call even if Alpaca is unavailable
        """
        try:
            from api.alpaca_broker import get_alpaca_broker
            alpaca_broker = get_alpaca_broker()
            
            # Only register if Alpaca is available and configured
            if alpaca_broker and alpaca_broker.is_available():
                # Fetch broker data (may be DISCONNECTED if API call fails)
                broker = alpaca_broker.get_broker()
                with self._lock:
                    self._brokers[broker.id] = broker
        except Exception:
            # PHASE 4: Never raise - Alpaca unavailable is not a fatal error
            pass
    
    def get_all(self) -> List[Dict[str, Any]]:
        """
        Get all brokers as list of dicts - for API responses
        
        PHASE 4: Updates Alpaca broker data on each call (non-blocking)
        PHASE 6: Thread-safe
        """
        # PHASE 4: Refresh Alpaca broker data if available
        try:
            from api.alpaca_broker import get_alpaca_broker
            alpaca_broker = get_alpaca_broker()
            if alpaca_broker and alpaca_broker.is_available():
                # PHASE 6: Non-blocking - fetch latest account data
                updated_broker = alpaca_broker.get_broker()
                with self._lock:
                    self._brokers[updated_broker.id] = updated_broker
        except Exception:
            # PHASE 4: Never raise - continue with cached data if Alpaca fails
            pass
        
        with self._lock:
            return [broker.to_dict() for broker in self._brokers.values()]
    
    def get_by_id(self, broker_id: str) -> Optional[Broker]:
        """Get broker by ID - returns None if not found"""
        return self._brokers.get(broker_id)
    
    def get_connected(self) -> List[Broker]:
        """Get all connected brokers"""
        return [b for b in self._brokers.values() if b.status == BrokerStatus.CONNECTED]
    
    def has_trading_enabled(self) -> bool:
        """Check if any broker has trading enabled - PHASE 4 safety check"""
        return any(b.trading_enabled for b in self._brokers.values())
    
    def aggregate_positions(self) -> Dict[str, Any]:
        """
        PHASE 4: Aggregate positions across all brokers (read-only)
        
        Returns:
            Aggregated position data:
            - total_exposure_by_symbol: Dict[symbol, total_qty]
            - total_market_value: float
            - broker_attribution: Dict[symbol, List[broker_id]]
            - broker_count: int
        """
        try:
            from api.alpaca_broker import get_alpaca_broker
            
            aggregated = {
                "total_exposure_by_symbol": {},
                "total_market_value": 0.0,
                "broker_attribution": {},
                "broker_count": 0,
                "errors": [],
            }
            
            # Get positions from all brokers
            with self._lock:
                brokers_list = list(self._brokers.values())
            
            for broker in brokers_list:
                try:
                    # Get positions from Alpaca if available
                    if broker.id == "alpaca-paper":
                        alpaca_broker = get_alpaca_broker()
                        if alpaca_broker and alpaca_broker.is_available():
                            positions = alpaca_broker.get_positions()
                            
                            for pos in positions:
                                symbol = pos.get("symbol", "")
                                if not symbol:
                                    continue
                                
                                qty = float(pos.get("qty", 0.0))
                                market_value = float(pos.get("market_value", 0.0))
                                side = pos.get("side", "long")
                                
                                # Aggregate quantities (long positive, short negative)
                                sign = 1.0 if side == "long" else -1.0
                                net_qty = sign * qty
                                
                                if symbol not in aggregated["total_exposure_by_symbol"]:
                                    aggregated["total_exposure_by_symbol"][symbol] = 0.0
                                    aggregated["broker_attribution"][symbol] = []
                                
                                aggregated["total_exposure_by_symbol"][symbol] += net_qty
                                aggregated["total_market_value"] += market_value
                                aggregated["broker_attribution"][symbol].append(broker.id)
                    # PHASE 4: Could add other brokers here in future
                except Exception as e:
                    # PHASE 4: Skip failed brokers, continue with others
                    aggregated["errors"].append(f"Broker {broker.id}: {str(e)}")
                    continue
            
            aggregated["broker_count"] = len(brokers_list)
            
            return aggregated
        except Exception as e:
            # PHASE 4: Return safe defaults on error
            return {
                "total_exposure_by_symbol": {},
                "total_market_value": 0.0,
                "broker_attribution": {},
                "broker_count": 0,
                "errors": [str(e)],
            }


# Global broker registry instance
_broker_registry: BrokerRegistry = BrokerRegistry()


def get_broker_registry() -> BrokerRegistry:
    """Get global broker registry instance"""
    return _broker_registry
