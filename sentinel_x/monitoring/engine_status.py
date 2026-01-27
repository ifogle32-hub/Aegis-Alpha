"""
PHASE 1 — ENGINE STATUS SNAPSHOT

Read-only engine status collector.

REGRESSION LOCK:
Observability only.
No execution logic.
No trading logic.
No broker mutations.

DO NOT IMPORT INTO ENGINE CORE
"""

import time
from typing import Dict, Optional
from datetime import datetime
from collections import deque

from sentinel_x.monitoring.logger import logger
from sentinel_x.core.engine import get_engine
from sentinel_x.core.engine_mode import get_engine_mode, EngineMode
from sentinel_x.core.state import get_state, BotState

# Rolling window for tick rate calculation (last 60 seconds)
_tick_timestamps: deque = deque(maxlen=60)
_last_tick_ts: Optional[float] = None


def record_tick() -> None:
    """
    Record a tick timestamp for rate calculation.
    
    Called by engine loop (non-invasive, read-only tracking).
    """
    global _last_tick_ts
    current_time = time.time()
    _tick_timestamps.append(current_time)
    _last_tick_ts = current_time


def get_engine_status() -> Dict:
    """
    Get read-only engine status snapshot.
    
    Returns:
        Dictionary with engine status fields:
        - engine_state: RUNNING / STOPPED
        - engine_mode: TRAINING / PAPER / LIVE / RESEARCH / PAUSED / KILLED
        - uptime_seconds: Engine uptime in seconds
        - loop_active: bool - True if engine loop is running
        - last_tick_ts: float - Timestamp of last tick (or None)
        - ticks_per_minute: float - Rolling average ticks per minute
        
    Rules:
        - Never starts or stops the engine
        - Never mutates engine state
        - Returns safe defaults if engine not available
    """
    try:
        engine = get_engine()
        if not engine:
            return {
                'engine_state': 'STOPPED',
                'engine_mode': 'UNKNOWN',
                'uptime_seconds': 0.0,
                'loop_active': False,
                'last_tick_ts': None,
                'ticks_per_minute': 0.0
            }
        
        # Get engine mode (authoritative)
        try:
            current_mode = get_engine_mode()
            engine_mode = current_mode.value
        except Exception:
            engine_mode = 'UNKNOWN'
        
        # Get engine state
        try:
            state = get_state()
            engine_state = state.value if state else 'STOPPED'
        except Exception:
            engine_state = 'STOPPED'
        
        # Calculate uptime
        uptime_seconds = 0.0
        loop_active = False
        if hasattr(engine, 'started_at'):
            try:
                uptime_seconds = time.time() - engine.started_at
                loop_active = (engine_mode != 'KILLED' and engine_state == 'RUNNING')
            except Exception:
                pass
        
        # Calculate ticks per minute from rolling window
        ticks_per_minute = 0.0
        if _tick_timestamps:
            try:
                # Count ticks in last 60 seconds
                current_time = time.time()
                recent_ticks = sum(1 for ts in _tick_timestamps if current_time - ts <= 60.0)
                ticks_per_minute = float(recent_ticks)
            except Exception:
                pass
        
        return {
            'engine_state': engine_state,
            'engine_mode': engine_mode,
            'uptime_seconds': max(0.0, uptime_seconds),
            'loop_active': loop_active,
            'last_tick_ts': _last_tick_ts,
            'ticks_per_minute': ticks_per_minute
        }
        
    except Exception as e:
        logger.error(f"Error getting engine status (non-fatal): {e}", exc_info=True)
        # Return safe defaults on error
        return {
            'engine_state': 'STOPPED',
            'engine_mode': 'UNKNOWN',
            'uptime_seconds': 0.0,
            'loop_active': False,
            'last_tick_ts': None,
            'ticks_per_minute': 0.0
        }
