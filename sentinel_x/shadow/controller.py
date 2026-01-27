"""
PHASE 4 — SHADOW TRAINING CONTROLLER

ShadowTrainingController: Manages shadow training lifecycle.

PHASE 7 — STARTUP ORDER (ENFORCED):
1. python -m api.main
2. api.shadow_routes
3. sentinel_x.shadow.status
4. sentinel_x.shadow.controller (THIS MODULE)
5. sentinel_x.shadow.trainer (lazy - only when start() called)
6. sentinel_x.shadow.heartbeat (owned by trainer)

No other order is allowed.

DEPENDENCY RULES:
- Controller OWNS trainer (lazy construction)
- Controller NEVER imported by trainer or heartbeat
- Controller is the ONLY component allowed to start/stop training
- Controller exposes lightweight get_status() snapshot
- No threads started at import time
- Locks created lazily on first get_* call

DAEMON SAFETY (PHASE 8):
- No background threads start at import time
- No singleton trainers created during import
- All runtime wiring happens after engine startup
- Safe for: python -m api.main, gunicorn --workers 1, launchd restarts

Responsibilities:
- Start shadow training exactly once
- Track training lifecycle (STARTING, RUNNING, PAUSED, ERROR)
- Attach to engine tick loop safely
- Prevent duplicate threads on restart
- Support replay-driven training

SAFETY GUARANTEES:
- Shadow training may NEVER place real trades
- Shadow training may NEVER touch execution adapters
- Replay replaces live feeds entirely
- Only ONE instance may run at a time
"""

import threading
import time
from typing import Optional, Dict, Any, TYPE_CHECKING
from enum import Enum
from datetime import datetime

from sentinel_x.monitoring.logger import logger
# PHASE 7: Lazy imports - avoid heavy dependencies at import time
# Feed imports are lazy to avoid numpy/pandas dependencies
# TYPE_CHECKING: Only import for type hints, not at runtime
if TYPE_CHECKING:
    from sentinel_x.shadow.trainer import ShadowTrainer
    from sentinel_x.shadow.replay import HistoricalReplayFeed
    from sentinel_x.shadow.feed import MarketFeed, MarketTick


class TrainingState(str, Enum):
    """Shadow training lifecycle states."""
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    STOPPING = "STOPPING"


class ShadowTrainingController:
    """
    Controller for shadow training lifecycle.
    
    Ensures:
    - Training starts exactly once
    - No duplicate trainers on restart
    - Safe attachment to engine loop
    - Replay-driven training support
    """
    
    def __init__(self):
        """Initialize shadow training controller."""
        self._lock = threading.RLock()
        self._state = TrainingState.IDLE
        # PHASE 4: Trainer is lazily constructed (not imported at module level)
        self._trainer: Optional['ShadowTrainer'] = None
        self._replay_feed: Optional['HistoricalReplayFeed'] = None
        self._started = False
        self._error_count = 0
        self._last_error: Optional[str] = None
        self._last_heartbeat: Optional[datetime] = None
        
        # Thread safety
        self._training_thread: Optional[threading.Thread] = None
        self._training_thread_running = False
        
        logger.info("ShadowTrainingController initialized")
    
    def is_enabled(self) -> bool:
        """Check if shadow training is enabled."""
        with self._lock:
            return self._state in (TrainingState.STARTING, TrainingState.RUNNING, TrainingState.PAUSED)
    
    def get_state(self) -> TrainingState:
        """Get current training state."""
        with self._lock:
            return self._state
    
    def start(
        self,
        symbols: list,
        replay_feed: Optional['HistoricalReplayFeed'] = None,
        replay_mode: bool = False,
    ) -> bool:
        """
        Start shadow training.
        
        Args:
            symbols: List of symbols to train on
            replay_feed: Optional historical replay feed
            replay_mode: If True, use replay feed instead of live feed
        
        Returns:
            True if started successfully, False otherwise
        
        SAFETY:
        - Prevents duplicate starts
        - Never touches execution adapters
        - Replay feed blocks live feeds
        """
        with self._lock:
            # Prevent duplicate starts
            if self._started and self._state in (TrainingState.STARTING, TrainingState.RUNNING):
                logger.warning("Shadow training already started")
                return False
            
            # Set state to STARTING
            self._state = TrainingState.STARTING
            self._started = True
            
            try:
                # PHASE 1: Check if runtime already has trainer (runtime owns trainer)
                # If runtime has trainer, use it. Otherwise create new one.
                from sentinel_x.shadow.runtime import get_shadow_runtime
                runtime = get_shadow_runtime()
                runtime_trainer = runtime.get_trainer()
                
                if runtime_trainer:
                    # PHASE 1: Use trainer from runtime (runtime owns it)
                    self._trainer = runtime_trainer
                    logger.debug("Controller using trainer from ShadowRuntime")
                elif self._trainer is None:
                    # PHASE 1: Fallback - create trainer if runtime doesn't have one
                    # This should not happen in normal flow, but provides safety
                    from sentinel_x.shadow.trainer import ShadowTrainer, ShadowTrainerConfig
                    from sentinel_x.shadow.definitions import ShadowMode
                    
                    config = ShadowTrainerConfig(
                        enabled=True,
                        replay_mode=ShadowMode.LIVE if not replay_mode else ShadowMode.HISTORICAL,
                    )
                    # PHASE 1: Create trainer without heartbeat (runtime will inject)
                    self._trainer = ShadowTrainer(config, heartbeat_monitor=None)
                    logger.warning("Controller created trainer without runtime (fallback)")
                
                # Set replay feed if provided
                if replay_feed:
                    self._replay_feed = replay_feed
                    # Replay feed replaces live feed entirely
                    logger.info("Replay feed configured - live feeds blocked")
                
                # Start trainer
                self._trainer.start(symbols)
                
                # If replay feed, attach it to trainer
                if self._replay_feed:
                    self._trainer.market_feed = self._replay_feed
                    self._replay_feed.start()
                
                # Start training thread
                self._start_training_thread()
                
                # Set state to RUNNING
                self._state = TrainingState.RUNNING
                self._last_heartbeat = datetime.utcnow()
                self._error_count = 0
                self._last_error = None
                
                logger.info(
                    f"Shadow training started | "
                    f"symbols={len(symbols)} | "
                    f"replay_mode={replay_mode}"
                )
                
                return True
                
            except Exception as e:
                self._state = TrainingState.ERROR
                self._error_count += 1
                self._last_error = str(e)
                logger.error(f"Error starting shadow training: {e}", exc_info=True)
                return False
    
    def stop(self) -> None:
        """Stop shadow training."""
        with self._lock:
            if self._state == TrainingState.IDLE:
                return
            
            self._state = TrainingState.STOPPING
            
            try:
                # Stop training thread
                self._stop_training_thread()
                
                # Stop replay feed
                if self._replay_feed:
                    self._replay_feed.stop()
                
                # Stop trainer
                if self._trainer:
                    self._trainer.stop()
                
                self._state = TrainingState.IDLE
                self._started = False
                
                logger.info("Shadow training stopped")
                
            except Exception as e:
                self._state = TrainingState.ERROR
                self._error_count += 1
                self._last_error = str(e)
                logger.error(f"Error stopping shadow training: {e}", exc_info=True)
    
    def pause(self) -> None:
        """Pause shadow training."""
        with self._lock:
            if self._state != TrainingState.RUNNING:
                return
            
            try:
                if self._trainer:
                    self._trainer.pause()
                
                if self._replay_feed:
                    self._replay_feed.pause()
                
                self._state = TrainingState.PAUSED
                logger.info("Shadow training paused")
                
            except Exception as e:
                self._error_count += 1
                self._last_error = str(e)
                logger.error(f"Error pausing shadow training: {e}", exc_info=True)
    
    def resume(self) -> None:
        """Resume shadow training."""
        with self._lock:
            if self._state != TrainingState.PAUSED:
                return
            
            try:
                if self._trainer:
                    self._trainer.resume()
                
                if self._replay_feed:
                    self._replay_feed.resume()
                
                self._state = TrainingState.RUNNING
                self._last_heartbeat = datetime.utcnow()
                logger.info("Shadow training resumed")
                
            except Exception as e:
                self._state = TrainingState.ERROR
                self._error_count += 1
                self._last_error = str(e)
                logger.error(f"Error resuming shadow training: {e}", exc_info=True)
    
    def process_tick(self, tick: 'MarketTick') -> None:
        """
        Process market tick in shadow training.
        
        Called from engine loop.
        
        SAFETY:
        - Never executes trades
        - Never touches execution adapters
        - Only simulates outcomes
        """
        # PHASE 7: Lazy import to avoid numpy dependency at import time
        from sentinel_x.shadow.feed import MarketTick
        
        if not self.is_enabled():
            return
        
        try:
            with self._lock:
                if self._state != TrainingState.RUNNING:
                    return
                
                if self._trainer:
                    self._trainer.process_tick(tick)
                    self._last_heartbeat = datetime.utcnow()
                    
        except Exception as e:
            self._error_count += 1
            self._last_error = str(e)
            logger.error(f"Error processing tick in shadow training: {e}", exc_info=True)
            # SAFETY: Errors don't crash engine - continue running
    
    def _start_training_thread(self) -> None:
        """Start training thread for replay processing."""
        if self._training_thread_running:
            return
        
        self._training_thread_running = True
        self._training_thread = threading.Thread(
            target=self._training_loop,
            daemon=True,
            name="ShadowTrainingLoop",
        )
        self._training_thread.start()
        logger.debug("Shadow training thread started")
    
    def _stop_training_thread(self) -> None:
        """Stop training thread."""
        self._training_thread_running = False
        if self._training_thread:
            self._training_thread.join(timeout=5.0)
        logger.debug("Shadow training thread stopped")
    
    def _training_loop(self) -> None:
        """
        Training loop for replay feed processing.
        
        PHASE 5: Sleep-based loop with minimum 0.5s sleep to reduce CPU usage.
        """
        while self._training_thread_running:
            try:
                if self._state != TrainingState.RUNNING:
                    time.sleep(0.5)  # PHASE 5: Minimum 0.5s sleep (no busy-wait)
                    continue
                
                # Check trainer training_active flag and call step()
                if self._trainer and self._trainer.training_active:
                    self._trainer.step()
                    time.sleep(0.1)  # Small sleep between steps
                else:
                    # Process replay feed if active (fallback)
                    if self._replay_feed and self._replay_feed.running:
                        tick = self._replay_feed.get_next_tick()
                        if tick:
                            self.process_tick(tick)
                        else:
                            # Replay finished
                            logger.info("Replay feed finished")
                            time.sleep(0.5)  # PHASE 5: Minimum 0.5s sleep
                    else:
                        # No replay feed - wait for ticks from engine
                        time.sleep(0.5)  # PHASE 5: Minimum 0.5s sleep (no busy-wait)
                
            except Exception as e:
                self._error_count += 1
                self._last_error = str(e)
                logger.error(f"Error in training loop: {e}", exc_info=True)
                time.sleep(1.0)  # Back off on error
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get controller status.
        
        Returns:
            Status dictionary
        """
        with self._lock:
            heartbeat_age_ms = None
            if self._last_heartbeat:
                age = (datetime.utcnow() - self._last_heartbeat).total_seconds()
                heartbeat_age_ms = int(age * 1000)
            
            return {
                "enabled": self.is_enabled(),
                "state": self._state.value,
                "started": self._started,
                "error_count": self._error_count,
                "last_error": self._last_error,
                "heartbeat_age_ms": heartbeat_age_ms,
                "has_replay_feed": self._replay_feed is not None,
                "replay_active": self._replay_feed.running if self._replay_feed else False,
            }


# Global controller instance
_controller: Optional[ShadowTrainingController] = None
# PHASE 7: Lock created lazily to avoid import-time side effects
_controller_lock: Optional[threading.Lock] = None


def get_shadow_training_controller() -> ShadowTrainingController:
    """
    Get global shadow training controller instance (singleton).
    
    PHASE 7: Lock created lazily on first call to avoid import-time side effects.
    Controller is only created when explicitly requested, not at import time.
    
    Returns:
        ShadowTrainingController instance
    """
    global _controller, _controller_lock
    
    if _controller_lock is None:
        _controller_lock = threading.Lock()
    
    if _controller is None:
        with _controller_lock:
            if _controller is None:
                _controller = ShadowTrainingController()
    
    return _controller
