# api/main.py
"""
Aegis Alpha Control Plane

PHASE 1-6 — Production-Grade Trading Infrastructure Control Plane

FastAPI application serving as the control plane for Sentinel X.
All endpoints are read-only in MONITOR mode. Trading is never enabled by default.

SAFETY RULES:
- Default mode = MONITOR (no trading)
- All endpoints must be fast and deterministic
- Never break /status endpoint
- Never enable trading by default
- Kill-switch always exposed
"""

# --- MODULE EXECUTION MODE PATCH ---
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
from contextlib import asynccontextmanager

# Import modular components
from api.engine import get_engine_runtime, start_engine_loop, EngineState
from api.brokers import get_broker_registry
from api.security import get_kill_switch, get_safety_guard
from api.contracts import (
    default_strategies_response,
    default_risk_config_response,
    default_capital_allocations_response,
    default_capital_transfers_response,
    default_performance_stats_response,
    default_performance_equity_response,
    default_performance_pnl_response,
    default_alerts_response,
    default_research_jobs_response,
    default_security_info_response,
)
from api.strategies.registry import (
    StrategyMode,
    get_strategy_registry,
)

# PHASE 7: Import shadow routes (startup order enforced)
# STARTUP ORDER (PHASE 7):
# 1. python -m api.main
# 2. api.shadow_routes
# 3. sentinel_x.shadow.status
# 4. sentinel_x.shadow.controller
# 5. sentinel_x.shadow.trainer (lazy - only when start() called)
# 6. sentinel_x.shadow.heartbeat (owned by trainer)
# No other order is allowed.
from api.shadow_routes import router as shadow_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    PHASE 3: Lifespan handler for FastAPI startup and shutdown.
    
    Replaces deprecated @app.on_event("startup") and @app.on_event("shutdown").
    Provides proper async context management for lifecycle events.
    """
    from sentinel_x.monitoring.logger import logger
    import socket
    import os
    import sys
    
    # PHASE 7: Log startup
    pid = os.getpid()
    port = 8000
    mode = os.getenv("ENGINE_MODE", "SHADOW")
    shadow_enabled = os.getenv("SHADOW_ENABLED", "true").lower() == "true"
    
    logger.info("=" * 60)
    logger.info("Aegis Alpha Control Plane - Starting")
    logger.info(f"PID: {pid}")
    logger.info(f"Mode: {mode}")
    logger.info(f"Shadow Enabled: {shadow_enabled}")
    logger.info("=" * 60)
    
    # PHASE 4: Check port binding
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            logger.warning(
                f"Port {port} already bound (expected during reload). Continuing startup."
            )
        else:
            logger.info(f"Port {port} is available")
    except Exception as e:
        logger.warning(f"Could not check port {port}: {e}")
    
    # PHASE 7: Acquire startup lock
    try:
        from sentinel_x.core.startup_lock import get_startup_lock
        startup_lock = get_startup_lock()
        if not startup_lock.acquire():
            logger.critical("Another Sentinel X instance is running. Exiting.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error acquiring startup lock: {e}", exc_info=True)
        # Continue anyway - lock is best-effort
    
    # PHASE 5: Initialize config
    try:
        from sentinel_x.core.config import get_config
        config = get_config()
        logger.info(f"Configuration loaded: {len(config.symbols)} symbols")
    except Exception as e:
        logger.error(f"Error loading configuration: {e}", exc_info=True)
    
    # ============================================================
    # PHASE 1: Shadow Mode is an explicit governance state required by Rork.
    # ============================================================
    # Shadow Mode must be an explicit engine state, not inferred.
    # Rork relies on engine.state["shadow_mode"] as the source of truth.
    # This is set during startup based on SHADOW_ENABLED configuration.
    # ============================================================
    from api.engine import get_engine_runtime, EngineState
    engine_runtime = get_engine_runtime()
    
    # PHASE 2: Load shadow enable flag from config (default False)
    # Safe string-to-boolean conversion
    shadow_enabled = os.getenv("SHADOW_ENABLED", "false").lower() == "true"
    
    # PHASE 1: Set shadow_mode and state during startup
    if shadow_enabled:
        with engine_runtime._lock:
            engine_runtime.shadow_mode = True
            if engine_runtime.state == EngineState.BOOTING:
                engine_runtime.state = EngineState.SHADOW
                logger.info("Engine state set to SHADOW (shadow_mode enabled)")
    else:
        # PHASE 5: Fail safe - ensure BOOTING never persists
        with engine_runtime._lock:
            if engine_runtime.state == EngineState.BOOTING:
                engine_runtime.state = EngineState.MONITOR
                engine_runtime.shadow_mode = False
                logger.info("Engine state set to MONITOR (shadow_mode disabled)")
    
    # PHASE 5: Defensive check - prevent stuck BOOTING state
    final_state = engine_runtime.get_state_dict()
    if final_state.get("state") == "BOOTING":
        logger.warning("Engine stuck in BOOTING state - forcing transition")
        with engine_runtime._lock:
            if shadow_enabled:
                engine_runtime.shadow_mode = True
                engine_runtime.state = EngineState.SHADOW
                logger.warning("Forced transition: BOOTING → SHADOW (shadow_enabled=true)")
            else:
                engine_runtime.shadow_mode = False
                engine_runtime.state = EngineState.MONITOR
                logger.warning("Forced transition: BOOTING → MONITOR (shadow_enabled=false)")
    
    # PHASE 1: Start shadow runtime if enabled
    shadow_runtime = None
    if shadow_enabled:
        try:
            from sentinel_x.shadow.runtime import get_shadow_runtime
            shadow_runtime = get_shadow_runtime()
            
            # PHASE 5: Process guard - check if already started
            if shadow_runtime.is_started():
                logger.warning("Shadow runtime already started - skipping")
            else:
                # PHASE 5: Only start shadow if not in LIVE mode
                engine_runtime = get_engine_runtime()
                engine_state = engine_runtime.get_state_dict()
                system_mode = engine_state.get("state", "MONITOR")
                
                if system_mode != "ARMED":  # SHADOW mode
                    success = shadow_runtime.start()
                    if success:
                        logger.info("Shadow runtime started (SHADOW mode)")
                    else:
                        logger.error("Shadow runtime failed to start")
                else:
                    logger.info("Shadow runtime disabled (LIVE/ARMED mode)")
        except Exception as e:
            logger.error(f"Error starting shadow runtime: {e}", exc_info=True)
    
    # PHASE 5: Start engine loop only if in LIVE mode
    engine_started = False
    try:
        engine_runtime = get_engine_runtime()
        engine_state = engine_runtime.get_state_dict()
        system_mode = engine_state.get("state", "MONITOR")
        
        if system_mode == "ARMED":  # LIVE mode
            start_engine_loop()
            engine_started = True
            logger.info("Engine loop started (LIVE mode)")
        else:
            logger.info("Engine loop NOT started (SHADOW mode)")
    except Exception as e:
        logger.error(f"Error starting engine loop: {e}", exc_info=True)
    
    # PHASE 7: Log port bind success
    logger.info(f"FastAPI server starting on port {port}")
    logger.info("Routes available: /status, /shadow/status")
    
    # Yield control to FastAPI
    yield
    
    # PHASE 7: Shutdown
    logger.info("=" * 60)
    logger.info("Aegis Alpha Control Plane - Shutting down")
    logger.info("=" * 60)
    
    # Stop shadow runtime
    if shadow_runtime and shadow_runtime.is_started():
        try:
            shadow_runtime.stop()
            logger.info("Shadow runtime stopped")
        except Exception as e:
            logger.error(f"Error stopping shadow runtime: {e}", exc_info=True)
    
    # Stop engine loop (if started)
    if engine_started:
        try:
            from api.engine import stop_engine_loop
            stop_engine_loop()
            logger.info("Engine loop stopped")
        except Exception as e:
            logger.error(f"Error stopping engine loop: {e}", exc_info=True)
    
    logger.info("Shutdown complete")
    
    logger.info("Shutdown complete")


app = FastAPI(title="Aegis Alpha Control Plane", lifespan=lifespan)

# PHASE 4: Register shadow routes
app.include_router(shadow_router)

# Rork shadow metrics endpoint
@app.get("/rork/shadow/metrics")
def rork_shadow_metrics():
    from sentinel_x.shadow.runtime import get_shadow_runtime
    return {
        "source": "aegis-alpha",
        "component": "shadow",
        "metrics": get_shadow_runtime().metrics(),
    }

# Rork shadow status endpoint
@app.get("/rork/shadow/status")
def rork_shadow_status():
    """
    Rork live status endpoint for Shadow runtime.
    Read-only. Mobile-safe. Stable schema.
    """
    from sentinel_x.shadow.runtime import get_shadow_runtime
    from api.engine import get_engine_runtime
    
    runtime = get_shadow_runtime()
    engine = get_engine_runtime()
    
    engine_state = engine.get_state_dict()
    shadow_enabled = engine_state.get("shadow_mode", False)
    
    if not shadow_enabled:
        return {
            "shadow_mode": False,
            "status": "DISABLED"
        }
    
    if not runtime.is_started():
        return {
            "shadow_mode": True,
            "status": "STOPPED",
            "heartbeat_age_ms": None,
            "tick_count": 0,
            "active_strategies": 0,
            "cpu_safe": True,
        }

    metrics = runtime.metrics()

    # Determine status badge
    if metrics.get("idle", True):
        status = "IDLE"
    else:
        status = "TRAINING"

    return {
        "shadow_mode": True,
        "status": status,
        "heartbeat_age_ms": metrics.get("heartbeat_age_ms"),
        "tick_count": runtime.get_tick_count(),
        "active_strategies": runtime.get_active_strategy_count(),
        "cpu_safe": metrics.get("cpu_safe", True),
    }

# CORS for Rork / mobile / web preview
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/status")
def status():
    """
    PHASE 6: Get system status (always works, never blocks).
    
    PHASE 7: Extended status endpoint - NEVER raises exceptions
    Includes ARMED status information
    
    Returns system, engine, shadow, kill-switch, audit, broker, and ARMED status.
    
    SAFETY:
    - Always returns 200
    - Never triggers imports that start loops
    - Only reads runtime state
    - Never blocks
    """
    try:
        engine_runtime = get_engine_runtime()
        broker_registry = get_broker_registry()
        kill_switch = get_kill_switch()
        
        from api.shadow import get_shadow_registry
        from api.audit import get_audit_logger
        from api.approvals import get_approval_manager
        
        shadow_registry = get_shadow_registry()
        audit_logger = get_audit_logger()
        approval_manager = get_approval_manager()
        
        engine_state = engine_runtime.get_state_dict()
        brokers = broker_registry.get_all()
        
        # PHASE 6: Aggregate positions for exposure summary
        aggregated = broker_registry.aggregate_positions()
        exposure_summary = {
            "total_symbols": len(aggregated.get("total_exposure_by_symbol", {})),
            "total_market_value": aggregated.get("total_market_value", 0.0),
            "broker_count": aggregated.get("broker_count", 0),
        }
        
        # PHASE 7: Get ARMED status from engine state
        armed_status = engine_state.get("armed", {
            "active": False,
            "expires_at": None,
            "approval_count": 0,
        })
        
        # PHASE 7: Get active ARMED request if any
        active_request = approval_manager.get_active_request()
        armed_request_status = active_request.to_dict() if active_request else None
        
        # PHASE 7: Get strategy modes for status endpoint
        from api.strategies.registry import get_strategy_registry, StrategyMode
        from api.strategies.promotion import get_strategy_promotion
        from api.strategies.auto_promotion import get_auto_promotion_engine
        strategy_registry = get_strategy_registry()
        strategy_modes = strategy_registry.get_strategy_modes_dict()
        
        # PHASE 7: Calculate strategy counts
        shadow_count = sum(1 for mode in strategy_modes.values() if mode == StrategyMode.SHADOW.value)
        paper_count = sum(1 for mode in strategy_modes.values() if mode == StrategyMode.PAPER.value)
        disabled_count = sum(1 for mode in strategy_modes.values() if mode == StrategyMode.DISABLED.value)
        
        # PHASE 7: Get last promotion event
        try:
            promotion_engine = get_strategy_promotion()
            last_promotions = promotion_engine.get_promotions(limit=1)
            last_promotion_event = last_promotions[0] if last_promotions else None
        except Exception:
            last_promotion_event = None
        
        # PHASE 14: Get detailed strategy states and auto-promotion rules
        try:
            auto_promotion_engine = get_auto_promotion_engine()
            promotion_rule = auto_promotion_engine.get_promotion_rule()
            
            strategies_detailed = {}
            for strategy_id in strategy_modes.keys():
                try:
                    strategy_state = auto_promotion_engine.get_strategy_state(strategy_id)
                    eligible = auto_promotion_engine.is_eligible_for_promotion(strategy_id)
                    
                    strategies_detailed[strategy_id] = {
                        "mode": strategy_modes.get(strategy_id, "UNKNOWN"),
                        "eligible_for_promotion": eligible,
                        "auto_promotion_enabled": strategy_state.auto_promotion_enabled if strategy_state else False,
                        "last_decision": strategy_state.last_decision if strategy_state else None,
                        "last_decision_reason": strategy_state.last_decision_reason if strategy_state else None,
                    }
                except Exception:
                    # Per-strategy errors must not block status endpoint
                    strategies_detailed[strategy_id] = {
                        "mode": strategy_modes.get(strategy_id, "UNKNOWN"),
                        "eligible_for_promotion": False,
                        "auto_promotion_enabled": False,
                        "last_decision": None,
                        "last_decision_reason": None,
                    }
            
            auto_promotion_rules = promotion_rule.to_dict()
        except Exception:
            # PHASE 14: Auto-promotion errors must not block status endpoint
            strategies_detailed = {}
            auto_promotion_rules = {}
        
        # PHASE 7: Determine system mode (SHADOW if engine.state != ARMED, PAPER if ARMED)
        system_mode = "PAPER" if engine_state.get("state") == "ARMED" else "SHADOW"
        
        return {
            "system": {
                "name": "Aegis Alpha",
                "node_id": "local-dev",
                "version": "0.1.0",
                "environment": "local",
            },
            "system_mode": system_mode,  # PHASE 7: System-level mode
            "engine": engine_state,
            "strategies": strategy_modes,  # PHASE 7: Strategy-level modes
            "strategies_detailed": strategies_detailed,  # PHASE 14: Detailed strategy states
            "strategy_counts": {  # PHASE 7: Strategy counts
                "shadow": shadow_count,
                "paper": paper_count,
                "disabled": disabled_count,
                "total": len(strategy_modes),
            },
            "last_promotion_event": last_promotion_event,  # PHASE 7: Last promotion event
            "auto_promotion_rules": auto_promotion_rules,  # PHASE 14: Auto-promotion rules
            "armed": {
                "active": armed_status.get("active", False),
                "expires_at": armed_status.get("expires_at"),
                "expires_in_seconds": armed_status.get("expires_in_seconds", 0),
                "approval_count": armed_status.get("approval_count", 0),
                "required_approvals": 2,
                "active_request": armed_request_status,
            },
            "shadow": {
                "enabled": shadow_registry.is_enabled(),
            },
            "kill_switch": kill_switch.to_dict(),
            "audit": {
                "enabled": True,  # Audit is always enabled
            },
            "broker_count": len(brokers),
            "brokers": brokers,
            "aggregated_exposure_summary": exposure_summary,
            "ok": True,
        }
    except Exception as e:
        # PHASE 7: /status NEVER raises - return degraded state with ARMED defaults
        return {
            "system": {
                "name": "Aegis Alpha",
                "node_id": "local-dev",
                "version": "0.1.0",
                "environment": "local",
            },
            "system_mode": "SHADOW",  # PHASE 7: Default to SHADOW on error
            "engine": {
                "state": "DEGRADED",
                "loop_tick": 0,
                "heartbeat_age_ms": 999999,
                "shadow_mode": False,
                "trading_window": "CLOSED",
            },
            "strategies": {},  # PHASE 7: Empty strategies on error
            "strategies_detailed": {},  # PHASE 14: Empty detailed strategies on error
            "strategy_counts": {  # PHASE 7: Zero counts on error
                "shadow": 0,
                "paper": 0,
                "disabled": 0,
                "total": 0,
            },
            "last_promotion_event": None,  # PHASE 7: No promotion event on error
            "auto_promotion_rules": {},  # PHASE 14: Empty rules on error
            "armed": {
                "active": False,
                "expires_at": None,
                "approval_count": 0,
                "required_approvals": 2,
                "active_request": None,
            },
            "shadow": {
                "enabled": False,
            },
            "kill_switch": {"status": "READY", "armed": False, "triggered_at": None, "triggered_by": "system"},
            "audit": {
                "enabled": True,
            },
            "broker_count": 0,
            "brokers": [],
            "aggregated_exposure_summary": {
                "total_symbols": 0,
                "total_market_value": 0.0,
                "broker_count": 0,
            },
            "ok": False,
            "error": str(e),
        }


@app.get("/brokers")
def brokers():
    """
    PHASE 2: Broker abstraction endpoint
    PHASE 4: Alpaca PAPER broker integration (read-only)
    
    Returns all registered brokers including:
    - paper-sim (simulated broker)
    - alpaca-paper (Alpaca PAPER account, if configured)
    
    SAFETY:
    - Always returns a list (never 404)
    - Never throws uncaught exceptions
    - Fast and safe for frequent polling
    - Alpaca unavailable does not break endpoint
    """
    try:
        broker_registry = get_broker_registry()
        return broker_registry.get_all()
    except Exception:
        # PHASE 4: Never raise - return empty list on error
        # Sentinel X remains ONLINE even if broker registry fails
        return []


@app.get("/positions")
def positions():
    """
    PHASE 4: Get open positions from Alpaca PAPER (read-only)
    PHASE 5: Graceful failure handling
    
    Returns:
        List of normalized positions, empty list if none or on error
    
    SAFETY:
    - Always returns 200 (never 404)
    - Never throws uncaught exceptions
    - Returns [] if Alpaca unavailable
    - Safe for frequent polling by Sentinel X
    """
    try:
        from api.alpaca_broker import get_alpaca_broker
        alpaca_broker = get_alpaca_broker()
        
        if alpaca_broker and alpaca_broker.is_available():
            positions_list = alpaca_broker.get_positions()
            return positions_list
        else:
            # PHASE 5: Alpaca not available - return empty list
            return []
    except Exception:
        # PHASE 5: Never raise - return empty list on any error
        # Sentinel X remains ONLINE even if positions fetch fails
        return []


@app.get("/orders")
def orders(limit: int = 50, status: str = None):
    """
    PHASE 4: Get recent orders from Alpaca PAPER (read-only)
    PHASE 5: Graceful failure handling
    
    Args:
        limit: Maximum number of orders to return (default 50)
        status: Optional order status filter (e.g., "filled", "open", "canceled")
    
    Returns:
        List of normalized orders, empty list if none or on error
    
    SAFETY:
    - Always returns 200 (never 404)
    - Never throws uncaught exceptions
    - Returns [] if Alpaca unavailable
    - Safe for frequent polling by Sentinel X
    - No order mutation endpoints exist
    """
    try:
        from api.alpaca_broker import get_alpaca_broker
        alpaca_broker = get_alpaca_broker()
        
        if alpaca_broker and alpaca_broker.is_available():
            orders_list = alpaca_broker.get_orders(limit=limit, status=status)
            return orders_list
        else:
            # PHASE 5: Alpaca not available - return empty list
            return []
    except Exception:
        # PHASE 5: Never raise - return empty list on any error
        # Sentinel X remains ONLINE even if orders fetch fails
        return []



# PHASE 1 — SHADOW TRADING ENDPOINTS

@app.get("/shadow/signals")
def shadow_signals(limit: int = 100, strategy_id: str = None):
    """
    PHASE 1: Get SHADOW trading signals (read-only)
    
    Args:
        limit: Maximum number of signals to return (default 100)
        strategy_id: Optional filter by strategy ID
    
    Returns:
        List of SHADOW signals, empty list if none
    
    SAFETY:
    - Always returns 200 (never 404)
    - Signals are computational only, never executed
    """
    try:
        from api.shadow import get_shadow_registry
        shadow_registry = get_shadow_registry()
        signals = shadow_registry.get_signals(limit=limit, strategy_id=strategy_id)
        return signals
    except Exception:
        return []


# --- SHADOW LIFECYCLE ENDPOINTS ---

@app.post("/shadow/start")
def shadow_start():
    """
    Explicitly start ShadowRuntime.
    Safe to call multiple times (idempotent).
    """
    try:
        from sentinel_x.shadow.runtime import get_shadow_runtime
        shadow_runtime = get_shadow_runtime()

        if shadow_runtime.is_started():
            return {
                "success": True,
                "message": "Shadow runtime already started",
                "started": True,
            }

        shadow_runtime.start()
        return {
            "success": True,
            "message": "Shadow runtime started",
            "started": True,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to start shadow runtime: {str(e)}",
            "started": False,
        }


@app.post("/shadow/stop")
def shadow_stop():
    """
    Explicitly stop ShadowRuntime.
    Safe to call multiple times (idempotent).
    """
    try:
        from sentinel_x.shadow.runtime import get_shadow_runtime
        shadow_runtime = get_shadow_runtime()

        if not shadow_runtime.is_started():
            return {
                "success": True,
                "message": "Shadow runtime already stopped",
                "started": False,
            }

        shadow_runtime.stop()
        return {
            "success": True,
            "message": "Shadow runtime stopped",
            "started": False,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to stop shadow runtime: {str(e)}",
            "started": False,
        }


# PHASE 2 — ENGINE PROMOTION ENDPOINTS

@app.get("/engine/state")
def engine_state():
    """
    PHASE 2: Get current engine state
    
    Returns:
        Engine state information
    """
    try:
        engine_runtime = get_engine_runtime()
        return engine_runtime.get_state_dict()
    except Exception:
        return {
            "state": "DEGRADED",
            "loop_tick": 0,
            "heartbeat_age_ms": 999999,
            "shadow_mode": False,
            "trading_window": "CLOSED",
        }


@app.post("/engine/promote")
def engine_promote(target: str):
    """
    PHASE 2: Promote engine state (MONITOR → SHADOW only)
    
    Args:
        target: Target state ("SHADOW" only, ARMED rejected - use /engine/armed/request)
    
    Returns:
        Promotion result and updated engine state
    
    SAFETY:
    - Only MONITOR → SHADOW allowed
    - ARMED is rejected (use /engine/armed/request)
    - Kill-switch must be READY
    - All promotions logged
    """
    try:
        from api.engine import EngineState
        from api.shadow import get_shadow_registry
        from api.audit import get_audit_logger
        from api.security import get_kill_switch
        
        engine_runtime = get_engine_runtime()
        kill_switch = get_kill_switch()
        shadow_registry = get_shadow_registry()
        audit_logger = get_audit_logger()
        
        # PHASE 3: Check kill-switch
        if not kill_switch.can_promote():
            return {
                "success": False,
                "message": f"Cannot promote - kill-switch status is {kill_switch.status.value}",
                "engine_state": engine_runtime.get_state_dict(),
            }
        
        # Parse target state
        target_upper = target.upper()
        if target_upper not in [s.value for s in EngineState]:
            return {
                "success": False,
                "message": f"Invalid target state: {target}",
                "engine_state": engine_runtime.get_state_dict(),
            }
        
        target_state = EngineState[target_upper]
        
        # PHASE 3: Reject ARMED promotion via this endpoint
        if target_state == EngineState.ARMED:
            return {
                "success": False,
                "message": "ARMED state requires multi-signature approval via POST /engine/armed/request",
                "engine_state": engine_runtime.get_state_dict(),
            }
        
        # PHASE 2: Attempt promotion (check kill-switch first)
        success, message = engine_runtime.promote_to(target_state, kill_switch_allowed=kill_switch.can_promote())
        
        if success:
            # PHASE 2: Enable shadow signal generation if promoted to SHADOW
            if target_state == EngineState.SHADOW:
                shadow_registry.set_enabled(True)
            
            # PHASE 5: Log promotion
            audit_logger.log_event(
                event_type="engine_promotion",
                actor="api",
                payload={
                    "target_state": target_state.value,
                    "message": message,
                }
            )
        
        return {
            "success": success,
            "message": message,
            "engine_state": engine_runtime.get_state_dict(),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "engine_state": engine_runtime.get_state_dict() if 'engine_runtime' in locals() else {},
        }


# PHASE 3 — KILL-SWITCH ENDPOINTS

@app.get("/kill-switch/status")
def kill_switch_status():
    """
    PHASE 3: Get kill-switch status
    
    Returns:
        Kill-switch state information
    """
    try:
        kill_switch = get_kill_switch()
        return kill_switch.to_dict()
    except Exception:
        return {
            "status": "READY",
            "armed": False,
            "triggered_at": None,
            "triggered_by": "system",
        }


@app.post("/kill-switch/trigger")
def kill_switch_trigger(level: str):
    """
    PHASE 3: Trigger kill-switch escalation
    PHASE 6: Kill-switch override for ARMED state
    
    Args:
        level: "SOFT_KILL" or "HARD_KILL"
    
    Returns:
        Trigger result and updated kill-switch status
    
    SAFETY:
    - HARD_KILL overrides everything including ARMED
    - PHASE 6: Kill-switch instantly revokes ARMED state
    - All triggers logged
    """
    try:
        from api.security import KillSwitchStatus
        from api.shadow import get_shadow_registry
        from api.audit import get_audit_logger
        from api.engine import revoke_armed
        
        kill_switch = get_kill_switch()
        shadow_registry = get_shadow_registry()
        audit_logger = get_audit_logger()
        engine_runtime = get_engine_runtime()
        
        level_upper = level.upper()
        if level_upper not in ["SOFT_KILL", "HARD_KILL"]:
            return {
                "success": False,
                "message": f"Invalid level: {level}. Must be SOFT_KILL or HARD_KILL",
                "kill_switch": kill_switch.to_dict(),
            }
        
        kill_level = KillSwitchStatus[level_upper]
        triggered = kill_switch.trigger(kill_level, triggered_by="api")
        
        if triggered:
            # PHASE 3: Automatic strategy demotion on kill-switch with explicit reason
            from api.strategies.promotion import get_strategy_promotion
            from api.engine import revoke_armed
            strategy_promotion = get_strategy_promotion()
            demoted_count = strategy_promotion.demote_all_to_shadow(
                actor="system",
                reason=f"kill_switch_{kill_level.value}",
                correlation_id=None,
                explicit_reason="kill_switch"
            )
            
            # PHASE 6: Kill-switch override for ARMED state
            current_state = engine_runtime.get_state_dict()["state"]
            if current_state == "ARMED":
                revoked, revoke_msg = revoke_armed(reason=f"kill_switch_{kill_level.value}")
                if revoked:
                    audit_logger.log_event(
                        event_type="armed_kill_switch_override",
                        actor="api",
                        payload={
                            "kill_level": kill_level.value,
                            "revoke_message": revoke_msg,
                            "strategies_demoted": demoted_count,
                        }
                    )
            
            # PHASE 3: Disable shadow signal generation if HARD_KILL
            if kill_level == KillSwitchStatus.HARD_KILL:
                shadow_registry.set_enabled(False)
            
            # PHASE 5: Log kill-switch trigger
            audit_logger.log_event(
                event_type="kill_switch_trigger",
                actor="api",
                payload={
                    "level": kill_level.value,
                    "strategies_demoted": demoted_count,
                }
            )
        
        return {
            "success": triggered,
            "message": f"Kill-switch {kill_level.value} {'triggered' if triggered else 'already at or above level'}",
            "kill_switch": kill_switch.to_dict(),
            "engine_state": engine_runtime.get_state_dict(),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "kill_switch": get_kill_switch().to_dict(),
        }


@app.post("/kill-switch/reset")
def kill_switch_reset():
    """
    PHASE 3: Reset kill-switch to READY
    
    Returns:
        Reset result and updated kill-switch status
    
    SAFETY:
    - All resets logged
    """
    try:
        from api.audit import get_audit_logger
        
        kill_switch = get_kill_switch()
        audit_logger = get_audit_logger()
        
        reset = kill_switch.reset()
        
        if reset:
            # PHASE 5: Log kill-switch reset
            audit_logger.log_event(
                event_type="kill_switch_reset",
                actor="api",
                payload={}
            )
        
        return {
            "success": reset,
            "message": "Kill-switch reset to READY" if reset else "Kill-switch already READY",
            "kill_switch": kill_switch.to_dict(),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "kill_switch": get_kill_switch().to_dict(),
        }


# PHASE 4 — POSITION AGGREGATION ENDPOINT

@app.get("/positions/aggregate")
def positions_aggregate():
    """
    PHASE 4: Get aggregated positions across all brokers (read-only)
    
    Returns:
        Aggregated position data by symbol
    
    SAFETY:
    - Always returns 200 (never 404)
    - Read-only operation
    - Gracefully handles broker failures
    """
    try:
        broker_registry = get_broker_registry()
        aggregated = broker_registry.aggregate_positions()
        return aggregated
    except Exception:
        return {
            "total_exposure_by_symbol": {},
            "total_market_value": 0.0,
            "broker_attribution": {},
            "broker_count": 0,
            "errors": [],
        }


# PHASE 5 — AUDIT LOGGING ENDPOINT

@app.get("/audit/logs")
def audit_logs(limit: int = 100, event_type: str = None):
    """
    PHASE 5: Get audit logs (read-only)
    PHASE 8: Extended to include ARMED operations
    
    Args:
        limit: Maximum number of log entries to return (default 100)
        event_type: Optional filter by event type
    
    Returns:
        List of audit log entries, most recent first
    
    SAFETY:
    - Always returns 200 (never 404)
    - Read-only access
    - No sensitive secrets exposed
    """
    try:
        from api.audit import get_audit_logger
        audit_logger = get_audit_logger()
        logs = audit_logger.get_logs(limit=limit, event_type=event_type)
        return logs
    except Exception:
        return []


# PHASE 3-5 — ARMED PROMOTION ENDPOINTS

@app.post("/engine/armed/request")
def armed_request(reason: str, approval_window_seconds: int = 900):
    """
    PHASE 3: Create ARMED promotion request
    
    Args:
        reason: Reason for ARMED activation
        approval_window_seconds: Approval window in seconds (300-3600, default 900)
    
    Returns:
        Request ID and status
    
    SAFETY:
    - Only allowed when engine.state == SHADOW
    - Only one active request at a time
    - All requests logged
    """
    try:
        from api.approvals import get_approval_manager
        from api.audit import get_audit_logger
        from api.engine import EngineState
        
        engine_runtime = get_engine_runtime()
        approval_manager = get_approval_manager()
        audit_logger = get_audit_logger()
        
        # Check current state
        current_state = engine_runtime.get_state_dict()["state"]
        if current_state != "SHADOW":
            return {
                "success": False,
                "message": f"Cannot create ARMED request - engine state must be SHADOW (current: {current_state})",
                "engine_state": engine_runtime.get_state_dict(),
            }
        
        # Create request
        request_id, message = approval_manager.create_request(
            reason=reason,
            approval_window_seconds=approval_window_seconds
        )
        
        if request_id:
            # PHASE 8: Log request creation with correlation_id
            audit_logger.log_event(
                event_type="armed_request_created",
                actor="api",
                payload={
                    "request_id": request_id,
                    "reason": reason,
                    "approval_window_seconds": approval_window_seconds,
                },
                correlation_id=request_id
            )
            
            return {
                "success": True,
                "message": message,
                "request_id": request_id,
                "request": approval_manager.get_request(request_id).to_dict(),
            }
        else:
            return {
                "success": False,
                "message": message,
                "engine_state": engine_runtime.get_state_dict(),
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "engine_state": get_engine_runtime().get_state_dict(),
        }


@app.post("/engine/armed/approve")
def armed_approve(
    request_id: str,
    approver_id: str,
    approver_role: str,
    approval_method: str,
    device_id: str = None
):
    """
    PHASE 3: Submit approval for ARMED request
    PHASE 4: Enforces mobile confirmation requirement
    
    Args:
        request_id: Approval request ID
        approver_id: Unique approver identifier
        approver_role: "admin" | "operator" | "risk"
        approval_method: "mobile" | "api"
        device_id: Required if approval_method == "mobile"
    
    Returns:
        Approval result and updated request status
    
    SAFETY:
    - Reject duplicate approvers
    - Mobile approval requires device_id
    - At least one mobile approval required
    - All approvals logged
    """
    try:
        from api.approvals import (
            get_approval_manager,
            ApproverRole,
            ApprovalMethod,
        )
        from api.audit import get_audit_logger
        
        approval_manager = get_approval_manager()
        audit_logger = get_audit_logger()
        
        # Validate approver_role
        try:
            role = ApproverRole[approver_role.upper()]
        except KeyError:
            return {
                "success": False,
                "message": f"Invalid approver_role: {approver_role}. Must be admin, operator, or risk",
            }
        
        # Validate approval_method
        try:
            method = ApprovalMethod[approval_method.upper()]
        except KeyError:
            return {
                "success": False,
                "message": f"Invalid approval_method: {approval_method}. Must be mobile or api",
            }
        
        # PHASE 4: Mobile approval requires device_id
        if method == ApprovalMethod.MOBILE and not device_id:
            return {
                "success": False,
                "message": "Mobile approval requires device_id",
            }
        
        # Add approval
        success, message = approval_manager.add_approval(
            request_id=request_id,
            approver_id=approver_id,
            approver_role=role,
            approval_method=method,
            device_id=device_id
        )
        
        # PHASE 8: Log approval with correlation_id
        audit_logger.log_event(
            event_type="armed_approval",
            actor="api",
            payload={
                "request_id": request_id,
                "approver_id": approver_id,
                "approver_role": approver_role,
                "approval_method": approval_method,
                "device_id": device_id,
                "success": success,
            },
            correlation_id=request_id
        )
        
        request = approval_manager.get_request(request_id)
        return {
            "success": success,
            "message": message,
            "request": request.to_dict() if request else None,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
        }


@app.get("/engine/armed/status")
def armed_status():
    """
    PHASE 3: Get current ARMED request status
    
    Returns:
        Current ARMED request state, approvals collected, expiration timer
    
    SAFETY:
    - Always returns 200 (never 404)
    - Shows active request if any
    - Shows ARMED state metadata if active
    """
    try:
        from api.approvals import get_approval_manager
        
        engine_runtime = get_engine_runtime()
        approval_manager = get_approval_manager()
        
        # Get active request
        active_request = approval_manager.get_active_request()
        
        engine_state = engine_runtime.get_state_dict()
        
        result = {
            "engine_state": engine_state["state"],
            "armed": engine_state.get("armed", {}),
            "active_request": active_request.to_dict() if active_request else None,
        }
        
        return result
    except Exception as e:
        return {
            "engine_state": "DEGRADED",
            "armed": {"active": False, "expires_at": None, "approval_count": 0},
            "active_request": None,
            "error": str(e),
        }


@app.post("/engine/armed/activate")
def armed_activate(request_id: str, armed_ttl_seconds: int = 900):
    """
    PHASE 5: Activate ARMED state
    
    Args:
        request_id: Approved request ID
        armed_ttl_seconds: TTL for ARMED state in seconds (default 900 = 15 minutes)
    
    Returns:
        Activation result and updated engine state
    
    SAFETY:
    - Only activates if ALL conditions met:
      - Engine.state == SHADOW
      - Kill-switch == READY
      - Approval count >= required threshold
      - Mobile approval present
      - Request not expired
    - All activations logged
    """
    try:
        from api.engine import activate_armed, EngineState
        from api.security import get_kill_switch
        from api.audit import get_audit_logger
        
        engine_runtime = get_engine_runtime()
        kill_switch = get_kill_switch()
        audit_logger = get_audit_logger()
        
        # Check kill-switch
        if not kill_switch.can_promote():
            return {
                "success": False,
                "message": f"Cannot activate ARMED - kill-switch status is {kill_switch.status.value}",
                "engine_state": engine_runtime.get_state_dict(),
            }
        
        # Activate ARMED
        success, message = activate_armed(request_id, armed_ttl_seconds)
        
        if success:
            # PHASE 8: Log activation with correlation_id
            audit_logger.log_event(
                event_type="armed_activation",
                actor="api",
                payload={
                    "request_id": request_id,
                    "armed_ttl_seconds": armed_ttl_seconds,
                    "message": message,
                },
                correlation_id=request_id
            )
        
        return {
            "success": success,
            "message": message,
            "engine_state": engine_runtime.get_state_dict(),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "engine_state": get_engine_runtime().get_state_dict(),
        }


@app.post("/engine/armed/revoke")
def armed_revoke(reason: str = "manual_revocation"):
    """
    PHASE 6: Revoke ARMED state
    PHASE 8: Automatic demotion of all strategies
    
    Args:
        reason: Reason for revocation (default "manual_revocation")
    
    Returns:
        Revocation result and updated engine state
    
    SAFETY:
    - Reverts ARMED → SHADOW
    - PHASE 8: Automatically demotes all strategies to SHADOW
    - All revocations logged
    """
    try:
        from api.engine import revoke_armed
        from api.audit import get_audit_logger
        from api.strategies.promotion import get_strategy_promotion
        
        engine_runtime = get_engine_runtime()
        audit_logger = get_audit_logger()
        strategy_promotion = get_strategy_promotion()
        
        success, message = revoke_armed(reason)
        
        if success:
            # PHASE 8: Automatically demote all strategies to SHADOW
            demoted_count = strategy_promotion.demote_all_to_shadow(actor="system")
            
            # PHASE 8: Log revocation
            audit_logger.log_event(
                event_type="armed_revocation",
                actor="api",
                payload={
                    "reason": reason,
                    "message": message,
                    "strategies_demoted": demoted_count,
                }
            )
        
        return {
            "success": success,
            "message": message,
            "engine_state": engine_runtime.get_state_dict(),
            "strategies_demoted": demoted_count if success else 0,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "engine_state": get_engine_runtime().get_state_dict(),
        }


# PHASE 2-3 — STRATEGY ENDPOINTS

@app.get("/strategies")
def get_strategies():
    registry = get_strategy_registry()
    return registry.list()

@app.post("/strategies/register")
def register_strategy_endpoint(payload: dict):
    required = {"id", "name"}
    if not required.issubset(payload):
        raise HTTPException(status_code=400, detail="Missing required fields")

    registry = get_strategy_registry()
    return registry.register(
        strategy_id=payload["id"],
        name=payload["name"],
        description=payload.get("description", ""),
        default_mode=StrategyMode(payload.get("default_mode", "SHADOW")),
    )

@app.post("/strategies/{strategy_id}/mode")
def set_strategy_mode_endpoint(strategy_id: str, payload: dict):
    mode = payload.get("mode")
    if mode not in StrategyMode.__members__:
        raise HTTPException(status_code=400, detail="Invalid mode")

    registry = get_strategy_registry()
    updated = registry.set_mode(strategy_id, StrategyMode[mode])

    if not updated:
        raise HTTPException(status_code=404, detail="Strategy not found")

    return updated


@app.post("/strategies/{strategy_id}/promote")
def promote_strategy(strategy_id: str, payload: dict):
    """
    PHASE 4 — PROMOTE STRATEGY
    
    Promote strategy from SHADOW to PAPER.
    
    Args:
        strategy_id: Strategy identifier
        payload: { "reason": "manual" } (optional)
    
    Returns:
        PromotionDecision
    
    SAFETY:
    - Promotion requires engine.state == ARMED
    - Promotion requires kill-switch == READY
    - Promotion requires risk engine approval
    - All promotions logged
    - Never throws - returns failure decision on error
    """
    try:
        from api.strategies.promotion import get_strategy_promotion, PromotionReason
        
        promotion_engine = get_strategy_promotion()
        reason = payload.get("reason", PromotionReason.MANUAL.value)
        
        decision = promotion_engine.promote(
            strategy_id=strategy_id,
            actor="api",
            reason=reason,
            correlation_id=None
        )
        
        if not decision.approved:
            # Return 400 with decision details
            raise HTTPException(
                status_code=400,
                detail=decision.reason
            )
        
        return decision.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        # Never throw - return failure decision
        from api.strategies.promotion import PromotionDecision
        decision = PromotionDecision(
            strategy_id=strategy_id,
            from_mode="UNKNOWN",
            to_mode="PAPER",
            approved=False,
            reason=f"Promotion error: {str(e)}",
            actor="api",
            correlation_id=None,
        )
        raise HTTPException(status_code=500, detail=decision.reason)


@app.post("/strategies/promote_all")
def promote_all_strategies_to_shadow():
    """
    Promote all registered strategies to SHADOW mode.
    Safe:
    - No LIVE promotion
    - No engine arming
    - Idempotent
    """
    from api.strategies.registry import get_strategy_registry, StrategyMode
    
    registry = get_strategy_registry()
    promoted = []
    
    # Get all strategies and promote them to SHADOW
    strategies = registry.list()
    for strategy in strategies:
        strategy_id = strategy.get("id")
        current_mode = strategy.get("mode")
        
        if current_mode != StrategyMode.SHADOW.value:
            updated = registry.set_mode(strategy_id, StrategyMode.SHADOW)
            if updated:
                promoted.append(strategy_id)
    
    return {
        "success": True,
        "target": "SHADOW",
        "promoted_strategies": promoted,
        "count": len(promoted),
    }


@app.post("/strategies/{strategy_id}/demote")
def demote_strategy(strategy_id: str, payload: dict):
    """
    PHASE 4 — DEMOTE STRATEGY
    
    Demote strategy from PAPER to SHADOW.
    
    Args:
        strategy_id: Strategy identifier
        payload: { "reason": "manual" } (optional)
    
    Returns:
        PromotionDecision
    
    SAFETY:
    - Demotion always allowed (safe operation)
    - All demotions logged
    - Never throws - returns failure decision on error
    """
    try:
        from api.strategies.promotion import get_strategy_promotion, PromotionReason
        
        promotion_engine = get_strategy_promotion()
        reason = payload.get("reason", PromotionReason.MANUAL.value)
        
        decision = promotion_engine.demote(
            strategy_id=strategy_id,
            actor="api",
            reason=reason,
            correlation_id=None
        )
        
        if not decision.approved:
            # Return 400 with decision details
            raise HTTPException(
                status_code=400,
                detail=decision.reason
            )
        
        return decision.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        # Never throw - return failure decision
        from api.strategies.promotion import PromotionDecision
        decision = PromotionDecision(
            strategy_id=strategy_id,
            from_mode="UNKNOWN",
            to_mode="SHADOW",
            approved=False,
            reason=f"Demotion error: {str(e)}",
            actor="api",
            correlation_id=None,
        )
        raise HTTPException(status_code=500, detail=decision.reason)


@app.get("/strategies/promotions")
def get_strategy_promotions(limit: int = 100):
    """
    PHASE 4 — GET PROMOTION HISTORY
    
    Get recent strategy promotion/demotion decisions.
    
    Args:
        limit: Maximum number of decisions to return (default 100)
    
    Returns:
        List of PromotionDecision records (most recent first)
    
    SAFETY:
    - Always returns 200 (never 404)
    - Returns empty list if no promotions
    - Read-only operation
    """
    try:
        from api.strategies.promotion import get_strategy_promotion
        
        promotion_engine = get_strategy_promotion()
        promotions = promotion_engine.get_promotions(limit=limit)
        
        return {
            "promotions": promotions,
            "count": len(promotions),
            "limit": limit,
        }
    except Exception as e:
        # Never throw - return empty list on error
        return {
            "promotions": [],
            "count": 0,
            "limit": limit,
            "error": str(e),
        }


@app.post("/strategies/{strategy_id}/auto-promotion/enable")
def enable_auto_promotion(strategy_id: str):
    """
    PHASE 15 — ENABLE AUTO-PROMOTION
    
    Enable auto-promotion for a strategy.
    
    Args:
        strategy_id: Strategy identifier
    
    Returns:
        Success result
    
    SAFETY:
    - Never throws - returns failure on error
    - All actions logged
    """
    try:
        from api.strategies.auto_promotion import get_auto_promotion_engine
        
        auto_promotion_engine = get_auto_promotion_engine()
        success = auto_promotion_engine.set_auto_promotion_enabled(
            strategy_id=strategy_id,
            enabled=True,
            actor="api"
        )
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_id}")
        
        return {
            "success": True,
            "message": f"Auto-promotion enabled for strategy {strategy_id}",
            "strategy_id": strategy_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        # Never throw - return failure
        raise HTTPException(status_code=500, detail=f"Error enabling auto-promotion: {str(e)}")


@app.post("/strategies/{strategy_id}/auto-promotion/disable")
def disable_auto_promotion(strategy_id: str):
    """
    PHASE 15 — DISABLE AUTO-PROMOTION
    
    Disable auto-promotion for a strategy.
    
    Args:
        strategy_id: Strategy identifier
    
    Returns:
        Success result
    
    SAFETY:
    - Never throws - returns failure on error
    - All actions logged
    """
    try:
        from api.strategies.auto_promotion import get_auto_promotion_engine
        
        auto_promotion_engine = get_auto_promotion_engine()
        success = auto_promotion_engine.set_auto_promotion_enabled(
            strategy_id=strategy_id,
            enabled=False,
            actor="api"
        )
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_id}")
        
        return {
            "success": True,
            "message": f"Auto-promotion disabled for strategy {strategy_id}",
            "strategy_id": strategy_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        # Never throw - return failure
        raise HTTPException(status_code=500, detail=f"Error disabling auto-promotion: {str(e)}")


# PHASE 4-6 — EXECUTION ENDPOINT

@app.post("/execute")
def execute(request: dict):
    """
    PHASE 4: Execute order request (internal use only)
    
    Args:
        request: Execution request dict with:
            - symbol: str
            - side: "buy" | "sell"
            - qty: float
            - order_type: "market" | "limit"
            - limit_price: float (optional, required for limit orders)
            - strategy_id: str
    
    Returns:
        Execution result with:
            - accepted: bool
            - broker_order_id: str (optional)
            - status: str
            - reason: str (optional)
    
    SAFETY:
    - Internal use only (not UI-triggered)
    - Rejects if not ARMED
    - Execution guard MUST pass
    - All attempts logged
    - Paper trading ONLY
    """
    try:
        from api.execution.router import get_execution_router
        from api.execution.base import ExecutionRequest, OrderSide, OrderType
        
        execution_router = get_execution_router()
        
        # PHASE 4: Validate request
        required_fields = ["symbol", "side", "qty", "order_type"]
        for field in required_fields:
            if field not in request:
                return {
                    "success": False,
                    "accepted": False,
                    "reason": f"Missing required field: {field}",
                }
        
        # PHASE 4: Validate order_type
        order_type_str = request["order_type"].lower()
        if order_type_str not in ["market", "limit"]:
            return {
                "success": False,
                "accepted": False,
                "reason": f"Invalid order_type: {request['order_type']}. Must be 'market' or 'limit'",
            }
        
        # PHASE 4: Validate side
        side_str = request["side"].lower()
        if side_str not in ["buy", "sell"]:
            return {
                "success": False,
                "accepted": False,
                "reason": f"Invalid side: {request['side']}. Must be 'buy' or 'sell'",
            }
        
        # PHASE 4: Limit orders require limit_price
        if order_type_str == "limit" and "limit_price" not in request:
            return {
                "success": False,
                "accepted": False,
                "reason": "limit_price required for limit orders",
            }
        
        # PHASE 4: Create ExecutionRequest
        exec_request = ExecutionRequest(
            symbol=request["symbol"],
            side=OrderSide(side_str),
            qty=float(request["qty"]),
            order_type=OrderType(order_type_str),
            limit_price=request.get("limit_price"),
            strategy_id=request.get("strategy_id", "unknown"),
        )
        
        # PHASE 4: Execute through router (applies guard automatically)
        result = execution_router.execute(exec_request)
        
        # PHASE 4: Return result
        return {
            "success": result.accepted,
            "accepted": result.accepted,
            "broker_order_id": result.broker_order_id,
            "status": result.status.value,
            "reason": result.reason,
            "request_id": result.request_id,
        }
        
    except Exception as e:
        # PHASE 4: Error during execution
        return {
            "success": False,
            "accepted": False,
            "status": "error",
            "reason": f"Execution error: {str(e)}",
        }


# PHASE 3 — SENTINEL API CONTRACT (LOCKED)
# All endpoints below are contract stubs - return valid JSON, never 404

# /strategies endpoint moved to PHASE 2-3 section above


# Risk config endpoint moved to PHASE 5-6 section below


@app.get("/capital/allocations")
def capital_allocations():
    """Get capital allocations - contract stub"""
    try:
        return default_capital_allocations_response()
    except Exception:
        return []


@app.get("/capital/transfers")
def capital_transfers():
    """Get capital transfers - contract stub"""
    try:
        return default_capital_transfers_response()
    except Exception:
        return []


@app.get("/performance/stats")
def performance_stats():
    """Get performance statistics - contract stub"""
    try:
        return default_performance_stats_response()
    except Exception:
        return {"equity": 100000.0, "pnl": 0.0}


@app.get("/performance/equity")
def performance_equity(days: int = 30):
    """Get equity performance time-series - contract stub"""
    try:
        return default_performance_equity_response()
    except Exception:
        return []


@app.get("/performance/pnl")
def performance_pnl(period: str = "30d"):
    """Get PnL performance time-series - contract stub"""
    try:
        return default_performance_pnl_response()
    except Exception:
        return []


@app.get("/alerts")
def alerts(limit: int = 50):
    """Get alerts - contract stub"""
    try:
        return default_alerts_response()
    except Exception:
        return []


@app.get("/research/jobs")
def research_jobs():
    """Get research jobs - contract stub"""
    try:
        return default_research_jobs_response()
    except Exception:
        return []


@app.get("/security/info")
def security_info():
    """Get security information - contract stub"""
    try:
        return default_security_info_response()
    except Exception:
        return {"auth": "none", "mobile_controls": "disabled", "kill_switch": "local-only"}


# PHASE 4 — SAFETY ENDPOINT (Optional - for verification)
@app.get("/safety/check")
def safety_check():
    """
    PHASE 4: Safety check endpoint for verifying control plane invariants.
    Read-only, never modifies state.
    """
    try:
        engine_runtime = get_engine_runtime()
        broker_registry = get_broker_registry()
        safety_guard = get_safety_guard()
        
        engine_state = engine_runtime.get_state_dict()
        brokers = broker_registry.get_all()
        broker_trading_enabled = broker_registry.has_trading_enabled()
        
        trading_allowed = safety_guard.check_trading_allowed(
            engine_state=engine_state["state"],
            trading_window=engine_state["trading_window"],
            shadow_mode=engine_state["shadow_mode"],
            broker_trading_enabled=broker_trading_enabled
        )
        
        return {
            "trading_allowed": trading_allowed,
            "engine_state": engine_state["state"],
            "trading_window": engine_state["trading_window"],
            "shadow_mode": engine_state["shadow_mode"],
            "broker_trading_enabled": broker_trading_enabled,
            "kill_switch_safe": get_kill_switch().is_safe(),
            "monitor_mode": engine_state["state"] == "MONITOR",
        }
    except Exception as e:
        return {
            "trading_allowed": False,
            "error": str(e),
            "monitor_mode": True,  # Default to safe
        }


# PHASE 5-6 — RISK ENDPOINTS

@app.get("/risk/config")
def risk_config():
    """
    PHASE 5: Get risk configuration (read-only)
    
    Returns:
        Risk configuration with all thresholds and rules
    
    SAFETY:
    - Always returns 200 (never 404)
    - Read-only access
    - No dynamic mutation
    """
    try:
        from api.risk.config import get_risk_config
        
        config = get_risk_config()
        return config.to_dict()
    except Exception as e:
        return {
            "error": str(e),
            "config_version": "unknown",
        }


@app.get("/risk/decisions")
def risk_decisions(limit: int = 100, approved_only: bool = None):
    """
    PHASE 6: Get risk decision history (read-only)
    
    Args:
        limit: Maximum number of decisions to return (default 100)
        approved_only: Filter by approval status (None = all, True = approved only, False = rejected only)
    
    Returns:
        List of risk decision records (most recent first)
    
    SAFETY:
    - Always returns 200 (never 404)
    - Read-only access
    - Paginated results
    - Regulator-grade explainability
    """
    try:
        from api.risk.engine import get_risk_engine
        
        risk_engine = get_risk_engine()
        decisions = risk_engine.get_decisions(limit=limit, approved_only=approved_only)
        
        return {
            "decisions": decisions,
            "count": len(decisions),
            "limit": limit,
        }
    except Exception as e:
        return {
            "decisions": [],
            "count": 0,
            "error": str(e),
        }

# --- FIXED __main__ UVICORN BLOCK ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
