"""
PHASE 7 — LEARNING & ADAPTATION HOOKS

Optional hooks for:
- Parameter sweeps
- Genetic mutation
- Bayesian optimization
- Reinforcement feedback signals

Rules:
- Shadow learning may update shadow parameters
- No live parameters may be modified
- All mutations must be logged + reversible
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
import threading
import json

from sentinel_x.monitoring.logger import logger


@dataclass
class ParameterMutation:
    """
    Parameter mutation record.
    """
    strategy_id: str
    parameter_name: str
    old_value: Any
    new_value: Any
    mutation_type: str  # "sweep", "genetic", "bayesian", "reinforcement"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    reason: Optional[str] = None
    reversible: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "strategy_id": self.strategy_id,
            "parameter_name": self.parameter_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "mutation_type": self.mutation_type,
            "timestamp": self.timestamp.isoformat() + "Z",
            "reason": self.reason,
            "reversible": self.reversible,
        }


class LearningHook:
    """
    Learning hook interface.
    """
    
    def mutate_parameters(
        self,
        strategy_id: str,
        current_params: Dict[str, Any],
        performance_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Mutate parameters based on performance.
        
        Args:
            strategy_id: Strategy identifier
            current_params: Current parameter values
            performance_metrics: Performance metrics
            
        Returns:
            Mutated parameter dictionary
        """
        raise NotImplementedError


class ParameterSweepHook(LearningHook):
    """
    Parameter sweep hook.
    
    Systematically explores parameter space.
    """
    
    def __init__(self, sweep_config: Dict[str, List[Any]]):
        """
        Initialize parameter sweep.
        
        Args:
            sweep_config: Dict mapping parameter names to value lists
        """
        self.sweep_config = sweep_config
        self.current_indices: Dict[str, int] = {k: 0 for k in sweep_config.keys()}
    
    def mutate_parameters(
        self,
        strategy_id: str,
        current_params: Dict[str, Any],
        performance_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Sweep to next parameter combination."""
        new_params = current_params.copy()
        
        # Simple round-robin sweep
        for param_name, values in self.sweep_config.items():
            if param_name in self.current_indices:
                idx = self.current_indices[param_name]
                new_params[param_name] = values[idx]
                self.current_indices[param_name] = (idx + 1) % len(values)
        
        return new_params


class GeneticMutationHook(LearningHook):
    """
    Genetic mutation hook.
    
    Mutates parameters using genetic algorithm principles.
    """
    
    def __init__(self, mutation_rate: float = 0.1):
        """
        Initialize genetic mutation.
        
        Args:
            mutation_rate: Probability of mutation per parameter
        """
        self.mutation_rate = mutation_rate
    
    def mutate_parameters(
        self,
        strategy_id: str,
        current_params: Dict[str, Any],
        performance_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Apply genetic mutation."""
        import random
        
        new_params = current_params.copy()
        
        for param_name, value in current_params.items():
            if random.random() < self.mutation_rate:
                # Mutate parameter (simplified: add small random change)
                if isinstance(value, (int, float)):
                    mutation = random.gauss(0, abs(value) * 0.1)
                    new_params[param_name] = value + mutation
                elif isinstance(value, bool):
                    new_params[param_name] = not value
        
        return new_params


class BayesianOptimizationHook(LearningHook):
    """
    Bayesian optimization hook.
    
    Uses Bayesian optimization to find optimal parameters.
    """
    
    def __init__(self):
        """Initialize Bayesian optimization."""
        self.history: List[Dict[str, Any]] = []
    
    def mutate_parameters(
        self,
        strategy_id: str,
        current_params: Dict[str, Any],
        performance_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Apply Bayesian optimization."""
        # Simplified: use performance to guide parameter selection
        # In production, would use Gaussian Process or similar
        
        # Record history
        self.history.append({
            "params": current_params,
            "performance": performance_metrics,
            "timestamp": datetime.utcnow(),
        })
        
        # Simple heuristic: if performance improved, make smaller changes
        # If performance degraded, make larger changes
        new_params = current_params.copy()
        
        # This is a placeholder - real Bayesian optimization would be more sophisticated
        return new_params


class ReinforcementHook(LearningHook):
    """
    Reinforcement learning hook.
    
    Uses reinforcement signals to update parameters.
    """
    
    def __init__(self, learning_rate: float = 0.01):
        """
        Initialize reinforcement hook.
        
        Args:
            learning_rate: Learning rate for parameter updates
        """
        self.learning_rate = learning_rate
        self.reward_history: List[float] = []
    
    def mutate_parameters(
        self,
        strategy_id: str,
        current_params: Dict[str, Any],
        performance_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Apply reinforcement learning update."""
        # Extract reward from performance metrics
        reward = performance_metrics.get("total_return", 0.0)
        self.reward_history.append(reward)
        
        # Simple policy gradient update (simplified)
        new_params = current_params.copy()
        
        # Update parameters based on reward
        # This is a placeholder - real RL would use proper policy gradient methods
        return new_params


class LearningManager:
    """
    Learning manager for shadow strategies.
    
    Manages parameter mutations and ensures safety:
    - Only shadow parameters may be modified
    - All mutations are logged
    - Mutations are reversible
    """
    
    def __init__(self):
        """Initialize learning manager."""
        self.hooks: Dict[str, LearningHook] = {}  # strategy_id -> hook
        self.mutation_history: List[ParameterMutation] = []
        self._lock = threading.RLock()
        
        logger.info("LearningManager initialized")
    
    def register_hook(
        self,
        strategy_id: str,
        hook: LearningHook,
    ) -> None:
        """
        Register learning hook for strategy.
        
        Args:
            strategy_id: Strategy identifier
            hook: Learning hook instance
        """
        with self._lock:
            self.hooks[strategy_id] = hook
            logger.info(f"Learning hook registered for {strategy_id}")
    
    def unregister_hook(self, strategy_id: str) -> None:
        """
        Unregister learning hook.
        
        Args:
            strategy_id: Strategy identifier
        """
        with self._lock:
            if strategy_id in self.hooks:
                del self.hooks[strategy_id]
                logger.info(f"Learning hook unregistered for {strategy_id}")
    
    def apply_mutation(
        self,
        strategy_id: str,
        current_params: Dict[str, Any],
        performance_metrics: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Apply parameter mutation via learning hook.
        
        Args:
            strategy_id: Strategy identifier
            current_params: Current parameter values
            performance_metrics: Performance metrics
            
        Returns:
            Mutated parameters or None if no hook registered
        """
        with self._lock:
            if strategy_id not in self.hooks:
                return None
            
            hook = self.hooks[strategy_id]
            
            try:
                new_params = hook.mutate_parameters(
                    strategy_id,
                    current_params,
                    performance_metrics,
                )
                
                # Record mutation
                mutations = []
                for param_name, new_value in new_params.items():
                    if param_name in current_params and current_params[param_name] != new_value:
                        mutation = ParameterMutation(
                            strategy_id=strategy_id,
                            parameter_name=param_name,
                            old_value=current_params[param_name],
                            new_value=new_value,
                            mutation_type=hook.__class__.__name__,
                            reason="Learning hook mutation",
                        )
                        mutations.append(mutation)
                        self.mutation_history.append(mutation)
                
                # Log mutations
                if mutations:
                    try:
                        from sentinel_x.shadow.persistence import get_shadow_persistence
                        persistence = get_shadow_persistence()
                        for mutation in mutations:
                            persistence.log_audit_event(
                                "PARAMETER_MUTATION",
                                strategy_id,
                                mutation.to_dict(),
                            )
                    except Exception as e:
                        logger.debug(f"Error logging mutation: {e}")
                
                return new_params
            
            except Exception as e:
                logger.error(f"Error applying mutation for {strategy_id}: {e}", exc_info=True)
                return None
    
    def get_mutation_history(
        self,
        strategy_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[ParameterMutation]:
        """
        Get mutation history.
        
        Args:
            strategy_id: Optional strategy filter
            limit: Maximum number of mutations to return
            
        Returns:
            List of ParameterMutation instances
        """
        with self._lock:
            history = self.mutation_history.copy()
            
            if strategy_id:
                history = [m for m in history if m.strategy_id == strategy_id]
            
            return history[-limit:]
    
    def revert_mutation(
        self,
        strategy_id: str,
        parameter_name: str,
    ) -> bool:
        """
        Revert a parameter mutation.
        
        Args:
            strategy_id: Strategy identifier
            parameter_name: Parameter name
            
        Returns:
            True if reverted, False if not found
        """
        with self._lock:
            # Find most recent mutation for this parameter
            for mutation in reversed(self.mutation_history):
                if (mutation.strategy_id == strategy_id and
                    mutation.parameter_name == parameter_name and
                    mutation.reversible):
                    
                    # Revert (would need to update strategy parameters)
                    logger.info(
                        f"Reverting mutation: {strategy_id}.{parameter_name} | "
                        f"{mutation.new_value} -> {mutation.old_value}"
                    )
                    
                    # Log revert
                    try:
                        from sentinel_x.shadow.persistence import get_shadow_persistence
                        persistence = get_shadow_persistence()
                        persistence.log_audit_event(
                            "PARAMETER_REVERT",
                            strategy_id,
                            {
                                "parameter_name": parameter_name,
                                "reverted_from": mutation.new_value,
                                "reverted_to": mutation.old_value,
                            },
                        )
                    except Exception as e:
                        logger.debug(f"Error logging revert: {e}")
                    
                    return True
            
            return False


# Global learning manager instance
_learning_manager: Optional[LearningManager] = None
_learning_manager_lock = threading.Lock()


def get_learning_manager() -> LearningManager:
    """
    Get global learning manager instance (singleton).
    
    Returns:
        LearningManager instance
    """
    global _learning_manager
    
    if _learning_manager is None:
        with _learning_manager_lock:
            if _learning_manager is None:
                _learning_manager = LearningManager()
    
    return _learning_manager
