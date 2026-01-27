"""
Strategy lifecycle management - registration, evaluation, ranking, and pruning.

ENGINE SAFETY LOCK:
- No analytics logic may exist in engine boot path
- No optional arguments in execution-critical functions
- No UI-triggered execution
- All future features must attach via observers
- StrategyManager must be safe to import even if optional components fail
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

# ============================================================
# PHASE 1-9 — STRATEGY LIFECYCLE GOVERNANCE SYSTEM
# ============================================================
# SAFETY: training-only promotion system
# SAFETY: no execution behavior modified
# REGRESSION LOCK — STRATEGY GOVERNANCE
#
# Lifecycle states:
# - TRAINING: Only active state, strategies execute here
# - DISABLED: Strategy is inert but visible
# - SHADOW: Reserved but locked (future-locked placeholder)
# - APPROVED: Reserved but locked (future-locked placeholder)
#
# Rules:
# - Only TRAINING strategies can execute
# - Promotion affects capital_weight and ranking only (remains TRAINING)
# - Demotion sets lifecycle to DISABLED (reversible)
# - No LIVE trading paths enabled
# - All decisions explainable and reversible
# ============================================================

import inspect
from typing import List, Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from collections import deque

# CRITICAL: All imports must be safe - wrap optional imports
try:
    from sentinel_x.strategies.base import BaseStrategy
except Exception:
    BaseStrategy = object  # Fallback for import safety

try:
    from sentinel_x.research.backtester import Trade
except Exception:
    Trade = None

try:
    from sentinel_x.research.metrics import calculate_all_metrics
except Exception:
    calculate_all_metrics = None

try:
    from sentinel_x.data.storage import Storage
except Exception:
    Storage = object  # Fallback

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from sentinel_x.monitoring.event_bus import get_event_bus
except Exception:
    get_event_bus = None

try:
    from sentinel_x.strategies.test_strategy import TestStrategy
except Exception:
    TestStrategy = None

try:
    from sentinel_x.utils import safe_emit
except Exception:
    safe_emit = lambda x: None

try:
    from sentinel_x.intelligence.models import StrategyLifecycleState
except Exception:
    # Fallback if models not available
    class StrategyLifecycleState:
        TRAINING = "TRAINING"
        SHADOW = "SHADOW"
        APPROVED = "APPROVED"
        DISABLED = "DISABLED"

import asyncio


class StrategyStatus(Enum):
    """Strategy status."""
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    AUTO_DISABLED = "AUTO_DISABLED"  # Auto-disabled by rules


@dataclass
class StrategyEvaluation:
    """Strategy evaluation results."""
    strategy_name: str
    symbol: str
    sharpe: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    expectancy: float
    composite_score: float
    total_trades: int
    final_return: float
    timestamp: datetime


class StrategyManager:
    """Manages strategy lifecycle: registration, evaluation, ranking, pruning."""
    
    def __init__(self, storage: Optional[Storage] = None, 
                 max_drawdown_threshold: float = 0.2,  # 20% max drawdown
                 min_expectancy: float = 0.0,
                 top_n: int = 3,  # Promote top N strategies
                 max_consecutive_losses: int = 5,  # Auto-disable after N consecutive losses
                 negative_expectancy_window: int = 10,  # Auto-disable if negative expectancy over N trades
                 # PHASE 2-4: Governance parameters
                 min_trades_for_promotion: int = 20,  # Minimum trades required for promotion consideration
                 promotion_threshold: float = 0.7,  # Minimum composite score for promotion
                 demotion_threshold: float = 0.3,  # Score below which demotion occurs
                 # PHASE 3: Scoring weights (normalized, bounded)
                 score_weight_expectancy: float = 0.35,  # Weight for normalized expectancy
                 score_weight_sharpe: float = 0.25,  # Weight for normalized Sharpe
                 score_weight_win_rate: float = 0.25,  # Weight for win rate
                 score_weight_drawdown_penalty: float = 0.15,  # Penalty weight for max drawdown
                 # PHASE 6: Governance limits
                 max_active_strategies: int = 10,  # Maximum TRAINING strategies
                 max_disabled_strategies: int = 50,  # Maximum DISABLED strategies (soft limit)
                 max_total_strategies: int = 100):  # Hard cap on total strategies
        """
        Initialize strategy manager with lifecycle governance.
        
        SAFETY: training-only promotion system
        SAFETY: no execution behavior modified
        REGRESSION LOCK — STRATEGY GOVERNANCE
        
        Args:
            storage: Storage instance for persistence
            max_drawdown_threshold: Maximum allowed drawdown (0.2 = 20%)
            min_expectancy: Minimum required expectancy
            top_n: Number of top strategies to promote
            max_consecutive_losses: Auto-disable after N consecutive losses
            negative_expectancy_window: Auto-disable if negative expectancy over N trades
            min_trades_for_promotion: Minimum trades required for promotion (PHASE 2)
            promotion_threshold: Minimum composite score for promotion (PHASE 4)
            demotion_threshold: Score below which demotion occurs (PHASE 5)
            score_weight_expectancy: Weight for normalized expectancy in composite score (PHASE 3)
            score_weight_sharpe: Weight for normalized Sharpe in composite score (PHASE 3)
            score_weight_win_rate: Weight for win rate in composite score (PHASE 3)
            score_weight_drawdown_penalty: Penalty weight for max drawdown (PHASE 3)
            max_active_strategies: Maximum TRAINING strategies allowed (PHASE 6)
            max_disabled_strategies: Maximum DISABLED strategies (soft limit) (PHASE 6)
            max_total_strategies: Hard cap on total strategies (PHASE 6)
        """
        self.storage = storage or Storage()
        self.max_drawdown_threshold = max_drawdown_threshold
        self.min_expectancy = min_expectancy
        self.top_n = top_n
        self.max_consecutive_losses = max_consecutive_losses
        self.negative_expectancy_window = negative_expectancy_window
        
        # PHASE 2-4: Governance parameters
        self.min_trades_for_promotion = min_trades_for_promotion
        self.promotion_threshold = promotion_threshold
        self.demotion_threshold = demotion_threshold
        
        # PHASE 3: Scoring weights (bounded and validated)
        self.score_weight_expectancy = max(0.0, min(1.0, score_weight_expectancy))
        self.score_weight_sharpe = max(0.0, min(1.0, score_weight_sharpe))
        self.score_weight_win_rate = max(0.0, min(1.0, score_weight_win_rate))
        self.score_weight_drawdown_penalty = max(0.0, min(1.0, score_weight_drawdown_penalty))
        # Normalize weights to sum to 1.0
        total_weight = (self.score_weight_expectancy + self.score_weight_sharpe + 
                       self.score_weight_win_rate + self.score_weight_drawdown_penalty)
        if total_weight > 0:
            self.score_weight_expectancy /= total_weight
            self.score_weight_sharpe /= total_weight
            self.score_weight_win_rate /= total_weight
            self.score_weight_drawdown_penalty /= total_weight
        
        # PHASE 6: Governance limits
        self.max_active_strategies = max(1, max_active_strategies)
        self.max_disabled_strategies = max(0, max_disabled_strategies)
        self.max_total_strategies = max(1, max_total_strategies)
        
        self.strategies: Dict[str, BaseStrategy] = {}
        self.evaluations: Dict[str, StrategyEvaluation] = {}
        self.status: Dict[str, StrategyStatus] = {}
        
        # PHASE 1: Lifecycle states for strategies (enum-based, TRAINING only active)
        # SAFETY: lifecycle governs participation, not execution code
        # REGRESSION LOCK — LIFECYCLE STATES
        self.strategy_states: Dict[str, StrategyLifecycleState] = {}  # strategy -> lifecycle state enum
        self.promotion_scores: Dict[str, Dict[str, Any]] = {}  # strategy -> promotion readiness score
        
        # PHASE 2: Normalized metrics storage
        self.normalized_metrics: Dict[str, Dict[str, Any]] = {}  # strategy -> normalized metrics
        
        # PHASE 3: Rolling performance stats per strategy
        self.rolling_pnl: Dict[str, deque] = {}  # strategy -> deque of PnL values
        self.rolling_trades: Dict[str, deque] = {}  # strategy -> deque of trade results
        self.consecutive_losses: Dict[str, int] = {}  # strategy -> consecutive loss count
        self.last_disable_reason: Dict[str, str] = {}  # strategy -> reason for auto-disable
        
        # PHASE 7: Audit trail for lifecycle transitions
        self.lifecycle_history: Dict[str, List[Dict[str, Any]]] = {}  # strategy -> list of transitions
        self.capital_weights: Dict[str, float] = {}  # strategy -> capital weight (0.0-1.0)
        self.strategy_rankings: List[str] = []  # Ordered list by ranking (highest first)
        
        # PHASE 8: Backtest metrics storage (advisory only, offline)
        # SAFETY: backtest metrics are advisory only
        # SAFETY: promotion logic remains training-only
        self.backtest_metrics: Dict[str, Dict[str, Any]] = {}  # strategy -> backtest metrics
        
        # CRITICAL: Event bus must NOT block boot
        try:
            self.event_bus = get_event_bus() if get_event_bus else None
        except Exception:
            self.event_bus = None
        
        # CRITICAL: Storage operations must NOT block boot
        try:
            self._load_status_from_storage()
        except Exception as e:
            logger.error(f"Error loading status from storage (non-fatal): {e}", exc_info=True)
        
        # CRITICAL: Built-in strategy registration must NOT block boot
        try:
            self.register_builtin_strategies()
        except Exception as e:
            logger.error(f"Error registering built-in strategies (non-fatal): {e}", exc_info=True)

        logger.info(f"StrategyManager initialized: max_dd={max_drawdown_threshold}, "
                   f"min_expectancy={min_expectancy}, top_n={top_n}, "
                   f"max_consecutive_losses={max_consecutive_losses}, "
                   f"negative_expectancy_window={negative_expectancy_window}, "
                   f"min_trades_for_promotion={self.min_trades_for_promotion}, "
                   f"promotion_threshold={self.promotion_threshold}, "
                   f"demotion_threshold={self.demotion_threshold}, "
                   f"max_active_strategies={self.max_active_strategies}, "
                   f"max_disabled_strategies={self.max_disabled_strategies}, "
                   f"max_total_strategies={self.max_total_strategies}")
    
    def register(self, strategy: BaseStrategy) -> None:
        """
        PHASE 4: Register a strategy (with factory enforcement check).
        
        SAFETY: All strategies MUST be created via StrategyFactory
        REGRESSION LOCK — STRATEGY INSTANTIATION
        
        Never throws - logs errors and skips broken strategies.
        
        Args:
            strategy: Strategy instance to register
        """
        try:
            # PHASE 4: Check if strategy was created via factory (enforcement)
            try:
                from sentinel_x.intelligence.factory_enforcement import (
                    check_strategy_instance,
                    is_enforcement_enabled
                )
                
                # Check factory enforcement (non-blocking, logs warning if violation)
                # SAFETY: During transition period, allow registration but mark for audit
                # In strict mode, this would prevent registration
                enforcement_enabled = is_enforcement_enabled()
                
                if enforcement_enabled:
                    try:
                        check_strategy_instance(strategy, raise_on_violation=False)  # Non-blocking check
                    except RuntimeError as e:
                        # Log violation but allow registration (backward compatibility during transition)
                        logger.warning(f"SAFETY WARNING: Strategy {strategy.__class__.__name__} may not have been created via factory: {e}")
                        # Mark for audit
                        if not hasattr(strategy, '_created_by_factory'):
                            strategy._factory_enforcement_bypassed = True
                    
                    # Check if strategy was not created via factory
                    if not hasattr(strategy, '_created_by_factory'):
                        # Allow registration but mark as bypassed (backward compatibility)
                        if not hasattr(strategy, '_factory_enforcement_bypassed'):
                            strategy._factory_enforcement_bypassed = True
                            logger.debug(f"Strategy {strategy.__class__.__name__} marked as factory-bypassed (backward compatibility)")
            except ImportError:
                # Factory enforcement not available, skip check
                logger.debug("Factory enforcement module not available, skipping check")
            except Exception as e:
                logger.debug(f"Error checking factory enforcement (non-fatal): {e}")
            
            # Guard: Check if class is abstract (prevent abstract instantiation)
            if inspect.isabstract(strategy.__class__):
                raise TypeError(f"Cannot register abstract strategy class: {strategy.__class__.__name__}")
            
            # Guard: Ensure strategy has on_tick method and it's callable
            if not hasattr(strategy, 'on_tick') or not callable(getattr(strategy, 'on_tick', None)):
                raise TypeError(f"Cannot register strategy without on_tick(): {strategy.__class__.__name__}")
            
            # Guard: Ensure safe_on_tick exists (from BaseStrategy)
            if not hasattr(strategy, 'safe_on_tick') or not callable(getattr(strategy, 'safe_on_tick', None)):
                raise TypeError(f"Cannot register strategy without safe_on_tick(): {strategy.__class__.__name__}")
            
            name = getattr(strategy, "name", strategy.__class__.__name__)
            
            # PHASE 6: Check governance limits (total strategies)
            if len(self.strategies) >= self.max_total_strategies:
                logger.warning(f"Max total strategies limit reached ({len(self.strategies)} >= {self.max_total_strategies}), "
                             f"but registering {name} anyway (governance limit is soft)")
            
            self.strategies[name] = strategy
            
            # PHASE 4: Initialize lifecycle state
            # TRAINING is the only active state
            # SHADOW/APPROVED are future-locked placeholders only
            if name not in self.status:
                # Check if this is a generated strategy (by name pattern or metadata)
                is_generated = name.startswith("Synthetic") or hasattr(strategy, "_is_generated")
                if is_generated:
                    # Generated strategies start as TRAINING, DISABLED
                    self.status[name] = StrategyStatus.DISABLED
                    self.strategy_states[name] = StrategyLifecycleState.TRAINING
                else:
                    # Built-in strategies start as TRAINING, ACTIVE (if enabled)
                    self.status[name] = StrategyStatus.ACTIVE
                    self.strategy_states[name] = StrategyLifecycleState.TRAINING
            elif name not in self.strategy_states:
                # Set default lifecycle state for existing strategies (TRAINING)
                self.strategy_states[name] = StrategyLifecycleState.TRAINING
            
            # Initialize rolling stats
            if name not in self.rolling_pnl:
                self.rolling_pnl[name] = deque(maxlen=1000)
            if name not in self.rolling_trades:
                self.rolling_trades[name] = deque(maxlen=1000)
            if name not in self.consecutive_losses:
                self.consecutive_losses[name] = 0
            
            lifecycle = self.strategy_states.get(name, StrategyLifecycleState.TRAINING)
            logger.info(f"Strategy registered: {name} (status: {self.status[name].value}, lifecycle: {lifecycle.value})")
            
            # PHASE 1: Initialize capital weight for new strategies (equal weight initially)
            if name not in self.capital_weights:
                self.capital_weights[name] = 0.0  # Will be set by allocator
            
            # PHASE 7: Initialize lifecycle history
            if name not in self.lifecycle_history:
                self.lifecycle_history[name] = [{
                    'from': None,
                    'to': lifecycle.value,
                    'reason': 'initial_registration',
                    'timestamp': datetime.now().isoformat()
                }]
        except Exception as e:
            logger.error(f"Strategy registration failed for {strategy.__class__.__name__}: {e}", exc_info=True)
            # Re-raise to allow caller to handle, but log first
            raise

    def register_builtin_strategies(self) -> None:
        """
        PHASE 4: Register built-in strategies (with factory enforcement).
        
        SAFETY: Attempts to use factory first, falls back to direct instantiation for backward compatibility
        REGRESSION LOCK — STRATEGY INSTANTIATION
        
        Note: main.py now creates strategies via factory, so this method is mainly for TestStrategy
        """
        try:
            # PHASE 4: Try to create TestStrategy via factory first
            try:
                from sentinel_x.intelligence.strategy_factory import get_strategy_factory
                from sentinel_x.intelligence.models import StrategyConfig
                
                factory = get_strategy_factory()
                
                # Create TestStrategy config
                test_config = StrategyConfig(
                    strategy_type="test",
                    timeframe=15,
                    lookback=10,
                    entry_params={},
                    exit_params={}
                )
                
                # Create via factory
                test_strategy = factory.create(test_config, name="TestStrategy")
                if test_strategy:
                    self.register(test_strategy)
                    logger.info("TestStrategy registered via factory")
                    return
            except (RuntimeError, ValueError, ImportError) as e:
                logger.debug(f"Failed to create TestStrategy via factory (non-fatal): {e}, falling back to direct instantiation")
                # Fallback to direct instantiation for backward compatibility
            
            # Fallback: Direct instantiation (backward compatibility)
            # Guard: Check if TestStrategy is abstract before instantiation
            if inspect.isabstract(TestStrategy):
                logger.error("TestStrategy is abstract - cannot instantiate")
                return
            
            # Guard: Verify TestStrategy has on_tick before instantiation
            if not hasattr(TestStrategy, 'on_tick') or not callable(getattr(TestStrategy, 'on_tick', None)):
                logger.error("TestStrategy missing on_tick() - cannot instantiate")
                return
            
            # PHASE 4: Direct instantiation (backward compatibility only)
            # Mark as factory-bypassed for audit
            test_strategy = TestStrategy()
            test_strategy._factory_enforcement_bypassed = True  # Mark for audit
            self.register(test_strategy)
            logger.warning("TestStrategy registered via direct instantiation (factory bypass - backward compatibility)")
        except Exception as e:
            logger.error(f"Failed to register TestStrategy: {e}", exc_info=True)
            # Continue boot even if TestStrategy fails

    def activate_only(self, strategy_name: str) -> None:
        """
        Activate only one strategy, disabling all others.
        Never throws - logs errors and continues.
        """
        try:
            if strategy_name not in self.strategies:
                raise ValueError(f"Strategy not found: {strategy_name}")

            # Disable all strategies
            for name in self.status.keys():
                self.status[name] = StrategyStatus.DISABLED
                try:
                    if hasattr(self.storage, 'update_strategy_status'):
                        self.storage.update_strategy_status(name, StrategyStatus.DISABLED.value)
                except Exception as e:
                    logger.warning(f"Failed to persist disabled status for {name}: {e}")

            # Activate target strategy
            self.status[strategy_name] = StrategyStatus.ACTIVE
            try:
                if hasattr(self.storage, 'update_strategy_status'):
                    self.storage.update_strategy_status(strategy_name, StrategyStatus.ACTIVE.value)
            except Exception as e:
                logger.warning(f"Failed to persist active status for {strategy_name}: {e}")
            
            logger.info(f"Strategy activated exclusively: {strategy_name}")
        except Exception as e:
            logger.error(f"Error in activate_only({strategy_name}): {e}", exc_info=True)
            # Re-raise to allow caller to handle, but log first
            raise
    
    def evaluate(self, strategy: BaseStrategy, symbol: str, 
                 backtest_result: Dict[str, Any]) -> StrategyEvaluation:
        """
        PHASE 3: Evaluate a strategy based on backtest results (with execution quality).
        
        Args:
            strategy: Strategy instance
            symbol: Trading symbol
            backtest_result: Result from backtester
            
        Returns:
            StrategyEvaluation object
        """
        returns = backtest_result['returns']
        equity_curve = backtest_result['equity_curve']
        trades = backtest_result['trades']
        
        # PHASE 3: Get execution quality score for strategy
        execution_quality_score = None
        try:
            from sentinel_x.execution.execution_metrics import get_execution_metrics_tracker
            metrics_tracker = get_execution_metrics_tracker()
            execution_metrics = metrics_tracker.get_latest_metrics(strategy.get_name())
            if execution_metrics:
                execution_quality_score = execution_metrics.execution_quality_score
        except Exception as e:
            logger.debug(f"Error getting execution quality score (non-fatal): {e}")
        
        # Calculate metrics (with execution quality)
        metrics = calculate_all_metrics(returns, equity_curve, trades, execution_quality_score)
        
        evaluation = StrategyEvaluation(
            strategy_name=strategy.get_name(),
            symbol=symbol,
            sharpe=metrics['sharpe'],
            max_drawdown=metrics['max_drawdown'],
            win_rate=metrics['win_rate'],
            profit_factor=metrics['profit_factor'],
            expectancy=metrics['expectancy'],
            composite_score=metrics['composite_score'],
            total_trades=metrics['total_trades'],
            final_return=metrics['final_return'],
            timestamp=datetime.now()
        )
        
        # Store evaluation
        key = f"{strategy.get_name()}_{symbol}"
        self.evaluations[key] = evaluation
        
        # Persist to storage
        try:
            if hasattr(self.storage, 'save_backtest'):
                self.storage.save_backtest(
                    strategy=strategy.get_name(),
                    symbol=symbol,
                    sharpe=evaluation.sharpe,
                    drawdown=evaluation.max_drawdown,
                    expectancy=evaluation.expectancy,
                    score=evaluation.composite_score,
                    timestamp=evaluation.timestamp
                )
        except Exception as e:
            logger.warning(f"Failed to persist backtest for {strategy.get_name()}: {e}")
        
        logger.debug(f"Evaluated {strategy.get_name()} on {symbol}: "
                    f"score={evaluation.composite_score:.4f}, "
                    f"sharpe={evaluation.sharpe:.4f}, "
                    f"dd={evaluation.max_drawdown:.4f}")
        
        return evaluation
    
    def rank_strategies(self) -> List[tuple]:
        """
        Rank strategies by composite score.
        
        Returns:
            List of tuples: (strategy_name, composite_score, evaluation)
            Sorted by score (highest first)
        """
        # Aggregate scores per strategy (average across symbols)
        strategy_scores: Dict[str, List[float]] = {}
        
        for key, evaluation in self.evaluations.items():
            strategy_name = evaluation.strategy_name
            if strategy_name not in strategy_scores:
                strategy_scores[strategy_name] = []
            strategy_scores[strategy_name].append(evaluation.composite_score)
        
        # Calculate average score per strategy
        rankings = []
        for strategy_name, scores in strategy_scores.items():
            avg_score = sum(scores) / len(scores) if scores else 0.0
            # Get latest evaluation for this strategy
            latest_eval = None
            for key, eval_obj in self.evaluations.items():
                if eval_obj.strategy_name == strategy_name:
                    if latest_eval is None or eval_obj.timestamp > latest_eval.timestamp:
                        latest_eval = eval_obj
            rankings.append((strategy_name, avg_score, latest_eval))
        
        # Sort by score (descending)
        rankings.sort(key=lambda x: x[1], reverse=True)
        
        return rankings
    
    def prune(self) -> List[str]:
        """
        Disable strategies that fail criteria.
        
        Criteria for disabling:
        - expectancy <= min_expectancy
        - max_drawdown > threshold
        
        Returns:
            List of strategy names that were disabled
        """
        disabled = []
        
        for key, evaluation in self.evaluations.items():
            strategy_name = evaluation.strategy_name
            
            # Check if should be disabled
            should_disable = False
            reason = []
            
            if evaluation.expectancy <= self.min_expectancy:
                should_disable = True
                reason.append(f"expectancy={evaluation.expectancy:.4f} <= {self.min_expectancy}")
            
            if evaluation.max_drawdown > self.max_drawdown_threshold:
                should_disable = True
                reason.append(f"drawdown={evaluation.max_drawdown:.4f} > {self.max_drawdown_threshold}")
            
            if should_disable and self.status.get(strategy_name) == StrategyStatus.ACTIVE:
                self.status[strategy_name] = StrategyStatus.DISABLED
                disabled.append(strategy_name)
                logger.warning(f"Strategy disabled: {strategy_name} - {', '.join(reason)}")
                
                # Persist status change
                try:
                    if hasattr(self.storage, 'update_strategy_status'):
                        self.storage.update_strategy_status(strategy_name, StrategyStatus.DISABLED.value)
                except Exception as e:
                    logger.warning(f"Failed to persist disabled status for {strategy_name}: {e}")
        
        return disabled
    
    def promote_top_n(self) -> List[str]:
        """
        PHASE 5: Promote top N strategies to ACTIVE status (TRAINING only).
        
        SAFETY: Only TRAINING lifecycle strategies can be promoted
        SAFETY: Promotions affect TRAINING only (no LIVE implications)
        
        Returns:
            List of strategy names that were promoted
        """
        rankings = self.rank_strategies()
        
        # Get top N strategies
        top_strategies = rankings[:self.top_n]
        
        promoted = []
        for strategy_name, score, evaluation in top_strategies:
            # SAFETY: Only promote TRAINING lifecycle strategies
            lifecycle_state = self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
            if lifecycle_state != StrategyLifecycleState.TRAINING:
                logger.debug(f"Skipping promotion of {strategy_name} (lifecycle={lifecycle_state.value}, TRAINING only)")
                continue
            
            if self.status.get(strategy_name) == StrategyStatus.DISABLED:
                self.status[strategy_name] = StrategyStatus.ACTIVE
                promoted.append(strategy_name)
                logger.info(f"Strategy promoted (TRAINING): {strategy_name} (score={score:.4f})")
                
                # Persist status change
                try:
                    if hasattr(self.storage, 'update_strategy_status'):
                        self.storage.update_strategy_status(strategy_name, StrategyStatus.ACTIVE.value)
                except Exception as e:
                    logger.warning(f"Failed to persist active status for {strategy_name}: {e}")
        
        return promoted
    
    def promote_top_percent(self, top_percent: float = 0.2) -> List[str]:
        """
        PHASE 5: Promote top X% strategies to ACTIVE status (TRAINING only).
        
        SAFETY: Only TRAINING lifecycle strategies can be promoted
        SAFETY: Promotions affect TRAINING only (no LIVE implications)
        
        Args:
            top_percent: Top percentage to promote (0.0-1.0, default 0.2 = 20%)
            
        Returns:
            List of strategy names that were promoted
        """
        rankings = self.rank_strategies()
        
        if not rankings:
            return []
        
        # Calculate number of strategies to promote (top X%)
        num_to_promote = max(1, int(len(rankings) * top_percent))
        top_strategies = rankings[:num_to_promote]
        
        promoted = []
        for strategy_name, score, evaluation in top_strategies:
            # SAFETY: Only promote TRAINING lifecycle strategies
            lifecycle_state = self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
            if lifecycle_state != StrategyLifecycleState.TRAINING:
                logger.debug(f"Skipping promotion of {strategy_name} (lifecycle={lifecycle_state.value}, TRAINING only)")
                continue
            
            if self.status.get(strategy_name) == StrategyStatus.DISABLED:
                self.status[strategy_name] = StrategyStatus.ACTIVE
                promoted.append(strategy_name)
                logger.info(f"Strategy promoted (TRAINING, top {top_percent:.1%}): {strategy_name} (score={score:.4f})")
                
                # Persist status change
                try:
                    if hasattr(self.storage, 'update_strategy_status'):
                        self.storage.update_strategy_status(strategy_name, StrategyStatus.ACTIVE.value)
                except Exception as e:
                    logger.warning(f"Failed to persist active status for {strategy_name}: {e}")
        
        return promoted
    
    def demote_bottom_percent(self, bottom_percent: float = 0.1) -> List[str]:
        """
        PHASE 5: Demote bottom Y% strategies to DISABLED (TRAINING only).
        
        SAFETY: Only TRAINING lifecycle strategies can be demoted
        SAFETY: No deletion - history preserved
        SAFETY: Demotions affect TRAINING only (no LIVE implications)
        
        Args:
            bottom_percent: Bottom percentage to demote (0.0-1.0, default 0.1 = 10%)
            
        Returns:
            List of strategy names that were demoted
        """
        rankings = self.rank_strategies()
        
        if not rankings:
            return []
        
        # Calculate number of strategies to demote (bottom Y%)
        num_to_demote = max(1, int(len(rankings) * bottom_percent))
        bottom_strategies = rankings[-num_to_demote:]
        
        demoted = []
        for strategy_name, score, evaluation in bottom_strategies:
            # SAFETY: Only demote TRAINING lifecycle strategies
            lifecycle_state = self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
            if lifecycle_state != StrategyLifecycleState.TRAINING:
                logger.debug(f"Skipping demotion of {strategy_name} (lifecycle={lifecycle_state.value}, TRAINING only)")
                continue
            
            if self.status.get(strategy_name) == StrategyStatus.ACTIVE:
                self.status[strategy_name] = StrategyStatus.DISABLED
                demoted.append(strategy_name)
                reason = f"Bottom {bottom_percent:.1%} performer (score={score:.4f})"
                self.last_disable_reason[strategy_name] = reason
                logger.info(f"Strategy demoted (TRAINING): {strategy_name} - {reason}")
                
                # Persist status change
                try:
                    if hasattr(self.storage, 'update_strategy_status'):
                        self.storage.update_strategy_status(strategy_name, StrategyStatus.DISABLED.value)
                except Exception as e:
                    logger.warning(f"Failed to persist disabled status for {strategy_name}: {e}")
        
        return demoted
    
    def get_active_strategies(self) -> List[BaseStrategy]:
        """
        PHASE 4: Get list of active strategies.
        
        SAFETY: Only TRAINING lifecycle strategies can be active.
        SHADOW/APPROVED are placeholders only (future-locked).
        
        Returns:
            List of active strategy instances (TRAINING lifecycle only)
        """
        active = []
        for name, strategy in self.strategies.items():
            # SAFETY: Only ACTIVE status AND TRAINING lifecycle can be active
            if (self.status.get(name) == StrategyStatus.ACTIVE and 
                self.strategy_states.get(name, StrategyLifecycleState.TRAINING) == StrategyLifecycleState.TRAINING):
                active.append(strategy)
        return active
    
    def is_active(self, strategy: BaseStrategy) -> bool:
        """
        PHASE 1: Check if strategy is active.
        
        SAFETY: Only TRAINING lifecycle strategies can be active.
        SHADOW/APPROVED are placeholders only (future-locked).
        DISABLED strategies never execute.
        
        Args:
            strategy: Strategy instance
            
        Returns:
            True if active (TRAINING lifecycle + ACTIVE status), False otherwise
        """
        name = strategy.get_name()
        status_active = self.status.get(name) == StrategyStatus.ACTIVE
        lifecycle_training = self.strategy_states.get(name, StrategyLifecycleState.TRAINING) == StrategyLifecycleState.TRAINING
        
        # SAFETY: Only TRAINING + ACTIVE strategies execute
        return status_active and lifecycle_training
    
    def get_status(self, strategy_name: str) -> StrategyStatus:
        """Get strategy status."""
        return self.status.get(strategy_name, StrategyStatus.DISABLED)
    
    def list_strategies(self) -> List[Dict[str, Any]]:
        """
        PHASE 7: List all strategies with status, lifecycle state, score, and governance info (read-only).
        
        Returns:
            List of dictionaries with name, status, lifecycle_state, score, capital_weight, ranking
        """
        strategies_list = []
        
        # Get rankings to get scores
        rankings = self.rank_strategies()
        rankings_dict = {name: (score, idx) for idx, (name, score, _) in enumerate(rankings)}
        
        # Build list from registered strategies
        for name, strategy in self.strategies.items():
            status = self.status.get(name, StrategyStatus.DISABLED)
            lifecycle_state = self.strategy_states.get(name, StrategyLifecycleState.TRAINING)
            score_data = rankings_dict.get(name, (None, None))
            score = score_data[0]
            ranking = score_data[1] + 1 if score_data[1] is not None else None
            
            # Try to get latest score from evaluations
            if score is None:
                for key, eval_obj in self.evaluations.items():
                    if eval_obj.strategy_name == name:
                        if score is None or eval_obj.timestamp > eval_obj.timestamp:
                            score = eval_obj.composite_score
                # Calculate composite score if not available
                if score is None:
                    score = self.calculate_composite_score(name)
            
            # Get governance summary
            governance_summary = self.get_strategy_governance_summary(name)
            
            strategies_list.append({
                'name': name,
                'status': status.value,
                'lifecycle_state': lifecycle_state.value if isinstance(lifecycle_state, StrategyLifecycleState) else str(lifecycle_state),
                'score': score,
                'capital_weight': self.capital_weights.get(name, 0.0),
                'ranking': ranking,
                'last_disable_reason': self.last_disable_reason.get(name),
                'promotion_eligible': governance_summary.get('promotion_eligibility', {}).get('eligible', False),
                'demotion_evaluation': governance_summary.get('demotion_evaluation', {}).get('should_demote', False)
            })
        
        return strategies_list
    
    def record_trade_result(self, strategy_name: str, pnl: float, is_win: bool) -> None:
        """
        Record a trade result for rolling performance tracking.
        
        ENGINE SAFETY LOCK:
        - NO mode parameter
        - NO realized_pnl argument (use pnl instead)
        - MUST NOT block execution
        - MUST NOT raise exceptions
        
        Args:
            strategy_name: Strategy name
            pnl: PnL from trade (positive = win, negative = loss)
            is_win: Whether trade was a win
        """
        # CRITICAL: All operations must be wrapped and non-blocking
        try:
            if strategy_name not in self.strategies:
                return  # Strategy not registered
            
            # CRITICAL: Rolling stats updates must NOT fail
            try:
                # Record PnL
                if strategy_name not in self.rolling_pnl:
                    self.rolling_pnl[strategy_name] = deque(maxlen=1000)
                self.rolling_pnl[strategy_name].append(pnl)
                
                # Record trade result
                if strategy_name not in self.rolling_trades:
                    self.rolling_trades[strategy_name] = deque(maxlen=1000)
                self.rolling_trades[strategy_name].append(1.0 if is_win else -1.0)
                
                # Update consecutive losses
                if strategy_name not in self.consecutive_losses:
                    self.consecutive_losses[strategy_name] = 0
                
                if is_win:
                    self.consecutive_losses[strategy_name] = 0
                else:
                    self.consecutive_losses[strategy_name] += 1
            except Exception as e:
                logger.error(f"Error updating rolling stats for {strategy_name}: {e}", exc_info=True)
                # Continue - don't block on stats errors
            
            # CRITICAL: Auto-disable check must NOT block
            try:
                self._check_auto_disable(strategy_name)
            except Exception as e:
                logger.error(f"Error checking auto-disable for {strategy_name}: {e}", exc_info=True)
                # Continue - auto-disable is informational only
        
        except Exception as e:
            logger.error(f"Error recording trade result for {strategy_name}: {e}", exc_info=True)
            # CRITICAL: Never raise - this is an analytics operation
    
    def get_rolling_performance(self, strategy_name: str) -> Dict[str, Any]:
        """
        PHASE 3: Get rolling performance stats for a strategy.
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            Dict with pnl, sharpe (approx), win_rate, drawdown, trades_count
        """
        try:
            pnl_values = list(self.rolling_pnl.get(strategy_name, []))
            trade_results = list(self.rolling_trades.get(strategy_name, []))
            
            if not pnl_values:
                return {
                    'pnl': 0.0,
                    'sharpe': 0.0,
                    'win_rate': 0.0,
                    'drawdown': 0.0,
                    'trades_count': 0,
                    'consecutive_losses': self.consecutive_losses.get(strategy_name, 0)
                }
            
            # Calculate metrics
            total_pnl = sum(pnl_values)
            wins = sum(1 for r in trade_results if r > 0)
            total_trades = len(trade_results)
            win_rate = wins / total_trades if total_trades > 0 else 0.0
            
            # Approximate Sharpe (simplified)
            if len(pnl_values) > 1:
                mean_pnl = sum(pnl_values) / len(pnl_values)
                variance = sum((x - mean_pnl) ** 2 for x in pnl_values) / len(pnl_values)
                std_dev = variance ** 0.5
                sharpe = (mean_pnl / std_dev) if std_dev > 0 else 0.0
            else:
                sharpe = 0.0
            
            # Calculate drawdown
            running_pnl = 0.0
            peak = 0.0
            max_dd = 0.0
            for pnl in pnl_values:
                running_pnl += pnl
                if running_pnl > peak:
                    peak = running_pnl
                drawdown = peak - running_pnl
                if drawdown > max_dd:
                    max_dd = drawdown
            
            # Normalize drawdown (as percentage of peak)
            drawdown_pct = max_dd / peak if peak > 0 else 0.0
            
            return {
                'pnl': total_pnl,
                'sharpe': sharpe,
                'win_rate': win_rate,
                'drawdown': drawdown_pct,
                'trades_count': total_trades,
                'consecutive_losses': self.consecutive_losses.get(strategy_name, 0)
            }
        
        except Exception as e:
            logger.error(f"Error getting rolling performance for {strategy_name}: {e}", exc_info=True)
            return {
                'pnl': 0.0,
                'sharpe': 0.0,
                'win_rate': 0.0,
                'drawdown': 0.0,
                'trades_count': 0,
                'consecutive_losses': 0
            }
    
    def _check_auto_disable(self, strategy_name: str) -> None:
        """
        PHASE 4: Check auto-disable rules for a strategy (includes execution quality).
        
        Rules:
        - Max drawdown exceeded
        - Consecutive losses exceeded
        - Negative expectancy window
        - PHASE 4: Persistent slippage degradation
        - PHASE 4: Execution failures
        - PHASE 4: Shadow vs execution divergence
        """
        try:
            if self.status.get(strategy_name) != StrategyStatus.ACTIVE:
                return  # Already disabled
            
            performance = self.get_rolling_performance(strategy_name)
            reasons = []
            
            # Rule 1: Max drawdown exceeded
            if performance['drawdown'] > self.max_drawdown_threshold:
                reasons.append(f"drawdown={performance['drawdown']:.2%} > {self.max_drawdown_threshold:.2%}")
            
            # Rule 2: Consecutive losses exceeded
            if performance['consecutive_losses'] >= self.max_consecutive_losses:
                reasons.append(f"consecutive_losses={performance['consecutive_losses']} >= {self.max_consecutive_losses}")
            
            # Rule 3: Negative expectancy window
            if performance['trades_count'] >= self.negative_expectancy_window:
                # Calculate expectancy
                pnl_values = list(self.rolling_pnl.get(strategy_name, []))
                if len(pnl_values) >= self.negative_expectancy_window:
                    recent_pnl = pnl_values[-self.negative_expectancy_window:]
                    avg_pnl = sum(recent_pnl) / len(recent_pnl)
                    if avg_pnl < 0:  # Negative expectancy
                        reasons.append(f"negative_expectancy={avg_pnl:.2f} over {self.negative_expectancy_window} trades")
            
            # PHASE 4: Rule 4: Persistent slippage degradation
            try:
                from sentinel_x.execution.execution_metrics import get_execution_metrics_tracker
                metrics_tracker = get_execution_metrics_tracker()
                execution_metrics = metrics_tracker.get_latest_metrics(strategy_name)
                
                if execution_metrics:
                    # Check for persistent high slippage (> 50 bps average over window)
                    if execution_metrics.avg_slippage_bps > 50.0:
                        reasons.append(f"persistent_slippage_degradation:avg={execution_metrics.avg_slippage_bps:.2f}bps")
                    
                    # Check for execution failures (high cancel/reject rate)
                    failure_rate = execution_metrics.cancel_rate + (execution_metrics.missed_fills / max(execution_metrics.total_requests, 1))
                    if failure_rate > 0.2:  # > 20% failure rate
                        reasons.append(f"execution_failures:failure_rate={failure_rate:.2%}")
                    
                    # Check for shadow divergence (> 50 bps divergence)
                    if abs(execution_metrics.shadow_divergence_bps) > 50.0:
                        reasons.append(f"shadow_execution_divergence:{execution_metrics.shadow_divergence_bps:.2f}bps")
                        
            except Exception as e:
                logger.debug(f"Error checking execution demotion triggers (non-fatal): {e}")
            
            # Auto-disable if any rule triggered
            if reasons:
                self.status[strategy_name] = StrategyStatus.AUTO_DISABLED
                reason_str = ", ".join(reasons)
                self.last_disable_reason[strategy_name] = reason_str
                
                logger.warning(f"Strategy AUTO-DISABLED: {strategy_name} - {reason_str}")
                
                # Persist status
                try:
                    if hasattr(self.storage, 'update_strategy_status'):
                        self.storage.update_strategy_status(strategy_name, StrategyStatus.AUTO_DISABLED.value)
                except Exception as e:
                    logger.warning(f"Failed to persist auto-disabled status for {strategy_name}: {e}")
                
                # Emit event (non-blocking)
                self._emit_auto_disable_event(strategy_name, reason_str)
        
        except Exception as e:
            logger.error(f"Error checking auto-disable for {strategy_name}: {e}", exc_info=True)
    
    def _emit_auto_disable_event(self, strategy_name: str, reason: str) -> None:
        """Emit auto-disable event and trigger alert (non-blocking)."""
        try:
            event = {
                'type': 'strategy_auto_disabled',
                'strategy': strategy_name,
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }
            safe_emit(self.event_bus.publish(event))
            
            # PHASE 5: Trigger alert
            try:
                from sentinel_x.monitoring.alerts import get_alert_manager
                alert_manager = get_alert_manager()
                safe_emit(alert_manager.alert_strategy_auto_disabled(strategy_name, reason))
            except Exception as e:
                logger.debug(f"Error triggering alert for auto-disable: {e}")
        except Exception as e:
            logger.error(f"Error emitting auto-disable event: {e}", exc_info=True)
    
    def get_strategy_ranking_with_performance(self) -> List[Dict[str, Any]]:
        """
        PHASE 3: Get strategy ranking with live performance stats.
        
        Returns:
            List of dicts with name, status, score, rolling_performance, disable_reason
        """
        try:
            rankings = self.rank_strategies()
            rankings_dict = {name: (score, eval_obj) for name, score, eval_obj in rankings}
            
            result = []
            for name, strategy in self.strategies.items():
                status = self.status.get(name, StrategyStatus.DISABLED)
                score_data = rankings_dict.get(name, (None, None))
                score = score_data[0]
                
                # Get rolling performance
                rolling_perf = self.get_rolling_performance(name)
                
                # Get disable reason if auto-disabled
                disable_reason = self.last_disable_reason.get(name) if status == StrategyStatus.AUTO_DISABLED else None
                
                result.append({
                    'name': name,
                    'status': status.value,
                    'score': score,
                    'rolling_performance': rolling_perf,
                    'disable_reason': disable_reason
                })
            
            # Sort by score (descending)
            result.sort(key=lambda x: x['score'] if x['score'] is not None else -999, reverse=True)
            
            return result
        
        except Exception as e:
            logger.error(f"Error getting strategy ranking with performance: {e}", exc_info=True)
            return []
    
    def calculate_promotion_readiness_score(self, strategy_name: str) -> Dict[str, Any]:
        """
        PHASE 3-4: Calculate promotion readiness score for a strategy (with execution quality).
        
        Score is informational ONLY - promotion requires governance rules.
        
        PHASE 4: Promotion gates MUST include:
        - Stable execution metrics
        - Low slippage variance
        - Acceptable latency
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            Dict with promotion readiness scores and metrics
        """
        try:
            # Get rolling performance
            perf = self.get_rolling_performance(strategy_name)
            
            # Get latest evaluation if available
            latest_eval = None
            for key, eval_obj in self.evaluations.items():
                if eval_obj.strategy_name == strategy_name:
                    if latest_eval is None or eval_obj.timestamp > latest_eval.timestamp:
                        latest_eval = eval_obj
            
            # Calculate performance score (0.0 - 1.0)
            sharpe = latest_eval.sharpe if latest_eval else perf.get('sharpe', 0.0)
            win_rate = latest_eval.win_rate if latest_eval else perf.get('win_rate', 0.0)
            expectancy = latest_eval.expectancy if latest_eval else 0.0
            
            # Normalize scores
            performance_score = min(max((sharpe / 3.0) * 0.4 + (win_rate * 0.3) + (max(0, expectancy) / 100.0) * 0.3, 0.0), 1.0)
            
            # Calculate risk score (0.0 - 1.0, higher is better)
            drawdown = latest_eval.max_drawdown if latest_eval else perf.get('drawdown', 1.0)
            risk_score = min(max(1.0 - (drawdown / 0.5), 0.0), 1.0)  # 0.5 = 50% drawdown is worst
            
            # Calculate stability score (based on consistency)
            trades_count = perf.get('trades_count', 0)
            consecutive_losses = perf.get('consecutive_losses', 0)
            if trades_count > 0:
                stability_factor = 1.0 - (consecutive_losses / max(trades_count, 10))
                stability_score = min(max(stability_factor, 0.0), 1.0)
            else:
                stability_score = 0.5  # Neutral if no trades
            
            # Regime robustness (simplified - would need multi-regime data)
            regime_robustness_score = 0.7  # Placeholder - would analyze across regimes
            
            # PHASE 2-3: Get execution quality score
            execution_quality_score = None
            execution_metrics = None
            try:
                from sentinel_x.execution.execution_metrics import get_execution_metrics_tracker
                metrics_tracker = get_execution_metrics_tracker()
                execution_metrics = metrics_tracker.get_latest_metrics(strategy_name)
                if execution_metrics:
                    execution_quality_score = execution_metrics.execution_quality_score
            except Exception as e:
                logger.debug(f"Error getting execution quality score (non-fatal): {e}")
            
            # PHASE 4: Promotion gates include execution quality
            # No strategy may promote without passing execution thresholds
            execution_passes_gates = True
            execution_gate_reasons = []
            
            if execution_metrics:
                # Gate 1: Stable execution metrics (slippage variance < 100 bps)
                if execution_metrics.slippage_variance > 100.0:
                    execution_passes_gates = False
                    execution_gate_reasons.append(f"high_slippage_variance:{execution_metrics.slippage_variance:.2f}bps")
                
                # Gate 2: Acceptable latency (< 500ms average, < 200ms std dev)
                if execution_metrics.avg_latency_ms > 500.0:
                    execution_passes_gates = False
                    execution_gate_reasons.append(f"high_latency:{execution_metrics.avg_latency_ms:.2f}ms")
                
                if execution_metrics.latency_std_ms > 200.0:
                    execution_passes_gates = False
                    execution_gate_reasons.append(f"high_latency_variance:{execution_metrics.latency_std_ms:.2f}ms")
                
                # Gate 3: Minimum execution quality score (>= 0.7)
                if execution_quality_score is not None and execution_quality_score < 0.7:
                    execution_passes_gates = False
                    execution_gate_reasons.append(f"low_execution_quality:{execution_quality_score:.2f}")
            
            # PHASE 3: Overall weighted score (includes execution quality)
            if execution_quality_score is not None:
                # Updated weights: 30% performance, 20% risk, 15% stability, 10% regime, 25% execution
                overall_score = (
                    performance_score * 0.3 +
                    risk_score * 0.2 +
                    stability_score * 0.15 +
                    regime_robustness_score * 0.1 +
                    execution_quality_score * 0.25
                )
            else:
                # No execution quality available - use original weights
                overall_score = (
                    performance_score * 0.4 +
                    risk_score * 0.3 +
                    stability_score * 0.2 +
                    regime_robustness_score * 0.1
                )
            
            score_data = {
                "overall_score": overall_score,
                "performance_score": performance_score,
                "risk_score": risk_score,
                "stability_score": stability_score,
                "regime_robustness_score": regime_robustness_score,
                "execution_quality_score": execution_quality_score,
                "execution_passes_gates": execution_passes_gates,
                "execution_gate_reasons": execution_gate_reasons,
                "metrics_snapshot": {
                    "sharpe": sharpe,
                    "win_rate": win_rate,
                    "expectancy": expectancy,
                    "drawdown": drawdown,
                    "trades_count": trades_count,
                    "consecutive_losses": consecutive_losses,
                    "execution_metrics": {
                        "avg_slippage_bps": execution_metrics.avg_slippage_bps if execution_metrics else None,
                        "slippage_variance": execution_metrics.slippage_variance if execution_metrics else None,
                        "fill_ratio": execution_metrics.fill_ratio if execution_metrics else None,
                        "avg_latency_ms": execution_metrics.avg_latency_ms if execution_metrics else None,
                        "latency_std_ms": execution_metrics.latency_std_ms if execution_metrics else None,
                        "cancel_rate": execution_metrics.cancel_rate if execution_metrics else None
                    } if execution_metrics else {}
                },
                "timestamp": datetime.utcnow()
            }
            
            # PHASE 6: Audit log score update
            try:
                from sentinel_x.monitoring.audit_logger import log_audit_event
                log_audit_event(
                    event_type="STRATEGY_SCORE_UPDATE",
                    request_id=f"score_{strategy_name}_{datetime.utcnow().isoformat()}",
                    metadata={
                        "strategy_name": strategy_name,
                        "overall_score": overall_score,
                        "performance_score": performance_score,
                        "risk_score": risk_score,
                        "stability_score": stability_score,
                        "execution_quality_score": execution_quality_score,
                        "execution_passes_gates": execution_passes_gates,
                        "calculation_weights": {
                            "performance": 0.3,
                            "risk": 0.2,
                            "stability": 0.15,
                            "regime": 0.1,
                            "execution": 0.25
                        } if execution_quality_score is not None else {
                            "performance": 0.4,
                            "risk": 0.3,
                            "stability": 0.2,
                            "regime": 0.1
                        },
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
            except Exception as e:
                logger.debug(f"Error logging score update (non-fatal): {e}")
            
            # Store score
            self.promotion_scores[strategy_name] = score_data
            
            return score_data
            
        except Exception as e:
            logger.error(f"Error calculating promotion readiness score for {strategy_name}: {e}", exc_info=True)
            return {
                "overall_score": 0.0,
                "performance_score": 0.0,
                "risk_score": 0.0,
                "stability_score": 0.0,
                "regime_robustness_score": 0.0,
                "execution_quality_score": None,
                "execution_passes_gates": False,
                "execution_gate_reasons": [f"calculation_error:{str(e)}"],
                "metrics_snapshot": {},
                "timestamp": datetime.utcnow()
            }
    
    def get_lifecycle_state(self, strategy_name: str) -> StrategyLifecycleState:
        """
        PHASE 4: Get lifecycle state for a strategy.
        
        Rules:
        - TRAINING: Only active state
        - SHADOW: Future-locked placeholder (informational only)
        - APPROVED: Future-locked placeholder (informational only)
        - DISABLED: Strategy disabled (visible but inactive)
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            StrategyLifecycleState enum (defaults to TRAINING)
        """
        return self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
    
    def set_lifecycle_state(self, strategy_name: str, state: StrategyLifecycleState) -> None:
        """
        PHASE 4: Set lifecycle state for a strategy.
        
        SAFETY: Only TRAINING state is active
        SAFETY: SHADOW/APPROVED are placeholders only (future-locked)
        SAFETY: DISABLED strategies remain visible but inactive
        
        Args:
            strategy_name: Strategy name
            state: Lifecycle state enum
        """
        if strategy_name not in self.strategies:
            raise ValueError(f"Strategy not found: {strategy_name}")
        
        # SAFETY: Ensure state is StrategyLifecycleState enum
        if not isinstance(state, StrategyLifecycleState):
            # Try to convert from string
            state_str = str(state).upper()
            try:
                state = StrategyLifecycleState(state_str)
            except ValueError:
                logger.error(f"Invalid lifecycle state: {state}, defaulting to TRAINING")
                state = StrategyLifecycleState.TRAINING
        
        current_state = self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
        
        # SAFETY: SHADOW and APPROVED are future-locked placeholders (informational only)
        if state in [StrategyLifecycleState.SHADOW, StrategyLifecycleState.APPROVED]:
            logger.warning(f"Setting lifecycle state to {state.value} (future-locked placeholder, informational only)")
            # Still allow setting for tracking purposes, but don't activate
        
        # SAFETY: DISABLED state disables strategy
        if state == StrategyLifecycleState.DISABLED:
            self.status[strategy_name] = StrategyStatus.DISABLED
        # SAFETY: Only TRAINING state can be active
        elif state == StrategyLifecycleState.TRAINING:
            # Keep existing status (ACTIVE or DISABLED) but update lifecycle
            pass  # Status already set
        
        self.strategy_states[strategy_name] = state
        logger.info(f"Lifecycle state updated: {strategy_name} {current_state.value} -> {state.value}")
        
        # Persist if storage supports it
        try:
            # Would need to add lifecycle_state column to storage
            pass
        except Exception as e:
            logger.debug(f"Error persisting lifecycle state: {e}")
    
    def compute_normalized_metrics(self, strategy_name: str) -> Dict[str, Any]:
        """
        PHASE 2: Compute normalized performance metrics per strategy.
        
        Metrics computed over rolling windows:
        - trades_count
        - realized_pnl
        - win_rate
        - max_drawdown
        - expectancy
        - sharpe (optional if data sufficient)
        
        Rules:
        - Metrics are read-only inputs
        - Handle low-trade-count bias
        - Ignore strategies below MIN_TRADES for promotion
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            Dict with normalized metrics
        """
        try:
            perf = self.get_rolling_performance(strategy_name)
            trades_count = perf.get('trades_count', 0)
            realized_pnl = perf.get('pnl', 0.0)
            win_rate = perf.get('win_rate', 0.0)
            max_drawdown = perf.get('drawdown', 0.0)
            sharpe = perf.get('sharpe', 0.0)
            
            # Calculate expectancy (average PnL per trade)
            expectancy = realized_pnl / trades_count if trades_count > 0 else 0.0
            
            # Normalize metrics (0.0 - 1.0 range where applicable)
            # For win_rate, already 0.0-1.0
            # For drawdown, normalize as penalty (higher drawdown = lower score)
            normalized_drawdown = min(max_drawdown / 1.0, 1.0)  # Cap at 100% drawdown
            
            # For sharpe, normalize to 0.0-1.0 (assuming sharpe ranges from -2 to 3)
            normalized_sharpe = min(max((sharpe + 2.0) / 5.0, 0.0), 1.0)
            
            # For expectancy, normalize based on reasonable range (e.g., -100 to +100)
            normalized_expectancy = min(max((expectancy + 100.0) / 200.0, 0.0), 1.0)
            
            metrics = {
                'trades_count': trades_count,
                'realized_pnl': realized_pnl,
                'win_rate': win_rate,
                'max_drawdown': max_drawdown,
                'expectancy': expectancy,
                'sharpe': sharpe,
                'normalized_win_rate': win_rate,  # Already 0.0-1.0
                'normalized_drawdown': normalized_drawdown,
                'normalized_sharpe': normalized_sharpe,
                'normalized_expectancy': normalized_expectancy,
                'meets_min_trades': trades_count >= self.min_trades_for_promotion,
                'timestamp': datetime.now().isoformat()
            }
            
            # Store normalized metrics
            self.normalized_metrics[strategy_name] = metrics
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error computing normalized metrics for {strategy_name}: {e}", exc_info=True)
            return {
                'trades_count': 0,
                'realized_pnl': 0.0,
                'win_rate': 0.0,
                'max_drawdown': 0.0,
                'expectancy': 0.0,
                'sharpe': 0.0,
                'normalized_win_rate': 0.0,
                'normalized_drawdown': 1.0,
                'normalized_sharpe': 0.0,
                'normalized_expectancy': 0.0,
                'meets_min_trades': False,
                'timestamp': datetime.now().isoformat()
            }
    
    def calculate_composite_score(self, strategy_name: str) -> float:
        """
        PHASE 3: Calculate deterministic composite score.
        
        Score formula:
        score = w1 * normalized_expectancy +
                w2 * normalized_sharpe +
                w3 * win_rate -
                w4 * max_drawdown_penalty
        
        Rules:
        - Weights configurable but bounded
        - Score computation deterministic
        - No randomness
        - No ML here
        
        SAFETY: scoring is deterministic and explainable
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            Composite score (0.0 - 1.0 range, higher is better)
        """
        try:
            # Get normalized metrics
            if strategy_name not in self.normalized_metrics:
                self.compute_normalized_metrics(strategy_name)
            
            metrics = self.normalized_metrics.get(strategy_name, {})
            
            # Extract normalized components
            normalized_expectancy = metrics.get('normalized_expectancy', 0.0)
            normalized_sharpe = metrics.get('normalized_sharpe', 0.0)
            normalized_win_rate = metrics.get('normalized_win_rate', 0.0)
            max_drawdown = metrics.get('max_drawdown', 0.0)
            
            # Calculate drawdown penalty (0.0 = no penalty, 1.0 = maximum penalty)
            drawdown_penalty = min(max_drawdown / self.max_drawdown_threshold, 1.0)
            
            # Calculate composite score using configured weights
            score = (
                self.score_weight_expectancy * normalized_expectancy +
                self.score_weight_sharpe * normalized_sharpe +
                self.score_weight_win_rate * normalized_win_rate -
                self.score_weight_drawdown_penalty * drawdown_penalty
            )
            
            # Ensure score is in valid range [0.0, 1.0]
            score = max(0.0, min(1.0, score))
            
            return score
            
        except Exception as e:
            logger.error(f"Error calculating composite score for {strategy_name}: {e}", exc_info=True)
            return 0.0
    
    def evaluate_promotion_eligibility(self, strategy_name: str) -> Dict[str, Any]:
        """
        PHASE 4-8: Evaluate if strategy is eligible for promotion (with backtest integration).
        
        SAFETY: training-only promotion system
        SAFETY: promotion logic remains training-only
        REGRESSION LOCK — BACKTEST GOVERNANCE BRIDGE
        
        Eligibility criteria:
        - trades_count >= MIN_TRADES (live training)
        - BOTH backtest_score >= threshold AND live_training_score >= threshold (PHASE 8)
        - Merged score >= threshold (PHASE 8)
        - drawdown within limits
        - no risk violations
        - lifecycle state is TRAINING (only TRAINING can be promoted)
        
        Promotion means:
        - Strategy remains TRAINING
        - Capital_weight (simulated only) increases
        - Priority increases in ranking
        
        Rules:
        - Promotion does NOT enable LIVE
        - Promotion does NOT change execution logic
        - Promotion affects simulated allocation only
        - Backtest results are ADVISORY (PHASE 8)
        - Live training metrics still required (PHASE 8)
        - Promotion requires BOTH backtest + live scores >= thresholds (PHASE 8)
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            Dict with eligible (bool), reason (str), score (float), metrics, and merged_score (PHASE 8)
        """
        try:
            if strategy_name not in self.strategies:
                return {
                    'eligible': False,
                    'reason': 'strategy_not_registered',
                    'score': 0.0,
                    'metrics': {},
                    'merged_score': 0.0
                }
            
            # Check lifecycle state - only TRAINING strategies can be promoted
            lifecycle_state = self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
            if lifecycle_state != StrategyLifecycleState.TRAINING:
                return {
                    'eligible': False,
                    'reason': f'lifecycle_state_not_training: {lifecycle_state.value}',
                    'score': 0.0,
                    'metrics': {},
                    'merged_score': 0.0
                }
            
            # Compute normalized metrics (live training)
            metrics = self.compute_normalized_metrics(strategy_name)
            
            # Check minimum trades requirement (live training)
            if not metrics.get('meets_min_trades', False):
                return {
                    'eligible': False,
                    'reason': f'insufficient_trades: {metrics.get("trades_count", 0)} < {self.min_trades_for_promotion}',
                    'score': 0.0,
                    'metrics': metrics,
                    'merged_score': 0.0
                }
            
            # Calculate composite score (live training)
            live_score = self.calculate_composite_score(strategy_name)
            
            # PHASE 8: Merge backtest + live metrics (advisory only)
            # PHASE 6 — SHADOW GATE CHECK (if using shadow/backtest data)
            merged_score = live_score  # Default to live score if no backtest
            backtest_metrics_dict = self.backtest_metrics.get(strategy_name)
            
            # If using backtest metrics, check shadow gate
            if backtest_metrics_dict:
                try:
                    from sentinel_x.core.shadow_guards import is_shadow_enabled
                    # Only use backtest metrics if shadow mode is enabled
                    if not is_shadow_enabled():
                        logger.debug(f"Shadow mode disabled, skipping backtest metrics for promotion evaluation of {strategy_name}")
                        backtest_metrics_dict = None  # Don't use backtest metrics if shadow is off
                except Exception as e:
                    logger.debug(f"Error checking shadow state for promotion: {e}")
                    backtest_metrics_dict = None  # Fail-safe: don't use backtest if check fails
            
            try:
                from sentinel_x.backtesting.governance_bridge import (
                    get_promotion_evaluator, BacktestMetrics, LiveTrainingMetrics
                )
                
                evaluator = get_promotion_evaluator()
                if evaluator and backtest_metrics_dict:
                    # Create BacktestMetrics from stored data
                    backtest_metrics = BacktestMetrics(
                        strategy_name=strategy_name,
                        trades_count=backtest_metrics_dict.get('trades_count', 0),
                        realized_pnl=backtest_metrics_dict.get('realized_pnl', 0.0),
                        win_rate=backtest_metrics_dict.get('win_rate', 0.0),
                        expectancy=backtest_metrics_dict.get('expectancy', 0.0),
                        sharpe=backtest_metrics_dict.get('sharpe'),
                        max_drawdown=backtest_metrics_dict.get('max_drawdown', 0.0),
                        total_return=backtest_metrics_dict.get('total_return', 0.0),
                        volatility=backtest_metrics_dict.get('volatility'),
                        timestamp=backtest_metrics_dict.get('timestamp')
                    )
                    
                    # Create LiveTrainingMetrics from current metrics
                    live_metrics = LiveTrainingMetrics(
                        strategy_name=strategy_name,
                        trades_count=metrics.get('trades_count', 0),
                        realized_pnl=metrics.get('realized_pnl', 0.0),
                        win_rate=metrics.get('win_rate', 0.0),
                        expectancy=metrics.get('expectancy', 0.0),
                        sharpe=metrics.get('sharpe'),
                        max_drawdown=metrics.get('max_drawdown', 0.0),
                        composite_score=live_score,
                        timestamp=datetime.now()
                    )
                    
                    # PHASE 8: Merge backtest + live metrics
                    merged_result = evaluator.merge(backtest_metrics, live_metrics)
                    merged_score = merged_result.merged_score
                    
                    # PHASE 8: Promotion requires BOTH thresholds
                    if not merged_result.promotion_eligible:
                        return {
                            'eligible': False,
                            'reason': f'merged_score_below_threshold: {merged_score:.4f} < {evaluator.merged_threshold} (backtest={merged_result.backtest_score:.4f}, live={merged_result.live_training_score:.4f})',
                            'score': live_score,
                            'metrics': metrics,
                            'merged_score': merged_score,
                            'backtest_score': merged_result.backtest_score,
                            'live_score': merged_result.live_training_score,
                            'notes': merged_result.notes
                        }
                else:
                    # No backtest metrics available - use live score only (with warning)
                    logger.debug(f"No backtest metrics for {strategy_name}, using live score only")
            except Exception as e:
                logger.debug(f"Error merging backtest metrics (non-fatal): {e}, using live score only")
                merged_score = live_score  # Fallback to live score only
            
            # Check promotion threshold (use merged score if available, else live score)
            promotion_score = merged_score if backtest_metrics_dict else live_score
            if promotion_score < self.promotion_threshold:
                return {
                    'eligible': False,
                    'reason': f'score_below_threshold: {promotion_score:.4f} < {self.promotion_threshold}',
                    'score': live_score,
                    'metrics': metrics,
                    'merged_score': merged_score
                }
            
            # Check drawdown within limits
            max_drawdown = metrics.get('max_drawdown', 0.0)
            if max_drawdown > self.max_drawdown_threshold:
                return {
                    'eligible': False,
                    'reason': f'drawdown_exceeded: {max_drawdown:.4f} > {self.max_drawdown_threshold}',
                    'score': live_score,
                    'metrics': metrics,
                    'merged_score': merged_score
                }
            
            # Check risk violations (no consecutive losses exceeded)
            consecutive_losses = self.consecutive_losses.get(strategy_name, 0)
            if consecutive_losses >= self.max_consecutive_losses:
                return {
                    'eligible': False,
                    'reason': f'consecutive_losses_exceeded: {consecutive_losses} >= {self.max_consecutive_losses}',
                    'score': live_score,
                    'metrics': metrics,
                    'merged_score': merged_score
                }
            
            # PHASE 6: Check governance limits
            active_count = len([s for s in self.strategies.keys() 
                               if self.strategy_states.get(s, StrategyLifecycleState.TRAINING) == StrategyLifecycleState.TRAINING
                               and self.status.get(s) == StrategyStatus.ACTIVE])
            if active_count >= self.max_active_strategies:
                return {
                    'eligible': False,
                    'reason': f'max_active_strategies_exceeded: {active_count} >= {self.max_active_strategies}',
                    'score': live_score,
                    'metrics': metrics,
                    'merged_score': merged_score
                }
            
            # All checks passed
            return {
                'eligible': True,
                'reason': 'all_criteria_met',
                'score': live_score,
                'metrics': metrics,
                'merged_score': merged_score
            }
            
        except Exception as e:
            logger.error(f"Error evaluating promotion eligibility for {strategy_name}: {e}", exc_info=True)
            return {
                'eligible': False,
                'reason': f'evaluation_error: {str(e)}',
                'score': 0.0,
                'metrics': {},
                'merged_score': 0.0
            }
    
    def record_backtest_metrics(self, strategy_name: str, backtest_metrics: Dict[str, Any]):
        """
        PHASE 8: Record backtest metrics for promotion evaluation (advisory only).
        
        SAFETY: backtest metrics are advisory only
        SAFETY: promotion logic remains training-only
        REGRESSION LOCK — BACKTEST GOVERNANCE BRIDGE
        
        Rules:
        - Backtest results are ADVISORY
        - Live training metrics still required
        - Promotion requires BOTH backtest + live scores >= thresholds
        
        Args:
            strategy_name: Strategy name
            backtest_metrics: Backtest metrics dictionary
        """
        try:
            # Store backtest metrics (advisory only, offline)
            self.backtest_metrics[strategy_name] = backtest_metrics
            logger.info(f"Backtest metrics recorded for {strategy_name} (advisory only)")
        except Exception as e:
            logger.error(f"Error recording backtest metrics for {strategy_name}: {e}", exc_info=True)
    
    def promote_strategy(self, strategy_name: str) -> bool:
        """
        PHASE 4: Promote strategy (TRAINING-only, affects ranking and capital weight only).
        
        SAFETY: training-only promotion system
        SAFETY: no execution behavior modified
        SAFETY: promotion does NOT enable LIVE
        SAFETY: promotion does NOT change execution logic
        REGRESSION LOCK — STRATEGY GOVERNANCE
        
        Promotion means:
        - Strategy remains TRAINING (lifecycle unchanged)
        - Capital_weight (simulated only) increases
        - Priority increases in ranking
        - Status remains ACTIVE (if already active)
        
        Rules:
        - Promotion does NOT enable LIVE
        - Promotion does NOT change execution logic
        - Promotion affects simulated allocation only
        - All decisions explainable and reversible
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            True if promoted, False otherwise
        """
        try:
            # Check eligibility
            eligibility = self.evaluate_promotion_eligibility(strategy_name)
            if not eligibility['eligible']:
                logger.debug(f"Strategy {strategy_name} not eligible for promotion: {eligibility['reason']}")
                return False
            
            # Ensure strategy is ACTIVE and TRAINING
            if self.status.get(strategy_name) != StrategyStatus.ACTIVE:
                self.status[strategy_name] = StrategyStatus.ACTIVE
            
            lifecycle_state = self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
            if lifecycle_state != StrategyLifecycleState.TRAINING:
                # Cannot promote non-TRAINING strategies
                logger.warning(f"Cannot promote strategy {strategy_name}: lifecycle state is {lifecycle_state.value}, not TRAINING")
                return False
            
            # Update ranking (strategy will be ranked higher based on score)
            score = eligibility['score']
            self.promotion_scores[strategy_name] = {
                'score': score,
                'promoted_at': datetime.now().isoformat(),
                'metrics': eligibility['metrics']
            }
            
            # Update capital weight (simulated only - will be used by allocator)
            # Capital weight is proportional to score relative to other strategies
            # This is computed dynamically by the allocator, but we can set a preference
            active_strategies = [s for s in self.strategies.keys() 
                                if self.strategy_states.get(s, StrategyLifecycleState.TRAINING) == StrategyLifecycleState.TRAINING
                                and self.status.get(s) == StrategyStatus.ACTIVE]
            
            # Calculate relative weight based on score
            total_score = sum(self.calculate_composite_score(s) for s in active_strategies)
            if total_score > 0:
                self.capital_weights[strategy_name] = score / total_score
            else:
                self.capital_weights[strategy_name] = 1.0 / max(len(active_strategies), 1)
            
            # PHASE 7: Record promotion in audit trail
            if strategy_name not in self.lifecycle_history:
                self.lifecycle_history[strategy_name] = []
            
            self.lifecycle_history[strategy_name].append({
                'from': lifecycle_state.value,
                'to': lifecycle_state.value,  # Remains TRAINING
                'action': 'PROMOTED',
                'reason': f'promotion_score={score:.4f}, {eligibility["reason"]}',
                'timestamp': datetime.now().isoformat(),
                'score': score,
                'capital_weight': self.capital_weights[strategy_name]
            })
            
            # PHASE 7: Audit log
            try:
                from sentinel_x.monitoring.audit_logger import log_audit_event
                log_audit_event(
                    event_type="STRATEGY_PROMOTED",
                    request_id=f"promote_{strategy_name}_{datetime.now().isoformat()}",
                    metadata={
                        "strategy_name": strategy_name,
                        "lifecycle_state": lifecycle_state.value,
                        "score": score,
                        "capital_weight": self.capital_weights[strategy_name],
                        "reason": eligibility['reason'],
                        "timestamp": datetime.now().isoformat()
                    }
                )
            except Exception as e:
                logger.debug(f"Error logging promotion (non-fatal): {e}")
            
            logger.info(f"Strategy promoted: {strategy_name} (score={score:.4f}, capital_weight={self.capital_weights[strategy_name]:.4f})")
            
            return True
            
        except Exception as e:
            logger.error(f"Error promoting strategy {strategy_name}: {e}", exc_info=True)
            return False
    
    def evaluate_demotion_conditions(self, strategy_name: str) -> Dict[str, Any]:
        """
        PHASE 5: Evaluate if strategy should be demoted.
        
        Demotion conditions:
        - trades_count >= MIN_TRADES
        AND
        - score < DEMOTION_THRESHOLD
        OR
        - drawdown breach
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            Dict with should_demote (bool), reason (str), score (float)
        """
        try:
            if strategy_name not in self.strategies:
                return {
                    'should_demote': False,
                    'reason': 'strategy_not_registered',
                    'score': 0.0
                }
            
            # Check lifecycle state - only TRAINING strategies can be demoted
            lifecycle_state = self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
            if lifecycle_state != StrategyLifecycleState.TRAINING:
                return {
                    'should_demote': False,
                    'reason': f'already_not_training: {lifecycle_state.value}',
                    'score': 0.0
                }
            
            # Compute normalized metrics
            metrics = self.compute_normalized_metrics(strategy_name)
            trades_count = metrics.get('trades_count', 0)
            
            # Check minimum trades requirement (must have sufficient data to demote)
            if trades_count < self.min_trades_for_promotion:
                return {
                    'should_demote': False,
                    'reason': f'insufficient_trades_for_demotion: {trades_count} < {self.min_trades_for_promotion}',
                    'score': 0.0
                }
            
            # Calculate composite score
            score = self.calculate_composite_score(strategy_name)
            
            # Check demotion threshold
            if score < self.demotion_threshold:
                return {
                    'should_demote': True,
                    'reason': f'score_below_demotion_threshold: {score:.4f} < {self.demotion_threshold}',
                    'score': score
                }
            
            # Check drawdown breach
            max_drawdown = metrics.get('max_drawdown', 0.0)
            if max_drawdown > self.max_drawdown_threshold:
                return {
                    'should_demote': True,
                    'reason': f'drawdown_breach: {max_drawdown:.4f} > {self.max_drawdown_threshold}',
                    'score': score
                }
            
            # Check consecutive losses
            consecutive_losses = self.consecutive_losses.get(strategy_name, 0)
            if consecutive_losses >= self.max_consecutive_losses:
                return {
                    'should_demote': True,
                    'reason': f'consecutive_losses_exceeded: {consecutive_losses} >= {self.max_consecutive_losses}',
                    'score': score
                }
            
            # No demotion needed
            return {
                'should_demote': False,
                'reason': 'criteria_not_met',
                'score': score
            }
            
        except Exception as e:
            logger.error(f"Error evaluating demotion conditions for {strategy_name}: {e}", exc_info=True)
            return {
                'should_demote': False,
                'reason': f'evaluation_error: {str(e)}',
                'score': 0.0
            }
    
    def demote_strategy(self, strategy_name: str) -> bool:
        """
        PHASE 5: Demote strategy (safe and reversible).
        
        SAFETY: training-only demotion system
        SAFETY: no execution behavior modified
        SAFETY: demotion affects ONLY the strategy
        SAFETY: engine continues uninterrupted
        SAFETY: other strategies unaffected
        SAFETY: all decisions explainable and reversible
        REGRESSION LOCK — STRATEGY GOVERNANCE
        
        Demotion action:
        - lifecycle_state = DISABLED
        - Strategy stops executing
        - Metrics preserved
        - No deletion
        
        Rules:
        - Demotion affects ONLY the strategy
        - Engine continues uninterrupted
        - Other strategies unaffected
        - No broker logic touched
        - Alpaca remains PAPER
        - Tradovate LIVE untouched
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            True if demoted, False otherwise
        """
        try:
            # Check demotion conditions
            demotion_eval = self.evaluate_demotion_conditions(strategy_name)
            if not demotion_eval['should_demote']:
                logger.debug(f"Strategy {strategy_name} does not meet demotion conditions: {demotion_eval['reason']}")
                return False
            
            # Get current state
            current_lifecycle = self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
            if current_lifecycle == StrategyLifecycleState.DISABLED:
                logger.debug(f"Strategy {strategy_name} already DISABLED")
                return False
            
            # PHASE 6: Check governance limits (prefer demotion over deletion)
            disabled_count = len([s for s in self.strategies.keys() 
                                 if self.strategy_states.get(s) == StrategyLifecycleState.DISABLED])
            if disabled_count >= self.max_disabled_strategies:
                logger.warning(f"Max disabled strategies reached ({disabled_count} >= {self.max_disabled_strategies}), "
                             f"but demoting {strategy_name} anyway (governance limit is soft)")
            
            # PHASE 6: Check total strategies limit (hard cap)
            total_count = len(self.strategies)
            if total_count >= self.max_total_strategies:
                logger.warning(f"Total strategies limit reached ({total_count} >= {self.max_total_strategies}), "
                             f"but demoting {strategy_name} anyway (limits are per-strategy)")
            
            # Demote: set lifecycle to DISABLED
            self.strategy_states[strategy_name] = StrategyLifecycleState.DISABLED
            self.status[strategy_name] = StrategyStatus.DISABLED
            
            # Store demotion reason
            reason = demotion_eval['reason']
            self.last_disable_reason[strategy_name] = reason
            
            # Reset capital weight
            self.capital_weights[strategy_name] = 0.0
            
            # PHASE 7: Record demotion in audit trail
            if strategy_name not in self.lifecycle_history:
                self.lifecycle_history[strategy_name] = []
            
            self.lifecycle_history[strategy_name].append({
                'from': current_lifecycle.value,
                'to': StrategyLifecycleState.DISABLED.value,
                'action': 'DEMOTED',
                'reason': reason,
                'timestamp': datetime.now().isoformat(),
                'score': demotion_eval.get('score', 0.0)
            })
            
            # PHASE 7: Audit log
            try:
                from sentinel_x.monitoring.audit_logger import log_audit_event
                log_audit_event(
                    event_type="STRATEGY_DEMOTED",
                    request_id=f"demote_{strategy_name}_{datetime.now().isoformat()}",
                    metadata={
                        "strategy_name": strategy_name,
                        "from_lifecycle": current_lifecycle.value,
                        "to_lifecycle": StrategyLifecycleState.DISABLED.value,
                        "reason": reason,
                        "score": demotion_eval.get('score', 0.0),
                        "timestamp": datetime.now().isoformat()
                    }
                )
            except Exception as e:
                logger.debug(f"Error logging demotion (non-fatal): {e}")
            
            # Persist status change
            try:
                if hasattr(self.storage, 'update_strategy_status'):
                    self.storage.update_strategy_status(strategy_name, StrategyStatus.DISABLED.value)
            except Exception as e:
                logger.warning(f"Failed to persist demoted status for {strategy_name}: {e}")
            
            logger.info(f"Strategy demoted: {strategy_name} (reason: {reason})")
            
            # Emit event (non-blocking)
            try:
                event = {
                    'type': 'strategy_demoted',
                    'strategy': strategy_name,
                    'from': current_lifecycle.value,
                    'to': StrategyLifecycleState.DISABLED.value,
                    'reason': reason,
                    'timestamp': datetime.now().isoformat() + "Z"
                }
                safe_emit(self.event_bus.publish(event)) if self.event_bus else None
            except Exception as e:
                logger.debug(f"Error emitting demotion event (non-fatal): {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error demoting strategy {strategy_name}: {e}", exc_info=True)
            return False
    
    def enforce_governance_limits(self) -> Dict[str, Any]:
        """
        PHASE 6: Enforce governance limits.
        
        If limits exceeded:
        - Prefer demotion over deletion
        - Log governance warning
        - Never stop engine
        
        Returns:
            Dict with actions taken and warnings
        """
        actions = []
        warnings = []
        
        try:
            active_count = len([s for s in self.strategies.keys() 
                               if self.strategy_states.get(s, StrategyLifecycleState.TRAINING) == StrategyLifecycleState.TRAINING
                               and self.status.get(s) == StrategyStatus.ACTIVE])
            
            disabled_count = len([s for s in self.strategies.keys() 
                                 if self.strategy_states.get(s) == StrategyLifecycleState.DISABLED])
            
            total_count = len(self.strategies)
            
            # Check active strategies limit
            if active_count > self.max_active_strategies:
                warning = f"Active strategies limit exceeded: {active_count} > {self.max_active_strategies}"
                warnings.append(warning)
                logger.warning(warning)
                
                # Demote lowest-scoring strategies
                active_strategies = [(s, self.calculate_composite_score(s)) 
                                    for s in self.strategies.keys()
                                    if self.strategy_states.get(s, StrategyLifecycleState.TRAINING) == StrategyLifecycleState.TRAINING
                                    and self.status.get(s) == StrategyStatus.ACTIVE]
                active_strategies.sort(key=lambda x: x[1])  # Sort by score (lowest first)
                
                demote_count = active_count - self.max_active_strategies
                for strategy_name, score in active_strategies[:demote_count]:
                    if self.demote_strategy(strategy_name):
                        actions.append(f"demoted_{strategy_name}_due_to_limit")
            
            # Check disabled strategies limit (soft limit - log warning only)
            if disabled_count > self.max_disabled_strategies:
                warning = f"Disabled strategies soft limit exceeded: {disabled_count} > {self.max_disabled_strategies}"
                warnings.append(warning)
                logger.warning(warning)
                # No action - soft limit, prefer demotion over deletion
            
            # Check total strategies limit (hard cap - log warning)
            if total_count >= self.max_total_strategies:
                warning = f"Total strategies hard limit reached: {total_count} >= {self.max_total_strategies}"
                warnings.append(warning)
                logger.warning(warning)
                # No action - limits prevent new registrations, but don't delete existing
            
            return {
                'actions': actions,
                'warnings': warnings,
                'active_count': active_count,
                'disabled_count': disabled_count,
                'total_count': total_count,
                'limits': {
                    'max_active': self.max_active_strategies,
                    'max_disabled': self.max_disabled_strategies,
                    'max_total': self.max_total_strategies
                }
            }
            
        except Exception as e:
            logger.error(f"Error enforcing governance limits: {e}", exc_info=True)
            return {
                'actions': [],
                'warnings': [f'governance_enforcement_error: {str(e)}'],
                'active_count': 0,
                'disabled_count': 0,
                'total_count': 0,
                'limits': {}
            }
    
    def get_strategy_governance_summary(self, strategy_name: str) -> Dict[str, Any]:
        """
        PHASE 7: Get comprehensive governance summary for a strategy.
        
        Exposes:
        - Strategy lifecycle state
        - Score components
        - Promotion / demotion reason
        - Timestamp of last state change
        - Capital weight
        - Ranking
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            Dict with governance summary
        """
        try:
            if strategy_name not in self.strategies:
                return {
                    'error': 'strategy_not_registered',
                    'strategy_name': strategy_name
                }
            
            lifecycle_state = self.strategy_states.get(strategy_name, StrategyLifecycleState.TRAINING)
            status = self.status.get(strategy_name, StrategyStatus.DISABLED)
            
            # Get normalized metrics
            metrics = self.normalized_metrics.get(strategy_name, {})
            if not metrics:
                self.compute_normalized_metrics(strategy_name)
                metrics = self.normalized_metrics.get(strategy_name, {})
            
            # Calculate composite score
            score = self.calculate_composite_score(strategy_name)
            
            # Get promotion eligibility
            promotion_eligibility = self.evaluate_promotion_eligibility(strategy_name)
            
            # Get demotion evaluation
            demotion_eval = self.evaluate_demotion_conditions(strategy_name)
            
            # Get lifecycle history
            history = self.lifecycle_history.get(strategy_name, [])
            last_transition = history[-1] if history else None
            
            # Get ranking position
            rankings = self.rank_strategies()
            ranking_position = None
            for idx, (name, rank_score, _) in enumerate(rankings):
                if name == strategy_name:
                    ranking_position = idx + 1
                    break
            
            return {
                'strategy_name': strategy_name,
                'lifecycle_state': lifecycle_state.value if isinstance(lifecycle_state, StrategyLifecycleState) else str(lifecycle_state),
                'status': status.value if isinstance(status, StrategyStatus) else str(status),
                'composite_score': score,
                'score_components': {
                    'normalized_expectancy': metrics.get('normalized_expectancy', 0.0),
                    'normalized_sharpe': metrics.get('normalized_sharpe', 0.0),
                    'normalized_win_rate': metrics.get('normalized_win_rate', 0.0),
                    'drawdown_penalty': min(metrics.get('max_drawdown', 0.0) / self.max_drawdown_threshold, 1.0)
                },
                'metrics': metrics,
                'promotion_eligibility': promotion_eligibility,
                'demotion_evaluation': demotion_eval,
                'capital_weight': self.capital_weights.get(strategy_name, 0.0),
                'ranking_position': ranking_position,
                'last_disable_reason': self.last_disable_reason.get(strategy_name),
                'last_transition': last_transition,
                'lifecycle_history': history,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting governance summary for {strategy_name}: {e}", exc_info=True)
            return {
                'error': f'governance_summary_error: {str(e)}',
                'strategy_name': strategy_name
            }
    
    def evaluate_and_govern_strategies(self) -> Dict[str, Any]:
        """
        PHASE 4-5: Periodically evaluate and govern strategies (promote/demote).
        
        This method should be called periodically (e.g., every hour or after N trades)
        to evaluate strategies and apply promotion/demotion rules.
        
        SAFETY: training-only promotion system
        SAFETY: no execution behavior modified
        SAFETY: all decisions explainable and reversible
        
        Rules:
        - Only TRAINING strategies can be promoted/demoted
        - Promotion affects capital_weight and ranking only (remains TRAINING)
        - Demotion sets lifecycle to DISABLED (reversible)
        - Governance limits are enforced
        - Engine continues uninterrupted
        
        Returns:
            Dict with promoted, demoted, and governance actions
        """
        try:
            promoted = []
            demoted = []
            governance_actions = []
            
            # Get all TRAINING strategies
            training_strategies = [
                name for name, state in self.strategy_states.items()
                if state == StrategyLifecycleState.TRAINING
            ]
            
            # Evaluate each strategy for promotion/demotion
            for strategy_name in training_strategies:
                try:
                    # Check promotion eligibility
                    promotion_eligibility = self.evaluate_promotion_eligibility(strategy_name)
                    if promotion_eligibility['eligible']:
                        if self.promote_strategy(strategy_name):
                            promoted.append(strategy_name)
                    
                    # Check demotion conditions
                    demotion_eval = self.evaluate_demotion_conditions(strategy_name)
                    if demotion_eval['should_demote']:
                        if self.demote_strategy(strategy_name):
                            demoted.append(strategy_name)
                
                except Exception as e:
                    logger.error(f"Error evaluating strategy {strategy_name}: {e}", exc_info=True)
                    # Continue with next strategy - don't block governance
            
            # Enforce governance limits
            governance_result = self.enforce_governance_limits()
            governance_actions = governance_result.get('actions', [])
            warnings = governance_result.get('warnings', [])
            
            if warnings:
                for warning in warnings:
                    logger.warning(f"Governance limit warning: {warning}")
            
            # PHASE 7: Audit log governance evaluation
            try:
                from sentinel_x.monitoring.audit_logger import log_audit_event
                log_audit_event(
                    event_type="STRATEGY_GOVERNANCE_EVAL",
                    request_id=f"governance_{datetime.now().isoformat()}",
                    metadata={
                        "promoted": promoted,
                        "demoted": demoted,
                        "governance_actions": governance_actions,
                        "warnings": warnings,
                        "timestamp": datetime.now().isoformat()
                    }
                )
            except Exception as e:
                logger.debug(f"Error logging governance evaluation (non-fatal): {e}")
            
            logger.info(f"Strategy governance evaluation complete: {len(promoted)} promoted, {len(demoted)} demoted")
            
            return {
                'promoted': promoted,
                'demoted': demoted,
                'governance_actions': governance_actions,
                'warnings': warnings,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in strategy governance evaluation: {e}", exc_info=True)
            return {
                'promoted': [],
                'demoted': [],
                'governance_actions': [],
                'warnings': [f'governance_evaluation_error: {str(e)}'],
                'timestamp': datetime.now().isoformat()
            }
    
    def _load_status_from_storage(self) -> None:
        """Load strategy status from storage."""
        try:
            if hasattr(self.storage, 'get_all_strategy_statuses'):
                statuses = self.storage.get_all_strategy_statuses()
                for name, status_str in statuses.items():
                    try:
                        # Map old DISABLED to AUTO_DISABLED if needed (preserve existing behavior)
                        if status_str == "DISABLED":
                            # Check if we have a disable reason to determine if it was auto-disabled
                            # For now, default to DISABLED (manual)
                            self.status[name] = StrategyStatus.DISABLED
                        else:
                            self.status[name] = StrategyStatus(status_str)
                    except ValueError:
                        self.status[name] = StrategyStatus.ACTIVE  # Default to ACTIVE
        except Exception as e:
            logger.warning(f"Error loading strategy status from storage: {e}")
    
    def get_strategy_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        PHASE 2 — STRATEGY METRICS AGGREGATION
        
        Get canonical metrics snapshot for all strategies.
        
        Returns:
            Dictionary mapping strategy name to metrics dict:
            {
                "enabled": bool,
                "allocation_weight": float,
                "pnl_realized": float,
                "pnl_unrealized": float,
                "pnl_total": float,
                "trades": int,
                "wins": int,
                "losses": int,
                "win_rate": float | None,
                "last_update_age": float | None
            }
        
        SAFETY: Read-only operation, never raises
        """
        import time
        snapshot = {}
        now = time.time()
        
        try:
            for strat_name, strat in self.strategies.items():
                try:
                    # PHASE 2: Extract metrics from BaseStrategy instance
                    # Use safe attribute access to handle missing fields
                    pnl_realized = getattr(strat, "pnl_realized", 0.0)
                    pnl_unrealized = getattr(strat, "pnl_unrealized", 0.0)
                    trades = getattr(strat, "trades", 0)
                    wins = getattr(strat, "wins", 0)
                    losses = getattr(strat, "losses", 0)
                    last_update_ts = getattr(strat, "last_update_ts", None)
                    
                    # Calculate derived metrics
                    pnl_total = pnl_realized + pnl_unrealized
                    win_rate = (wins / trades) if trades > 0 else None
                    last_update_age = (
                        (now - last_update_ts) if last_update_ts else None
                    )
                    
                    snapshot[strat_name] = {
                        "enabled": getattr(strat, "enabled", True),
                        "allocation_weight": getattr(strat, "allocation_weight", 1.0),
                        "pnl_realized": float(pnl_realized),
                        "pnl_unrealized": float(pnl_unrealized),
                        "pnl_total": float(pnl_total),
                        "trades": int(trades),
                        "wins": int(wins),
                        "losses": int(losses),
                        "win_rate": round(win_rate, 4) if win_rate is not None else None,
                        "last_update_age": round(last_update_age, 2) if last_update_age is not None else None
                    }
                except Exception as e:
                    # SAFETY: Skip broken strategies, continue with others
                    logger.debug(f"Error getting metrics for strategy {strat_name}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error in get_strategy_metrics: {e}", exc_info=True)
            # Return empty dict on error (never raise)
            return {}
        
        return snapshot
    
    def get_strategy_performance(self) -> Dict[str, Dict[str, Any]]:
        """
        PHASE 2 — MOBILE VISUALIZATION: Strategy Performance Snapshot
        
        Get strategy performance data including time-series for mobile charts.
        
        REGRESSION LOCK — mobile charts are read-only
        REGRESSION LOCK — no persistence
        
        Returns:
            Dictionary mapping strategy name to performance dict:
            {
                "allocation_weight": float,
                "trades": int,
                "pnl_total": float,
                "timeseries": [[timestamp, pnl_total], ...]  # List of [ts, pnl] tuples
            }
        
        SAFETY:
        - Read-only operation, never raises
        - Safe if no strategies exist (returns empty dict)
        - Updates timeseries before reading (ensures latest point included)
        - Timeseries may be empty (UI must handle gracefully)
        - Memory bounded (max 1000 points per strategy)
        """
        out = {}
        
        try:
            for name, strategy in self.strategies.items():
                try:
                    # PHASE 2: Update timeseries with current PnL before reading
                    # This ensures we capture the latest point
                    if hasattr(strategy, 'update_pnl_timeseries'):
                        strategy.update_pnl_timeseries()
                    
                    # Extract performance data with safe attribute access
                    allocation_weight = getattr(strategy, 'allocation_weight', 1.0)
                    trades = getattr(strategy, 'trades', 0)
                    pnl_realized = getattr(strategy, 'pnl_realized', 0.0)
                    pnl_unrealized = getattr(strategy, 'pnl_unrealized', 0.0)
                    pnl_total = pnl_realized + pnl_unrealized
                    
                    # Extract timeseries (may be empty)
                    timeseries = []
                    if hasattr(strategy, 'pnl_timeseries'):
                        try:
                            # Convert deque to list of tuples (already in correct format)
                            timeseries = list(strategy.pnl_timeseries)
                        except Exception:
                            # If timeseries access fails, use empty list
                            timeseries = []
                    
                    out[name] = {
                        "allocation_weight": float(allocation_weight),
                        "trades": int(trades),
                        "pnl_total": float(pnl_total),
                        "timeseries": timeseries,  # List of [timestamp, pnl_total] tuples
                    }
                except Exception as e:
                    # SAFETY: Skip broken strategies, continue with others
                    logger.debug(f"Error getting performance for strategy {name}: {e}")
                    continue
        except Exception as e:
            logger.error(f"Error in get_strategy_performance: {e}", exc_info=True)
            # Return empty dict on error (never raise)
            return {}
        
        return out


# Global strategy manager instance
_manager = None


def get_strategy_manager(storage: Optional[Storage] = None, **kwargs) -> StrategyManager:
    """Get global strategy manager instance."""
    global _manager
    if _manager is None:
        _manager = StrategyManager(storage, **kwargs)
    return _manager

