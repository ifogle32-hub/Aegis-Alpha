"""
PHASE 4: Push Notification System for Critical Events

Events:
- EMERGENCY KILL triggered
- Daily drawdown threshold breached
- Engine crash / restart

Channels:
- Mobile push (APNs / FCM) - via webhook
- Desktop OS notification - via webhook
- Optional webhook URL

Rules:
- Push is FIRE-AND-FORGET
- Never blocks engine
- Deduplicate repeated events
"""

import asyncio
import httpx
import os
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any, Set
from sentinel_x.monitoring.logger import logger
from sentinel_x.utils import safe_emit

# Configuration
WEBHOOK_URL = os.getenv("NOTIFICATION_WEBHOOK_URL", "")
NOTIFICATION_RETRY_MAX = 3
NOTIFICATION_RETRY_DELAY = 1.0  # seconds
NOTIFICATION_DEDUP_WINDOW = 60  # seconds

# Deduplication tracking (thread-safe for module-level)
_recent_events: Dict[str, float] = {}  # event_key -> timestamp
_dedup_lock = threading.Lock()  # Thread lock for sync operations


def _get_event_key(event_type: str, metadata: Dict[str, Any]) -> str:
    """Generate unique key for event deduplication."""
    # Use event type + relevant metadata for deduplication
    key_parts = [event_type]
    
    if event_type == "KILL":
        # KILL events are always unique (each kill is distinct)
        return f"{event_type}:{datetime.utcnow().isoformat()}"
    elif event_type == "DRAWNDOWN_BREACH":
        # Deduplicate by threshold value
        threshold = metadata.get("threshold", "")
        return f"{event_type}:{threshold}"
    elif event_type == "ENGINE_CRASH":
        # Deduplicate crashes within time window
        return f"{event_type}:{datetime.utcnow().timestamp() // 60}"  # Per minute
    
    return event_type


async def _is_duplicate(event_key: str) -> bool:
    """Check if event is duplicate within dedup window."""
    now = datetime.utcnow().timestamp()
    
    with _dedup_lock:
        # Clean old entries
        global _recent_events
        _recent_events = {k: v for k, v in _recent_events.items() 
                         if now - v < NOTIFICATION_DEDUP_WINDOW}
        
        # Check if this event was recent
        if event_key in _recent_events:
            last_seen = _recent_events[event_key]
            if now - last_seen < NOTIFICATION_DEDUP_WINDOW:
                return True
        
        # Mark as seen
        _recent_events[event_key] = now
        return False


async def _send_webhook_notification(event_type: str, message: str, metadata: Dict[str, Any]):
    """
    Send notification via webhook (fire-and-forget).
    
    PHASE 4: Retry with exponential backoff, drop silently after max retries.
    """
    if not WEBHOOK_URL:
        return  # Webhook not configured
    
    payload = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "message": message,
        "metadata": metadata
    }
    
    # Retry with exponential backoff
    for attempt in range(NOTIFICATION_RETRY_MAX):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(WEBHOOK_URL, json=payload)
                if response.status_code < 400:
                    logger.debug(f"Notification sent: {event_type} (attempt {attempt + 1})")
                    return
                else:
                    logger.warning(
                        f"Notification webhook error: {response.status_code} "
                        f"(attempt {attempt + 1}/{NOTIFICATION_RETRY_MAX})"
                    )
        except Exception as e:
            logger.debug(f"Notification send error: {e} (attempt {attempt + 1}/{NOTIFICATION_RETRY_MAX})")
        
        # Exponential backoff
        if attempt < NOTIFICATION_RETRY_MAX - 1:
            await asyncio.sleep(NOTIFICATION_RETRY_DELAY * (2 ** attempt))
    
    # Silent failure after max retries (never block engine)
    logger.debug(f"Notification dropped after {NOTIFICATION_RETRY_MAX} retries: {event_type}")


async def send_kill_notification(request_id: str):
    """
    PHASE 4: Send push notification for KILL event.
    
    Fire-and-forget, never blocks engine.
    """
    event_type = "KILL"
    message = "⚠️ EMERGENCY KILL: Trading engine has been shut down immediately"
    metadata = {
        "request_id": request_id,
        "severity": "critical"
    }
    
    # Check for duplicates
    event_key = _get_event_key(event_type, metadata)
    if await _is_duplicate(event_key):
        logger.debug(f"KILL notification deduplicated: {request_id}")
        return
    
    # Send asynchronously (fire-and-forget)
    safe_emit(_send_webhook_notification(event_type, message, metadata))


async def send_drawdown_notification(threshold: float, current_drawdown: float):
    """
    PHASE 4: Send push notification for drawdown breach.
    
    Fire-and-forget, never blocks engine.
    """
    event_type = "DRAWNDOWN_BREACH"
    message = f"⚠️ Drawdown Alert: Daily drawdown {current_drawdown*100:.2f}% exceeds threshold {threshold*100:.2f}%"
    metadata = {
        "threshold": str(threshold),
        "current_drawdown": str(current_drawdown),
        "severity": "warning"
    }
    
    # Check for duplicates
    event_key = _get_event_key(event_type, metadata)
    if await _is_duplicate(event_key):
        logger.debug(f"Drawdown notification deduplicated: {threshold}")
        return
    
    # Send asynchronously (fire-and-forget)
    safe_emit(_send_webhook_notification(event_type, message, metadata))


async def send_engine_crash_notification(error_message: str):
    """
    PHASE 4: Send push notification for engine crash/restart.
    
    Fire-and-forget, never blocks engine.
    """
    event_type = "ENGINE_CRASH"
    message = f"⚠️ Engine Error: {error_message}"
    metadata = {
        "error_message": error_message,
        "severity": "critical"
    }
    
    # Check for duplicates (per minute)
    event_key = _get_event_key(event_type, metadata)
    if await _is_duplicate(event_key):
        logger.debug(f"Engine crash notification deduplicated")
        return
    
    # Send asynchronously (fire-and-forget)
    safe_emit(_send_webhook_notification(event_type, message, metadata))


# PHASE 5: Additional alert types
async def send_first_trade_notification(symbol: str, side: str, qty: float, price: float, strategy: str, mode: str | None = None):
    """
    PHASE 5: Send notification for first trade of session.
    
    Fire-and-forget, never blocks engine.
    """
    event_type = "FIRST_TRADE"
    message = f"📊 First Trade: {side} {qty} {symbol} @ ${price:.2f} ({strategy})"
    metadata = {
        "symbol": symbol,
        "side": side,
        "qty": str(qty),
        "price": str(price),
        "strategy": strategy,
        "mode": mode or "PAPER",  # Default to PAPER if None
        "severity": "info"
    }
    
    # Check for duplicates (per session - use date as key)
    event_key = f"{event_type}:{datetime.utcnow().date()}"
    if await _is_duplicate(event_key):
        logger.debug(f"First trade notification deduplicated")
        return
    
    # Send asynchronously (fire-and-forget)
    safe_emit(_send_webhook_notification(event_type, message, metadata))


async def send_strategy_auto_disabled_notification(strategy: str, reason: str):
    """
    PHASE 5: Send notification when strategy is auto-disabled.
    
    Fire-and-forget, never blocks engine.
    """
    event_type = "STRATEGY_AUTO_DISABLED"
    message = f"🛑 Strategy Auto-Disabled: {strategy} - {reason}"
    metadata = {
        "strategy": strategy,
        "reason": reason,
        "severity": "warning"
    }
    
    # Check for duplicates (per strategy)
    event_key = f"{event_type}:{strategy}"
    if await _is_duplicate(event_key):
        logger.debug(f"Strategy auto-disabled notification deduplicated: {strategy}")
        return
    
    # Send asynchronously (fire-and-forget)
    safe_emit(_send_webhook_notification(event_type, message, metadata))


async def send_live_mode_armed_notification():
    """
    PHASE 5: Send notification when LIVE mode is armed.
    
    Fire-and-forget, never blocks engine.
    """
    event_type = "LIVE_MODE_ARMED"
    message = "🔴 LIVE MODE ARMED - Real capital at risk!"
    metadata = {
        "severity": "critical",
        "mode": "LIVE"
    }
    
    # Check for duplicates (per hour)
    event_key = f"{event_type}:{datetime.utcnow().timestamp() // 3600}"
    if await _is_duplicate(event_key):
        logger.debug(f"Live mode armed notification deduplicated")
        return
    
    # Send asynchronously (fire-and-forget)
    safe_emit(_send_webhook_notification(event_type, message, metadata))


async def send_drawdown_breach_notification(drawdown: float, threshold: float):
    """
    PHASE 5: Send notification when drawdown breaches threshold.
    
    Fire-and-forget, never blocks engine.
    """
    event_type = "DRAWNDOWN_BREACH"
    message = f"⚠️ Drawdown Alert: {drawdown*100:.2f}% exceeds threshold {threshold*100:.2f}%"
    metadata = {
        "drawdown": str(drawdown),
        "threshold": str(threshold),
        "severity": "warning"
    }
    
    # Check for duplicates (per threshold value)
    event_key = f"{event_type}:{threshold}"
    if await _is_duplicate(event_key):
        logger.debug(f"Drawdown breach notification deduplicated: {threshold}")
        return
    
    # Send asynchronously (fire-and-forget)
    safe_emit(_send_webhook_notification(event_type, message, metadata))


# ============================================================================
# PHASE 1 — PUSH NOTIFICATIONS (FROZEN / RECOVERED)
# ============================================================================
# REGRESSION LOCK — OBSERVABILITY ONLY
# CONTROL REQUESTS ARE NON-ACTUATING
# DO NOT ENABLE LIVE WITHOUT GOVERNANCE REVIEW
# ============================================================================

async def send_engine_frozen_notification(heartbeat_age: float, loop_tick_age: float):
    """
    PHASE 1 — PUSH NOTIFICATIONS (FROZEN / RECOVERED)
    
    Send push notification for ENGINE_FROZEN event.
    Triggered ONLY on state transition: RUNNING → FROZEN
    
    Event payload:
    {
      "event": "ENGINE_FROZEN",
      "timestamp": monotonic_time,
      "heartbeat_age": float,
      "loop_tick_age": float
    }
    
    Safety:
    - Alerts fire at most once per transition
    - No retries
    - No engine coupling
    - Fire-and-forget, never blocks engine
    """
    event_type = "ENGINE_FROZEN"
    message = f"🔴 ENGINE FROZEN: Heartbeat age {heartbeat_age:.1f}s, Loop tick age {loop_tick_age:.1f}s"
    metadata = {
        "heartbeat_age": str(heartbeat_age),
        "loop_tick_age": str(loop_tick_age),
        "severity": "critical",
        "timestamp": str(time.monotonic())
    }
    
    # Check for duplicates (per transition - use timestamp bucket)
    event_key = f"{event_type}:{int(time.time()) // 60}"  # Per minute dedup
    if await _is_duplicate(event_key):
        logger.debug(f"Engine frozen notification deduplicated")
        return
    
    # Send asynchronously (fire-and-forget)
    safe_emit(_send_webhook_notification(event_type, message, metadata))


async def send_engine_recovered_notification(heartbeat_age: float, loop_tick_age: float):
    """
    PHASE 1 — PUSH NOTIFICATIONS (FROZEN / RECOVERED)
    
    Send push notification for ENGINE_RECOVERED event.
    Triggered ONLY on state transition: FROZEN → RUNNING
    
    Event payload:
    {
      "event": "ENGINE_RECOVERED",
      "timestamp": monotonic_time,
      "heartbeat_age": float,
      "loop_tick_age": float
    }
    
    Safety:
    - Alerts fire at most once per transition
    - No retries
    - No engine coupling
    - Fire-and-forget, never blocks engine
    """
    event_type = "ENGINE_RECOVERED"
    message = f"🟢 ENGINE RECOVERED: Heartbeat age {heartbeat_age:.1f}s, Loop tick age {loop_tick_age:.1f}s"
    metadata = {
        "heartbeat_age": str(heartbeat_age),
        "loop_tick_age": str(loop_tick_age),
        "severity": "info",
        "timestamp": str(time.monotonic())
    }
    
    # Check for duplicates (per transition - use timestamp bucket)
    event_key = f"{event_type}:{int(time.time()) // 60}"  # Per minute dedup
    if await _is_duplicate(event_key):
        logger.debug(f"Engine recovered notification deduplicated")
        return
    
    # Send asynchronously (fire-and-forget)
    safe_emit(_send_webhook_notification(event_type, message, metadata))

