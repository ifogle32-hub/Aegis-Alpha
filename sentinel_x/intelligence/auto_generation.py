"""
PHASE 3: Auto-Generation (Parameter Variants Only)

Implement auto-generation via parameter variation.

Design:
- Seed strategies defined manually
- Generate variants by mutating parameters ONLY
  (lookbacks, thresholds, ATR multiples, sessions)

Rules:
- No new logic
- No mutation of code
- All variants go through StrategyFactory
- Max variant count enforced

Lifecycle:
- Generated → TRAINING
- Bottom performers disabled
- Top performers retained for scoring

SAFETY: Training-only
SAFETY: No executable logic generation
REGRESSION LOCK — DO NOT EXPAND WITHOUT REVIEW
"""
import random
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from sentinel_x.monitoring.logger import logger
from sentinel_x.intelligence.models import (
    StrategyConfig,
    StrategyGenome,
    StrategyLifecycleState,
    RiskLimits
)
from sentinel_x.intelligence.strategy_factory import get_strategy_factory


# SAFETY: Parameter mutation ranges (conservative)
PARAM_MUTATION_RANGES = {
    "momentum": {
        "fast_ema": (5, 25),
        "slow_ema": (15, 60),
        "lookback": (20, 100)
    },
    "mean_reversion": {
        "lookback": (10, 50),
        "entry_z": (1.0, 3.0),
        "exit_z": (0.1, 1.0)
    },
    "breakout": {
        "channel_period": (10, 40),
        "breakout_threshold": (0.002, 0.03)  # 0.2% to 3%
    }
}

# SAFETY: ATR multiple mutation ranges
ATR_MULTIPLE_RANGES = {
    "stop_atr": (1.0, 5.0),
    "take_profit_atr": (2.0, 10.0)
}

# SAFETY: Session options
SESSION_OPTIONS = ["RTH", "ETH", "ALL"]


class StrategyAutoGenerator:
    """
    PHASE 3: Strategy Auto-Generator
    
    Generates strategy variants by mutating parameters ONLY.
    No new logic, no mutation of code.
    All variants go through StrategyFactory.
    """
    
    def __init__(self, max_variants_per_seed: int = 10, max_total_strategies: int = 100):
        """
        Initialize auto-generator.
        
        Args:
            max_variants_per_seed: Max variants per seed strategy
            max_total_strategies: Max total strategies (governance limit)
        """
        self.max_variants_per_seed = max_variants_per_seed
        self.max_total_strategies = max_total_strategies
        self.factory = get_strategy_factory()
        self.seed_strategies: Dict[str, StrategyConfig] = {}  # seed_name -> config
        self.generated_variants: Dict[str, List[str]] = {}  # seed_name -> [variant_names]
        
        logger.info(f"StrategyAutoGenerator initialized: "
                   f"max_variants_per_seed={max_variants_per_seed}, "
                   f"max_total_strategies={max_total_strategies}")
    
    def register_seed(self, name: str, config: StrategyConfig) -> None:
        """
        Register a seed strategy for variant generation.
        
        SAFETY: Seed config must be validated.
        
        Args:
            name: Seed strategy name
            config: StrategyConfig (validated)
        """
        try:
            # SAFETY: Validate config
            config.validate()
            
            self.seed_strategies[name] = config
            self.generated_variants[name] = []
            
            logger.info(f"Registered seed strategy: {name} ({config.strategy_type})")
        except Exception as e:
            logger.error(f"Error registering seed strategy {name}: {e}", exc_info=True)
            raise
    
    def generate_variant(self, seed_name: str, mutation_factor: float = 0.2) -> Optional[StrategyConfig]:
        """
        PHASE 3: Generate variant by mutating parameters ONLY.
        
        Rules:
        - Mutate lookbacks, thresholds, ATR multiples, sessions
        - No new logic
        - No mutation of code
        - Variant goes through StrategyFactory
        
        Args:
            seed_name: Seed strategy name
            mutation_factor: Mutation factor (0.0 = no mutation, 1.0 = full range)
            
        Returns:
            StrategyConfig for variant or None on error/governance limit
        """
        try:
            # SAFETY: Check if seed exists
            if seed_name not in self.seed_strategies:
                logger.error(f"Seed strategy not found: {seed_name}")
                return None
            
            # SAFETY: Check governance limit - max variants per seed
            if len(self.generated_variants.get(seed_name, [])) >= self.max_variants_per_seed:
                logger.warning(f"Max variants per seed ({self.max_variants_per_seed}) reached for {seed_name}")
                return None
            
            # SAFETY: Check governance limit - max total strategies
            total_generated = sum(len(variants) for variants in self.generated_variants.values())
            if total_generated >= self.max_total_strategies:
                logger.warning(f"Max total strategies ({self.max_total_strategies}) reached")
                return None
            
            seed_config = self.seed_strategies[seed_name]
            
            # PHASE 3: Mutate parameters ONLY (no logic changes)
            variant_config = self._mutate_parameters(seed_config, mutation_factor)
            
            # SAFETY: Validate mutated config
            variant_config.validate()
            
            return variant_config
        
        except Exception as e:
            logger.error(f"Error generating variant from {seed_name}: {e}", exc_info=True)
            return None
    
    def _mutate_parameters(self, seed_config: StrategyConfig, mutation_factor: float) -> StrategyConfig:
        """
        SAFETY: Mutate parameters ONLY (no logic changes).
        
        Args:
            seed_config: Seed StrategyConfig
            mutation_factor: Mutation factor (0.0-1.0)
            
        Returns:
            Mutated StrategyConfig
        """
        # Clone config
        variant_config = StrategyConfig(
            strategy_type=seed_config.strategy_type,
            timeframe=seed_config.timeframe,  # Keep timeframe same (or allow mutation?)
            lookback=self._mutate_lookback(seed_config.lookback, seed_config.strategy_type, mutation_factor),
            entry_params=self._mutate_entry_params(seed_config, mutation_factor),
            exit_params=self._mutate_exit_params(seed_config, mutation_factor),
            stop_atr=self._mutate_atr(seed_config.stop_atr, "stop_atr", mutation_factor),
            take_profit_atr=self._mutate_atr(seed_config.take_profit_atr, "take_profit_atr", mutation_factor),
            session=self._mutate_session(seed_config.session, mutation_factor),
            risk_limits=self._mutate_risk_limits(seed_config.risk_limits, mutation_factor)
        )
        
        return variant_config
    
    def _mutate_lookback(self, lookback: int, strategy_type: str, mutation_factor: float) -> int:
        """Mutate lookback period."""
        if strategy_type in PARAM_MUTATION_RANGES:
            ranges = PARAM_MUTATION_RANGES[strategy_type]
            if "lookback" in ranges:
                min_lookback, max_lookback = ranges["lookback"]
                # Mutate within range
                delta = int((max_lookback - min_lookback) * mutation_factor)
                new_lookback = lookback + random.randint(-delta, delta)
                return max(min_lookback, min(max_lookback, new_lookback))
        # Default: mutate by ±20%
        delta = int(lookback * 0.2 * mutation_factor)
        return max(10, lookback + random.randint(-delta, delta))
    
    def _mutate_entry_params(self, seed_config: StrategyConfig, mutation_factor: float) -> Dict[str, Any]:
        """Mutate entry parameters."""
        strategy_type = seed_config.strategy_type
        entry_params = seed_config.entry_params.copy()
        
        if strategy_type in PARAM_MUTATION_RANGES:
            ranges = PARAM_MUTATION_RANGES[strategy_type]
            for param_name, param_range in ranges.items():
                if param_name == "lookback":
                    continue  # Handled separately
                if param_name in entry_params:
                    min_val, max_val = param_range
                    current_val = entry_params[param_name]
                    # Mutate within range
                    if isinstance(current_val, int):
                        delta = int((max_val - min_val) * mutation_factor)
                        new_val = current_val + random.randint(-delta, delta)
                        entry_params[param_name] = max(min_val, min(max_val, new_val))
                    else:
                        delta = (max_val - min_val) * mutation_factor
                        new_val = current_val + random.uniform(-delta, delta)
                        entry_params[param_name] = max(min_val, min(max_val, new_val))
        
        return entry_params
    
    def _mutate_exit_params(self, seed_config: StrategyConfig, mutation_factor: float) -> Dict[str, Any]:
        """Mutate exit parameters."""
        exit_params = seed_config.exit_params.copy()
        
        # For mean_reversion, mutate exit_z
        if seed_config.strategy_type == "mean_reversion" and "exit_z" in exit_params:
            ranges = PARAM_MUTATION_RANGES.get("mean_reversion", {})
            if "exit_z" in ranges:
                min_val, max_val = ranges["exit_z"]
                current_val = exit_params["exit_z"]
                delta = (max_val - min_val) * mutation_factor
                new_val = current_val + random.uniform(-delta, delta)
                exit_params["exit_z"] = max(min_val, min(max_val, new_val))
        
        return exit_params
    
    def _mutate_atr(self, atr_value: float, atr_type: str, mutation_factor: float) -> float:
        """Mutate ATR multiple."""
        if atr_type in ATR_MULTIPLE_RANGES:
            min_val, max_val = ATR_MULTIPLE_RANGES[atr_type]
            delta = (max_val - min_val) * mutation_factor
            new_val = atr_value + random.uniform(-delta, delta)
            return max(min_val, min(max_val, new_val))
        return atr_value
    
    def _mutate_session(self, session: str, mutation_factor: float) -> str:
        """Mutate trading session."""
        # With low mutation factor, keep same session
        if random.random() > mutation_factor:
            return session
        # Otherwise, randomly select from options
        return random.choice(SESSION_OPTIONS)
    
    def _mutate_risk_limits(self, risk_limits: RiskLimits, mutation_factor: float) -> RiskLimits:
        """Mutate risk limits (conservative)."""
        # SAFETY: Risk limits mutation is conservative (reduce, don't increase)
        new_max_position_size = risk_limits.max_position_size * (1.0 - random.uniform(0, 0.1 * mutation_factor))
        new_max_daily_loss = risk_limits.max_daily_loss * (1.0 - random.uniform(0, 0.1 * mutation_factor))
        new_max_trades = max(1, int(risk_limits.max_trades_per_day * (1.0 - random.uniform(0, 0.1 * mutation_factor))))
        
        return RiskLimits(
            max_position_size=new_max_position_size,
            max_daily_loss=new_max_daily_loss,
            max_trades_per_day=new_max_trades
        )
    
    def generate_and_register_variant(self, seed_name: str, 
                                      mutation_factor: float = 0.2) -> Optional[str]:
        """
        PHASE 3: Generate variant, create strategy, and register.
        
        Lifecycle:
        - Generated → TRAINING
        - Registered with StrategyManager (DISABLED status)
        
        Args:
            seed_name: Seed strategy name
            mutation_factor: Mutation factor (0.0-1.0)
            
        Returns:
            Variant strategy name or None on error
        """
        try:
            # Generate variant config
            variant_config = self.generate_variant(seed_name, mutation_factor)
            if variant_config is None:
                return None
            
            # Create strategy from config (via StrategyFactory)
            strategy = self.factory.create_from_config(variant_config)
            if strategy is None:
                logger.error(f"Failed to create strategy from variant config")
                return None
            
            strategy_name = strategy.get_name()
            
            # Track variant
            if seed_name not in self.generated_variants:
                self.generated_variants[seed_name] = []
            self.generated_variants[seed_name].append(strategy_name)
            
            # Register with StrategyManager (DISABLED, TRAINING lifecycle)
            try:
                from sentinel_x.intelligence.strategy_manager import get_strategy_manager
                strategy_manager = get_strategy_manager()
                if strategy_manager:
                    strategy_manager.register(strategy)
                    # Set lifecycle state to TRAINING
                    strategy_manager.set_lifecycle_state(strategy_name, StrategyLifecycleState.TRAINING)
                    logger.info(f"Generated and registered variant: {strategy_name} (TRAINING, DISABLED)")
            except Exception as e:
                logger.error(f"Error registering variant with StrategyManager: {e}", exc_info=True)
            
            return strategy_name
        
        except Exception as e:
            logger.error(f"Error generating and registering variant from {seed_name}: {e}", exc_info=True)
            return None
    
    def generate_batch(self, seed_name: str, count: int = 5, 
                      mutation_factor: float = 0.2) -> List[str]:
        """
        Generate multiple variants from a seed.
        
        Args:
            seed_name: Seed strategy name
            count: Number of variants to generate
            mutation_factor: Mutation factor (0.0-1.0)
            
        Returns:
            List of variant strategy names
        """
        variants = []
        for _ in range(count):
            variant_name = self.generate_and_register_variant(seed_name, mutation_factor)
            if variant_name:
                variants.append(variant_name)
            else:
                # Hit governance limit or error
                break
        return variants
    
    def list_variants(self, seed_name: str) -> List[str]:
        """List all variants for a seed strategy."""
        return self.generated_variants.get(seed_name, [])


# Global auto-generator instance
_auto_generator: Optional[StrategyAutoGenerator] = None


def get_auto_generator(max_variants_per_seed: int = 10, 
                      max_total_strategies: int = 100) -> StrategyAutoGenerator:
    """Get global auto-generator instance."""
    global _auto_generator
    if _auto_generator is None:
        _auto_generator = StrategyAutoGenerator(max_variants_per_seed, max_total_strategies)
    return _auto_generator
