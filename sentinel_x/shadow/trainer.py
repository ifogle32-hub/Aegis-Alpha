"""
PHASE 3 — SHADOW TRAINER CORE

ShadowTrainer: Main coordinator for shadow training operations.

DEPENDENCY RULES:
- Trainer OWNS heartbeat (creates instance in __init__)
- Trainer NEVER imported by heartbeat
- Trainer calls heartbeat.beat() with parameters (heartbeat is passive)
- Trainer tracks tick_counter locally
- Trainer exposes get_status() that aggregates state

Why trainer owns heartbeat:
- Eliminates circular imports (trainer → heartbeat, one direction)
- Heartbeat is passive - never fetches state from trainer
- Trainer provides all data to heartbeat.beat() method
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import threading
import time

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.definitions import ShadowMode, SHADOW_GUARANTEES
from sentinel_x.shadow.feed import MarketFeed, MarketTick, create_market_feed
from sentinel_x.shadow.registry import StrategyRegistry, get_strategy_registry
from sentinel_x.shadow.simulator import SimulationEngine, get_simulation_engine
from sentinel_x.shadow.scorer import ShadowScorer, get_shadow_scorer
from sentinel_x.shadow.regime import RegimeAnalyzer, get_regime_analyzer
from sentinel_x.shadow.persistence import ShadowPersistence, get_shadow_persistence
from sentinel_x.shadow.promotion import PromotionEvaluator, get_promotion_evaluator
# PHASE 1: Lazy import to avoid circular imports at module level
# from sentinel_x.shadow.heartbeat import ShadowHeartbeatMonitor
from sentinel_x.shadow.governance import get_shadow_governance
from sentinel_x.strategies.base import BaseStrategy


@dataclass
class ShadowTrainerConfig:
    """
    Shadow trainer configuration.
    """
    enabled: bool = True
    replay_mode: ShadowMode = ShadowMode.LIVE
    initial_capital: float = 100000.0
    tick_interval: float = 1.0  # Seconds between ticks
    metrics_window_days: int = 30  # Metrics computation window
    auto_evaluate_promotion: bool = True  # Auto-evaluate promotion eligibility


class ShadowTrainer:
    """
    Shadow training coordinator.
    
    Responsibilities:
    - Receive market ticks
    - Dispatch ticks to registered strategies
    - Capture emitted signals
    - Pass signals to simulation engine
    - Record outcomes
    - Compute metrics
    - Evaluate promotion eligibility
    
    SAFETY GUARANTEES:
    - Cannot execute trades
    - Cannot mutate live positions
    - Can be paused/resumed
    - Failures cannot crash engine
    """
    
    def __init__(
        self,
        config: Optional[ShadowTrainerConfig] = None,
        heartbeat_monitor: Optional[Any] = None,
    ):
        """
        Initialize shadow trainer.
        
        PHASE 1: Trainer receives heartbeat via injection to eliminate circular imports.
        Trainer must NOT import heartbeat at module level.
        
        Args:
            config: Optional trainer configuration
            heartbeat_monitor: Optional heartbeat monitor (injected by runtime)
        """
        self.config = config or ShadowTrainerConfig()
        
        # Core components
        self.registry = get_strategy_registry()
        self.simulator = get_simulation_engine(initial_capital=self.config.initial_capital)
        self.scorer = get_shadow_scorer()
        self.regime_analyzer = get_regime_analyzer()
        self.persistence = get_shadow_persistence()
        self.promotion_evaluator = get_promotion_evaluator()
        # PHASE 1: Heartbeat injected by runtime - NO import here
        self.heartbeat_monitor = heartbeat_monitor
        self.governance = get_shadow_governance()
        
        # State
        self.training_active = False
        self.tick_counter = 0
        self.last_tick_time: Optional[datetime] = None
        self.last_step_ts: Optional[float] = None
        self.heartbeat: datetime = datetime.utcnow()
        
        # Market feed (will be initialized when started)
        self.market_feed: Optional[MarketFeed] = None
        
        # Thread safety
        self._lock = threading.RLock()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_running = False
        
        logger.info("ShadowTrainer initialized")
    
    def start(self, symbols: List[str]) -> None:
        """
        Start shadow training.
        
        Args:
            symbols: List of symbols to track
        """
        with self._lock:
            if self.training_active:
                logger.warning("Shadow training already active")
                return
            
            # Create market feed
            self.market_feed = create_market_feed(
                mode=self.config.replay_mode,
                symbols=symbols,
            )
            
            # Start feed
            self.market_feed.start()
            
            # Log replay start if in replay mode
            if hasattr(self.market_feed, 'start_date') and hasattr(self.market_feed, 'end_date'):
                self.governance.log_replay_start(
                    start_date=self.market_feed.start_date,
                    end_date=self.market_feed.end_date,
                    symbols=symbols,
                    replay_mode=str(self.market_feed.replay_mode) if hasattr(self.market_feed, 'replay_mode') else "unknown",
                )
            
            # Reset simulator
            self.simulator.reset()
            
            # Start training
            self.training_active = True
            self.tick_counter = 0
            self.last_tick_time = datetime.utcnow()
            self.heartbeat = datetime.utcnow()
            
            # Start watchdog
            self._start_watchdog()
            
            logger.info(
                f"Shadow training started | mode={self.config.replay_mode.value} | "
                f"symbols={len(symbols)}"
            )
    
    def stop(self) -> None:
        """Stop shadow training."""
        with self._lock:
            if not self.training_active:
                return
            
            # Stop feed
            if self.market_feed:
                self.market_feed.stop()
                
                # Log replay stop if in replay mode
                if hasattr(self.market_feed, 'start_date'):
                    self.governance.log_replay_stop(reason="manual stop")
            
            # Stop training
            self.training_active = False
            
            # Stop watchdog
            self._stop_watchdog()
            
            logger.info("Shadow training stopped")
    
    def start_training(self) -> None:
        """Activate training loop."""
        self.training_active = True
        self.last_step_ts = time.time()
    
    def step(self) -> None:
        """
        Execute one training step.
        
        Processes one tick from the market feed if available.
        """
        if not self.training_active:
            return
        
        if not self.market_feed or not self.market_feed.running:
            return
        
        # Get next tick from feed
        if hasattr(self.market_feed, 'get_next_tick'):
            tick = self.market_feed.get_next_tick()
            if tick:
                self.process_tick(tick)
                self.last_step_ts = time.time()
                if self.heartbeat_monitor:
                    self.heartbeat_monitor.tick()
    
    def pause(self) -> None:
        """Pause shadow training (can be resumed)."""
        with self._lock:
            if not self.training_active:
                return
            
            if self.market_feed:
                self.market_feed.stop()
            
            logger.info("Shadow training paused")
    
    def resume(self) -> None:
        """Resume shadow training."""
        with self._lock:
            if not self.training_active:
                logger.warning("Cannot resume: training not active")
                return
            
            if self.market_feed:
                self.market_feed.start()
            
            logger.info("Shadow training resumed")
    
    def process_tick(self, tick: MarketTick) -> None:
        """
        Process market tick.
        
        This is the main entry point for tick processing.
        Called from engine loop or feed callbacks.
        
        Args:
            tick: Market tick
        """
        if not self.config.enabled or not self.training_active:
            return
        
        try:
            with self._lock:
                self.tick_counter += 1
                self.last_tick_time = tick.timestamp
                self.heartbeat = datetime.utcnow()
            
            # Analyze regime
            regime_snapshot = self.regime_analyzer.analyze_tick(tick)
            self.persistence.save_regime_snapshot(regime_snapshot)
            
            # Process tick in simulator (fill pending orders)
            filled_orders = self.simulator.process_tick(tick)
            
            # Record filled orders
            for order in filled_orders:
                if order.status.value in ("FILLED", "PARTIAL"):
                    # Calculate PnL (simplified)
                    pnl = None  # Will be calculated by position tracking
                    
                    self.scorer.record_trade(
                        strategy_id=order.strategy_id,
                        symbol=order.symbol,
                        side=order.side.value,
                        quantity=order.filled_quantity,
                        fill_price=order.fill_price or 0.0,
                        timestamp=order.fill_timestamp or tick.timestamp,
                        pnl=pnl,
                    )
                    
                    self.persistence.save_trade(
                        strategy_id=order.strategy_id,
                        symbol=order.symbol,
                        side=order.side.value,
                        quantity=order.filled_quantity,
                        fill_price=order.fill_price or 0.0,
                        timestamp=order.fill_timestamp or tick.timestamp,
                        pnl=pnl,
                    )
            
            # Dispatch tick to all registered strategies
            strategies = self.registry.get_all_strategies()
            
            for strategy_id, strategy in strategies.items():
                try:
                    # Get strategy state
                    strategy_state = self.registry.get_state(strategy_id)
                    
                    # Call strategy on_tick (create market data dict)
                    market_data = {
                        "symbol": tick.symbol,
                        "price": tick.price,
                        "volume": tick.volume,
                        "timestamp": tick.timestamp,
                        "bid": tick.bid,
                        "ask": tick.ask,
                        "high": tick.high,
                        "low": tick.low,
                        "open": tick.open,
                        "close": tick.close,
                    }
                    
                    # Call strategy
                    order_intent = strategy.safe_on_tick(market_data) if hasattr(strategy, 'safe_on_tick') else None
                    
                    if order_intent:
                        # Submit order to simulator
                        order = self.simulator.submit_order(
                            strategy_id=strategy_id,
                            symbol=order_intent.get("symbol", tick.symbol),
                            side=order_intent.get("side", "BUY"),
                            quantity=order_intent.get("qty", 0),
                            order_type=order_intent.get("order_type", "MARKET"),
                            price=order_intent.get("price"),
                            stop_price=order_intent.get("stop_price"),
                        )
                        
                        logger.debug(
                            f"Shadow signal: {strategy_id} | "
                            f"symbol={order.symbol} | side={order.side.value}"
                        )
                
                except Exception as e:
                    logger.error(
                        f"Error processing tick for strategy {strategy_id}: {e}",
                        exc_info=True,
                    )
                    # Continue with other strategies
            
            # Update equity curve
            current_prices = {tick.symbol: tick.price}
            portfolio_value = self.simulator.get_portfolio_value(current_prices)
            
            for strategy_id in strategies.keys():
                self.scorer.record_equity(
                    strategy_id=strategy_id,
                    timestamp=tick.timestamp,
                    equity=portfolio_value,  # Simplified: same portfolio for all
                )
            
            # Periodic metrics computation
            if self.tick_counter % 100 == 0:  # Every 100 ticks
                self._compute_metrics()
            
            # Periodic promotion evaluation
            if self.config.auto_evaluate_promotion and self.tick_counter % 1000 == 0:
                self._evaluate_promotions()
            
            # PHASE 1: Emit heartbeat every N ticks
            # Trainer calls heartbeat.beat() with all required parameters
            # Heartbeat is passive - it never fetches state from trainer
            if self.heartbeat_monitor and self.tick_counter % self.heartbeat_monitor.heartbeat_interval_ticks == 0:
                # Determine feed type
                feed_type = "unknown"
                if self.market_feed:
                    if hasattr(self.market_feed, 'mode'):
                        feed_type = self.market_feed.mode.value if hasattr(self.market_feed.mode, 'value') else str(self.market_feed.mode)
                    elif hasattr(self.market_feed, 'replay_mode'):
                        feed_type = "replay"
                    else:
                        feed_type = "live"
                
                # Get active strategies count
                active_strategies = len(self.registry.get_all_strategies())
                
                # Get error count (simplified - would track errors in trainer)
                error_count = 0  # TODO: Track errors in trainer
                
                # Call heartbeat.beat() with all parameters
                self.heartbeat_monitor.beat(
                    tick_count=self.tick_counter,
                    trainer_alive=self.training_active,
                    active_strategies=active_strategies,
                    feed_type=feed_type,
                    error_count=error_count,
                    last_tick_ts=self.last_tick_time,
                )
        
        except Exception as e:
            # SAFETY: Failures cannot crash engine
            logger.error(f"Error in shadow training tick processing: {e}", exc_info=True)
    
    def register_strategy(
        self,
        strategy: BaseStrategy,
        description: Optional[str] = None,
        risk_profile: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Register strategy for shadow training.
        
        Args:
            strategy: Strategy instance
            description: Optional description
            risk_profile: Optional risk profile
            config: Optional configuration
            
        Returns:
            Strategy ID
        """
        strategy_id = self.registry.register(
            strategy,
            description=description,
            risk_profile=risk_profile,
            config=config,
        )
        
        # Save snapshot
        self.persistence.save_strategy_snapshot(
            strategy_id=strategy_id,
            version_hash=self.registry.get_metadata(strategy_id).version_hash,
            snapshot_data={
                "name": strategy.name if hasattr(strategy, 'name') else strategy.__class__.__name__,
                "description": description,
                "risk_profile": risk_profile,
                "config": config,
            },
        )
        
        # Log audit event
        self.persistence.log_audit_event(
            "STRATEGY_REGISTERED",
            strategy_id,
            {
                "name": strategy.name if hasattr(strategy, 'name') else strategy.__class__.__name__,
            },
        )
        
        return strategy_id
    
    def unregister_strategy(self, strategy_id: str) -> bool:
        """
        Unregister strategy.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            True if unregistered
        """
        success = self.registry.unregister(strategy_id)
        
        if success:
            self.persistence.log_audit_event(
                "STRATEGY_UNREGISTERED",
                strategy_id,
                {},
            )
        
        return success
    
    def _compute_metrics(self) -> None:
        """Compute metrics for all strategies."""
        try:
            strategies = self.registry.get_all_strategies()
            window_end = datetime.utcnow()
            window_start = window_end - timedelta(days=self.config.metrics_window_days)
            
            for strategy_id in strategies.keys():
                try:
                    metrics = self.scorer.compute_metrics(
                        strategy_id=strategy_id,
                        window_start=window_start,
                        window_end=window_end,
                        initial_capital=self.config.initial_capital,
                    )
                    
                    # Save metrics
                    self.persistence.save_metrics(metrics)
                    
                    # Log evaluation result
                    self.governance.log_strategy_evaluation(
                        strategy_id=strategy_id,
                        evaluation_result=metrics.to_dict(),
                    )
                    
                except Exception as e:
                    logger.error(f"Error computing metrics for {strategy_id}: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"Error in metrics computation: {e}", exc_info=True)
    
    def _evaluate_promotions(self) -> None:
        """Evaluate promotion eligibility for all strategies."""
        try:
            strategies = self.registry.get_all_strategies()
            
            for strategy_id in strategies.keys():
                try:
                    metadata = self.registry.get_metadata(strategy_id)
                    if metadata:
                        evaluation = self.promotion_evaluator.evaluate(
                            strategy_id=strategy_id,
                            registration_time=metadata.registered_at,
                        )
                        
                        # Save evaluation
                        self.persistence.save_promotion_evaluation(
                            strategy_id=strategy_id,
                            state=evaluation.state,
                            evaluation_data=evaluation.to_dict(),
                        )
                        
                        # Log promotion eligibility change
                        old_state = self.promotion_evaluator.get_current_state(strategy_id)
                        if old_state != evaluation.state:
                            self.governance.log_promotion_eligibility_change(
                                strategy_id=strategy_id,
                                old_state=old_state.value,
                                new_state=evaluation.state.value,
                                reason=evaluation.reason,
                            )
                
                except Exception as e:
                    logger.error(f"Error evaluating promotion for {strategy_id}: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"Error in promotion evaluation: {e}", exc_info=True)
    
    def _start_watchdog(self) -> None:
        """Start watchdog thread."""
        if self._watchdog_running:
            return
        
        self._watchdog_running = True
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="ShadowTrainerWatchdog",
        )
        self._watchdog_thread.start()
        logger.debug("Shadow trainer watchdog started")
    
    def _stop_watchdog(self) -> None:
        """Stop watchdog thread."""
        self._watchdog_running = False
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5.0)
        logger.debug("Shadow trainer watchdog stopped")
    
    def _watchdog_loop(self) -> None:
        """
        Watchdog loop to detect stalled training.
        
        PHASE 5: Sleep-based loop with minimum 1.0s sleep to reduce CPU usage.
        """
        while self._watchdog_running:
            try:
                time.sleep(30.0)  # PHASE 5: Check every 30 seconds (sleep-based, no busy-wait)
                
                if not self.training_active:
                    continue
                
                # Check heartbeat age
                heartbeat_age = (datetime.utcnow() - self.heartbeat).total_seconds()
                
                if heartbeat_age > 60:  # No tick in 60 seconds
                    logger.warning(
                        f"Shadow training appears stalled | "
                        f"heartbeat_age={heartbeat_age:.1f}s | "
                        f"tick_counter={self.tick_counter}"
                    )
                    
                    # Attempt restart (if feed stopped)
                    if self.market_feed and not self.market_feed.running:
                        logger.info("Attempting to restart shadow market feed")
                        try:
                            self.market_feed.start()
                        except Exception as e:
                            logger.error(f"Error restarting feed: {e}", exc_info=True)
            
            except Exception as e:
                logger.error(f"Error in watchdog loop: {e}", exc_info=True)
    
    def get_status(self) -> Dict[str, Any]:
        """
        PHASE 3: Get trainer status.
        
        Aggregates:
        - tick_counter (local)
        - heartbeat status (from heartbeat monitor)
        - error state
        - training state
        
        Returns:
            Status dictionary
        """
        with self._lock:
            # Get heartbeat status (if available)
            heartbeat_status = {}
            if self.heartbeat_monitor:
                try:
                    heartbeat_status = self.heartbeat_monitor.get_status()
                except Exception:
                    pass
            
            return {
                "enabled": self.config.enabled,
                "training_active": self.training_active,
                "replay_mode": self.config.replay_mode.value,
                "tick_counter": self.tick_counter,
                "heartbeat": self.heartbeat.isoformat() + "Z",
                "last_tick_time": self.last_tick_time.isoformat() + "Z" if self.last_tick_time else None,
                "registered_strategies": len(self.registry.get_all_strategies()),
                "guarantees": SHADOW_GUARANTEES.to_dict(),
                "heartbeat_status": heartbeat_status,
            }


# Global trainer instance
_trainer: Optional[ShadowTrainer] = None
# PHASE 7: Lock created lazily to avoid import-time side effects
_trainer_lock: Optional[threading.Lock] = None


def get_shadow_trainer(config: Optional[ShadowTrainerConfig] = None) -> ShadowTrainer:
    """
    Get global shadow trainer instance (singleton).
    
    PHASE 7: Lock created lazily on first call to avoid import-time side effects.
    Trainer is only created when explicitly requested, not at import time.
    
    Args:
        config: Optional trainer configuration
        
    Returns:
        ShadowTrainer instance
    """
    global _trainer, _trainer_lock
    
    if _trainer_lock is None:
        _trainer_lock = threading.Lock()
    
    if _trainer is None:
        with _trainer_lock:
            if _trainer is None:
                _trainer = ShadowTrainer(config)
    
    return _trainer
