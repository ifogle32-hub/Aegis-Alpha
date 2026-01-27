"""
PHASE 4 — UNIFIED HEALTH SNAPSHOT

Unified system health collector combining all status modules.

REGRESSION LOCK:
Observability only.
No execution logic.
No trading logic.
No broker mutations.

DO NOT IMPORT INTO ENGINE CORE
"""

from typing import Dict, List

from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.engine_status import get_engine_status
from sentinel_x.monitoring.strategy_status import get_strategy_status
from sentinel_x.monitoring.broker_status import get_broker_status
from sentinel_x.core.engine_mode import get_engine_mode, EngineMode


def get_system_health() -> Dict:
    """
    Get unified system health snapshot.
    
    Returns:
        Dictionary combining:
        - engine_status: Engine status dict
        - strategy_status: List of strategy status dicts
        - broker_status: Broker status dict
        - healthy: bool - True if system is healthy
        - warnings: List[str] - List of warning messages
        
    System is healthy if:
        - engine loop active
        - broker connected OR training mode (broker optional in training)
        - no fatal exceptions
    """
    try:
        # Get all status components
        engine_status = get_engine_status()
        strategy_status = get_strategy_status()
        broker_status = get_broker_status()
        
        # Determine if system is healthy
        healthy = True
        warnings: List[str] = []
        
        # Check engine loop
        if not engine_status.get('loop_active', False):
            healthy = False
            warnings.append("Engine loop is not active")
        
        # Check broker connection (broker required in LIVE mode, optional in TRAINING)
        current_mode = get_engine_mode()
        broker_connected = broker_status.get('connected', False)
        
        if current_mode == EngineMode.LIVE:
            if not broker_connected:
                healthy = False
                warnings.append("Broker not connected in LIVE mode")
            if broker_status.get('degraded', False):
                healthy = False
                warnings.append("Broker is in degraded state in LIVE mode")
        elif current_mode in (EngineMode.TRAINING, EngineMode.PAPER):
            # Broker is optional in TRAINING mode
            if not broker_connected:
                warnings.append("Broker not connected (optional in TRAINING mode)")
            if broker_status.get('degraded', False):
                warnings.append("Broker is in degraded state")
        else:
            # RESEARCH/PAUSED mode - broker not required
            pass
        
        # Check for engine errors
        if engine_status.get('engine_mode') == 'KILLED':
            healthy = False
            warnings.append("Engine mode is KILLED")
        
        # Check for active strategies
        active_strategies = [s for s in strategy_status if s.get('status') == 'ACTIVE']
        if not active_strategies and engine_status.get('loop_active', False):
            warnings.append("No active strategies")
        
        # ============================================================
        # PHASE 6 — UI BADGES (GREEN / YELLOW / RED)
        # ============================================================
        # Add badges to health response for UI display
        # 
        # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
        # SAFETY: display-only, no control actions, no auto-remediation
        # ============================================================
        from sentinel_x.monitoring.heartbeat import read_heartbeat
        import time
        
        # Get engine badge from heartbeat
        heartbeat = read_heartbeat()
        engine_badge = "⚪"
        engine_health = "UNKNOWN"
        
        if heartbeat:
            heartbeat_monotonic = heartbeat.get('heartbeat_monotonic')
            last_loop_tick_ts = heartbeat.get('last_loop_tick_ts')
            
            if heartbeat_monotonic and last_loop_tick_ts:
                now_mono = time.monotonic()
                heartbeat_age = now_mono - heartbeat_monotonic
                loop_tick_age = now_mono - last_loop_tick_ts
                
                # Classify engine health
                if loop_tick_age < 10.0:
                    engine_badge = "🟢"
                    engine_health = "RUNNING"
                elif heartbeat_age >= 10.0 and loop_tick_age < 30.0:
                    engine_badge = "🟡"
                    engine_health = "STALE"
                elif heartbeat_age >= 10.0 and loop_tick_age >= 30.0:
                    engine_badge = "🔴"
                    engine_health = "FROZEN"
        
        # Get strategy badges
        strategy_badges = {}
        if heartbeat:
            strategy_heartbeats = heartbeat.get('strategy_heartbeats', {})
            now_mono = time.monotonic()
            for strategy_name, strategy_data in strategy_heartbeats.items():
                last_tick_ts = strategy_data.get('last_tick_ts')
                if last_tick_ts:
                    strategy_age = now_mono - last_tick_ts
                    if strategy_age < 2.0:
                        strategy_badges[strategy_name] = {"badge": "🟢", "health": "GREEN", "age": strategy_age}
                    elif strategy_age < 30.0:
                        strategy_badges[strategy_name] = {"badge": "🟡", "health": "YELLOW", "age": strategy_age}
                    else:
                        strategy_badges[strategy_name] = {"badge": "🔴", "health": "RED", "age": strategy_age}
        
        return {
            'engine_status': engine_status,
            'strategy_status': strategy_status,
            'broker_status': broker_status,
            'healthy': healthy,
            'warnings': warnings,
            # PHASE 6: UI badges
            'engine_badge': engine_badge,
            'engine_health': engine_health,
            'strategy_badges': strategy_badges,
            'loop_phase': heartbeat.get('loop_phase', 'UNKNOWN') if heartbeat else 'UNKNOWN'
        }
        
    except Exception as e:
        logger.error(f"Error getting system health (non-fatal): {e}", exc_info=True)
        # Return safe defaults on error
        return {
            'engine_status': {
                'engine_state': 'UNKNOWN',
                'engine_mode': 'UNKNOWN',
                'uptime_seconds': 0.0,
                'loop_active': False,
                'last_tick_ts': None,
                'ticks_per_minute': 0.0
            },
            'strategy_status': [],
            'broker_status': {
                'broker_name': 'unknown',
                'mode': 'UNKNOWN',
                'connected': False,
                'last_successful_call_ts': None,
                'buying_power': None,
                'degraded': True
            },
            'healthy': False,
            'warnings': [f"Error getting system health: {str(e)}"]
        }
