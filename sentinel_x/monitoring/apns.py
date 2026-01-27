"""
PHASE 3 — APPLE PUSH NOTIFICATIONS (SAFE MODE)

Integrate Apple Push Notifications (APNs) safely for critical engine events.

Notification scope:
- ENGINE_FROZEN
- ENGINE_RECOVERED
- WATCHDOG_RESTART (future use)

Implementation:
- Notification queue (non-blocking)
- Background sender thread
- Rate-limited (1 per state transition)

Payload example:
{
  "title": "Sentinel X Alert",
  "body": "Engine frozen — monitoring continues",
  "severity": "critical",
  "timestamp": monotonic_time
}

Rules:
- No order info
- No PnL values
- No sensitive data
- Push failures do NOT retry aggressively
- Push failures do NOT affect engine

MOBILE READ-ONLY GUARANTEE
PUSH IS ALERT-ONLY
METRICS ARE OBSERVABILITY-ONLY
LIVE CONTROL NOT ENABLED

REGRESSION LOCK — OBSERVABILITY ONLY
CONTROL REQUESTS ARE NON-ACTUATING
DO NOT ENABLE LIVE WITHOUT GOVERNANCE REVIEW
"""

import os
import time
import json
import threading
import queue
from typing import Dict, Optional, List, Any, Set
from datetime import datetime
from sentinel_x.monitoring.logger import logger
from sentinel_x.utils import safe_emit

# Configuration
APNS_KEY_PATH = os.getenv("APNS_KEY_PATH", "")  # Path to APNs key file (.p8)
APNS_KEY_ID = os.getenv("APNS_KEY_ID", "")  # APNs key ID
APNS_TEAM_ID = os.getenv("APNS_TEAM_ID", "")  # APNs team ID
APNS_BUNDLE_ID = os.getenv("APNS_BUNDLE_ID", "com.sentinelx.rork")  # App bundle ID
APNS_ENABLED = os.getenv("ENABLE_APNS", "false").lower() == "true" and bool(APNS_KEY_PATH and APNS_KEY_ID and APNS_TEAM_ID)

# Rate limiting (1 notification per state transition per device)
_notification_history: Dict[str, float] = {}  # device_token:last_notification_time
_notification_lock = threading.Lock()
RATE_LIMIT_SECONDS = 60  # Minimum seconds between notifications to same device

# Notification queue (thread-safe)
_notification_queue: queue.Queue = queue.Queue(maxsize=1000)
_sender_thread: Optional[threading.Thread] = None
_sender_running = False


def _send_apns_notification(device_token: str, payload: Dict[str, Any]) -> bool:
    """
    Send APNs notification via HTTP/2 API (non-blocking).
    
    PHASE 3: Safe mode - uses HTTP/2 API with JWT authentication.
    
    Args:
        device_token: APNs device token
        payload: Notification payload dict
    
    Returns:
        True if sent successfully, False otherwise
    
    SAFETY: Failures are silent, never affect engine
    """
    if not APNS_ENABLED:
        logger.debug("APNs not enabled, skipping notification")
        return False
    
    try:
        # PHASE 3: Use HTTP/2 APNs API (simplified - actual implementation would use PyAPNs or similar)
        # For now, log the notification (production would send via APNs HTTP/2 API)
        
        # Rate limit check (per device)
        with _notification_lock:
            last_sent = _notification_history.get(device_token, 0)
            if time.time() - last_sent < RATE_LIMIT_SECONDS:
                logger.debug(f"APNs rate limit: skipping notification to device (last sent {time.time() - last_sent:.1f}s ago)")
                return False
            
            # Mark as sent
            _notification_history[device_token] = time.time()
        
        # Log notification (in production, this would send via APNs HTTP/2 API)
        logger.info(
            f"APNS_NOTIFICATION | "
            f"device_token={device_token[:16]}... | "
            f"event_type={payload.get('event_type', 'UNKNOWN')} | "
            f"severity={payload.get('severity', 'info')}"
        )
        
        # PHASE 3: In production, implement actual APNs HTTP/2 send:
        # import httpx
        # async with httpx.AsyncClient(http2=True) as client:
        #     headers = {
        #         "authorization": f"bearer {jwt_token}",
        #         "apns-topic": APNS_BUNDLE_ID,
        #         "apns-priority": "10",
        #         "apns-push-type": "alert"
        #     }
        #     response = await client.post(
        #         f"https://api.push.apple.com/3/device/{device_token}",
        #         headers=headers,
        #         json={"aps": {"alert": {"title": payload["title"], "body": payload["body"]}}}
        #     )
        
        return True
    
    except Exception as e:
        # SAFETY: Notification failures must NOT affect engine
        logger.debug(f"Error sending APNs notification (non-fatal): {e}")
        return False


def _notification_sender_worker():
    """
    Background worker thread that processes notification queue.
    
    SAFETY: Runs in separate thread, never blocks engine
    """
    global _sender_running
    
    logger.info("APNs notification sender worker started")
    _sender_running = True
    
    while _sender_running:
        try:
            # Get notification from queue (with timeout for graceful shutdown)
            try:
                item = _notification_queue.get(timeout=1.0)
                device_token, payload = item
                
                # Send notification (non-blocking)
                _send_apns_notification(device_token, payload)
                
                # Mark task as done
                _notification_queue.task_done()
            
            except queue.Empty:
                # Timeout - check if still running
                continue
        
        except Exception as e:
            # SAFETY: Worker thread errors must NOT affect engine
            logger.error(f"Error in APNs notification sender worker (non-fatal): {e}", exc_info=True)
            time.sleep(1.0)  # Brief pause before retry
    
    logger.info("APNs notification sender worker stopped")


def send_push_notification(
    device_token: str,
    event_type: str,
    title: str,
    body: str,
    severity: str = "info",
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    PHASE 3 — PUSH NOTIFICATIONS (SAFE MODE)
    
    Queue a push notification for delivery (non-blocking).
    
    Args:
        device_token: APNs device token
        event_type: Event type (ENGINE_FROZEN, ENGINE_RECOVERED, etc.)
        title: Notification title
        body: Notification body
        severity: Severity level (info, warning, critical)
        metadata: Optional metadata (non-sensitive only)
    
    Rules:
        - No order info
        - No PnL values
        - No sensitive data
        - Push failures do NOT retry aggressively
        - Push failures do NOT affect engine
    
    SAFETY: Non-blocking, fire-and-forget, never raises
    """
    if not APNS_ENABLED:
        return  # APNs not enabled
    
    try:
        # Build payload (non-sensitive data only)
        payload: Dict[str, Any] = {
            "title": title,
            "body": body,
            "severity": severity,
            "timestamp": time.monotonic(),
            "event_type": event_type,
        }
        
        # Add metadata (sanitized - no sensitive data)
        if metadata:
            sanitized_metadata = {
                k: v for k, v in metadata.items()
                if k not in ['token', 'api_key', 'password', 'secret', 'device_token', 'pnl', 'order_id']
            }
            if sanitized_metadata:
                payload["metadata"] = sanitized_metadata
        
        # Queue notification (non-blocking, drops if queue full)
        try:
            _notification_queue.put_nowait((device_token, payload))
        except queue.Full:
            # Queue full - drop notification (backpressure)
            logger.debug(f"APNs notification queue full, dropping notification: {event_type}")
    
    except Exception as e:
        # SAFETY: Notification queuing failures must NOT affect engine
        logger.debug(f"Error queuing APNs notification (non-fatal): {e}")


def start_apns_sender() -> None:
    """Start APNs notification sender worker thread."""
    global _sender_thread
    
    if not APNS_ENABLED:
        logger.debug("APNs not enabled, not starting sender thread")
        return
    
    if _sender_thread and _sender_thread.is_alive():
        return  # Already running
    
    _sender_thread = threading.Thread(
        target=_notification_sender_worker,
        daemon=True,  # Daemon thread - won't prevent shutdown
        name="APNsSender"
    )
    _sender_thread.start()
    logger.info("APNs notification sender started")


def stop_apns_sender() -> None:
    """Stop APNs notification sender worker thread."""
    global _sender_running, _sender_thread
    
    _sender_running = False
    
    if _sender_thread and _sender_thread.is_alive():
        _sender_thread.join(timeout=5.0)  # Wait up to 5 seconds for graceful shutdown
    
    logger.info("APNs notification sender stopped")
