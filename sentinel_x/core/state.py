"""Thread-safe global state management for Sentinel X."""
import threading
from enum import Enum
from sentinel_x.monitoring.logger import logger


class BotState(Enum):
    """Trading bot states."""
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    TRAINING = "TRAINING"
    TRADING = "TRADING"


class EngineMode(Enum):
    """
    Engine execution modes.
    
    RESEARCH: Default, always-on training/backtesting (no execution)
    PAPER: Paper execution enabled
    LIVE: Live execution enabled
    PAUSED: No execution, research continues
    KILLED: Hard stop (loop exits)
    """
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    KILLED = "KILLED"


class StateManager:
    """Thread-safe global state manager."""
    
    def __init__(self):
        self._state = BotState.STOPPED
        self._lock = threading.Lock()
        self._state_history = []
    
    def get_state(self) -> BotState:
        """Get current bot state."""
        with self._lock:
            return self._state
    
    def set_state(self, new_state: BotState) -> None:
        """Set bot state and log transition."""
        with self._lock:
            old_state = self._state
            if old_state != new_state:
                self._state = new_state
                self._state_history.append((old_state, new_state))
                logger.info(f"State transition: {old_state.value} -> {new_state.value}")
    
    def get_state_history(self) -> list:
        """Get state transition history."""
        with self._lock:
            return self._state_history.copy()


# Global state manager instance
_state_manager = StateManager()


def get_state() -> BotState:
    """Get current bot state."""
    return _state_manager.get_state()


def set_state(new_state: BotState) -> None:
    """Set bot state."""
    _state_manager.set_state(new_state)

