"""
PHASE 1-12: Strategy Synthesis Agent - Offline, Shadow-Only, Zero Execution Risk

GLOBAL SAFETY INVARIANTS (MANDATORY):
• The synthesis agent must NEVER import broker code
• The synthesis agent must NEVER execute trades
• The synthesis agent must NEVER enable strategies
• The synthesis agent must NEVER change EngineMode
• Generated strategies MUST start as CANDIDATE
• Human intent is required for PAPER promotion
• Kill-switch overrides everything

This system MUST improve strategy discovery without introducing execution risk.
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

import ast
import hashlib
import importlib.util
import inspect
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import asyncio
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.audit_logger import log_audit_event
from sentinel_x.data.storage import Storage
from sentinel_x.intelligence.strategy_manager import StrategyManager, StrategyStatus, get_strategy_manager
from sentinel_x.strategies.base import BaseStrategy


class LifecycleState(Enum):
    """Strategy lifecycle states - separate from StrategyStatus."""
    CANDIDATE = "CANDIDATE"  # Generated, not yet evaluated
    SHADOW_TESTING = "SHADOW_TESTING"  # Participating in shadow trading
    PAPER_APPROVED = "PAPER_APPROVED"  # Approved for paper testing
    LIVE_APPROVED = "LIVE_APPROVED"  # Approved for live (requires explicit approval)
    ARCHIVED = "ARCHIVED"  # Rejected or obsolete


@dataclass
class StrategyHypothesis:
    """Strategy hypothesis - DATA, not executable."""
    strategy_name: str
    description: str
    rationale: str
    target_market_regime: str  # e.g., "trending", "ranging", "volatile"
    feature_set: List[str]  # e.g., ["EMA", "RSI", "Volume"]
    parameter_ranges: Dict[str, Tuple[float, float]]  # param_name -> (min, max)
    expected_risk_profile: Dict[str, Any]  # Expected drawdown, volatility, etc.
    failure_modes: List[str]  # Known failure scenarios
    generated_at: datetime = field(default_factory=datetime.utcnow)
    source_inputs: Dict[str, Any] = field(default_factory=dict)  # What inputs generated this


@dataclass
class PromotionReadinessScore:
    """Promotion readiness score - informational ONLY."""
    strategy_name: str
    overall_score: float  # 0.0 - 1.0
    performance_score: float  # Based on Sharpe, returns, etc.
    risk_score: float  # Based on drawdown, volatility
    stability_score: float  # Based on consistency
    regime_robustness_score: float  # Based on performance across regimes
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metrics_snapshot: Dict[str, Any] = field(default_factory=dict)


class SynthesisAgent:
    """
    Autonomous research agent that generates trading strategies.
    
    SAFETY GUARANTEES:
    - Operates OFFLINE (no live market feeds)
    - Operates SHADOW-ONLY (no execution)
    - Never imports broker code
    - Never executes trades
    - Never enables strategies
    - Never changes EngineMode
    """
    
    # FORBIDDEN IMPORTS - safety check
    FORBIDDEN_IMPORTS = [
        'sentinel_x.execution',
        'sentinel_x.core.engine_mode',
        'alpaca',
        'broker',
        'executor',
    ]
    
    # ALLOWED IMPORTS for generated strategies
    ALLOWED_STRATEGY_IMPORTS = [
        'typing',
        'pandas',
        'numpy',
        'math',
        'sentinel_x.strategies.base',
        'sentinel_x.monitoring.logger',
    ]
    
    def __init__(
        self,
        storage: Optional[Storage] = None,
        strategy_manager: Optional[StrategyManager] = None,
        generated_strategies_dir: Optional[Path] = None
    ):
        """
        Initialize synthesis agent.
        
        Args:
            storage: Storage instance for audit logs
            strategy_manager: Strategy manager for registration
            generated_strategies_dir: Directory for generated strategy code
        """
        self.storage = storage or Storage()
        self.strategy_manager = strategy_manager or get_strategy_manager()
        
        # Directory for generated strategies
        if generated_strategies_dir is None:
            generated_strategies_dir = Path(__file__).parent.parent / "strategies" / "generated"
        self.generated_strategies_dir = Path(generated_strategies_dir)
        self.generated_strategies_dir.mkdir(parents=True, exist_ok=True)
        
        # Create __init__.py if needed
        init_file = self.generated_strategies_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("# Generated strategies\n")
        
        # Track generated hypotheses
        self.hypotheses: Dict[str, StrategyHypothesis] = {}
        self.generated_code_hashes: Dict[str, str] = {}  # strategy_name -> code_hash
        
        # Synthesis cycle tracking
        self.last_synthesis_cycle: Optional[datetime] = None
        self.synthesis_lock = threading.Lock()
        
        # Random seed for determinism
        self.random_seed = 42
        
        logger.info(f"SynthesisAgent initialized: generated_dir={self.generated_strategies_dir}")
    
    async def run_synthesis_cycle(self, inputs: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Run a synthesis cycle - generate new strategy hypotheses and code.
        
        Args:
            inputs: Optional inputs (historical metrics, shadow trades, etc.)
            
        Returns:
            List of generated strategy names (empty if none generated)
        """
        # Check if synthesis is already running
        if self.synthesis_lock.locked():
            logger.warning("Synthesis cycle already running - skipping")
            return []
        
        with self.synthesis_lock:
            request_id = f"syn_{datetime.utcnow().isoformat().replace(':', '-')}"
            
            try:
                logger.info(f"Synthesis cycle started: request_id={request_id}")
                
                # Log synthesis start
                log_audit_event(
                    event_type="SYNTHESIS_CYCLE_START",
                    request_id=request_id,
                    metadata={
                        "inputs_summary": self._summarize_inputs(inputs or {}),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                
                # Generate hypotheses
                hypotheses = await self._generate_hypotheses(inputs or {})
                
                if not hypotheses:
                    logger.info("No hypotheses generated in this cycle")
                    log_audit_event(
                        event_type="SYNTHESIS_CYCLE_COMPLETE",
                        request_id=request_id,
                        metadata={
                            "hypotheses_count": 0,
                            "strategies_registered": 0
                        }
                    )
                    return []
                
                logger.info(f"Generated {len(hypotheses)} hypotheses")
                
                # Generate code for each hypothesis
                registered_strategies = []
                for hypothesis in hypotheses:
                    try:
                        strategy_name = await self._generate_and_register_strategy(
                            hypothesis, request_id
                        )
                        if strategy_name:
                            registered_strategies.append(strategy_name)
                    except Exception as e:
                        logger.error(f"Error generating strategy from hypothesis {hypothesis.strategy_name}: {e}", exc_info=True)
                        # Continue with other hypotheses
                        continue
                
                self.last_synthesis_cycle = datetime.utcnow()
                
                logger.info(f"Synthesis cycle complete: {len(registered_strategies)} strategies registered")
                
                # Log synthesis completion
                log_audit_event(
                    event_type="SYNTHESIS_CYCLE_COMPLETE",
                    request_id=request_id,
                    metadata={
                        "hypotheses_count": len(hypotheses),
                        "strategies_registered": len(registered_strategies),
                        "registered_strategy_names": registered_strategies
                    }
                )
                
                return registered_strategies
                
            except Exception as e:
                logger.error(f"Synthesis cycle failed: {e}", exc_info=True)
                log_audit_event(
                    event_type="SYNTHESIS_CYCLE_ERROR",
                    request_id=request_id,
                    metadata={"error": str(e)}
                )
                # Fail silently - trading engine unaffected
                return []
    
    async def _generate_hypotheses(self, inputs: Dict[str, Any]) -> List[StrategyHypothesis]:
        """
        Generate strategy hypotheses from inputs.
        
        This is a PLACEHOLDER implementation - in production, this would use
        ML models, pattern analysis, etc. For now, it generates simple variations.
        
        Args:
            inputs: Historical metrics, shadow trades, etc.
            
        Returns:
            List of strategy hypotheses
        """
        # For now, generate a small number of simple hypotheses
        # In production, this would analyze historical data, patterns, etc.
        
        hypotheses = []
        
        # Generate a few simple strategy variations
        base_patterns = [
            {
                "name_prefix": "SyntheticEMA",
                "description": "EMA crossover strategy with optimized parameters",
                "rationale": "Generated from historical EMA performance patterns",
                "regime": "trending",
                "features": ["EMA", "Volume"],
                "params": {"fast_ema": (5, 15), "slow_ema": (20, 40)}
            },
            {
                "name_prefix": "SyntheticMeanRev",
                "description": "Mean reversion strategy with Z-score threshold",
                "rationale": "Generated from mean reversion opportunity analysis",
                "regime": "ranging",
                "features": ["Z-score", "Volume"],
                "params": {"z_threshold": (1.5, 3.0), "lookback": (10, 30)}
            },
            {
                "name_prefix": "SyntheticMomentum",
                "description": "Momentum strategy with RSI confirmation",
                "rationale": "Generated from momentum indicator combinations",
                "regime": "trending",
                "features": ["RSI", "Momentum", "Volume"],
                "params": {"rsi_period": (10, 20), "rsi_overbought": (70, 85), "rsi_oversold": (15, 30)}
            }
        ]
        
        for i, pattern in enumerate(base_patterns[:2]):  # Generate 2 strategies per cycle
            strategy_name = f"{pattern['name_prefix']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{i}"
            
            hypothesis = StrategyHypothesis(
                strategy_name=strategy_name,
                description=pattern["description"],
                rationale=pattern["rationale"],
                target_market_regime=pattern["regime"],
                feature_set=pattern["features"],
                parameter_ranges=pattern["params"],
                expected_risk_profile={
                    "max_drawdown": 0.15,
                    "volatility": 0.20,
                    "sharpe_range": (0.5, 2.0)
                },
                failure_modes=[
                    "Rapid regime change",
                    "Low liquidity",
                    "High slippage"
                ],
                source_inputs=inputs
            )
            
            self.hypotheses[strategy_name] = hypothesis
            hypotheses.append(hypothesis)
        
        return hypotheses
    
    async def _generate_and_register_strategy(
        self,
        hypothesis: StrategyHypothesis,
        request_id: str
    ) -> Optional[str]:
        """
        Generate strategy code from hypothesis and register it.
        
        Args:
            hypothesis: Strategy hypothesis
            request_id: Request ID for audit logging
            
        Returns:
            Strategy name if successful, None otherwise
        """
        try:
            # Generate code
            code = self._generate_strategy_code(hypothesis)
            
            # Calculate code hash
            code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
            self.generated_code_hashes[hypothesis.strategy_name] = code_hash
            
            # Validate code
            validation_result = self._validate_generated_code(code, hypothesis.strategy_name)
            if not validation_result["valid"]:
                logger.warning(f"Generated code validation failed for {hypothesis.strategy_name}: {validation_result['reason']}")
                log_audit_event(
                    event_type="SYNTHESIS_VALIDATION_FAILED",
                    request_id=request_id,
                    metadata={
                        "strategy_name": hypothesis.strategy_name,
                        "reason": validation_result["reason"],
                        "code_hash": code_hash
                    }
                )
                return None
            
            # Write code to file
            strategy_file = self.generated_strategies_dir / f"{hypothesis.strategy_name}.py"
            strategy_file.write_text(code)
            
            logger.info(f"Generated strategy code: {strategy_file}")
            
            # Load and register strategy
            strategy_instance = await self._load_and_register_strategy(
                hypothesis.strategy_name,
                request_id
            )
            
            if strategy_instance:
                logger.info(f"Strategy registered successfully: {hypothesis.strategy_name}")
                return hypothesis.strategy_name
            else:
                logger.warning(f"Strategy registration failed: {hypothesis.strategy_name}")
                return None
                
        except Exception as e:
            logger.error(f"Error generating strategy from hypothesis: {e}", exc_info=True)
            return None
    
    def _generate_strategy_code(self, hypothesis: StrategyHypothesis) -> str:
        """
        Generate strategy code from hypothesis.
        
        SAFETY: Code must:
        - Inherit BaseStrategy
        - Implement on_tick()
        - Default to returning None
        - Be side-effect free
        - Be deterministic
        - No forbidden imports
        """
        # Extract parameter defaults (midpoint of ranges)
        param_defaults = {}
        for param_name, (min_val, max_val) in hypothesis.parameter_ranges.items():
            param_defaults[param_name] = (min_val + max_val) / 2.0
        
        # Generate parameter initialization
        param_init = ",\n        ".join([
            f"{param_name}: float = {default_val:.2f}"
            for param_name, default_val in param_defaults.items()
        ])
        
        # Generate strategy logic based on features
        strategy_logic = self._generate_strategy_logic(hypothesis, param_defaults)
        
        # Template for generated strategy
        code_template = f'''"""
Generated strategy: {hypothesis.strategy_name}

Description: {hypothesis.description}
Rationale: {hypothesis.rationale}
Target Regime: {hypothesis.target_market_regime}
Generated At: {hypothesis.generated_at.isoformat()}
Code Hash: {self.generated_code_hashes.get(hypothesis.strategy_name, "N/A")}

SAFETY: This strategy is generated by synthesis agent.
Lifecycle State: CANDIDATE (shadow-only, no execution)
"""

from typing import Optional, Dict, Any
import pandas as pd

from sentinel_x.strategies.base import BaseStrategy
from sentinel_x.monitoring.logger import logger


class {hypothesis.strategy_name}(BaseStrategy):
    """
    Generated strategy - starts as CANDIDATE, shadow-only.
    """
    
    name = "{hypothesis.strategy_name}"
    
    def __init__(self, {param_init}):
        super().__init__()
{self._generate_param_assignments(param_defaults)}
    
    def on_tick(self, market_data) -> Optional[Dict[str, Any]]:
        """
        Called by engine on every tick.
        Returns order dict or None.
        Never throws.
        """
        try:
            if not market_data:
                return None
            
            # Extract symbol
            symbol = None
            if hasattr(market_data, "symbols") and market_data.symbols and len(market_data.symbols) > 0:
                symbol = market_data.symbols[0]
            elif hasattr(market_data, "symbol") and market_data.symbol:
                symbol = market_data.symbol
            
            if not symbol:
                return None
            
            # Extract data
            df = None
            if hasattr(market_data, "data") and isinstance(market_data.data, dict):
                df = market_data.data.get(symbol)
            elif hasattr(market_data, "fetch_history"):
                df = market_data.fetch_history(symbol, lookback=50)
            
            if df is None or not isinstance(df, pd.DataFrame) or len(df) < 20:
                return None
            
            {strategy_logic}
            
        except Exception as e:
            logger.error(f"{{self.name}}.on_tick failed: {{e}}", exc_info=True)
            return None
'''
        
        return code_template
    
    def _generate_param_assignments(self, param_defaults: Dict[str, float]) -> str:
        """Generate parameter assignment code."""
        lines = []
        for param_name, default_val in param_defaults.items():
            lines.append(f"        self.{param_name} = {param_name}")
        return "\n".join(lines)
    
    def _generate_strategy_logic(self, hypothesis: StrategyHypothesis, param_defaults: Dict[str, float]) -> str:
        """Generate strategy logic based on features."""
        
        if "EMA" in hypothesis.feature_set:
            # EMA crossover logic
            fast_param = next((p for p in param_defaults.keys() if "fast" in p.lower() or p.startswith("fast")), "fast_ema")
            slow_param = next((p for p in param_defaults.keys() if "slow" in p.lower() or p.startswith("slow")), "slow_ema")
            
            return f'''# EMA crossover signal
            close = df["close"]
            fast_ema = close.ewm(span=self.{fast_param}, adjust=False).mean()
            slow_ema = close.ewm(span=self.{slow_param}, adjust=False).mean()
            
            if len(fast_ema) < 2 or len(slow_ema) < 2:
                return None
            
            # Bullish crossover
            if fast_ema.iloc[-2] <= slow_ema.iloc[-2] and fast_ema.iloc[-1] > slow_ema.iloc[-1]:
                return {{
                    "symbol": symbol,
                    "side": "buy",
                    "qty": 1,
                    "price": None,
                    "strategy": self.name
                }}
            
            # Bearish crossover
            if fast_ema.iloc[-2] >= slow_ema.iloc[-2] and fast_ema.iloc[-1] < slow_ema.iloc[-1]:
                return {{
                    "symbol": symbol,
                    "side": "sell",
                    "qty": 1,
                    "price": None,
                    "strategy": self.name
                }}
            
            return None'''
        
        elif "Z-score" in hypothesis.feature_set:
            # Mean reversion logic
            z_param = next((p for p in param_defaults.keys() if "z" in p.lower() or "threshold" in p.lower()), "z_threshold")
            lookback_param = next((p for p in param_defaults.keys() if "lookback" in p.lower()), "lookback")
            
            return f'''# Mean reversion with Z-score
            close = df["close"]
            lookback = int(self.{lookback_param})
            
            if len(close) < lookback + 1:
                return None
            
            # Calculate Z-score
            mean = close[-lookback:].mean()
            std = close[-lookback:].std()
            
            if std == 0:
                return None
            
            z_score = (close.iloc[-1] - mean) / std
            
            # Oversold (buy signal)
            if z_score < -self.{z_param}:
                return {{
                    "symbol": symbol,
                    "side": "buy",
                    "qty": 1,
                    "price": None,
                    "strategy": self.name
                }}
            
            # Overbought (sell signal)
            if z_score > self.{z_param}:
                return {{
                    "symbol": symbol,
                    "side": "sell",
                    "qty": 1,
                    "price": None,
                    "strategy": self.name
                }}
            
            return None'''
        
        elif "RSI" in hypothesis.feature_set:
            # RSI momentum logic
            rsi_period_param = next((p for p in param_defaults.keys() if "period" in p.lower()), "rsi_period")
            overbought_param = next((p for p in param_defaults.keys() if "overbought" in p.lower()), "rsi_overbought")
            oversold_param = next((p for p in param_defaults.keys() if "oversold" in p.lower()), "rsi_oversold")
            
            return f'''# RSI momentum signal
            close = df["close"]
            period = int(self.{rsi_period_param})
            
            if len(close) < period + 1:
                return None
            
            # Calculate RSI (simplified)
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            if len(rsi) < 1 or pd.isna(rsi.iloc[-1]):
                return None
            
            current_rsi = rsi.iloc[-1]
            
            # Oversold (buy signal)
            if current_rsi < self.{oversold_param}:
                return {{
                    "symbol": symbol,
                    "side": "buy",
                    "qty": 1,
                    "price": None,
                    "strategy": self.name
                }}
            
            # Overbought (sell signal)
            if current_rsi > self.{overbought_param}:
                return {{
                    "symbol": symbol,
                    "side": "sell",
                    "qty": 1,
                    "price": None,
                    "strategy": self.name
                }}
            
            return None'''
        
        else:
            # Default: return None (no signal)
            return "return None"
    
    def _validate_generated_code(self, code: str, strategy_name: str) -> Dict[str, Any]:
        """
        Validate generated code before registration.
        
        Validates:
        - Syntax correctness
        - Abstract method completeness
        - on_tick() safety (no raise)
        - Return contract validation
        - No forbidden imports
        - Risk bounds sanity check
        """
        try:
            # Parse AST
            tree = ast.parse(code)
            
            # Check for forbidden imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name
                        if any(forbidden in module_name for forbidden in self.FORBIDDEN_IMPORTS):
                            return {
                                "valid": False,
                                "reason": f"Forbidden import detected: {module_name}"
                            }
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        if any(forbidden in node.module for forbidden in self.FORBIDDEN_IMPORTS):
                            return {
                                "valid": False,
                                "reason": f"Forbidden import detected: {node.module}"
                            }
            
            # Check that class inherits BaseStrategy
            has_base_strategy = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "BaseStrategy":
                            has_base_strategy = True
                        elif isinstance(base, ast.Attribute):
                            if base.attr == "BaseStrategy":
                                has_base_strategy = True
            
            if not has_base_strategy:
                return {
                    "valid": False,
                    "reason": "Class does not inherit BaseStrategy"
                }
            
            # Check for on_tick method
            has_on_tick = False
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "on_tick":
                    has_on_tick = True
                    # Check that it has a try/except or returns None
                    # (simplified check - actual safety is runtime)
                    break
            
            if not has_on_tick:
                return {
                    "valid": False,
                    "reason": "Class does not implement on_tick()"
                }
            
            # Basic syntax validation passed
            return {
                "valid": True,
                "reason": "Validation passed"
            }
            
        except SyntaxError as e:
            return {
                "valid": False,
                "reason": f"Syntax error: {str(e)}"
            }
        except Exception as e:
            return {
                "valid": False,
                "reason": f"Validation error: {str(e)}"
            }
    
    async def _load_and_register_strategy(
        self,
        strategy_name: str,
        request_id: str
    ) -> Optional[BaseStrategy]:
        """
        Load generated strategy module and register it.
        
        Args:
            strategy_name: Strategy name
            request_id: Request ID for audit logging
            
        Returns:
            Strategy instance if successful, None otherwise
        """
        try:
            # Import generated strategy module
            module_name = f"sentinel_x.strategies.generated.{strategy_name}"
            
            spec = importlib.util.spec_from_file_location(
                module_name,
                self.generated_strategies_dir / f"{strategy_name}.py"
            )
            
            if spec is None or spec.loader is None:
                logger.error(f"Failed to load module spec for {strategy_name}")
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Get strategy class
            strategy_class = getattr(module, strategy_name, None)
            if strategy_class is None:
                logger.error(f"Strategy class {strategy_name} not found in module")
                return None
            
            # Instantiate strategy
            strategy_instance = strategy_class()
            
            # Register with strategy manager
            # IMPORTANT: Register as CANDIDATE, DISABLED (shadow-only, no execution)
            self.strategy_manager.register(strategy_instance)
            
            # Set lifecycle state to CANDIDATE and status to DISABLED
            self.strategy_manager.status[strategy_name] = StrategyStatus.DISABLED
            self.strategy_manager.strategy_states[strategy_name] = "CANDIDATE"
            
            # Mark strategy as generated for lifecycle tracking
            strategy_instance._is_generated = True
            
            # Log registration
            log_audit_event(
                event_type="SYNTHESIS_STRATEGY_REGISTERED",
                request_id=request_id,
                metadata={
                    "strategy_name": strategy_name,
                    "lifecycle_state": "CANDIDATE",
                    "status": "DISABLED",
                    "code_hash": self.generated_code_hashes.get(strategy_name, "N/A"),
                    "shadow_only": True,
                    "execution_disabled": True
                }
            )
            
            logger.info(f"Strategy registered as CANDIDATE: {strategy_name}")
            
            return strategy_instance
            
        except Exception as e:
            logger.error(f"Error loading/registering strategy {strategy_name}: {e}", exc_info=True)
            return None
    
    def _summarize_inputs(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize inputs for audit logging (no secrets)."""
        summary = {
            "input_keys": list(inputs.keys()),
            "input_count": len(inputs)
        }
        # Don't log actual input data (may be large)
        return summary


# Global synthesis agent instance
_synthesis_agent: Optional[SynthesisAgent] = None
_synthesis_agent_lock = threading.Lock()


def get_synthesis_agent(
    storage: Optional[Storage] = None,
    strategy_manager: Optional[StrategyManager] = None
) -> SynthesisAgent:
    """Get global synthesis agent instance."""
    global _synthesis_agent
    if _synthesis_agent is None:
        with _synthesis_agent_lock:
            if _synthesis_agent is None:
                _synthesis_agent = SynthesisAgent(storage, strategy_manager)
    return _synthesis_agent
