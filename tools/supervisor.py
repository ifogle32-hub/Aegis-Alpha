#!/usr/bin/env python3
"""
Sentinel X External Supervisor

SAFETY: External watchdog only — does NOT modify engine logic

============================================================================
CRITICAL SAFETY NOTICE
============================================================================
This supervisor implements auto-restart behavior, which CONFLICTS with
previous system constraints that explicitly forbid auto-restarts.

USE WITH CAUTION:
- Auto-restart may interrupt live trading
- Restarts during broker operations may cause order state issues
- Only use in TRAINING/PAPER mode for testing
- NEVER use in LIVE trading mode

REGRESSION LOCK:
This supervisor is an OPTIONAL external layer.
It does NOT modify engine code or trading logic.
Auto-restart behavior is DISABLED by default.
============================================================================
"""

import subprocess
import time
import signal
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

# ============================================================================
# CONFIGURATION
# ============================================================================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_CMD = ["python", "run_sentinel_x.py"]
STATUS_CMD = ["python", "tools/status.py"]

CHECK_INTERVAL = int(os.getenv("SENTINEL_CHECK_INTERVAL", "30"))  # seconds
FREEZE_CONFIRMATIONS = int(os.getenv("SENTINEL_FREEZE_THRESHOLD", "2"))  # consecutive FROZEN checks
RESTART_COOLDOWN = int(os.getenv("SENTINEL_RESTART_COOLDOWN", "60"))  # seconds

# ============================================================================
# AUTO-RESTART CONTROL (DISABLED BY DEFAULT)
# ============================================================================
# Set SENTINEL_ENABLE_AUTO_RESTART=1 to enable auto-restart behavior
# WARNING: Auto-restart is dangerous and may cause data loss or order issues
# ============================================================================
ENABLE_AUTO_RESTART = os.getenv("SENTINEL_ENABLE_AUTO_RESTART", "0") == "1"

# State tracking
engine_proc: Optional[subprocess.Popen] = None
freeze_count = 0
restart_count = 0
last_restart_ts = 0.0

# Logging
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
SUPERVISOR_LOG = LOG_DIR / "supervisor.log"
ENGINE_LOG = LOG_DIR / "engine.log"


def log_supervisor(level: str, message: str):
    """Log supervisor events to file and stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{level}] {message}"
    print(log_entry)
    
    try:
        with open(SUPERVISOR_LOG, "a") as f:
            f.write(log_entry + "\n")
    except Exception:
        pass  # Logging failure should not crash supervisor


def is_engine_running() -> bool:
    """Check if engine process is running."""
    global engine_proc
    if engine_proc is None:
        return False
    return engine_proc.poll() is None


def start_engine() -> bool:
    """Start the engine process."""
    global engine_proc, restart_count, last_restart_ts
    
    if is_engine_running():
        log_supervisor("WARN", "Engine process already running, skipping start")
        return False

    log_supervisor("INFO", f"Starting engine: {' '.join(ENGINE_CMD)}")
    
    try:
        # Open log file for engine output
        log_file = open(ENGINE_LOG, "a")
        
        engine_proc = subprocess.Popen(
            ENGINE_CMD,
            cwd=PROJECT_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        
        log_supervisor("INFO", f"Engine started with PID: {engine_proc.pid}")
        
        restart_count += 1
        last_restart_ts = time.time()
        
        # Wait a moment to see if engine starts successfully
        time.sleep(5)
        
        if not is_engine_running():
            log_supervisor("ERROR", "Engine failed to start or crashed immediately")
            engine_proc = None
            return False
        
        log_supervisor("INFO", "Engine started successfully")
        return True
        
    except Exception as e:
        log_supervisor("ERROR", f"Failed to start engine: {e}")
        engine_proc = None
        return False


def stop_engine():
    """Stop the engine process gracefully."""
    global engine_proc
    
    if not is_engine_running():
        log_supervisor("WARN", "Engine process not running, skipping stop")
        return
    
    log_supervisor("INFO", "Stopping engine gracefully (SIGTERM)")
    
    try:
        engine_proc.send_signal(signal.SIGTERM)
        
        # Wait for graceful shutdown
        try:
            engine_proc.wait(timeout=10)
            log_supervisor("INFO", "Engine stopped gracefully")
        except subprocess.TimeoutExpired:
            log_supervisor("WARN", "Engine did not stop gracefully, forcing termination (SIGKILL)")
            engine_proc.kill()
            try:
                engine_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log_supervisor("ERROR", "Engine did not respond to SIGKILL")
        
    except Exception as e:
        log_supervisor("ERROR", f"Error stopping engine: {e}")
    finally:
        engine_proc = None


def restart_engine() -> bool:
    """Restart the engine (only if auto-restart enabled)."""
    global freeze_count
    
    if not ENABLE_AUTO_RESTART:
        log_supervisor("WARN", "Auto-restart DISABLED. Engine is FROZEN but will NOT be restarted.")
        log_supervisor("WARN", "To enable auto-restart, set: export SENTINEL_ENABLE_AUTO_RESTART=1")
        log_supervisor("WARN", "Manual intervention required.")
        return False
    
    # Rate limiting: Don't restart more than once per 5 minutes
    current_ts = time.time()
    if current_ts - last_restart_ts < 300:  # 5 minutes
        log_supervisor("WARN", "Restart rate limit: Last restart was less than 5 minutes ago")
        log_supervisor("WARN", "Skipping restart to prevent restart loop")
        return False
    
    log_supervisor("CRITICAL", "=" * 50)
    log_supervisor("CRITICAL", "AUTO-RESTART TRIGGERED")
    log_supervisor("CRITICAL", f"Frozen count: {freeze_count}/{FREEZE_CONFIRMATIONS}")
    log_supervisor("CRITICAL", f"Total restarts today: {restart_count}")
    log_supervisor("CRITICAL", "=" * 50)
    
    stop_engine()
    time.sleep(RESTART_COOLDOWN)
    
    success = start_engine()
    
    if success:
        log_supervisor("INFO", "Engine restarted successfully")
        freeze_count = 0
        return True
    else:
        log_supervisor("ERROR", "Engine restart failed")
        return False


def get_status() -> str:
    """Get engine status output."""
    try:
        result = subprocess.run(
            STATUS_CMD,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return "STATUS ERROR: Status check timed out"
    except Exception as e:
        return f"STATUS ERROR: {e}"


def is_frozen(status_text: str) -> bool:
    """Check if status indicates FROZEN state."""
    return "Loop: FROZEN" in status_text


def is_stopped(status_text: str) -> bool:
    """Check if status indicates STOPPED state."""
    return "ENGINE: STOPPED" in status_text


def main():
    """Main supervisor loop."""
    global freeze_count
    
    log_supervisor("INFO", "=" * 50)
    log_supervisor("INFO", "Sentinel X Supervisor Starting")
    log_supervisor("INFO", "=" * 50)
    log_supervisor("INFO", f"Project Directory: {PROJECT_ROOT}")
    log_supervisor("INFO", f"Check Interval: {CHECK_INTERVAL}s")
    log_supervisor("INFO", f"Freeze Threshold: {FREEZE_CONFIRMATIONS} consecutive checks")
    log_supervisor("INFO", f"Restart Cooldown: {RESTART_COOLDOWN}s")
    log_supervisor("INFO", f"Auto-Restart: {'ENABLED ⚠️' if ENABLE_AUTO_RESTART else 'DISABLED (safe)'}")
    log_supervisor("INFO", "=" * 50)
    
    # Initial engine check
    if not is_engine_running():
        log_supervisor("WARN", "Engine process not running, attempting to start...")
        if not start_engine():
            log_supervisor("ERROR", "Failed to start engine initially")
            sys.exit(1)
    else:
        log_supervisor("INFO", "Engine process already running")
    
    # Main monitoring loop
    try:
        while True:
            status_text = get_status()
            
            # Check for FROZEN state
            if is_frozen(status_text):
                freeze_count += 1
                log_supervisor("WARN", f"FROZEN detected ({freeze_count}/{FREEZE_CONFIRMATIONS} consecutive checks)")
                
                if freeze_count >= FREEZE_CONFIRMATIONS:
                    log_supervisor("CRITICAL", "Freeze threshold exceeded, considering restart...")
                    restart_engine()
                    # Note: freeze_count is reset inside restart_engine on success
            elif is_stopped(status_text):
                log_supervisor("WARN", "Engine STOPPED detected")
                if ENABLE_AUTO_RESTART:
                    log_supervisor("INFO", "Auto-restart enabled, attempting to start engine...")
                    if not start_engine():
                        log_supervisor("ERROR", "Failed to restart stopped engine")
                else:
                    log_supervisor("WARN", "Auto-restart disabled, engine remains stopped")
                freeze_count = 0
            else:
                # RUNNING or STALE - reset frozen count
                if freeze_count > 0:
                    log_supervisor("INFO", "Engine recovered from frozen state (frozen_count reset)")
                    freeze_count = 0
            
            # Check if engine process is still alive (even if status says otherwise)
            if not is_engine_running():
                log_supervisor("WARN", "Engine process not found (may have crashed)")
                if ENABLE_AUTO_RESTART:
                    log_supervisor("INFO", "Auto-restart enabled, attempting to start engine...")
                    if not start_engine():
                        log_supervisor("ERROR", "Failed to restart crashed engine")
                else:
                    log_supervisor("WARN", "Auto-restart disabled, engine remains down")
            
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        log_supervisor("INFO", "\nSupervisor received SIGINT, shutting down gracefully...")
        stop_engine()
        sys.exit(0)
    except Exception as e:
        log_supervisor("ERROR", f"Supervisor error: {e}")
        stop_engine()
        sys.exit(1)


if __name__ == "__main__":
    main()
