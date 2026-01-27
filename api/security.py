"""
Security and Safety Enforcement

PHASE 4 — CONTROL PLANE SAFETY RULES

Enforces invariants:
- No endpoint may trigger execution
- No trading unless engine.state == ARMED
- Kill-switch status always exposed
- Default mode = MONITOR
- Shadow mode computes but does not execute
"""

import threading
from enum import Enum
from typing import Dict, Any
from dataclasses import dataclass, field


class KillSwitchStatus(Enum):
    """
    PHASE 3: Kill switch status with escalation levels
    
    States:
    - READY: Normal monitoring, all operations allowed
    - SOFT_KILL: Freeze promotions + shadow signal generation
    - HARD_KILL: Freeze all engine activity
    """
    READY = "READY"
    SOFT_KILL = "SOFT_KILL"
    HARD_KILL = "HARD_KILL"


@dataclass
class KillSwitch:
    """
    PHASE 3: Kill switch with escalation levels
    
    Always exposed, never auto-armed.
    HARD_KILL overrides everything.
    """
    status: KillSwitchStatus = KillSwitchStatus.READY
    armed: bool = False
    triggered_at: float = 0.0
    triggered_by: str = "system"  # "system" | "user" | "api"
    
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def to_dict(self) -> Dict[str, Any]:
        """Get kill switch state as dict"""
        with self._lock:
            return {
                "status": self.status.value,
                "armed": self.armed,
                "triggered_at": self.triggered_at if self.triggered_at > 0 else None,
                "triggered_by": self.triggered_by,
            }
    
    def is_safe(self) -> bool:
        """
        PHASE 3: Check if system is safe to operate
        
        Returns True only if status == READY
        """
        with self._lock:
            return self.status == KillSwitchStatus.READY
    
    def is_shadow_allowed(self) -> bool:
        """
        PHASE 3: Check if shadow signal generation is allowed
        
        Allowed if status is READY or SOFT_KILL (but not HARD_KILL)
        """
        with self._lock:
            return self.status != KillSwitchStatus.HARD_KILL
    
    def can_promote(self) -> bool:
        """
        PHASE 3: Check if engine promotion is allowed
        
        Allowed only if status == READY
        """
        with self._lock:
            return self.status == KillSwitchStatus.READY
    
    def trigger(self, level: KillSwitchStatus, triggered_by: str = "system") -> bool:
        """
        PHASE 3: Trigger kill switch escalation
        
        Args:
            level: SOFT_KILL or HARD_KILL
            triggered_by: "system" | "user" | "api"
        
        Returns:
            True if triggered, False if already at or above level
        """
        import time
        with self._lock:
            # Can only escalate, not de-escalate
            if level == KillSwitchStatus.SOFT_KILL:
                if self.status == KillSwitchStatus.READY:
                    self.status = KillSwitchStatus.SOFT_KILL
                    self.armed = True
                    self.triggered_at = time.time()
                    self.triggered_by = triggered_by
                    return True
            elif level == KillSwitchStatus.HARD_KILL:
                if self.status != KillSwitchStatus.HARD_KILL:
                    self.status = KillSwitchStatus.HARD_KILL
                    self.armed = True
                    self.triggered_at = time.time()
                    self.triggered_by = triggered_by
                    return True
            return False
    
    def reset(self) -> bool:
        """
        PHASE 3: Reset kill switch to READY
        
        Returns:
            True if reset, False if already READY
        """
        with self._lock:
            if self.status != KillSwitchStatus.READY:
                self.status = KillSwitchStatus.READY
                self.armed = False
                self.triggered_at = 0.0
                self.triggered_by = "system"
                return True
            return False


class SafetyGuard:
    """
    Safety guard for enforcing control plane invariants.
    
    PHASE 4: Prevents trading execution unless explicit conditions met.
    """
    
    def __init__(self, kill_switch: KillSwitch):
        self.kill_switch = kill_switch
        self._lock = threading.Lock()
    
    def check_trading_allowed(
        self,
        engine_state: str,
        trading_window: str,
        shadow_mode: bool,
        broker_trading_enabled: bool
    ) -> bool:
        """
        Check if trading is allowed - PHASE 4 safety check.
        
        Returns True only if ALL conditions met:
        - Engine state == ARMED
        - Trading window == OPEN
        - Shadow mode == False
        - Broker trading enabled == True
        - Kill switch is safe
        """
        with self._lock:
            # Kill switch check (highest priority)
            if not self.kill_switch.is_safe():
                return False
            
            # Engine must be ARMED
            if engine_state != "ARMED":
                return False
            
            # Trading window must be OPEN
            if trading_window != "OPEN":
                return False
            
            # Shadow mode must be disabled
            if shadow_mode:
                return False
            
            # Broker must have trading enabled
            if not broker_trading_enabled:
                return False
            
            return True
    
    def enforce_monitor_mode(self) -> Dict[str, Any]:
        """
        Enforce MONITOR mode safety.
        
        PHASE 4: In MONITOR mode, all trading operations are blocked.
        """
        return {
            "allowed": False,
            "reason": "System is in MONITOR mode - trading disabled",
            "mode": "MONITOR",
        }


# Global instances
_kill_switch: KillSwitch = KillSwitch()
_safety_guard: SafetyGuard = SafetyGuard(_kill_switch)


def get_kill_switch() -> KillSwitch:
    """Get global kill switch instance"""
    return _kill_switch


def get_safety_guard() -> SafetyGuard:
    """Get global safety guard instance"""
    return _safety_guard
