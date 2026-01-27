"""
PHASE 4: Factory Enforcement

Ensure ALL strategy creation routes go through StrategyFactory.

SAFETY: Factory is the ONLY instantiation path
REGRESSION LOCK — DO NOT MODIFY WITHOUT REVIEW

Invariant: ALL strategies MUST be created via StrategyFactory
"""
import sys
import traceback
from typing import Dict, Set
from sentinel_x.monitoring.logger import logger


# PHASE 4: Track factory-created strategies
_factory_created_strategies: Set[str] = set()  # Strategy names created via factory
_factory_enforcement_enabled: bool = True  # Set to True to enforce factory-only


def enable_factory_enforcement(enabled: bool = True) -> None:
    """Enable or disable factory enforcement."""
    global _factory_enforcement_enabled
    _factory_enforcement_enabled = enabled
    logger.info(f"Factory enforcement {'ENABLED' if enabled else 'DISABLED'}")


def register_factory_created(strategy_name: str) -> None:
    """
    PHASE 4: Register strategy as created via factory.
    
    Args:
        strategy_name: Strategy name
    """
    global _factory_created_strategies
    _factory_created_strategies.add(strategy_name)
    logger.debug(f"Registered factory-created strategy: {strategy_name}")


def check_strategy_created_via_factory(strategy_name: str, raise_on_violation: bool = True) -> bool:
    """
    PHASE 4: Check if strategy was created via factory.
    
    Args:
        strategy_name: Strategy name
        raise_on_violation: If True, raise RuntimeError on violation
        
    Returns:
        True if created via factory, False otherwise
        
    Raises:
        RuntimeError: If strategy was not created via factory and raise_on_violation=True
    """
    global _factory_enforcement_enabled, _factory_created_strategies
    
    if not _factory_enforcement_enabled:
        return True  # Enforcement disabled, allow all
    
    if strategy_name in _factory_created_strategies:
        return True  # Created via factory
    
    if raise_on_violation:
        # Get stack trace to identify bypass location
        stack_trace = ''.join(traceback.format_stack()[-5:-1])  # Last 4 frames
        error_msg = (
            f"SAFETY VIOLATION: Strategy '{strategy_name}' was NOT created via StrategyFactory. "
            f"ALL strategies MUST be created via StrategyFactory.create(). "
            f"\nStack trace:\n{stack_trace}"
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    return False


def check_strategy_instance(strategy, raise_on_violation: bool = True) -> bool:
    """
    PHASE 4: Check if strategy instance was created via factory.
    
    Args:
        strategy: Strategy instance
        raise_on_violation: If True, raise RuntimeError on violation (default: True)
        
    Returns:
        True if created via factory, False otherwise
        
    Raises:
        RuntimeError: If strategy was not created via factory and raise_on_violation=True
    """
    global _factory_enforcement_enabled
    
    if not _factory_enforcement_enabled:
        return True  # Enforcement disabled, allow all
    
    # Check if strategy has _created_by_factory marker
    if hasattr(strategy, '_created_by_factory') and strategy._created_by_factory:
        return True
    
    # Check if strategy name is in factory-created set
    strategy_name = getattr(strategy, 'name', None)
    if not strategy_name:
        strategy_name = getattr(strategy, '__class__', type).__name__
    
    if strategy_name:
        return check_strategy_created_via_factory(strategy_name, raise_on_violation=raise_on_violation)
    
    # No marker and no name - likely created outside factory
    if raise_on_violation:
        stack_trace = ''.join(traceback.format_stack()[-5:-1])
        error_msg = (
            f"SAFETY VIOLATION: Strategy instance was NOT created via StrategyFactory. "
            f"Strategy instance missing _created_by_factory marker. "
            f"ALL strategies MUST be created via StrategyFactory.create(). "
            f"\nStack trace:\n{stack_trace}"
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    return False


def get_factory_created_count() -> int:
    """Get count of strategies created via factory."""
    return len(_factory_created_strategies)


def list_factory_created() -> Set[str]:
    """List all strategies created via factory."""
    return _factory_created_strategies.copy()


def is_enforcement_enabled() -> bool:
    """Get factory enforcement enabled status."""
    global _factory_enforcement_enabled
    return _factory_enforcement_enabled


def audit_strategy_creation() -> Dict[str, any]:
    """
    PHASE 4: Audit strategy creation to find bypasses.
    
    Returns:
        Dict with audit results
    """
    return {
        'factory_created_count': len(_factory_created_strategies),
        'factory_created_strategies': list(_factory_created_strategies),
        'enforcement_enabled': _factory_enforcement_enabled
    }
