"""Broker manager for multi-broker support."""
from typing import Dict, Optional
from sentinel_x.execution.broker_base import BaseBroker
from sentinel_x.monitoring.logger import logger


class BrokerManager:
    """
    Manages multiple brokers and active broker selection.
    
    Supports:
    - Multiple brokers (paper, alpaca, future: ibkr, ccxt, etc.)
    - Active broker switching (idle only)
    - Broker state tracking
    """
    
    def __init__(self):
        """Initialize broker manager."""
        self.brokers: Dict[str, BaseBroker] = {}
        self.active_broker_name: Optional[str] = None
        logger.info("BrokerManager initialized")
    
    def register_broker(self, broker: BaseBroker) -> None:
        """
        Register a broker.
        
        Args:
            broker: Broker instance implementing BaseBroker
        """
        try:
            broker_name = broker.name
            self.brokers[broker_name] = broker
            logger.info(f"Broker registered: {broker_name} (mode: {broker.mode})")
            
            # Set as active if first broker or if it's paper broker
            if self.active_broker_name is None or broker_name == "paper":
                self.active_broker_name = broker_name
                logger.info(f"Active broker set to: {broker_name}")
        except Exception as e:
            logger.error(f"Error registering broker: {e}", exc_info=True)
    
    def get_active_broker(self) -> Optional[BaseBroker]:
        """Get currently active broker."""
        if self.active_broker_name:
            return self.brokers.get(self.active_broker_name)
        return None
    
    def set_active_broker(self, broker_name: str) -> bool:
        """
        Set active broker (only when idle).
        
        Args:
            broker_name: Name of broker to activate
            
        Returns:
            True if switched, False if rejected
        """
        if broker_name not in self.brokers:
            logger.error(f"Broker not found: {broker_name}")
            return False
        
        # Safety: Only allow switching when no active positions/orders
        # This is a simplified check - in production, verify broker is idle
        old_broker = self.get_active_broker()
        if old_broker:
            positions = old_broker.get_positions()
            if positions:
                logger.warning(f"Cannot switch broker: {len(positions)} open positions")
                return False
        
        self.active_broker_name = broker_name
        logger.info(f"Active broker switched to: {broker_name}")
        return True
    
    def list_brokers(self) -> Dict[str, Dict]:
        """
        List all registered brokers.
        
        Returns:
            Dict mapping broker name to broker info
        """
        result = {}
        for name, broker in self.brokers.items():
            result[name] = {
                'name': broker.name,
                'mode': broker.mode,
                'active': name == self.active_broker_name,
            }
        return result


# Global broker manager instance
_broker_manager: Optional[BrokerManager] = None


def get_broker_manager() -> BrokerManager:
    """Get global broker manager instance."""
    global _broker_manager
    if _broker_manager is None:
        _broker_manager = BrokerManager()
    return _broker_manager
