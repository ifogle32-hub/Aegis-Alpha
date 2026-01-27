"""
Engine Loop and State Management

PHASE 1 — ENGINE LOOP + HEARTBEAT (CONTROL PLANE SAFE)

Implements a background engine loop that:
- Updates a monotonic loop_tick
- Updates a heartbeat timestamp every second
- Never blocks request handlers
- Runs as a daemon thread started at FastAPI startup

PHASE 4 — CONTROL PLANE SAFETY RULES
- Default mode = MONITOR
- Shadow mode computes but does not execute
- No trading unless engine.state == ARMED
"""

import time
import threading
from enum import Enum
from typing import Dict, Any, Tuple
from dataclasses import dataclass, field


class EngineState(Enum):
    """Engine state enum - locked values for control plane safety"""
    BOOTING = "BOOTING"
    MONITOR = "MONITOR"  # Default - read-only observation
    SHADOW = "SHADOW"    # Compute but do not execute
    ARMED = "ARMED"      # Trading enabled (not default)
    DEGRADED = "DEGRADED"  # System degradation detected


class TradingWindow(Enum):
    """Trading window state"""
    OPEN = "OPEN"
    CLOSED = "CLOSED"  # Default - no trading


@dataclass
class EngineRuntime:
    """
    Engine runtime state - thread-safe mutable state for control plane.
    
    SAFETY INVARIANTS:
    - Default state: MONITOR (no trading)
    - Default trading_window: CLOSED
    - Default shadow_mode: False
    - ARMED is TEMPORARY and EXPIRING
    - ARMED must NEVER persist across restarts
    - All fields are atomic (simple types or guarded by lock)
    """
    state: EngineState = EngineState.BOOTING
    loop_tick: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    shadow_mode: bool = False
    trading_window: TradingWindow = TradingWindow.CLOSED
    
    # PHASE 1 — ARMED STATE METADATA
    # ARMED metadata is TEMPORARY and NEVER persists
    armed_at: float = 0.0  # Timestamp when ARMED was activated
    armed_expires_at: float = 0.0  # Timestamp when ARMED expires
    armed_reason: str = ""  # Reason for ARMED activation
    armed_approvals: list = field(default_factory=list)  # List of approvals collected
    
    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def get_state_dict(self) -> Dict[str, Any]:
        """Get current state as dict - thread-safe, never raises"""
        with self._lock:
            try:
                now = time.time()
                armed_active = (self.state == EngineState.ARMED and 
                               self.armed_expires_at > 0 and 
                               now < self.armed_expires_at)
                
                result = {
                    "state": self.state.value,
                    "loop_tick": self.loop_tick,
                    "heartbeat_age_ms": int((time.time() - self.last_heartbeat) * 1000),
                    "shadow_mode": self.shadow_mode,
                    "trading_window": self.trading_window.value,
                }
                
                # PHASE 1: Include ARMED metadata if ARMED is active
                if armed_active:
                    result["armed"] = {
                        "active": True,
                        "armed_at": self.armed_at,
                        "expires_at": self.armed_expires_at,
                        "expires_in_seconds": max(0, int(self.armed_expires_at - now)),
                        "reason": self.armed_reason,
                        "approval_count": len(self.armed_approvals),
                    }
                else:
                    result["armed"] = {
                        "active": False,
                        "expires_at": None,
                        "approval_count": 0,
                    }
                
                return result
            except Exception:
                # SAFETY: Never raise from state access
                return {
                    "state": EngineState.DEGRADED.value,
                    "loop_tick": 0,
                    "heartbeat_age_ms": 999999,
                    "shadow_mode": False,
                    "trading_window": TradingWindow.CLOSED.value,
                    "armed": {
                        "active": False,
                        "expires_at": None,
                        "approval_count": 0,
                    },
                }
    
    def update_heartbeat(self) -> None:
        """Update heartbeat timestamp - called by engine loop"""
        with self._lock:
            self.loop_tick += 1
            self.last_heartbeat = time.time()
    
    def set_state(self, new_state: EngineState) -> None:
        """Set engine state - thread-safe"""
        with self._lock:
            # PHASE 6: Clear ARMED metadata when leaving ARMED state
            if self.state == EngineState.ARMED and new_state != EngineState.ARMED:
                self.armed_at = 0.0
                self.armed_expires_at = 0.0
                self.armed_reason = ""
                self.armed_approvals = []
            self.state = new_state
    
    def set_trading_window(self, window: TradingWindow) -> None:
        """Set trading window - thread-safe"""
        with self._lock:
            self.trading_window = window
    
    def is_trading_allowed(self) -> bool:
        """
        PHASE 9 — EXECUTION GUARDRAILS (PRE-EXECUTION ONLY)
        
        Check if trading is allowed. Returns True only if:
        - Engine state == ARMED
        - Current time < armed_expires_at
        - Kill-switch is READY (checked externally)
        """
        with self._lock:
            # PHASE 9: Execution guardrails
            if self.state != EngineState.ARMED:
                return False
            
            now = time.time()
            if self.armed_expires_at <= 0 or now >= self.armed_expires_at:
                return False
            
            return True
    
    def can_promote_to(self, target_state: EngineState, kill_switch_allowed: bool = True) -> Tuple[bool, str]:
        """
        PHASE 2: Check if promotion to target state is allowed.
        
        Rules:
        - Only MONITOR → SHADOW is allowed
        - ARMED is NOT reachable
        - Must be healthy (heartbeat < threshold)
        - PHASE 3: Kill-switch must allow promotion
        
        Args:
            target_state: Target engine state
            kill_switch_allowed: Whether kill-switch allows promotion (default True)
        
        Returns:
            (allowed: bool, reason: str)
        """
        with self._lock:
            # PHASE 3: Check kill-switch first (highest priority)
            if not kill_switch_allowed:
                return False, "Kill-switch does not allow promotion"
            
            # PHASE 3: ARMED promotion must go through request flow
            if target_state == EngineState.ARMED:
                return False, "ARMED state requires multi-signature approval via /engine/armed/request"
            
            # Can only promote from MONITOR to SHADOW
            if target_state == EngineState.SHADOW:
                if self.state == EngineState.MONITOR:
                    # Check heartbeat health (must be < 5 seconds old)
                    heartbeat_age = time.time() - self.last_heartbeat
                    if heartbeat_age > 5.0:
                        return False, f"Engine unhealthy - heartbeat age {heartbeat_age:.1f}s > 5s"
                    return True, "Promotion allowed"
                else:
                    return False, f"Cannot promote to SHADOW from {self.state.value}"
            
            # All other promotions not allowed
            return False, f"Promotion to {target_state.value} not allowed"
    
    def promote_to(self, target_state: EngineState, kill_switch_allowed: bool = True) -> Tuple[bool, str]:
        """
        PHASE 2: Promote engine to target state.
        
        Rules:
        - Only MONITOR → SHADOW allowed
        - ARMED rejected
        - PHASE 3: Kill-switch must allow promotion
        - Logs promotion attempt
        
        Args:
            target_state: Target engine state
            kill_switch_allowed: Whether kill-switch allows promotion (default True)
        
        Returns:
            (success: bool, message: str)
        """
        allowed, reason = self.can_promote_to(target_state, kill_switch_allowed)
        
        if not allowed:
            return False, reason
        
        with self._lock:
            old_state = self.state
            self.state = target_state
            
            # PHASE 2: Update shadow_mode flag
            if target_state == EngineState.SHADOW:
                self.shadow_mode = True
            else:
                self.shadow_mode = False
        
        # PHASE 5: Log promotion (will be called from audit logger)
        return True, f"Promoted from {old_state.value} to {target_state.value}"


# Global engine runtime instance
_engine_runtime: EngineRuntime = EngineRuntime(state=EngineState.BOOTING)
_engine_thread: threading.Thread | None = None
_engine_running: bool = False


def get_engine_runtime() -> EngineRuntime:
    """Get global engine runtime instance"""
    return _engine_runtime


def engine_loop() -> None:
    """
    Background engine loop - runs as daemon thread.
    
    PHASE 1: Never blocks request handlers
    PHASE 5: Production runtime compatible
    PHASE 6: Auto-expiry monitoring for ARMED state
    """
    global _engine_runtime, _engine_running
    
    # PHASE 6: ARMED must NEVER persist across restarts
    # Note: Shadow mode state is set during lifespan init, not here.
    # This loop only monitors and maintains state, it does not initialize it.
    
    # Clear any ARMED metadata (safety)
    with _engine_runtime._lock:
        _engine_runtime.armed_at = 0.0
        _engine_runtime.armed_expires_at = 0.0
        _engine_runtime.armed_reason = ""
        _engine_runtime.armed_approvals = []
    
    # Main loop - updates heartbeat every second
    while _engine_running:
        try:
            _engine_runtime.update_heartbeat()
            
            # PHASE 6: Kill-switch override check (highest priority)
            overridden, _ = check_kill_switch_override()
            if overridden:
                from api.audit import get_audit_logger
                audit_logger = get_audit_logger()
                audit_logger.log_event(
                    event_type="armed_kill_switch_override",
                    actor="system",
                    payload={
                        "triggered_at": time.time(),
                    }
                )
            
            # PHASE 6: Auto-expiry check for ARMED state
            with _engine_runtime._lock:
                if (_engine_runtime.state == EngineState.ARMED and 
                    _engine_runtime.armed_expires_at > 0):
                    now = time.time()
                    if now >= _engine_runtime.armed_expires_at:
                        # ARMED expired - revert to SHADOW
                        from api.audit import get_audit_logger
                        audit_logger = get_audit_logger()
                        audit_logger.log_event(
                            event_type="armed_expiry",
                            actor="system",
                            payload={
                                "expired_at": now,
                                "was_armed_at": _engine_runtime.armed_at,
                            }
                        )
                        _engine_runtime.state = EngineState.SHADOW
                        _engine_runtime.shadow_mode = True
                        _engine_runtime.armed_at = 0.0
                        _engine_runtime.armed_expires_at = 0.0
                        _engine_runtime.armed_reason = ""
                        _engine_runtime.armed_approvals = []
                        
                        # PHASE 8: Automatic strategy demotion on ARMED expiry with explicit reason
                        try:
                            from api.strategies.promotion import get_strategy_promotion
                            strategy_promotion = get_strategy_promotion()
                            demoted_count = strategy_promotion.demote_all_to_shadow(
                                actor="system",
                                reason="armed_expiry",
                                correlation_id=None,
                                explicit_reason="engine_disarmed"
                            )
                            audit_logger.log_event(
                                event_type="armed_expiry_auto_demotion",
                                actor="system",
                                payload={
                                    "strategies_demoted": demoted_count,
                                    "reason": "engine_disarmed",
                                }
                            )
                        except Exception:
                            pass  # Non-fatal
            
            # PHASE 3: Cleanup expired approval requests
            try:
                from api.approvals import get_approval_manager
                approval_manager = get_approval_manager()
                approval_manager.cleanup_expired()
            except Exception:
                pass  # Non-fatal
            
            # PHASE 13: Auto-promotion evaluation (non-blocking, hard timeout)
            try:
                from api.strategies.auto_promotion import get_auto_promotion_engine
                auto_promotion_engine = get_auto_promotion_engine()
                
                # Evaluate cycle with hard timeout (5 seconds max)
                summary = auto_promotion_engine.evaluate_cycle(timeout_seconds=5.0)
                
                # Log summary if any evaluations occurred
                if summary.get("evaluated", 0) > 0:
                    logger.debug(
                        f"Auto-promotion cycle: evaluated={summary.get('evaluated')}, "
                        f"promoted={summary.get('promoted')}, demoted={summary.get('demoted')}, "
                        f"errors={summary.get('errors')}, duration_ms={summary.get('duration_ms', 0):.1f}"
                    )
            except Exception as e:
                # PHASE 13: Auto-promotion errors must not crash engine loop
                # Log but continue
                try:
                    from sentinel_x.monitoring.logger import logger
                except ImportError:
                    import logging
                    logger = logging.getLogger(__name__)
                logger.error(f"Auto-promotion evaluation error (non-fatal): {e}", exc_info=True)
            
            time.sleep(1.0)  # 1 second heartbeat interval
        except Exception:
            # SAFETY: Engine loop must never crash
            # On any exception, mark as DEGRADED but continue
            _engine_runtime.set_state(EngineState.DEGRADED)
            time.sleep(1.0)


def activate_armed(
    request_id: str,
    armed_ttl_seconds: int = 900  # 15 minutes default
) -> Tuple[bool, str]:
    """
    PHASE 5 — ARMED ACTIVATION
    
    Activate ARMED state only if ALL conditions are satisfied:
    - Engine.state == SHADOW
    - Kill-switch == READY
    - Approval count >= required threshold
    - Mobile approval present
    - Request not expired
    
    Args:
        request_id: Approval request ID
        armed_ttl_seconds: TTL for ARMED state (default 15 minutes)
    
    Returns:
        (success: bool, message: str)
    """
    global _engine_runtime
    
    from api.approvals import get_approval_manager
    from api.security import get_kill_switch
    
    approval_manager = get_approval_manager()
    kill_switch = get_kill_switch()
    
    # Get request
    request = approval_manager.get_request(request_id)
    if not request:
        return False, f"Request not found: {request_id}"
    
    # Check if request is ready for activation
    ready, reason = request.is_ready_for_activation()
    if not ready:
        return False, reason
    
    with _engine_runtime._lock:
        # PHASE 5: Check all activation conditions
        if _engine_runtime.state != EngineState.SHADOW:
            return False, f"Cannot activate ARMED from {_engine_runtime.state.value}, must be SHADOW"
        
        if not kill_switch.can_promote():
            return False, f"Kill-switch does not allow activation (status: {kill_switch.status.value})"
        
        # Set ARMED state with metadata
        now = time.time()
        old_state = _engine_runtime.state
        _engine_runtime.state = EngineState.ARMED
        _engine_runtime.armed_at = now
        _engine_runtime.armed_expires_at = now + armed_ttl_seconds
        _engine_runtime.armed_reason = request.reason
        _engine_runtime.armed_approvals = [a.to_dict() for a in request.approvals]
        _engine_runtime.shadow_mode = False  # Disable shadow mode when ARMED
    
    # Mark request as activated
    approval_manager.mark_activated(request_id)
    
    return True, f"ARMED state activated (expires in {armed_ttl_seconds}s)"


def revoke_armed(reason: str = "manual_revocation") -> Tuple[bool, str]:
    """
    PHASE 6 — ARMED REVOCATION
    PHASE 3 — AUTO-DEMOTE STRATEGIES
    
    Revoke ARMED state and revert to SHADOW.
    Automatically demotes all strategies to SHADOW when ARMED is revoked.
    
    Args:
        reason: Reason for revocation
    
    Returns:
        (success: bool, message: str)
    """
    global _engine_runtime
    
    with _engine_runtime._lock:
        if _engine_runtime.state != EngineState.ARMED:
            return False, f"Engine is not ARMED (current state: {_engine_runtime.state.value})"
        
        old_state = _engine_runtime.state
        _engine_runtime.state = EngineState.SHADOW
        _engine_runtime.shadow_mode = True
        
        # Clear ARMED metadata
        _engine_runtime.armed_at = 0.0
        _engine_runtime.armed_expires_at = 0.0
        _engine_runtime.armed_reason = ""
        _engine_runtime.armed_approvals = []
    
    # PHASE 3: Auto-demote all strategies to SHADOW
    try:
        from api.strategies.promotion import get_strategy_promotion
        promotion_engine = get_strategy_promotion()
        demoted_count = promotion_engine.demote_all_to_shadow(
            actor="system",
            reason="armed_revocation",
            correlation_id=None
        )
        if demoted_count > 0:
            return True, f"ARMED state revoked (reason: {reason}), {demoted_count} strategies demoted to SHADOW"
    except Exception as e:
        # PHASE 3: Demotion failure must not block ARMED revocation
        # Log but continue
        try:
            from sentinel_x.monitoring.logger import logger
        except ImportError:
            import logging
            logger = logging.getLogger(__name__)
        logger.error(f"Error demoting strategies during ARMED revocation (non-fatal): {e}", exc_info=True)
    
    return True, f"ARMED state revoked (reason: {reason})"


def check_kill_switch_override() -> Tuple[bool, str]:
    """
    PHASE 6 — KILL-SWITCH OVERRIDE
    
    Check if kill-switch should override ARMED state.
    If ARMED and kill-switch is triggered, revert to MONITOR.
    
    Returns:
        (overridden: bool, message: str)
    """
    global _engine_runtime
    
    from api.security import get_kill_switch
    
    kill_switch = get_kill_switch()
    
    with _engine_runtime._lock:
        if _engine_runtime.state != EngineState.ARMED:
            return False, "Engine is not ARMED"
        
        # PHASE 6: Kill-switch overrides ARMED instantly
        if not kill_switch.can_promote():
            # Revert to MONITOR (highest safety)
            old_state = _engine_runtime.state
            _engine_runtime.state = EngineState.MONITOR
            _engine_runtime.shadow_mode = False
            
            # Clear ARMED metadata
            _engine_runtime.armed_at = 0.0
            _engine_runtime.armed_expires_at = 0.0
            _engine_runtime.armed_reason = ""
            _engine_runtime.armed_approvals = []
            
            # PHASE 8: Automatic strategy demotion on kill-switch override
            try:
                from api.strategies.promotion import get_strategy_promotion
                strategy_promotion = get_strategy_promotion()
                demoted_count = strategy_promotion.demote_all_to_shadow(actor="system")
            except Exception:
                demoted_count = 0
            
            return True, f"Kill-switch override: {old_state.value} → MONITOR (strategies demoted: {demoted_count})"
    
    return False, "Kill-switch is READY"


def check_execution_guardrails() -> Tuple[bool, str]:
    """
    PHASE 9 — EXECUTION GUARDRAILS (PRE-EXECUTION ONLY)
    
    Check if execution is allowed before ANY order submission.
    
    Returns True only if ALL are true:
    - Engine.state == ARMED
    - Current time < armed_expires_at
    - Kill-switch == READY
    
    If any check fails:
    - HARD STOP
    - Log audit event
    - Do NOT attempt execution
    
    Returns:
        (allowed: bool, reason: str)
    
    Usage:
        This function MUST be called before any order execution.
        If it returns False, execution must be blocked immediately.
    """
    global _engine_runtime
    
    from api.security import get_kill_switch
    
    kill_switch = get_kill_switch()
    
    with _engine_runtime._lock:
        # PHASE 9: Execution guardrails
        # Check 1: Engine state must be ARMED
        if _engine_runtime.state != EngineState.ARMED:
            return False, f"Execution blocked - engine state is {_engine_runtime.state.value}, not ARMED"
        
        # Check 2: ARMED must not be expired
        now = time.time()
        if _engine_runtime.armed_expires_at <= 0 or now >= _engine_runtime.armed_expires_at:
            return False, f"Execution blocked - ARMED state expired at {_engine_runtime.armed_expires_at}"
        
        # Check 3: Kill-switch must be READY
        if not kill_switch.can_promote():
            return False, f"Execution blocked - kill-switch status is {kill_switch.status.value}"
        
        # All checks passed
        return True, "Execution allowed"


def start_engine_loop() -> None:
    """
    Start engine loop as daemon thread.
    
    PHASE 1: Called at FastAPI startup
    PHASE 5: Production runtime compatible - restart-safe
    PHASE 6: Kill-switch override monitoring
    """
    global _engine_thread, _engine_running
    
    # Only start if not already running
    if _engine_thread is not None and _engine_thread.is_alive():
        return
    
    _engine_running = True
    _engine_thread = threading.Thread(target=engine_loop, daemon=True, name="engine-loop")
    _engine_thread.start()


def stop_engine_loop() -> None:
    """
    Stop engine loop gracefully.
    
    PHASE 3: Called at FastAPI shutdown.
    """
    global _engine_thread, _engine_running
    
    _engine_running = False
    
    if _engine_thread is not None and _engine_thread.is_alive():
        # Wait for thread to finish (with timeout)
        _engine_thread.join(timeout=5.0)
        if _engine_thread.is_alive():
            logger.warning("Engine loop thread did not stop within timeout")
