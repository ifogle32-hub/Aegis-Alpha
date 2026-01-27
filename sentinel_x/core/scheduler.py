"""Scheduler for managing training vs trading windows."""
from datetime import datetime
from typing import Optional
from sentinel_x.core.config import Config, get_config
from sentinel_x.core.state import BotState, get_state, set_state
from sentinel_x.monitoring.logger import logger

FORCE_TRADING = True# set True to bypass training window


class Scheduler:
    """Manages training and trading windows based on time of day."""
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.last_mode = None
        self.training_triggered = False
    
    def get_mode(self) -> str:
        """
        Get current mode based on time of day.
        
        Returns:
            "TRAINING" or "TRADING"
        """
        if FORCE_TRADING:
            return "TRADING"
        
        current_hour = datetime.now().hour
        
        # Check if in training window
        if self._is_in_window(current_hour, 
                             self.config.training_window_start,
                             self.config.training_window_end):
            return "TRAINING"
        
        # Check if in trading window
        if self._is_in_window(current_hour,
                             self.config.trading_window_start,
                             self.config.trading_window_end):
            return "TRADING"
        
        # Default to training if outside both windows
        return "TRAINING"
    
    def _is_in_window(self, hour: int, start: int, end: int) -> bool:
        """
        Check if hour is within a time window.
        
        Handles wraparound (e.g., 22-6 window).
        """
        if start <= end:
            # Normal window (e.g., 9-16)
            return start <= hour < end
        else:
            # Wraparound window (e.g., 22-6)
            return hour >= start or hour < end
    
    def update_state(self) -> None:
        """
        Update bot state based on current scheduler mode.
        
        Only updates if bot is in RUNNING, TRAINING, or TRADING state.
        Never updates when state is STOPPED (respects manual pause).
        Ensures training window triggers once per cycle (not every loop).
        """
        current_state = get_state()
        
        # CRITICAL: Never update state when STOPPED - this respects manual pause/resume
        if current_state == BotState.STOPPED:
            return
        
        # Only update if in a valid running state
        if current_state != BotState.RUNNING and current_state != BotState.TRAINING and current_state != BotState.TRADING:
            return
        
        mode = self.get_mode()
        
        # Detect mode change
        mode_changed = (mode != self.last_mode)
        self.last_mode = mode
        
        if mode == "TRAINING":
            # Only trigger training state if we just entered training mode
            if mode_changed and current_state != BotState.TRAINING:
                set_state(BotState.TRAINING)
                self.training_triggered = False
            elif not mode_changed and current_state == BotState.TRAINING:
                # Already in training, stay there
                pass
            elif current_state == BotState.RUNNING and not self.training_triggered:
                # First time entering training
                set_state(BotState.TRAINING)
                self.training_triggered = True
        elif mode == "TRADING":
            # Enter trading mode when leaving training
            if mode_changed or (current_state == BotState.TRAINING and mode == "TRADING"):
                set_state(BotState.TRADING)
                self.training_triggered = False


# Global scheduler instance
_scheduler = None


def get_scheduler(config: Optional[Config] = None) -> Scheduler:
    """Get global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler(config)
    return _scheduler
