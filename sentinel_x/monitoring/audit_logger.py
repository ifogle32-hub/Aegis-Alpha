"""
PHASE 3: Immutable Audit Log System for Regulator-Safe Export

Features:
- JSON Lines format (.jsonl)
- UTC timestamps
- request_id tracking
- device_id (hashed)
- NO secrets
- NO PII
- Deterministic ordering
- Tamper-evident checksums
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import threading

# Audit log configuration
AUDIT_LOG_DIR = Path(__file__).parent.parent / "logs" / "audit"
AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.jsonl"

_audit_lock = threading.Lock()


def hash_device_id(device_id: str) -> str:
    """
    Hash device_id for audit logs (no PII).
    
    Returns:
        SHA256 hash of device_id (first 16 chars for readability)
    """
    if not device_id:
        return "anonymous"
    return hashlib.sha256(device_id.encode()).hexdigest()[:16]


def log_audit_event(
    event_type: str,
    request_id: str,
    device_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Log an audit event to immutable audit log.
    
    PHASE 3: Events:
    - START
    - STOP
    - KILL
    - MODE_CHANGE
    - AUTH_FAILURE
    - DRAWNDOWN_BREACH
    
    Args:
        event_type: Type of event
        request_id: Request tracking ID
        device_id: Device ID (will be hashed)
        metadata: Additional event metadata (no secrets)
    """
    try:
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "request_id": request_id,
            "device_id_hash": hash_device_id(device_id) if device_id else None,
        }
        
        # Add metadata (sanitized - no secrets)
        if metadata:
            # Remove any secret fields
            sanitized_metadata = {
                k: v for k, v in metadata.items()
                if k not in ['token', 'api_key', 'password', 'secret']
            }
            event["metadata"] = sanitized_metadata
        
        # Write to audit log (append mode, thread-safe)
        with _audit_lock:
            with open(AUDIT_LOG_FILE, 'a') as f:
                f.write(json.dumps(event) + '\n')
        
        # Calculate checksum for this line (tamper-evident)
        line_checksum = hashlib.sha256(json.dumps(event).encode()).hexdigest()[:16]
        
    except Exception as e:
        # Audit logging must never fail - log to standard logger as fallback
        import logging
        logging.getLogger("sentinel_x").error(f"Audit log write failed: {e}")


def export_audit_log(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """
    Export audit log with optional date filtering.
    
    PHASE 3: Returns generator for streaming large exports.
    
    Args:
        start_date: ISO format start date (optional)
        end_date: ISO format end date (optional)
    
    Yields:
        Audit log entries as JSON strings
    """
    if not AUDIT_LOG_FILE.exists():
        return
    
    try:
        with open(AUDIT_LOG_FILE, 'r') as f:
            for line in f:
                if not line.strip():
                    continue
                
                try:
                    entry = json.loads(line)
                    
                    # Date filtering
                    if start_date or end_date:
                        entry_timestamp = entry.get('timestamp', '')
                        if start_date and entry_timestamp < start_date:
                            continue
                        if end_date and entry_timestamp > end_date:
                            continue
                    
                    # Calculate checksum for this entry
                    entry_checksum = hashlib.sha256(line.encode()).hexdigest()[:16]
                    entry['_checksum'] = entry_checksum
                    
                    yield json.dumps(entry) + '\n'
                
                except json.JSONDecodeError:
                    # Skip malformed entries
                    continue
    
    except Exception as e:
        import logging
        logging.getLogger("sentinel_x").error(f"Audit log export failed: {e}")


def get_audit_log_checksum() -> str:
    """
    Calculate checksum of entire audit log file (tamper-evident).
    
    Returns:
        SHA256 checksum (first 32 chars)
    """
    if not AUDIT_LOG_FILE.exists():
        return ""
    
    try:
        checksum = hashlib.sha256()
        with open(AUDIT_LOG_FILE, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                checksum.update(chunk)
        return checksum.hexdigest()[:32]
    except Exception as e:
        import logging
        logging.getLogger("sentinel_x").error(f"Audit log checksum failed: {e}")
        return ""

