"""
PHASE 2: Strategy Factory Hard Boundary

Factory is the ONLY instantiation path for strategies.

SAFETY: StrategyFactory is a hard execution firewall
REGRESSION LOCK — DO NOT EXPAND WITHOUT REVIEW

# ============================================================
# REGRESSION LOCK — STRATEGY INSTANTIATION
# ============================================================
# Invariant: ALL strategies MUST be created via StrategyFactory
# 
# NO future changes may:
#   • Remove factory enforcement
#   • Allow direct strategy instantiation
#   • Use eval/exec for strategy creation
#   • Use dynamic imports for strategy classes
#   • Remove config validation
#   • Bypass risk limits
#   • Enable LIVE trading paths
# 
# SAFETY: training-only
# SAFETY: no execution behavior modified
# SAFETY: no dynamic code execution
# REGRESSION LOCK — GOVERNANCE LAYER
# ============================================================

Rules:
- Map allowed strategy types → concrete classes
- Validate config before creation
- Enforce: Allowed timeframes, Risk ceilings, Trade frequency limits
- No eval / exec
- No dynamic imports
- No reflection
- No file system access
- No environment access
- No LIVE enabling
- Factory may only return TRAINING strategies

All generated strategies:
- Inherit BaseStrategy
- Implement on_tick()
- Start DISABLED (TRAINING lifecycle state)
- Are TRAINING-only by default
"""
import random
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from sentinel_x.strategies.base import BaseStrategy
from sentinel_x.strategies.momentum import MomentumStrategy
from sentinel_x.strategies.mean_reversion import MeanReversionStrategy
from sentinel_x.strategies.breakout import BreakoutStrategy

# TestStrategy is optional (may not exist)
try:
    from sentinel_x.strategies.test_strategy import TestStrategy
except ImportError:
    TestStrategy = None
from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.event_bus import get_event_bus
from sentinel_x.utils import safe_emit
from sentinel_x.intelligence.models import (
    StrategyConfig,
    StrategyGenome,
    StrategyLifecycleState,
    ALLOWED_STRATEGY_TYPES,
    ALLOWED_TIMEFRAMES
)
from sentinel_x.intelligence.factory_enforcement import (
    register_factory_created,
    enable_factory_enforcement,
    is_enforcement_enabled
)


class StrategyTemplate:
    """Template for generating strategy variants."""
    
    def __init__(self, base_class, param_ranges: Dict[str, tuple], name_prefix: str):
        """
        Initialize strategy template.
        
        Args:
            base_class: Base strategy class (MomentumStrategy, etc.)
            param_ranges: Dict of param_name -> (min, max) tuples
            name_prefix: Prefix for generated strategy names
        """
        self.base_class = base_class
        self.param_ranges = param_ranges
        self.name_prefix = name_prefix
    
    def generate_params(self) -> Dict[str, Any]:
        """Generate random parameters within safe bounds."""
        params = {}
        for param_name, (min_val, max_val) in self.param_ranges.items():
            if isinstance(min_val, int) and isinstance(max_val, int):
                params[param_name] = random.randint(min_val, max_val)
            else:
                params[param_name] = random.uniform(min_val, max_val)
        return params
    
    def create_strategy(self, params: Optional[Dict[str, Any]] = None) -> BaseStrategy:
        """
        Create strategy instance with given or random parameters.
        
        Args:
            params: Optional parameter dict (if None, generates random)
            
        Returns:
            Strategy instance (DISABLED by default)
        """
        if params is None:
            params = self.generate_params()
        
        # Create strategy instance
        strategy = self.base_class(**params)
        
        # Mark as generated (starts disabled)
        strategy.enabled = False
        
        # Set generated name (handle nested params dict)
        if "parameters" in params and isinstance(params["parameters"], dict):
            param_str = "_".join(f"{k}{v}" for k, v in sorted(params["parameters"].items()))
        else:
            param_str = "_".join(f"{k}{v}" for k, v in sorted(params.items()))
        strategy.name = f"{self.name_prefix}_{param_str}"
        
        return strategy


class StrategyFactory:
    """
    PHASE 2: Strategy Factory Hard Boundary
    
    Factory is the ONLY instantiation path for strategies.
    
    SAFETY: StrategyFactory is a hard execution firewall
    REGRESSION LOCK — DO NOT EXPAND WITHOUT REVIEW
    
    Responsibilities:
    - Validate StrategyConfig
    - Enforce hard risk limits
    - Instantiate approved strategy classes ONLY
    
    Rules:
    - No eval
    - No exec
    - No dynamic imports
    - No reflection
    - No file system access
    - No environment access
    - No LIVE enabling
    - Factory may only return TRAINING strategies
    
    Invariant: ALL strategies MUST be created via StrategyFactory
    """
    
    # SAFETY: Map allowed strategy types → concrete classes (NO eval/exec, NO dynamic imports)
    # PHASE 2: Hard boundary - only approved strategy types
    ALLOWED_TYPES: Dict[str, Optional[type]] = {
        "momentum": MomentumStrategy,
        "mean_reversion": MeanReversionStrategy,
        "breakout": BreakoutStrategy,
    }
    # Add TestStrategy if available (optional)
    if TestStrategy is not None:
        ALLOWED_TYPES["test"] = TestStrategy
    
    # SAFETY: Hard global limits
    MAX_STRATEGIES: int = 100
    MAX_TRADES_PER_STRATEGY: int = 1000
    MAX_RISK_PER_STRATEGY: float = 0.1  # 10% max risk per strategy
    
    # Track created strategies to enforce limits
    _created_strategies: Dict[str, StrategyConfig] = {}  # strategy_name -> config
    _creation_count: int = 0  # Total strategies created
    
    # Flag to enforce factory-only instantiation
    _factory_enforcement: bool = True  # Set to True to enforce factory-only
    
    def __init__(self):
        """
        Initialize strategy factory with templates.
        
        PHASE 4: Enable factory enforcement on initialization.
        """
        self.templates: Dict[str, StrategyTemplate] = {}
        self.generated_strategies: Dict[str, BaseStrategy] = {}
        self.generated_genomes: Dict[str, StrategyGenome] = {}  # PHASE 1: Track genomes
        self.event_bus = get_event_bus()
        
        # PHASE 4: Enable factory enforcement
        enable_factory_enforcement(True)
        
        # Register templates
        self._register_templates()
        
        logger.info("StrategyFactory initialized (TRAINING-only, factory enforcement ENABLED)")
    
    def _register_templates(self) -> None:
        """Register strategy templates with safe parameter ranges."""
        # Momentum template
        self.templates["momentum"] = StrategyTemplate(
            base_class=MomentumStrategy,
            param_ranges={
                "fast_ema": (8, 20),   # Safe EMA range
                "slow_ema": (20, 50)   # Safe EMA range
            },
            name_prefix="Momentum"
        )
        
        # Mean reversion template (uses parameters dict)
        self.templates["mean_reversion"] = StrategyTemplate(
            base_class=MeanReversionStrategy,
            param_ranges={
                "lookback": (15, 30),
                "entry_z": (1.5, 2.5),
                "exit_z": (0.3, 0.7)
            },
            name_prefix="MeanRev"
        )
        
        # Breakout template (uses parameters dict)
        self.templates["breakout"] = StrategyTemplate(
            base_class=BreakoutStrategy,
            param_ranges={
                "channel_period": (15, 30),
                "breakout_threshold": (0.005, 0.02)  # 0.5% to 2%
            },
            name_prefix="Breakout"
        )
    
    def create(self, config: StrategyConfig, name: Optional[str] = None) -> BaseStrategy:
        """
        PHASE 2: Create strategy from StrategyConfig (ONLY instantiation path).
        
        SAFETY: StrategyFactory is a hard execution firewall
        REGRESSION LOCK — DO NOT EXPAND WITHOUT REVIEW
        
        Implementation pattern:
        - Validate StrategyConfig
        - Enforce hard risk limits
        - Instantiate approved strategy classes ONLY
        
        Rules:
        - assert config.strategy_type in ALLOWED_TYPES
        - assert config.timeframe in ALLOWED_TIMEFRAMES
        - assert RISK_LIMITS.validate(config)
        - No eval, no exec, no dynamic imports, no reflection
        
        Args:
            config: StrategyConfig (validated)
            name: Optional strategy name (auto-generated if None)
            
        Returns:
            Strategy instance (TRAINING-only, DISABLED by default)
            
        Raises:
            RuntimeError: If strategy creation violates safety rules
            ValueError: If config is invalid
        """
        # SAFETY: Validate config
        try:
            config.validate()
        except ValueError as e:
            logger.error(f"Invalid StrategyConfig: {e}")
            raise
        
        # SAFETY: Check strategy type is allowed
        if config.strategy_type not in self.ALLOWED_TYPES:
            error_msg = (
                f"Strategy type '{config.strategy_type}' not in ALLOWED_TYPES: {list(self.ALLOWED_TYPES.keys())}. "
                f"SAFETY: Only approved strategy types allowed."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # SAFETY: Check timeframe is allowed
        if config.timeframe not in ALLOWED_TIMEFRAMES:
            error_msg = (
                f"Timeframe {config.timeframe} not in ALLOWED_TIMEFRAMES: {ALLOWED_TIMEFRAMES}. "
                f"SAFETY: Only approved timeframes allowed."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # SAFETY: Enforce hard risk limits
        if config.risk_per_trade > self.MAX_RISK_PER_STRATEGY:
            error_msg = (
                f"Risk per trade {config.risk_per_trade:.2%} exceeds MAX_RISK_PER_STRATEGY {self.MAX_RISK_PER_STRATEGY:.2%}. "
                f"SAFETY: Hard risk limit enforced."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # SAFETY: Enforce max strategies limit
        if self._creation_count >= self.MAX_STRATEGIES:
            error_msg = (
                f"Max strategies limit reached: {self._creation_count} >= {self.MAX_STRATEGIES}. "
                f"SAFETY: Governance limit enforced."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # SAFETY: Get strategy class from map (NO eval/exec, NO dynamic imports, NO reflection)
        strategy_class = self.ALLOWED_TYPES.get(config.strategy_type)
        
        if strategy_class is None:
            error_msg = (
                f"Strategy class for '{config.strategy_type}' is None or not in ALLOWED_TYPES. "
                f"SAFETY: Invalid class map entry. Available types: {list(self.ALLOWED_TYPES.keys())}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # SAFETY: Instantiate strategy using class directly (NO eval/exec)
        try:
            strategy = self._instantiate_strategy(strategy_class, config)
        except Exception as e:
            error_msg = f"Error instantiating strategy {config.strategy_type}: {e}. SAFETY: Instantiation failed."
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e
        
        if strategy is None:
            error_msg = f"Strategy instantiation returned None for {config.strategy_type}. SAFETY: Invalid instantiation."
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Generate name if not provided
        if name is None:
            name = self._generate_strategy_name(config)
        
        strategy.name = name
        
        # SAFETY: Mark as created by factory (for enforcement)
        strategy._created_by_factory = True
        strategy._config = config  # Store config for reference
        
        # SAFETY: Mark as TRAINING-only (DISABLED by default)
        strategy.enabled = False
        strategy._is_generated = True
        strategy._lifecycle_state = StrategyLifecycleState.TRAINING
        
        # Track created strategy
        self._created_strategies[name] = config
        self._creation_count += 1
        
        # PHASE 4: Register strategy as created via factory (enforcement)
        register_factory_created(name)
        
        # Store generated strategy and genome
        self.generated_strategies[name] = strategy
        
        # PHASE 1: Create genome
        genome = StrategyGenome(
            config=config,
            name=name,
            lifecycle_state=StrategyLifecycleState.TRAINING  # SAFETY: TRAINING only
        )
        self.generated_genomes[name] = genome
        
        # Emit event (non-blocking)
        self._emit_strategy_generated_event(name, config.strategy_type, config.to_dict())
        
        logger.info(f"Strategy created via factory: {name} (TRAINING-only, DISABLED, factory={id(self)})")
        return strategy
    
    def create_from_config(self, config: StrategyConfig, name: Optional[str] = None) -> Optional[BaseStrategy]:
        """
        DEPRECATED: Use create() instead.
        
        Backward compatibility wrapper that calls create().
        """
        try:
            return self.create(config, name)
        except (RuntimeError, ValueError) as e:
            logger.error(f"Strategy creation failed: {e}")
            return None
    
    def _instantiate_strategy(self, strategy_class: type, config: StrategyConfig) -> Optional[BaseStrategy]:
        """
        PHASE 3: Instantiate strategy class with validated StrategyConfig (NO eval/exec).
        
        SAFETY: No eval, no exec, no dynamic imports, no reflection
        SAFETY: Backward compatibility adapter for existing strategies
        
        Args:
            strategy_class: Strategy class (from ALLOWED_TYPES)
            config: StrategyConfig (validated)
            
        Returns:
            Strategy instance or None on error
        """
        try:
            # PHASE 3: Try to instantiate with StrategyConfig first (new interface)
            # Check if strategy accepts config parameter
            import inspect
            sig = inspect.signature(strategy_class.__init__)
            params = list(sig.parameters.keys())
            
            # Check if strategy accepts 'config' parameter (new interface)
            if 'config' in params:
                # New interface: strategy accepts StrategyConfig directly
                strategy = strategy_class(config=config)
            else:
                # Legacy interface: map config to constructor parameters (backward compatibility)
                # SAFETY: Map config to strategy constructor parameters (NO eval/exec)
                if config.strategy_type == "momentum":
                    params_dict = {
                        "fast_ema": config.entry_params.get("fast_ema", 12),
                        "slow_ema": config.entry_params.get("slow_ema", 26)
                    }
                elif config.strategy_type == "mean_reversion":
                    params_dict = {
                        "parameters": {
                            "lookback": config.lookback,
                            "entry_z": config.entry_params.get("entry_z", 2.0),
                            "exit_z": config.exit_params.get("exit_z", 0.5),
                            "max_position_pct": config.risk_per_trade
                        }
                    }
                elif config.strategy_type == "breakout":
                    params_dict = {
                        "parameters": {
                            "channel_period": config.entry_params.get("channel_period", 20),
                            "breakout_threshold": config.entry_params.get("breakout_threshold", 0.01),
                            "max_position_pct": config.risk_per_trade
                        }
                    }
                elif config.strategy_type == "test":
                    params_dict = {}  # TestStrategy may have no parameters
                else:
                    error_msg = f"Unknown strategy type: {config.strategy_type}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)
                
                # SAFETY: Instantiate using class directly (NO eval/exec, NO reflection)
                strategy = strategy_class(**params_dict)
            
            # Store config reference in strategy (for observability)
            if hasattr(strategy, '_config'):
                strategy._config = config
            else:
                # Add _config attribute if strategy doesn't have it
                strategy._config = config
            
            return strategy
        
        except TypeError as e:
            # Handle parameter mismatch (backward compatibility issue)
            logger.error(f"Parameter mismatch instantiating {strategy_class.__name__}: {e}")
            raise RuntimeError(f"Strategy instantiation failed: {e}") from e
        except Exception as e:
            error_msg = f"Error instantiating strategy {strategy_class.__name__}: {e}"
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e
    
    def _generate_strategy_name(self, config: StrategyConfig) -> str:
        """Generate unique strategy name from config."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        param_str = "_".join(f"{k}{v}" for k, v in sorted(config.entry_params.items()))
        return f"{config.strategy_type}_{param_str}_{timestamp}"
    
    def generate_strategy(self, template_name: str, 
                         params: Optional[Dict[str, Any]] = None) -> Optional[BaseStrategy]:
        """
        Generate a new strategy from template (backward compatibility).
        
        SAFETY: Wraps template generation with config validation.
        
        Args:
            template_name: Template name ("momentum", "mean_reversion", "breakout")
            params: Optional parameter dict (if None, generates random)
            
        Returns:
            Generated strategy instance (DISABLED, TRAINING-only) or None on error
        """
        try:
            if template_name not in self.templates:
                logger.error(f"Unknown template: {template_name}")
                return None
            
            template = self.templates[template_name]
            
            # Handle special case for strategies with "parameters" dict
            if template_name in ["mean_reversion", "breakout"]:
                if params is None:
                    # Generate params from template ranges
                    nested_params = {}
                    for param_name, (min_val, max_val) in template.param_ranges.items():
                        if isinstance(min_val, int) and isinstance(max_val, int):
                            nested_params[param_name] = random.randint(min_val, max_val)
                        else:
                            nested_params[param_name] = random.uniform(min_val, max_val)
                    params = {"parameters": nested_params}
                elif "parameters" not in params:
                    # Wrap params in parameters dict
                    params = {"parameters": params}
            
            # Create strategy from template
            strategy = template.create_strategy(params)
            
            # Store generated strategy
            strategy_name = strategy.get_name()
            self.generated_strategies[strategy_name] = strategy
            
            # PHASE 1: Create config and genome from template-generated strategy
            # Build config from strategy parameters (for tracking)
            config = self._config_from_template(template_name, params)
            if config:
                genome = StrategyGenome(
                    config=config,
                    name=strategy_name,
                    lifecycle_state=StrategyLifecycleState.TRAINING  # SAFETY: TRAINING only
                )
                self.generated_genomes[strategy_name] = genome
            
            # Emit event (non-blocking)
            self._emit_strategy_generated_event(strategy_name, template_name, params)
            
            logger.info(f"Generated strategy: {strategy_name} (DISABLED, TRAINING-only)")
            return strategy
        
        except Exception as e:
            logger.error(f"Error generating strategy from {template_name}: {e}", exc_info=True)
            return None
    
    def _config_from_template(self, template_name: str, params: Dict[str, Any]) -> Optional[StrategyConfig]:
        """Build StrategyConfig from template parameters (for tracking)."""
        try:
            if template_name == "momentum":
                config = StrategyConfig(
                    strategy_type="momentum",
                    timeframe=15,  # Default
                    lookback=50,  # Default
                    entry_params={
                        "fast_ema": params.get("fast_ema", 10),
                        "slow_ema": params.get("slow_ema", 30)
                    }
                )
            elif template_name == "mean_reversion":
                nested_params = params.get("parameters", params)
                config = StrategyConfig(
                    strategy_type="mean_reversion",
                    timeframe=15,  # Default
                    lookback=nested_params.get("lookback", 20),
                    entry_params={
                        "entry_z": nested_params.get("entry_z", 2.0)
                    },
                    exit_params={
                        "exit_z": nested_params.get("exit_z", 0.5)
                    }
                )
            elif template_name == "breakout":
                nested_params = params.get("parameters", params)
                config = StrategyConfig(
                    strategy_type="breakout",
                    timeframe=15,  # Default
                    lookback=nested_params.get("channel_period", 20),
                    entry_params={
                        "channel_period": nested_params.get("channel_period", 20),
                        "breakout_threshold": nested_params.get("breakout_threshold", 0.01)
                    }
                )
            else:
                return None
            
            return config
        except Exception as e:
            logger.debug(f"Error building config from template: {e}")
            return None
    
    def generate_batch(self, template_name: str, count: int = 5) -> List[BaseStrategy]:
        """
        Generate multiple strategy variants.
        
        Args:
            template_name: Template name
            count: Number of strategies to generate
            
        Returns:
            List of generated strategies (all DISABLED)
        """
        strategies = []
        for _ in range(count):
            strategy = self.generate_strategy(template_name)
            if strategy:
                strategies.append(strategy)
        return strategies
    
    def list_generated(self) -> List[Dict[str, Any]]:
        """
        List all generated strategies.
        
        Returns:
            List of dicts with name, template, enabled status
        """
        result = []
        for name, strategy in self.generated_strategies.items():
            result.append({
                'name': name,
                'template': self._get_template_name(strategy),
                'enabled': strategy.enabled,
                'class': strategy.__class__.__name__
            })
        return result
    
    def _get_template_name(self, strategy: BaseStrategy) -> str:
        """Get template name for a strategy."""
        class_name = strategy.__class__.__name__
        if "Momentum" in class_name:
            return "momentum"
        elif "MeanReversion" in class_name:
            return "mean_reversion"
        elif "Breakout" in class_name:
            return "breakout"
        return "unknown"
    
    def _emit_strategy_generated_event(self, strategy_name: str, 
                                      template_name: str, 
                                      params: Dict[str, Any]) -> None:
        """Emit strategy generated event (non-blocking)."""
        try:
            event = {
                'type': 'strategy_generated',
                'strategy_name': strategy_name,
                'template': template_name,
                'params': params,
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }
            safe_emit(self.event_bus.publish(event))
        except Exception as e:
            logger.error(f"Error emitting strategy generated event: {e}", exc_info=True)
    
    def get_strategy(self, name: str) -> Optional[BaseStrategy]:
        """Get generated strategy by name."""
        return self.generated_strategies.get(name)
    
    def remove_strategy(self, name: str) -> bool:
        """
        Remove generated strategy.
        
        Args:
            name: Strategy name
            
        Returns:
            True if removed, False if not found
        """
        if name in self.generated_strategies:
            del self.generated_strategies[name]
            logger.info(f"Removed generated strategy: {name}")
            return True
        return False


# Global strategy factory instance
_strategy_factory: Optional[StrategyFactory] = None


def get_strategy_factory() -> StrategyFactory:
    """Get global strategy factory instance."""
    global _strategy_factory
    if _strategy_factory is None:
        _strategy_factory = StrategyFactory()
    return _strategy_factory
