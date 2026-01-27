"""
PHASE 3 — HEARTBEAT MODULE

Cross-process heartbeat mechanism for Sentinel X engine monitoring.

ROOT CAUSE ANALYSIS (PHASE 1):
The engine runs in a background process. External monitors (tools/status.py)
must read the heartbeat file to report the TRUE runtime state. Monitors
should NEVER import TradingEngine as this creates a NEW engine instance
and inspects the wrong process, resulting in false STOPPED status.

DESIGN (PHASE 2):
- File-based heartbeat at /tmp/sentinel_x_heartbeat.json
- Written by running engine every tick
- Read by external tools
- Cross-process safe (JSON file)
- Lightweight and non-blocking
- Safe to fail silently

REGRESSION LOCK:
Observability only.
No execution logic.
No trading logic.
No broker mutations.

SAFETY GUARANTEES (PHASE 6):
- Engine cannot crash due to heartbeat failures
- Monitor cannot influence engine
- No changes to Alpaca / Tradovate behavior
- No changes to execution_router
- No changes to strategy lifecycle

LOG ONLY. No control flow.
"""

import json
import os
import time
from typing import Dict, Optional

from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.engine_status import get_engine_status
from sentinel_x.monitoring.strategy_status import get_strategy_status
from sentinel_x.monitoring.broker_status import get_broker_status


_last_heartbeat_ts: Optional[float] = None
_heartbeat_interval: float = 60.0  # 60 seconds
_HEARTBEAT_FILE = "/tmp/sentinel_x_heartbeat.json"


def write_heartbeat(state: dict) -> None:
    """
    Write heartbeat state to file.
    
    Called every loop tick to publish engine state to file.
    
    PHASE 4: Engine heartbeat emission
    - Called from engine.py run_forever() loop every iteration
    - Heartbeat data reflects actual running state
    - Heartbeat must NOT affect timing or execution
    
    Args:
        state: Dictionary with engine state fields
            - timestamp: epoch seconds (required)
            - pid: process ID (required)
            - engine: engine state string (RUNNING/STOPPED)
            - mode: engine mode (TRAINING/PAPER/LIVE)
            - broker: active broker name or NONE
    
    Rules:
        - Write only. No control flow.
        - Non-invasive (never blocks engine)
        - Safe to call from engine loop
        - Never raises exceptions
        - Observability-only. No execution impact.
    """
    try:
        with open(_HEARTBEAT_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        # Heartbeat file write must never block or crash
        # SAFETY: Engine cannot crash due to heartbeat failures
        logger.debug(f"Error writing heartbeat file (non-fatal): {e}")


def read_heartbeat() -> Optional[Dict]:
    """
    Read heartbeat file from disk.
    
    PHASE 3: External monitor interface
    - Called by tools/status.py to check engine state
    - Returns None if file doesn't exist or is invalid
    - Safe to call from any process
    
    Returns:
        Dictionary with heartbeat data or None if file doesn't exist/invalid
        Fields:
            - timestamp: epoch seconds
            - pid: process ID
            - engine: engine state string
            - mode: engine mode (TRAINING/PAPER/LIVE)
            - broker: active broker name
    
    Rules:
        - Read only. No mutations.
        - Never raises exceptions
        - Safe to call from external tools
        - Observability-only. No execution impact.
    """
    try:
        if not os.path.exists(_HEARTBEAT_FILE):
            return None
        
        with open(_HEARTBEAT_FILE, "r") as f:
            data = json.load(f)
            # Validate required fields
            if not isinstance(data, dict):
                return None
            if "timestamp" not in data:
                return None
            return data
    except Exception as e:
        # Read failures are silent - monitor handles None gracefully
        logger.debug(f"Error reading heartbeat file (non-fatal): {e}")
        return None


def log_heartbeat() -> None:
    """
    Log structured heartbeat every 60 seconds.
    
    Logs:
    - engine_mode
    - active_strategies
    - trades_per_min
    - broker_connected
    
    Rules:
    - LOG ONLY. No control flow.
    - Non-invasive (never blocks engine)
    - Safe to call from engine loop
    """
    global _last_heartbeat_ts
    
    try:
        current_time = time.time()
        
        # Check if 60 seconds have passed
        if _last_heartbeat_ts is None:
            _last_heartbeat_ts = current_time
            return
        
        if current_time - _last_heartbeat_ts < _heartbeat_interval:
            return
        
        # Get status data
        engine_status = get_engine_status()
        strategy_status = get_strategy_status()
        broker_status = get_broker_status()
        
        # Extract fields
        engine_mode = engine_status.get('engine_mode', 'UNKNOWN')
        active_strategies = [s for s in strategy_status if s.get('status') == 'ACTIVE']
        active_strategies_count = len(active_strategies)
        
        # Calculate trades per minute from ticks
        ticks_per_min = engine_status.get('ticks_per_minute', 0.0)
        
        # Broker status
        broker_connected = broker_status.get('connected', False)
        broker_name = broker_status.get('broker_name', 'none')
        
        # Log structured heartbeat
        logger.info(
            f"HEARTBEAT | "
            f"mode={engine_mode} | "
            f"active_strategies={active_strategies_count} | "
            f"ticks_per_min={ticks_per_min:.1f} | "
            f"broker={broker_name} | "
            f"broker_connected={broker_connected}"
        )
        
        # Update last heartbeat timestamp
        _last_heartbeat_ts = current_time
        
    except Exception as e:
        # Heartbeat logging must never block or crash
        logger.debug(f"Error logging heartbeat (non-fatal): {e}")
        # Don't update timestamp on error - will retry next call
