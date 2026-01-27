"""Kill switch mechanism for instant shutdown."""
import os
from pathlib import Path
from sentinel_x.monitoring.logger import logger


class KillSwitch:
    """
    Kill switch for instant shutdown of Sentinel X.
    
    PHASE 4/10: Hardened kill-switch with atomic state and idempotent behavior.
    """
    
    def __init__(self, kill_file: str = "./KILL"):
        self.kill_file = Path(kill_file)
        self._env_var = "KILL_SWITCH"
        self._killed_state = False  # In-memory state for instant checks
    
    def is_killed(self) -> bool:
        """
        Check if kill switch is triggered.
        
        PHASE 4: Atomic check - checks in-memory state first for speed.
        
        Checks:
        1. In-memory state (fastest)
        2. Environment variable KILL_SWITCH=true
        3. File flag: ./KILL exists
        
        Returns:
            True if kill switch is triggered, False otherwise
        """
        # PHASE 4: Fast path - check in-memory state first
        if self._killed_state:
            return True
        
        # Check environment variable
        try:
            env_kill = os.getenv(self._env_var, "").lower() == "true"
            if env_kill:
                self._killed_state = True  # Cache state
                logger.warning("Kill switch triggered via environment variable")
                return True
        except Exception:
            pass  # Fail silently on env check
        
        # Check file flag
        try:
            if self.kill_file.exists():
                self._killed_state = True  # Cache state
                logger.warning(f"Kill switch triggered via file: {self.kill_file}")
                return True
        except Exception:
            pass  # Fail silently on file check
        
        return False
    
    def activate(self) -> None:
        """
        PHASE 4: Activate kill switch (atomic, idempotent).
        
        Sets in-memory state and creates kill file.
        Safe to call multiple times.
        """
        self._killed_state = True
        try:
            self.create_kill_file()
        except Exception as e:
            logger.error(f"Error creating kill file: {e}", exc_info=True)
            # State is still set in memory, so kill is active
    
    def create_kill_file(self) -> None:
        """Create kill file (for testing/debugging)."""
        self.kill_file.touch()
        logger.info(f"Kill file created: {self.kill_file}")
    
    def remove_kill_file(self) -> None:
        """Remove kill file."""
        if self.kill_file.exists():
            self.kill_file.unlink()
            logger.info(f"Kill file removed: {self.kill_file}")


# Global kill switch instance
_kill_switch = KillSwitch()


def is_killed() -> bool:
    """Check if kill switch is triggered."""
    return _kill_switch.is_killed()

