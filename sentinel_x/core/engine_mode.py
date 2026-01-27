"""
EngineMode - Control plane permission system for Sentinel X.

────────────────────────────────────────
PHASE 7 — PERMANENT REGRESSION LOCK
────────────────────────────────────────

REGRESSION LOCK:
- Engine stability > features
- Execution must never block engine
- No required realized_pnl signatures
- UI is observer only
- Engine ALWAYS boots
- Engine ALWAYS enters TRAINING first (RESEARCH mode)
- PAPER trading only when explicitly enabled
- STOP = return to training, never shutdown
- START command → PAPER trading
- No "offline agent" state exists

CONTROL PHILOSOPHY:
- EngineMode controls EXECUTION PERMISSIONS, not process lifecycle
- Engine is always running if API responds
- EngineMode values: RESEARCH, PAPER, LIVE, PAUSED, KILLED
- Rork controls permissions, not execution

INVARIANT ASSERTIONS:
• EngineMode NEVER idles (always RESEARCH, PAPER, or LIVE)
• STOP ≠ OFFLINE, STOP ⇒ TRAINING (RESEARCH mode)
• START ⇒ PAPER_TRADING (PAPER mode)
• No UI event may stop the engine thread
• EngineMode changes are atomic and logged
• Default mode on boot: RESEARCH (training)

DO NOT CHANGE WITHOUT ARCHITECT REVIEW
"""
import threading
from enum import Enum
from sentinel_x.monitoring.logger import logger


class EngineMode(Enum):
    """
    Engine execution mode - controls permissions, not lifecycle.
    
    PHASE 1: Canonical mode semantics:
    - RESEARCH: No execution (backtesting only)
    - TRAINING: Alpaca PAPER auto-connected, orders execute continuously
    - PAPER: Alias of TRAINING (backward compatible, internally normalized to TRAINING)
    - LIVE: Tradovate ONLY, locked by explicit guard
    """
    RESEARCH = "RESEARCH"  # No execution (backtesting only)
    TRAINING = "TRAINING"  # Alpaca PAPER auto-connected, continuous execution
    PAPER = "PAPER"       # Alias of TRAINING (backward compatible)
    LIVE = "LIVE"         # Tradovate ONLY, explicit guard required
    PAUSED = "PAUSED"     # Paused (all execution blocked)
    KILLED = "KILLED"     # Emergency stop (irreversible without restart)


class EngineModeManager:
    """Thread-safe EngineMode manager."""
    
    def __init__(self, initial_mode: EngineMode = EngineMode.RESEARCH):
        # PHASE 2: Engine ALWAYS enters TRAINING first (RESEARCH mode)
        # PAPER trading only when explicitly enabled
        self._mode = initial_mode
        self._lock = threading.Lock()
        self._mode_history = []
        self._last_error = None
    
    def get_mode(self) -> EngineMode:
        """Get current engine mode."""
        with self._lock:
            return self._mode
    
    def set_mode(self, new_mode: EngineMode, reason: str = None) -> None:
        """
        Set engine mode and log transition.
        
        PHASE 6: LIVE TRADING HARD LOCK
        When setting to LIVE mode, validates that Alpaca is not active.
        """
        with self._lock:
            old_mode = self._mode
            if old_mode != new_mode:
                # PHASE 6: LIVE TRADING HARD LOCK
                # Validate LIVE mode transition - ensure Alpaca is not active
                if new_mode == EngineMode.LIVE:
                    # Check if engine exists and has router with Alpaca executor
                    try:
                        from sentinel_x.core.engine import get_engine
                        engine = get_engine()
                        if engine and engine.order_router:
                            router = engine.order_router
                            # Check for Alpaca executor (hard block)
                            if router.alpaca_executor:
                                error_msg = "Alpaca forbidden in LIVE mode. LIVE mode requires Tradovate executor only."
                                logger.critical(error_msg)
                                raise RuntimeError(error_msg)
                            # Check active executor type
                            if router.active_executor:
                                from sentinel_x.execution.alpaca_executor import AlpacaExecutor, AlpacaPaperExecutor
                                if isinstance(router.active_executor, (AlpacaExecutor, AlpacaPaperExecutor)):
                                    error_msg = "Alpaca forbidden in LIVE mode. LIVE mode requires Tradovate executor only."
                                    logger.critical(error_msg)
                                    raise RuntimeError(error_msg)
                    except RuntimeError:
                        # Re-raise RuntimeError from validation
                        raise
                    except Exception as e:
                        # Log other errors but don't block mode transition
                        logger.warning(f"Error validating LIVE mode transition (non-fatal): {e}")
                
                self._mode = new_mode
                reason_str = f" ({reason})" if reason else ""
                self._mode_history.append((old_mode, new_mode, reason))
                logger.info(
                    f"EngineMode transition: {old_mode.value} -> {new_mode.value}{reason_str}"
                )
    
    def get_mode_history(self) -> list:
        """Get mode transition history."""
        with self._lock:
            return self._mode_history.copy()
    
    def set_last_error(self, error: str) -> None:
        """Set last error (for status reporting)."""
        with self._lock:
            self._last_error = error
    
    def get_last_error(self) -> str | None:
        """Get last error."""
        with self._lock:
            return self._last_error
    
    def clear_error(self) -> None:
        """Clear last error."""
        with self._lock:
            self._last_error = None


# PHASE 1: Global EngineMode manager instance - defaults to TRAINING on boot
# === TRAINING BASELINE — DO NOT MODIFY ===
_mode_manager = EngineModeManager(initial_mode=EngineMode.TRAINING)


def get_engine_mode() -> EngineMode:
    """
    Get current engine mode.
    
    PHASE 1: Normalizes PAPER to TRAINING internally.
    PAPER and TRAINING are semantically equivalent.
    """
    mode = _mode_manager.get_mode()
    # Normalize PAPER to TRAINING (canonical form)
    if mode == EngineMode.PAPER:
        return EngineMode.TRAINING
    return mode


def set_engine_mode(mode: EngineMode, reason: str = None) -> None:
    """Set engine mode."""
    _mode_manager.set_mode(mode, reason)


def get_engine_mode_manager() -> EngineModeManager:
    """Get global EngineMode manager instance."""
    return _mode_manager
