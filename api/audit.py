"""
Audit & Compliance Logging

PHASE 5 — AUDIT & COMPLIANCE LOGGING

Implement append-only audit logging for compliance and governance.

Events logged:
- Engine state changes
- SHADOW promotions
- Kill-switch triggers
- Broker connectivity changes
- SHADOW signal generation
"""

import os
import json
import threading
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path


class AuditLogger:
    """
    Append-only audit logger.
    
    PHASE 5: Immutable log entries
    PHASE 7: Thread-safe, non-blocking
    """
    
    def __init__(self, log_file: Optional[str] = None):
        # Default log file location
        if log_file is None:
            log_dir = Path.home() / ".aegis_alpha" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = str(log_dir / "audit.log")
        
        self.log_file = log_file
        self._lock = threading.Lock()
        self._enabled = True
    
    def log_event(
        self,
        event_type: str,
        actor: str = "system",
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> None:
        """
        Log an audit event.
        
        PHASE 5: Append-only, never deletes or mutates
        PHASE 8: Extended with correlation_id for ARMED requests
        
        Args:
            event_type: Type of event (e.g., "engine_state_change", "kill_switch_trigger")
            actor: "system" | "user" | "api"
            payload: Event-specific data (no secrets)
            correlation_id: Optional correlation ID (e.g., request_id for ARMED operations)
        """
        if not self._enabled:
            return
        
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "actor": actor,
            "payload": payload or {},
        }
        
        # PHASE 8: Include correlation_id if provided
        if correlation_id:
            event["correlation_id"] = correlation_id
        
        # PHASE 5: Thread-safe append to log file
        with self._lock:
            try:
                with open(self.log_file, "a") as f:
                    f.write(json.dumps(event) + "\n")
            except Exception:
                # PHASE 5: Never raise - logging failure should not crash system
                pass
    
    def get_logs(self, limit: int = 100, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get audit logs.
        
        PHASE 5: Read-only access
        
        Args:
            limit: Maximum number of log entries to return
            event_type: Optional filter by event type
        
        Returns:
            List of log entries, most recent first
        """
        logs = []
        
        if not os.path.exists(self.log_file):
            return []
        
        with self._lock:
            try:
                with open(self.log_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            log_entry = json.loads(line)
                            if event_type is None or log_entry.get("event_type") == event_type:
                                logs.append(log_entry)
                        except json.JSONDecodeError:
                            # Skip invalid log entries
                            continue
            except Exception:
                # PHASE 5: Return empty list on error, never raise
                return []
        
        # Sort by timestamp (most recent first)
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # Limit results
        return logs[:limit]
    
    def enable(self) -> None:
        """Enable audit logging"""
        with self._lock:
            self._enabled = True
    
    def disable(self) -> None:
        """Disable audit logging (for testing)"""
        with self._lock:
            self._enabled = False


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get global audit logger instance"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
