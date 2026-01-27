"""
PHASE 3 — BROKER HEALTH CHECK (READ-ONLY)

Read-only broker status collector.

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

from sentinel_x.monitoring.logger import logger
from sentinel_x.core.engine import get_engine
from sentinel_x.core.engine_mode import get_engine_mode, EngineMode


# Track last successful call timestamps per broker
_last_successful_call: Dict[str, float] = {}


def _record_successful_call(broker_name: str) -> None:
    """Record a successful broker call (called by broker executors)."""
    _last_successful_call[broker_name] = time.time()


def get_broker_status() -> Dict:
    """
    Get read-only broker status snapshot.
    
    Returns:
        Dictionary with broker status fields:
        - broker_name: Name of active broker (alpaca, tradovate, paper, or none)
        - mode: PAPER / LIVE
        - connected: bool - True if broker is connected
        - last_successful_call_ts: float - Timestamp of last successful call (or None)
        - buying_power: float - Buying power if available (or None)
        - degraded: bool - True if broker is in degraded state
        
    Rules:
        - Use existing executor objects
        - NO order submissions
        - NO account mutations
        - Catch all exceptions → degraded=True
    """
    try:
        engine = get_engine()
        if not engine or not engine.order_router:
            return {
                'broker_name': 'none',
                'mode': 'UNKNOWN',
                'connected': False,
                'last_successful_call_ts': None,
                'buying_power': None,
                'degraded': True
            }
        
        router = engine.order_router
        executor = router.active_executor
        
        if not executor:
            # Check if any executor is registered
            if router.alpaca_executor:
                executor = router.alpaca_executor
            elif router.paper_executor:
                executor = router.paper_executor
            else:
                return {
                    'broker_name': 'none',
                    'mode': 'UNKNOWN',
                    'connected': False,
                    'last_successful_call_ts': None,
                    'buying_power': None,
                    'degraded': False  # Not degraded, just not connected
                }
        
        # Get broker name
        broker_name = getattr(executor, 'name', 'unknown')
        
        # Determine mode
        current_mode = get_engine_mode()
        if current_mode == EngineMode.LIVE:
            mode = 'LIVE'
        elif current_mode in (EngineMode.TRAINING, EngineMode.PAPER):
            mode = 'PAPER'
        else:
            mode = 'PAPER'  # Default to PAPER for safety
        
        # Check connection status (non-invasive)
        connected = False
        degraded = False
        buying_power = None
        last_successful_call_ts = _last_successful_call.get(broker_name)
        
        try:
            # Try to get connection status
            if hasattr(executor, 'connected'):
                connected = bool(executor.connected)
            elif hasattr(executor, 'health_check'):
                # Use health check if available (read-only)
                try:
                    health = executor.health_check()
                    connected = health.get('connected', False) if isinstance(health, dict) else False
                except Exception:
                    degraded = True
                    connected = False
            else:
                # Assume connected if we can't check
                connected = True
            
            # Try to get buying power (read-only, non-invasive)
            if connected and hasattr(executor, 'get_account'):
                try:
                    account = executor.get_account()
                    if account:
                        if isinstance(account, dict):
                            buying_power = account.get('buying_power') or account.get('day_trading_buying_power')
                        else:
                            # Try object attributes
                            buying_power = getattr(account, 'buying_power', None) or getattr(account, 'day_trading_buying_power', None)
                        
                        if buying_power is not None:
                            buying_power = float(buying_power)
                            # Record successful call
                            _record_successful_call(broker_name)
                            last_successful_call_ts = _last_successful_call.get(broker_name)
                except Exception as e:
                    logger.debug(f"Error getting buying power (non-fatal): {e}")
                    degraded = True
                    # Don't set buying_power - leave as None
            
        except Exception as e:
            logger.error(f"Error checking broker status (non-fatal): {e}", exc_info=True)
            degraded = True
            connected = False
        
        return {
            'broker_name': broker_name,
            'mode': mode,
            'connected': connected,
            'last_successful_call_ts': last_successful_call_ts,
            'buying_power': buying_power,
            'degraded': degraded
        }
        
    except Exception as e:
        logger.error(f"Error getting broker status (non-fatal): {e}", exc_info=True)
        # Return safe defaults on error
        return {
            'broker_name': 'unknown',
            'mode': 'UNKNOWN',
            'connected': False,
            'last_successful_call_ts': None,
            'buying_power': None,
            'degraded': True
        }
