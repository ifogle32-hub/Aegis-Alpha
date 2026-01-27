"""
PHASE 3 — STRATEGY REGISTRY & ISOLATION

StrategyRegistry for dynamic registration, isolation, and versioning.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import threading
from collections import defaultdict

from sentinel_x.monitoring.logger import logger
from sentinel_x.strategies.base import BaseStrategy


@dataclass
class StrategyMetadata:
    """
    Strategy metadata and versioning information.
    """
    name: str
    version_hash: str
    registered_at: datetime
    description: Optional[str] = None
    risk_profile: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "name": self.name,
            "version_hash": self.version_hash,
            "registered_at": self.registered_at.isoformat() + "Z",
            "description": self.description,
            "risk_profile": self.risk_profile,
            "config": self.config,
        }


class StrategyRegistry:
    """
    Thread-safe strategy registry with isolation.
    
    Features:
    - Dynamic registration/unregistration
    - Per-strategy isolation (no state bleed)
    - Versioned strategies (hash + metadata)
    - Strategy lifecycle management
    """
    
    def __init__(self):
        """Initialize strategy registry."""
        self._strategies: Dict[str, BaseStrategy] = {}
        self._metadata: Dict[str, StrategyMetadata] = {}
        self._state: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._lock = threading.RLock()
        
        logger.info("StrategyRegistry initialized")
    
    def register(
        self,
        strategy: BaseStrategy,
        description: Optional[str] = None,
        risk_profile: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Register a strategy.
        
        Args:
            strategy: Strategy instance
            description: Optional strategy description
            risk_profile: Optional risk profile dict
            config: Optional strategy configuration
            
        Returns:
            Strategy ID (versioned hash)
        """
        with self._lock:
            name = strategy.name if hasattr(strategy, 'name') else strategy.__class__.__name__
            
            # Generate version hash
            version_hash = self._compute_version_hash(strategy, config)
            strategy_id = f"{name}_{version_hash[:8]}"
            
            # Check if already registered
            if strategy_id in self._strategies:
                logger.warning(f"Strategy {strategy_id} already registered, updating")
            
            # Store strategy
            self._strategies[strategy_id] = strategy
            self._metadata[strategy_id] = StrategyMetadata(
                name=name,
                version_hash=version_hash,
                registered_at=datetime.utcnow(),
                description=description or self._get_strategy_description(strategy),
                risk_profile=risk_profile or self._get_default_risk_profile(),
                config=config,
            )
            
            # Initialize isolated state
            self._state[strategy_id] = {}
            
            logger.info(f"Registered strategy: {strategy_id} (version: {version_hash[:8]})")
            return strategy_id
    
    def unregister(self, strategy_id: str) -> bool:
        """
        Unregister a strategy.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            True if unregistered, False if not found
        """
        with self._lock:
            if strategy_id not in self._strategies:
                logger.warning(f"Strategy {strategy_id} not found for unregistration")
                return False
            
            del self._strategies[strategy_id]
            del self._metadata[strategy_id]
            del self._state[strategy_id]
            
            logger.info(f"Unregistered strategy: {strategy_id}")
            return True
    
    def get_strategy(self, strategy_id: str) -> Optional[BaseStrategy]:
        """
        Get strategy by ID.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            Strategy instance or None
        """
        with self._lock:
            return self._strategies.get(strategy_id)
    
    def get_all_strategies(self) -> Dict[str, BaseStrategy]:
        """
        Get all registered strategies.
        
        Returns:
            Dict mapping strategy_id to strategy instance
        """
        with self._lock:
            return self._strategies.copy()
    
    def get_metadata(self, strategy_id: str) -> Optional[StrategyMetadata]:
        """
        Get strategy metadata.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            StrategyMetadata or None
        """
        with self._lock:
            return self._metadata.get(strategy_id)
    
    def get_state(self, strategy_id: str) -> Dict[str, Any]:
        """
        Get isolated state for strategy.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            State dictionary (empty if not found)
        """
        with self._lock:
            return self._state.get(strategy_id, {}).copy()
    
    def set_state(self, strategy_id: str, key: str, value: Any) -> None:
        """
        Set isolated state for strategy.
        
        Args:
            strategy_id: Strategy identifier
            key: State key
            value: State value
        """
        with self._lock:
            if strategy_id not in self._state:
                self._state[strategy_id] = {}
            self._state[strategy_id][key] = value
    
    def clear_state(self, strategy_id: str) -> None:
        """
        Clear isolated state for strategy.
        
        Args:
            strategy_id: Strategy identifier
        """
        with self._lock:
            if strategy_id in self._state:
                self._state[strategy_id] = {}
    
    def list_strategies(self) -> List[Dict[str, Any]]:
        """
        List all registered strategies with metadata.
        
        Returns:
            List of strategy info dictionaries
        """
        with self._lock:
            return [
                {
                    "strategy_id": strategy_id,
                    **self._metadata[strategy_id].to_dict(),
                }
                for strategy_id in self._strategies.keys()
            ]
    
    def _compute_version_hash(
        self,
        strategy: BaseStrategy,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Compute version hash for strategy.
        
        Args:
            strategy: Strategy instance
            config: Optional configuration
            
        Returns:
            SHA256 hash string
        """
        # Hash based on class name, module, and config
        components = [
            strategy.__class__.__name__,
            strategy.__class__.__module__,
        ]
        
        if config:
            components.append(str(sorted(config.items())))
        
        # Include strategy attributes if available
        if hasattr(strategy, 'name'):
            components.append(str(strategy.name))
        
        hash_input = "|".join(components)
        return hashlib.sha256(hash_input.encode()).hexdigest()
    
    def _get_strategy_description(self, strategy: BaseStrategy) -> str:
        """
        Get strategy description.
        
        Args:
            strategy: Strategy instance
            
        Returns:
            Description string
        """
        if hasattr(strategy, 'describe'):
            try:
                desc = strategy.describe()
                if isinstance(desc, str):
                    return desc
                elif isinstance(desc, dict):
                    return desc.get('description', 'No description')
            except Exception:
                pass
        
        return f"{strategy.__class__.__name__} strategy"
    
    def _get_default_risk_profile(self) -> Dict[str, Any]:
        """Get default risk profile."""
        return {
            "max_position_size": 1.0,
            "max_drawdown": 0.2,
            "risk_per_trade": 0.01,
        }


# Global registry instance
_registry: Optional[StrategyRegistry] = None
_registry_lock = threading.Lock()


def get_strategy_registry() -> StrategyRegistry:
    """
    Get global strategy registry instance (singleton).
    
    Returns:
        StrategyRegistry instance
    """
    global _registry
    
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = StrategyRegistry()
    
    return _registry
