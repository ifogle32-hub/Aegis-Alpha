"""
EXECUTION-CRITICAL: Simplified Engine Loop

OBJECTIVE:
• Engine ALWAYS runs
• Training/backtesting runs when not trading
• Execution loop never crashes
• UI is OPTIONAL
• START = PAPER_TRADING
• STOP = TRAINING_ONLY

SAFETY RULES:
• Loop NEVER exits except on KILLED mode
• All exceptions caught and logged
• Training always runs when not trading
• Execution triggered by strategies (not in loop)
"""

import time
import threading
from sentinel_x.core.engine_mode import EngineMode, get_engine_mode, set_engine_mode
from sentinel_x.core.kill_switch import is_killed
from sentinel_x.monitoring.logger import logger


class TradingEngine:
    """
    Simplified trading engine with always-on loop.
    
    INVARIANTS:
    - Engine loop NEVER exits (except KILLED mode)
    - Training ALWAYS runs when not trading
    - Execution loop NEVER crashes
    - UI commands are OPTIONAL (engine runs independently)
    """
    
    def __init__(self, execution_router, trainer):
        """
        Initialize engine.
        
        Args:
            execution_router: Execution router instance
            trainer: Trainer instance for backtesting/training
        """
        self.execution_router = execution_router
        self.trainer = trainer
        self.running = True
        self._lock = threading.Lock()
        self.tick_count = 0
        
        # Ensure we start in TRAINING mode
        current_mode = get_engine_mode()
        if current_mode not in (EngineMode.RESEARCH, EngineMode.PAPER, EngineMode.LIVE):
            set_engine_mode(EngineMode.RESEARCH, reason="boot_default_to_training")
        
        logger.info("TradingEngine initialized - always-on loop ready")

    def start_trading(self) -> None:
        """
        START command: Enable PAPER trading.
        
        Sets EngineMode to PAPER, enabling execution.
        Training continues in background.
        """
        logger.info("ENGINE → START PAPER TRADING")
        try:
            with self._lock:
                set_engine_mode(EngineMode.PAPER, reason="ui_start_command")
            logger.info("EngineMode set to PAPER - trading enabled")
        except Exception as e:
            logger.error(f"Error starting trading: {e}", exc_info=True)
            # Don't raise - engine continues

    def stop_trading(self) -> None:
        """
        STOP command: Disable trading, return to TRAINING.
        
        Sets EngineMode to RESEARCH (TRAINING mode).
        Training continues immediately.
        """
        logger.info("ENGINE → STOP TRADING, RETURN TO TRAINING")
        try:
            with self._lock:
                set_engine_mode(EngineMode.RESEARCH, reason="ui_stop_command")
            logger.info("EngineMode set to RESEARCH - training only")
        except Exception as e:
            logger.error(f"Error stopping trading: {e}", exc_info=True)
            # Don't raise - engine continues

    def run_forever(self) -> None:
        """
        Always-on engine loop - NEVER exits except on KILLED mode.
        
        CANONICAL STRUCTURE:
        - Loop runs forever
        - All exceptions caught
        - Training runs when not trading
        - Execution triggered by strategies (not in loop)
        - Never crashes
        """
        logger.info("=" * 60)
        logger.info("ENGINE LOOP STARTED - Always-On Daemon")
        logger.info("=" * 60)
        
        # Ensure we start in TRAINING mode
        initial_mode = get_engine_mode()
        if initial_mode == EngineMode.KILLED:
            logger.critical("EngineMode is KILLED at boot - exiting")
            return
        
        if initial_mode not in (EngineMode.RESEARCH, EngineMode.PAPER, EngineMode.LIVE):
            set_engine_mode(EngineMode.RESEARCH, reason="boot_safety_default")
            initial_mode = EngineMode.RESEARCH
        
        logger.info(f"Initial EngineMode: {initial_mode.value}")
        
        # Main loop - NEVER exits except on KILLED
        while True:
            self.tick_count += 1
            
            # Check for KILLED mode (only way to exit)
            current_mode = get_engine_mode()
            if current_mode == EngineMode.KILLED:
                logger.critical("EngineMode is KILLED - exiting loop")
                break
            
            # Kill-switch check (non-fatal, just log)
            if is_killed():
                logger.warning("Kill-switch active - execution blocked, training continues")
            
            # Main loop logic - all exceptions caught
            try:
                # Determine current mode
                current_mode = get_engine_mode()
                
                # TRAINING mode: run training/backtesting
                if current_mode == EngineMode.RESEARCH:
                    self._run_training_tick()
                
                # PAPER/LIVE mode: trading enabled (execution triggered by strategies)
                elif current_mode in (EngineMode.PAPER, EngineMode.LIVE):
                    self._run_trading_tick()
                
                # PAUSED mode: continue loop, run training
                elif current_mode == EngineMode.PAUSED:
                    logger.debug("EngineMode is PAUSED - running training only")
                    self._run_training_tick()
                
            except KeyboardInterrupt:
                # Keyboard interrupt = graceful shutdown
                logger.info("Keyboard interrupt received - setting mode to KILLED")
                try:
                    set_engine_mode(EngineMode.KILLED, reason="keyboard_interrupt")
                except Exception:
                    pass
                break
                
            except Exception as e:
                # CRITICAL: Catch ALL exceptions and continue
                # Engine loop NEVER crashes
                logger.error(
                    f"Unexpected error in engine loop tick {self.tick_count}: {e}",
                    exc_info=True
                )
                # Continue loop - never exit on error
                # Sleep briefly to avoid tight error loop
                time.sleep(1.0)
            
            # Sleep between ticks (configurable, default 1 second)
            time.sleep(1.0)
        
        logger.info("Engine loop exited (KILLED mode)")

    def _run_training_tick(self) -> None:
        """
        Run training/backtesting tick.
        
        Called when in RESEARCH or PAUSED mode.
        Training always runs when not trading.
        """
        try:
            if self.trainer:
                # Run training step (backtesting, strategy evaluation, etc.)
                self.trainer.train_step()
            else:
                logger.debug("Trainer not available - skipping training tick")
        except Exception as e:
            # Training errors are non-fatal - log and continue
            logger.error(f"Training tick error: {e}", exc_info=True)
            # Continue loop - training failure doesn't stop engine

    def _run_trading_tick(self) -> None:
        """
        Run trading tick.
        
        Called when in PAPER or LIVE mode.
        Execution is triggered by strategies, not directly in loop.
        This method can be used for periodic trading tasks if needed.
        """
        try:
            # Execution is triggered by strategies via execution_router
            # This method can be used for periodic tasks (heartbeat, metrics, etc.)
            current_mode = get_engine_mode()
            if current_mode == EngineMode.PAPER:
                logger.debug("PAPER trading mode active - execution triggered by strategies")
            elif current_mode == EngineMode.LIVE:
                logger.debug("LIVE trading mode active - execution triggered by strategies")
        except Exception as e:
            # Trading tick errors are non-fatal - log and continue
            logger.error(f"Trading tick error: {e}", exc_info=True)
            # Continue loop - trading tick failure doesn't stop engine
