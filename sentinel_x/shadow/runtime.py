"""
PHASE 1 — SHADOW RUNTIME OWNER

ShadowRuntime: Central singleton that owns ALL shadow components.

PHASE 1 RULES:
- NO shadow module imports another shadow module directly
- ShadowRuntime owns trainer, heartbeat, controller
- All threads start ONLY in ShadowRuntime.start()
- All threads stopped in ShadowRuntime.stop()

PHASE 5 RULES:
- Thread caps enforced
- Sleep-based loops (no busy-wait)
- CPU usage minimized
- Process guards prevent duplicate starts
"""

import threading
import time
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from sentinel_x.monitoring.logger import logger


class ShadowRuntime:
    """
    Shadow subsystem runtime singleton.
    
    PHASE 1: Owns ALL shadow components to eliminate circular imports.
    PHASE 5: Controls thread lifecycle and CPU usage.
    
    Responsibilities:
    - Own trainer and heartbeat (no cross-imports)
    - Control startup / shutdown
    - Enforce thread caps
    - Provide safe getters
    - No side effects at import time
    """
    
    _instance: Optional['ShadowRuntime'] = None
    _lock: Optional[threading.Lock] = None
    
    def __init__(self):
        """Initialize shadow runtime (private - use get_shadow_runtime())."""
        self._enabled = False
        self._heartbeat_monitor: Optional[Any] = None
        self._trainer: Optional[Any] = None
        self._controller: Optional[Any] = None
        self._rork_interface: Optional[Any] = None
        self._started = False
        self._init_lock = threading.RLock()
        
        # PHASE 5: Thread tracking
        self._threads: list[threading.Thread] = []
        
        logger.debug("ShadowRuntime initialized (no threads started)")
    
    @classmethod
    def get_instance(cls) -> 'ShadowRuntime':
        """
        Get ShadowRuntime singleton instance.
        
        PHASE 5: Lock created lazily to avoid import-time side effects.
        
        Returns:
            ShadowRuntime instance
        """
        if cls._lock is None:
            cls._lock = threading.Lock()
        
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        
        return cls._instance
    
    def start(self, symbols: list = None) -> bool:
        """
        Start shadow runtime.
        
        PHASE 1: Instantiates trainer and heartbeat, wires them together.
        PHASE 5: Enforces thread caps, logs thread count.
        PHASE 4: Does NOT modify engine.shadow_mode - that is governance state.
        
        SAFETY:
        - Only starts/stops threads
        - Does NOT toggle engine.shadow_mode
        - Shadow runtime ≠ Shadow enabled (engine state)
        
        Args:
            symbols: Optional list of symbols to train on
        
        Returns:
            True if started successfully, False otherwise
        """
        with self._init_lock:
            # PHASE 5: Process guard - prevent duplicate starts
            if self._started:
                logger.warning("Shadow runtime already started - NO-OP")
                return False
            
            try:
                # PHASE 5: Log thread count before start
                initial_thread_count = threading.active_count()
                initial_thread_names = [t.name for t in threading.enumerate()]
                logger.info(f"ShadowRuntime.start() | initial_threads={initial_thread_count} | names={initial_thread_names}")
                
                # PHASE 1: Lazy imports to avoid circular dependencies
                from sentinel_x.shadow.heartbeat import ShadowHeartbeatMonitor
                from sentinel_x.shadow.trainer import ShadowTrainer, ShadowTrainerConfig
                from sentinel_x.shadow.controller import get_shadow_training_controller
                from sentinel_x.core.config import get_config
                from sentinel_x.shadow.definitions import ShadowMode
                
                # PHASE 1: Instantiate heartbeat FIRST (no dependencies)
                self._heartbeat_monitor = ShadowHeartbeatMonitor()
                logger.debug("Heartbeat monitor instantiated")
                
                # PHASE 1: Instantiate trainer with heartbeat injection
                config = ShadowTrainerConfig(
                    enabled=True,
                    replay_mode=ShadowMode.LIVE,
                )
                self._trainer = ShadowTrainer(
                    config=config,
                    heartbeat_monitor=self._heartbeat_monitor,  # PHASE 1: Inject heartbeat
                )
                logger.debug("Trainer instantiated with heartbeat injection")
                
                # Get controller
                self._controller = get_shadow_training_controller()
                
                # PHASE 1: Set trainer in controller (controller owns trainer lifecycle)
                if hasattr(self._controller, '_trainer'):
                    self._controller._trainer = self._trainer
                
                # Get symbols from config if not provided
                if symbols is None:
                    config_obj = get_config()
                    symbols = config_obj.symbols
                
                # Start controller (which starts trainer)
                success = self._controller.start(
                    symbols=symbols,
                    replay_mode=False,
                )
                
                if success:
                    self._enabled = True
                    self._started = True
                    
                    # 🔑 REQUIRED: activate training loop
                    self._trainer.start_training()
                    
                    # PHASE 5: Log thread count after start
                    final_thread_count = threading.active_count()
                    final_thread_names = [t.name for t in threading.enumerate()]
                    new_threads = [t for t in final_thread_names if t not in initial_thread_names]
                    
                    logger.info(f"Shadow runtime started | symbols={len(symbols)}")
                    logger.info(f"ShadowRuntime threads | total={final_thread_count} | new={new_threads}")
                    
                    # PHASE 5: Verify thread caps
                    if final_thread_count > 10:
                        logger.warning(f"High thread count: {final_thread_count} (expected ≤10)")
                else:
                    logger.error("Failed to start shadow runtime")
                
                return success
                
            except Exception as e:
                logger.error(f"Error starting shadow runtime: {e}", exc_info=True)
                return False
    
    def stop(self) -> None:
        """
        Stop shadow runtime.
        
        PHASE 1: Stops all components in reverse order.
        PHASE 5: Joins threads with timeout, logs cleanup.
        """
        with self._init_lock:
            if not self._started:
                return
            
            try:
                # PHASE 5: Log thread count before stop
                initial_thread_count = threading.active_count()
                logger.info(f"ShadowRuntime.stop() | initial_threads={initial_thread_count}")
                
                # Stop controller (stops trainer)
                if self._controller:
                    self._controller.stop()
                
                # PHASE 5: Join all threads with timeout
                threads_to_join = []
                if self._trainer and hasattr(self._trainer, '_watchdog_thread'):
                    if self._trainer._watchdog_thread and self._trainer._watchdog_thread.is_alive():
                        threads_to_join.append(("ShadowTrainerWatchdog", self._trainer._watchdog_thread))
                
                if self._controller and hasattr(self._controller, '_training_thread'):
                    if self._controller._training_thread and self._controller._training_thread.is_alive():
                        threads_to_join.append(("ShadowTrainingLoop", self._controller._training_thread))
                
                for thread_name, thread in threads_to_join:
                    thread.join(timeout=5.0)
                    if thread.is_alive():
                        logger.warning(f"Thread {thread_name} did not stop within timeout")
                    else:
                        logger.debug(f"Thread {thread_name} stopped")
                
                self._enabled = False
                self._started = False
                
                # PHASE 5: Log thread count after stop
                final_thread_count = threading.active_count()
                logger.info(f"Shadow runtime stopped | final_threads={final_thread_count}")
                
            except Exception as e:
                logger.error(f"Error stopping shadow runtime: {e}", exc_info=True)
    
    def is_enabled(self) -> bool:
        """Check if shadow runtime is enabled."""
        return self._enabled
    
    def is_started(self) -> bool:
        """Check if shadow runtime is started."""
        return self._started
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get shadow runtime status.
        
        Returns:
            Status dictionary
        """
        try:
            status = {
                "enabled": self._enabled,
                "started": self._started,
            }
            
            # Get controller status if available
            if self._controller:
                try:
                    controller_status = self._controller.get_status()
                    status.update({
                        "controller_state": controller_status.get("state"),
                        "controller_enabled": controller_status.get("enabled"),
                        "error_count": controller_status.get("error_count", 0),
                    })
                except Exception:
                    pass
            
            # Get trainer status if available
            if self._trainer:
                try:
                    trainer_status = self._trainer.get_status()
                    status.update({
                        "trainer_active": trainer_status.get("training_active", False),
                        "tick_counter": trainer_status.get("tick_counter", 0),
                    })
                except Exception:
                    pass
            
            # PHASE 5: Add thread count
            status["thread_count"] = threading.active_count()
            
            return status
            
        except Exception as e:
            logger.error(f"Error getting shadow runtime status: {e}", exc_info=True)
            return {
                "enabled": False,
                "started": False,
                "error": str(e),
            }
    
    def metrics(self) -> Dict[str, Any]:
        """
        Read-only Shadow runtime metrics.
        SAFE:
        - No thread creation
        - No state mutation
        - No side effects
        """
        import time
        import threading

        now = time.time()

        data = {
            "idle": True,
            "threads": [],
            "heartbeat_last_tick_ms": None,
            "heartbeat_age_ms": None,
            "trainer_last_step_ms": None,
            "trainer_lag_ms": None,
            "cpu_safe": True,
        }

        # Thread visibility
        data["threads"] = [
            t.name for t in threading.enumerate()
            if t.name.startswith("Shadow")
        ]

        # Heartbeat metrics
        if self._heartbeat_monitor:
            last = getattr(self._heartbeat_monitor, "last_tick_ts", None)
            if last:
                age_ms = int((now - last) * 1000)
                data["heartbeat_last_tick_ms"] = age_ms
                data["heartbeat_age_ms"] = age_ms
                data["idle"] = age_ms > 60_000

        # Trainer metrics
        if self._trainer:
            last = getattr(self._trainer, "last_step_ts", None)
            if last:
                lag_ms = int((now - last) * 1000)
                data["trainer_last_step_ms"] = lag_ms
                data["trainer_lag_ms"] = lag_ms
                data["idle"] = data["idle"] and lag_ms > 60_000

        return data
    
    def get_tick_count(self) -> int:
        """Get current tick count from trainer."""
        if self._trainer:
            return getattr(self._trainer, "tick_counter", 0)
        return 0
    
    def get_active_strategy_count(self) -> int:
        """Get active strategy count from trainer."""
        if self._trainer:
            registry = getattr(self._trainer, "registry", None)
            if registry:
                get_all_strategies = getattr(registry, "get_all_strategies", None)
                if get_all_strategies:
                    strategies = get_all_strategies()
                    return len(strategies) if isinstance(strategies, dict) else 0
        return 0
    
    def get_controller(self):
        """Get shadow training controller (lazy)."""
        if self._controller is None:
            from sentinel_x.shadow.controller import get_shadow_training_controller
            self._controller = get_shadow_training_controller()
        return self._controller
    
    def get_trainer(self):
        """Get shadow trainer (direct access)."""
        return self._trainer
    
    def get_heartbeat_monitor(self):
        """Get heartbeat monitor (direct access)."""
        return self._heartbeat_monitor
    
    def get_rork_interface(self):
        """Get rork interface (lazy)."""
        if self._rork_interface is None:
            from sentinel_x.shadow.rork import get_rork_shadow_interface
            self._rork_interface = get_rork_shadow_interface()
        return self._rork_interface


def get_shadow_runtime() -> ShadowRuntime:
    """
    Get ShadowRuntime singleton instance.
    
    Returns:
        ShadowRuntime instance
    """
    return ShadowRuntime.get_instance()
