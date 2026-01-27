"""
PHASE 1-2: Strategy Variant Generator

Auto-generation framework that produces parameter variants of existing strategies.

SAFETY: Auto-generation is parameter-only
SAFETY: Training-only
REGRESSION LOCK — STRATEGY VARIANT SYSTEM

Design Principle:
- Operate ONLY on StrategyConfig parameters
- Never generate executable logic
- Never alter signal code
- Never bypass StrategyFactory

Auto-generation explores:
- Lookback windows
- Thresholds
- ATR multiples
- Session filters
- Timeframes (from allowed whitelist)
"""
import random
from typing import Dict, List, Optional, Any
from datetime import datetime
from sentinel_x.monitoring.logger import logger
from sentinel_x.intelligence.models import (
    StrategyConfig,
    StrategyGenome,
    StrategyLifecycleState,
    ALLOWED_TIMEFRAMES
)
from sentinel_x.intelligence.strategy_factory import get_strategy_factory
from sentinel_x.intelligence.governance import get_governance


# SAFETY: Parameter mutation bounds (conservative, bounded)
# PHASE 1: Variants differ in ONLY ONE OR TWO parameters
PARAM_MUTATION_BOUNDS = {
    "momentum": {
        "lookback": (20, 100),
        "entry_params": {
            "fast_ema": (5, 25),
            "slow_ema": (15, 60)
        }
    },
    "mean_reversion": {
        "lookback": (10, 50),
        "entry_params": {
            "entry_z": (1.0, 3.0)
        },
        "exit_params": {
            "exit_z": (0.1, 1.0)
        }
    },
    "breakout": {
        "lookback": (10, 40),  # channel_period
        "entry_params": {
            "channel_period": (10, 40),
            "breakout_threshold": (0.002, 0.03)  # 0.2% to 3%
        }
    },
    "test": {
        "lookback": (5, 20),
        "entry_params": {}
    }
}

# SAFETY: ATR multiple mutation bounds
ATR_BOUNDS = {
    "stop_atr": (1.0, 5.0),
    "take_profit_atr": (2.0, 10.0)
}

# SAFETY: Session options (whitelist)
SESSION_OPTIONS = ["RTH", "ETH", "ALL"]

# PHASE 3: Auto-generation governance limits
MAX_SEED_STRATEGIES = 10  # Max seed strategies to track
MAX_VARIANTS_PER_SEED = 10  # Max variants per seed (enforced)
MAX_TOTAL_STRATEGIES = 100  # Max total strategies (hard cap)


class StrategyVariantGenerator:
    """
    PHASE 2: Strategy Variant Generator
    
    Generates parameter variants of existing strategies.
    
    SAFETY: parameter-only mutation
    SAFETY: training-only
    REGRESSION LOCK — NO LOGIC GENERATION
    
    Rules:
    - Variants differ in ONLY ONE OR TWO parameters
    - No random logic without bounds
    - All variants validated via StrategyConfig rules
    - Max variants per seed enforced (e.g. <= 10)
    - All variants MUST pass through StrategyFactory
    """
    
    def __init__(self, 
                 max_variants_per_seed: int = MAX_VARIANTS_PER_SEED,
                 max_total_strategies: int = MAX_TOTAL_STRATEGIES):
        """
        Initialize variant generator.
        
        Args:
            max_variants_per_seed: Max variants per seed (default: 10)
            max_total_strategies: Max total strategies (default: 100)
        """
        self.max_variants_per_seed = max_variants_per_seed
        self.max_total_strategies = max_total_strategies
        self.factory = get_strategy_factory()
        self.governance = get_governance()
        
        # PHASE 1: Track seed strategies and generated variants
        self.seed_strategies: Dict[str, StrategyConfig] = {}  # seed_name -> config
        self.generated_variants: Dict[str, List[str]] = {}  # seed_name -> [variant_names]
        self.variant_configs: Dict[str, StrategyConfig] = {}  # variant_name -> config
        
        logger.info(f"StrategyVariantGenerator initialized: "
                   f"max_variants_per_seed={max_variants_per_seed}, "
                   f"max_total_strategies={max_total_strategies}")
    
    def register_seed(self, name: str, config: StrategyConfig) -> None:
        """
        PHASE 1: Register a seed strategy for variant generation.
        
        SAFETY: Seed config must be validated.
        
        Args:
            name: Seed strategy name
            config: StrategyConfig (validated)
        """
        try:
            # SAFETY: Validate config
            config.validate()
            
            # PHASE 3: Check seed strategy limit
            if len(self.seed_strategies) >= MAX_SEED_STRATEGIES:
                logger.warning(f"Max seed strategies limit reached ({len(self.seed_strategies)} >= {MAX_SEED_STRATEGIES})")
                return
            
            self.seed_strategies[name] = config
            self.generated_variants[name] = []
            
            logger.info(f"Registered seed strategy: {name} ({config.strategy_type})")
        except Exception as e:
            logger.error(f"Error registering seed strategy {name}: {e}", exc_info=True)
            raise
    
    def generate(self, seed_name: str, max_variants: Optional[int] = None) -> List[StrategyConfig]:
        """
        PHASE 2: Generate bounded parameter variants from seed config.
        
        SAFETY: parameter-only mutation
        SAFETY: training-only
        REGRESSION LOCK — NO LOGIC GENERATION
        
        Rules:
        - Variants differ in ONLY ONE OR TWO parameters
        - No random logic without bounds
        - All variants validated via StrategyConfig rules
        - Max variants per seed enforced
        
        Args:
            seed_name: Seed strategy name
            max_variants: Optional max variants to generate (default: self.max_variants_per_seed)
            
        Returns:
            List of StrategyConfig variants (validated)
        """
        try:
            # Check if seed exists
            if seed_name not in self.seed_strategies:
                logger.error(f"Seed strategy not found: {seed_name}")
                return []
            
            seed_config = self.seed_strategies[seed_name]
            
            # PHASE 3: Check governance limits via governance module
            max_variants = max_variants or self.max_variants_per_seed
            
            # Check variants per seed limit
            current_variants = len(self.generated_variants.get(seed_name, []))
            allowed, violation = self.governance.check_variant_count(seed_name, current_variants + 1)
            if not allowed:
                logger.warning(f"Generation skipped for {seed_name}: {violation}")
                return []
            
            # Check total strategies limit
            total_generated = sum(len(variants) for variants in self.generated_variants.values())
            allowed, violation = self.governance.check_strategy_count(total_generated + 1)
            if not allowed:
                logger.warning(f"Generation skipped: {violation}")
                return []
            
            # PHASE 3: Check seed strategy limit
            seed_count = len(self.seed_strategies)
            allowed, violation = self.governance.check_seed_count(seed_count)
            if not allowed:
                logger.warning(f"Seed strategy limit reached: {violation}")
                # Continue - existing seeds can still generate variants
            
            # PHASE 2: Generate bounded variants (ONLY ONE OR TWO parameters differ)
            variants = []
            strategy_type = seed_config.strategy_type
            
            # Get mutation bounds for this strategy type
            mutation_bounds = PARAM_MUTATION_BOUNDS.get(strategy_type, {})
            if not mutation_bounds:
                logger.warning(f"No mutation bounds defined for strategy type: {strategy_type}")
                return []
            
            # Generate variants (each variant differs in 1-2 parameters)
            variants_to_generate = min(max_variants, self.max_variants_per_seed - current_variants)
            
            for i in range(variants_to_generate):
                try:
                    variant_config = self._mutate_parameters(seed_config, mutation_bounds, strategy_type)
                    if variant_config:
                        variants.append(variant_config)
                except Exception as e:
                    logger.error(f"Error generating variant {i+1} from {seed_name}: {e}", exc_info=True)
                    continue  # Continue with next variant
            
            logger.info(f"Generated {len(variants)} variants from seed {seed_name}")
            return variants
        
        except Exception as e:
            logger.error(f"Error generating variants from {seed_name}: {e}", exc_info=True)
            return []
    
    def _mutate_parameters(self, seed_config: StrategyConfig, 
                          mutation_bounds: Dict[str, Any],
                          strategy_type: str) -> Optional[StrategyConfig]:
        """
        PHASE 2: Mutate parameters ONLY (no logic changes).
        
        SAFETY: Variants differ in ONLY ONE OR TWO parameters
        SAFETY: No random logic without bounds
        SAFETY: All variants validated via StrategyConfig rules
        
        Args:
            seed_config: Seed StrategyConfig
            mutation_bounds: Mutation bounds for strategy type
            strategy_type: Strategy type
            
        Returns:
            Mutated StrategyConfig or None on error
        """
        try:
            # PHASE 2: Variant differs in ONLY ONE OR TWO parameters
            # Select 1-2 parameters to mutate (randomly)
            params_to_mutate = []
            
            # Available parameters to mutate
            available_params = []
            if "lookback" in mutation_bounds:
                available_params.append("lookback")
            if "entry_params" in mutation_bounds and seed_config.entry_params:
                available_params.extend([f"entry_{k}" for k in mutation_bounds["entry_params"].keys() 
                                        if k in seed_config.entry_params])
            if "exit_params" in mutation_bounds and seed_config.exit_params:
                available_params.extend([f"exit_{k}" for k in mutation_bounds["exit_params"].keys() 
                                        if k in seed_config.exit_params])
            if "stop_atr" in ATR_BOUNDS:
                available_params.append("stop_atr")
            if "take_profit_atr" in ATR_BOUNDS:
                available_params.append("take_profit_atr")
            if "session" in SESSION_OPTIONS:
                available_params.append("session")
            
            # Select 1-2 parameters to mutate (bounded)
            num_to_mutate = random.randint(1, min(2, len(available_params)))
            params_to_mutate = random.sample(available_params, num_to_mutate)
            
            # Clone seed config (parameter-only mutation)
            variant_config = StrategyConfig(
                strategy_type=seed_config.strategy_type,
                timeframe=seed_config.timeframe,  # Keep same (no timeframe mutation in this phase)
                lookback=seed_config.lookback,  # Will be mutated if selected
                entry_params=seed_config.entry_params.copy(),
                exit_params=seed_config.exit_params.copy(),
                stop_atr=seed_config.stop_atr,  # Will be mutated if selected
                take_profit_atr=seed_config.take_profit_atr,  # Will be mutated if selected
                session=seed_config.session,  # Will be mutated if selected
                max_trades_per_day=seed_config.max_trades_per_day,
                risk_per_trade=seed_config.risk_per_trade,
                risk_limits=seed_config.risk_limits  # Keep same
            )
            
            # Mutate selected parameters (bounded)
            for param in params_to_mutate:
                if param == "lookback" and "lookback" in mutation_bounds:
                    min_val, max_val = mutation_bounds["lookback"]
                    variant_config.lookback = random.randint(min_val, max_val)
                
                elif param.startswith("entry_"):
                    param_key = param.replace("entry_", "")
                    if param_key in mutation_bounds.get("entry_params", {}):
                        min_val, max_val = mutation_bounds["entry_params"][param_key]
                        if isinstance(min_val, int) and isinstance(max_val, int):
                            variant_config.entry_params[param_key] = random.randint(min_val, max_val)
                        else:
                            variant_config.entry_params[param_key] = random.uniform(min_val, max_val)
                
                elif param.startswith("exit_"):
                    param_key = param.replace("exit_", "")
                    if param_key in mutation_bounds.get("exit_params", {}):
                        min_val, max_val = mutation_bounds["exit_params"][param_key]
                        if isinstance(min_val, int) and isinstance(max_val, int):
                            variant_config.exit_params[param_key] = random.randint(min_val, max_val)
                        else:
                            variant_config.exit_params[param_key] = random.uniform(min_val, max_val)
                
                elif param == "stop_atr" and "stop_atr" in ATR_BOUNDS:
                    min_val, max_val = ATR_BOUNDS["stop_atr"]
                    variant_config.stop_atr = random.uniform(min_val, max_val)
                
                elif param == "take_profit_atr" and "take_profit_atr" in ATR_BOUNDS:
                    min_val, max_val = ATR_BOUNDS["take_profit_atr"]
                    variant_config.take_profit_atr = random.uniform(min_val, max_val)
                
                elif param == "session":
                    # Randomly select session (bounded to whitelist)
                    variant_config.session = random.choice(SESSION_OPTIONS)
            
            # SAFETY: Validate mutated config (all variants validated)
            # PHASE 9: Safety lock - all variants must pass validation
            # REGRESSION LOCK — STRATEGY VARIANT SYSTEM
            variant_config.validate()
            
            return variant_config
        
        except Exception as e:
            logger.error(f"Error mutating parameters: {e}", exc_info=True)
            return None
    
    def generate_and_register(self, seed_name: str, max_variants: Optional[int] = None) -> List[str]:
        """
        PHASE 4: Generate variants and register via StrategyFactory.
        
        Flow:
        Seed StrategyConfig
        → VariantGenerator.generate()
        → StrategyFactory.create()
        → StrategyManager.register(strategy)
        
        SAFETY: All variants MUST pass through StrategyFactory
        SAFETY: All variants are TRAINING-only
        
        Args:
            seed_name: Seed strategy name
            max_variants: Optional max variants to generate
            
        Returns:
            List of variant strategy names (created via factory)
        """
        try:
            # PHASE 2: Generate variants (parameter-only)
            variant_configs = self.generate(seed_name, max_variants)
            if not variant_configs:
                return []
            
            variant_names = []
            
            # PHASE 4: Instantiate each variant via StrategyFactory (ONLY instantiation path)
            for variant_config in variant_configs:
                try:
                    # PHASE 4: Create strategy via factory (hard boundary)
                    variant_name = f"{seed_name}_variant_{len(self.generated_variants.get(seed_name, [])) + 1}"
                    
                    strategy = self.factory.create(variant_config, name=variant_name)
                    if strategy is None:
                        logger.error(f"Factory returned None for variant from {seed_name}")
                        continue
                    
                    # PHASE 5: Ensure TRAINING lifecycle state
                    strategy._lifecycle_state = StrategyLifecycleState.TRAINING
                    
                    # Track variant
                    variant_names.append(variant_name)
                    self.variant_configs[variant_name] = variant_config
                    
                    if seed_name not in self.generated_variants:
                        self.generated_variants[seed_name] = []
                    self.generated_variants[seed_name].append(variant_name)
                    
                    # PHASE 4: Register with StrategyManager (with factory check)
                    # SAFETY: All variants MUST pass through StrategyFactory
                    # REGRESSION LOCK — STRATEGY INSTANTIATION
                    try:
                        from sentinel_x.intelligence.strategy_manager import get_strategy_manager
                        strategy_manager = get_strategy_manager()
                        if strategy_manager:
                            strategy_manager.register(strategy)
                            # PHASE 5: Set lifecycle state to TRAINING
                            # SAFETY: All generated strategies are TRAINING-only
                            # SAFETY: No SHADOW, APPROVED, or LIVE transitions
                            strategy_manager.set_lifecycle_state(variant_name, StrategyLifecycleState.TRAINING)
                            logger.info(f"Generated and registered variant: {variant_name} (TRAINING, via factory)")
                    except Exception as e:
                        logger.error(f"Error registering variant with StrategyManager: {e}", exc_info=True)
                    
                except (RuntimeError, ValueError) as e:
                    logger.error(f"Error creating variant via factory: {e}", exc_info=True)
                    continue  # Continue with next variant
            
            return variant_names
        
        except Exception as e:
            logger.error(f"Error generating and registering variants from {seed_name}: {e}", exc_info=True)
            return []
    
    def list_seeds(self) -> List[str]:
        """List all registered seed strategies."""
        return list(self.seed_strategies.keys())
    
    def list_variants(self, seed_name: str) -> List[str]:
        """List all variants for a seed strategy."""
        return self.generated_variants.get(seed_name, [])
    
    def get_seed_config(self, seed_name: str) -> Optional[StrategyConfig]:
        """Get seed config by name."""
        return self.seed_strategies.get(seed_name)
    
    def get_variant_config(self, variant_name: str) -> Optional[StrategyConfig]:
        """Get variant config by name."""
        return self.variant_configs.get(variant_name)
    
    def get_seed_variant_mapping(self) -> Dict[str, List[str]]:
        """
        PHASE 8: Get seed → variants mapping (for observability).
        
        Returns:
            Dict mapping seed_name -> [variant_names]
        """
        return dict(self.generated_variants)  # Return copy for safety


# Global variant generator instance
_variant_generator: Optional[StrategyVariantGenerator] = None


def get_variant_generator(max_variants_per_seed: int = MAX_VARIANTS_PER_SEED,
                         max_total_strategies: int = MAX_TOTAL_STRATEGIES) -> StrategyVariantGenerator:
    """Get global variant generator instance."""
    global _variant_generator
    if _variant_generator is None:
        _variant_generator = StrategyVariantGenerator(max_variants_per_seed, max_total_strategies)
    return _variant_generator
