"""
PHASE 7 — STARTUP LOCKING

Prevent multiple Sentinel X instances from running simultaneously.

Ensures:
- Only ONE instance may run at a time
- Fail fast if another instance is running
- Log and exit cleanly if lock is held
"""

import os
import fcntl
import sys
from pathlib import Path
from typing import Optional

from sentinel_x.monitoring.logger import logger


class StartupLock:
    """
    File-based lock to prevent multiple instances.
    
    Uses fcntl on Unix systems (macOS, Linux).
    """
    
    def __init__(self, lock_file: str = "/tmp/sentinel_x.lock"):
        """
        Initialize startup lock.
        
        Args:
            lock_file: Path to lock file
        """
        self.lock_file = Path(lock_file)
        self.lock_fd: Optional[int] = None
    
    def acquire(self) -> bool:
        """
        Acquire startup lock.
        
        Returns:
            True if lock acquired, False if another instance is running
        
        Raises:
            SystemExit: If lock cannot be acquired (another instance running)
        """
        try:
            # Create lock file if it doesn't exist
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Open lock file
            self.lock_fd = os.open(str(self.lock_file), os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
            
            # Try to acquire exclusive lock (non-blocking)
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                
                # Write PID to lock file
                os.write(self.lock_fd, str(os.getpid()).encode())
                os.fsync(self.lock_fd)
                
                logger.info(f"Startup lock acquired | pid={os.getpid()} | lock_file={self.lock_file}")
                return True
                
            except BlockingIOError:
                # Another instance is holding the lock
                try:
                    # Read PID from lock file
                    with open(self.lock_file, 'r') as f:
                        pid = f.read().strip()
                except Exception:
                    pid = "unknown"
                
                logger.error(
                    f"Startup lock held by another instance | "
                    f"pid={pid} | lock_file={self.lock_file}"
                )
                
                # Close file descriptor
                if self.lock_fd:
                    os.close(self.lock_fd)
                    self.lock_fd = None
                
                return False
                
        except Exception as e:
            logger.error(f"Error acquiring startup lock: {e}", exc_info=True)
            if self.lock_fd:
                try:
                    os.close(self.lock_fd)
                except Exception:
                    pass
                self.lock_fd = None
            return False
    
    def release(self) -> None:
        """Release startup lock."""
        if self.lock_fd:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
                self.lock_fd = None
                
                # Remove lock file
                try:
                    self.lock_file.unlink()
                except Exception:
                    pass
                
                logger.info(f"Startup lock released | lock_file={self.lock_file}")
            except Exception as e:
                logger.error(f"Error releasing startup lock: {e}", exc_info=True)
    
    def __enter__(self):
        """Context manager entry."""
        if not self.acquire():
            logger.critical("Another Sentinel X instance is running. Exiting.")
            sys.exit(1)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()


# Global lock instance
_lock: Optional[StartupLock] = None


def get_startup_lock() -> StartupLock:
    """
    Get global startup lock instance.
    
    Returns:
        StartupLock instance
    """
    global _lock
    if _lock is None:
        _lock = StartupLock()
    return _lock
