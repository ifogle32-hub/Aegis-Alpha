"""FastAPI control plane server for Sentinel X (Rork).

────────────────────────────────────────
PHASE 7 — UI HEALTH & OBSERVABILITY (READ-ONLY)
────────────────────────────────────────

UI IS OBSERVER ONLY:
- UI must NEVER execute trades (all trade endpoints require API key auth)
- UI must NEVER arm brokers (no arming endpoints exist)
- UI must NEVER mutate engine state (only EngineMode changes via /control/* endpoints)

EXPOSE READ-ONLY:
- engine_mode: Current engine mode
- broker_connected: True/false broker connection status
- broker_type: ALPACA_PAPER / TRADOVATE / PAPER / NONE
- last_execution_status: Status of last order execution (if any)
- last_error: Last error message from engine (if any)

ASSERTION:
- UI failure cannot affect engine (engine has zero dependencies on UI state)

────────────────────────────────────────
PHASE 6 — UI & ANALYTICS SAFETY BOUNDARY
────────────────────────────────────────

REGRESSION LOCK:
- All UI, dashboards, metrics, charts, strategy analytics:
  * MUST be read-only
  * MUST subscribe to engine state
  * MUST NEVER call engine internals directly
  * MUST NEVER block execution
- If UI crashes → engine continues unaffected
- UI only changes EngineMode via control endpoints
- START command → PAPER mode
- STOP command → RESEARCH mode (training)

PRODUCTION HARDENING:
- Request timeouts on control endpoints
- API key authentication (enforced for mutating endpoints)
- Per-IP rate limiting (KILL bypasses rate limits)
- Structured logging with request_id
- Operation locking to prevent concurrent mutations
- Status robustness guarantees
"""

# ============================================================
# REGRESSION LOCK — DO NOT MODIFY
# Stable execution baseline.
# Changes require architectural review.
# ============================================================
# NO future changes may:
#   • Alter executor signatures
#   • Change router → executor contracts
#   • Introduce lifecycle dependencies in bootstrap
#   • Affect TRAINING auto-connect behavior
# ============================================================

import os
import time
import uuid
import asyncio
import threading
import json
import hashlib
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Set, List, Any
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Request, Response, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.audit_logger import log_audit_event, export_audit_log, get_audit_log_checksum
from sentinel_x.monitoring.notifications import send_kill_notification
from sentinel_x.core.state import BotState, get_state, set_state
from sentinel_x.core.kill_switch import is_killed, KillSwitch
from sentinel_x.core.engine import get_engine
from sentinel_x.core.engine_mode import EngineMode, get_engine_mode, set_engine_mode, get_engine_mode_manager
from sentinel_x.monitoring.event_bus import get_event_bus
from sentinel_x.monitoring.shadow_comparison import get_shadow_comparison_manager
from sentinel_x.intelligence.synthesis_agent import get_synthesis_agent
from sentinel_x.intelligence.strategy_manager import StrategyStatus
from sentinel_x.execution.execution_metrics import get_execution_metrics_tracker
from sentinel_x.utils import safe_emit
from sentinel_x.api.schemas import (
    StatusResponse, StrategyView, MetricsView, PositionView,
    ActionResponse, StrategiesResponse, MetricsResponse, PositionsResponse,
    BrokerHealthResponse, UIHealthResponse, BacktestResultView
)
from sentinel_x.api.rork_adapter import get_rork_mobile_state
from sentinel_x.api.shadow_control import ShadowStatusResponse
from sentinel_x.core.shadow_registry import get_shadow_controller

# Global references (set by main.py)
_engine = None
_strategy_manager = None
_storage = None
_executor = None
_order_router = None

# Context variable for request tracking
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

# PHASE 1: WebSocket connections for metrics streaming
_websocket_connections: Set[WebSocket] = set()
_websocket_lock = threading.Lock()

# SHADOW COMPARISON: WebSocket connections for shadow vs live streaming
_shadow_websocket_connections: Set[WebSocket] = set()
_shadow_websocket_lock = threading.Lock()

# PHASE 1: WebSocket connections for health streaming (read-only)
_health_websocket_connections: Set[WebSocket] = set()
_health_websocket_lock = threading.Lock()
_health_broadcast_task: Optional[asyncio.Task] = None

# PHASE 1: State transition tracking for push notifications
_previous_engine_status: Optional[str] = None  # Track previous status for transition detection
_status_lock = threading.Lock()  # Thread-safe status tracking

# PHASE 2: WebSocket connections for strategy PnL streaming (read-only)
_strategy_websocket_connections: Set[WebSocket] = set()
_strategy_websocket_lock = threading.Lock()
_strategy_broadcast_task: Optional[asyncio.Task] = None

# PHASE 7: Historical replay buffer (ring buffer for health snapshots)
# MEMORY ONLY — NO DB, NO DISK
from collections import deque
health_buffer: deque = deque(maxlen=300)  # 300 snapshots (~5 minutes at 1s intervals)
_replay_buffer_lock = threading.Lock()  # Thread-safe buffer access

# PHASE 3: Strategy PnL buffer (ring buffer for strategy PnL snapshots)
_strategy_pnl_buffer: deque = deque(maxlen=300)  # 300 snapshots (2s interval = 10 minutes history)
_strategy_pnl_lock = threading.Lock()  # Thread-safe buffer access
_strategy_pnl_broadcast_task: Optional[asyncio.Task] = None  # Background broadcast task

# PHASE 2: Device token storage (in-memory, revocable)
_device_tokens: Dict[str, Dict] = {}  # device_id -> {token_hash, permissions, created_at}
_device_tokens_lock = threading.Lock()
ENABLE_DEVICE_TOKENS = os.getenv("ENABLE_DEVICE_TOKENS", "false").lower() == "true"
DEVICE_TOKEN_SECRET = os.getenv("DEVICE_TOKEN_SECRET", os.getenv("API_KEY", ""))

# PHASE 4: Push notification configuration
_enable_notifications = os.getenv("ENABLE_PUSH_NOTIFICATIONS", "false").lower() == "true"
_notification_webhook_url = os.getenv("NOTIFICATION_WEBHOOK_URL", "")


def set_engine(engine):
    """Set global engine reference."""
    global _engine
    _engine = engine


def set_strategy_manager(manager):
    """Set global strategy manager reference."""
    global _strategy_manager
    _strategy_manager = manager


def set_storage(storage):
    """Set global storage reference."""
    global _storage
    _storage = storage


def set_executor(executor):
    """Set global executor reference."""
    global _executor
    _executor = executor


def set_order_router(router):
    """Set global order router reference."""
    global _order_router
    _order_router = router


# ============================================================================
# PRODUCTION HARDENING: Configuration
# ============================================================================

# API Key authentication
API_KEY = os.getenv("API_KEY", "")
ENABLE_AUTH = os.getenv("ENABLE_API_AUTH", "true").lower() == "true" and bool(API_KEY)

# Request timeout for control endpoints (seconds)
CONTROL_ENDPOINT_TIMEOUT = float(os.getenv("API_TIMEOUT", "5.0"))

# Rate limiting configuration
RATE_LIMIT_START_STOP = os.getenv("RATE_LIMIT_START_STOP", "5/minute")
# Note: KILL is exempt from rate limiting for safety - see kill_switch endpoint

# Safety guard: Operation lock to prevent concurrent control actions
_operation_lock = threading.Lock()

# Uptime tracking for monotonicity guarantee
_api_start_time = time.time()
_last_reported_uptime = 0.0
_uptime_lock = threading.Lock()


# ============================================================================
# PRODUCTION HARDENING: Async Timeout Decorator
# ============================================================================

def with_timeout(timeout_seconds: float):
    """
    Decorator to add async timeout to endpoint handlers.
    Logs timeout events and raises 504 Gateway Timeout.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request_id = request_id_ctx.get()
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"TIMEOUT | request_id={request_id} | "
                    f"endpoint={func.__name__} | "
                    f"timeout={timeout_seconds}s"
                )
                raise HTTPException(
                    status_code=504,
                    detail=f"Operation timed out after {timeout_seconds}s"
                )
        return wrapper
    return decorator


# ============================================================================
# PRODUCTION HARDENING: Authentication
# ============================================================================

async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """
    REQUIRED API key check for mutating endpoints.
    Supports both X-API-Key header and Authorization: Bearer token.
    Rejects with 401 if auth is enabled and key is missing/invalid.
    """
    request_id = request_id_ctx.get()
    client_ip = get_remote_address(request)
    
    if not ENABLE_AUTH:
        return True  # Auth disabled via env flag
    
    # Check X-API-Key header
    if x_api_key and x_api_key == API_KEY:
        # PHASE 1: Log auth success (request_id only, never API key)
        logger.info(
            f"AUTH_SUCCESS | request_id={request_id} | "
            f"client={client_ip} | "
            f"endpoint={request.url.path}"
        )
        return True
    
    # Check Authorization Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]  # Remove "Bearer " prefix
        if token == API_KEY:
            # PHASE 1: Log auth success (request_id only, never API key)
            logger.info(
                f"AUTH_SUCCESS | request_id={request_id} | "
                f"client={client_ip} | "
                f"endpoint={request.url.path}"
            )
            return True
    
    # No valid auth found - log and reject
    # PHASE 1: Never log API key, only request_id
    logger.warning(
        f"AUTH_FAILURE | request_id={request_id} | "
        f"client={client_ip} | "
        f"endpoint={request.url.path} | "
        f"reason=invalid_or_missing_key"
    )
    # PHASE 3: Audit log auth failure
    log_audit_event("AUTH_FAILURE", request_id, metadata={"endpoint": request.url.path})
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ============================================================================
# PHASE 2: Per-Device API Token Management
# ============================================================================

def hash_token(token: str) -> str:
    """Hash token for storage (never store plain tokens)."""
    return hashlib.sha256(token.encode()).hexdigest()


def validate_device_token(device_id: str, token: str, required_permission: str) -> bool:
    """
    Validate device token with scoped permissions.
    
    PHASE 2: Token format: <device_id>:<signed_token>
    Required permission: start, stop, kill, read
    """
    if not ENABLE_DEVICE_TOKENS:
        return False  # Device tokens disabled
    
    with _device_tokens_lock:
        if device_id not in _device_tokens:
            return False
        
        device_info = _device_tokens[device_id]
        token_hash = hash_token(token)
        
        # Check token hash matches
        if device_info['token_hash'] != token_hash:
            return False
        
        # Check permission scope
        permissions = device_info.get('permissions', [])
        if required_permission not in permissions and 'all' not in permissions:
            return False
        
        return True


def create_device_token(device_id: str, permissions: List[str]) -> str:
    """
    Create a device token.
    
    PHASE 2: Returns token in format: <device_id>:<signed_token>
    """
    if not DEVICE_TOKEN_SECRET:
        raise ValueError("DEVICE_TOKEN_SECRET not configured")
    
    # Generate signed token
    timestamp = str(int(time.time()))
    token_data = f"{device_id}:{timestamp}:{DEVICE_TOKEN_SECRET}"
    signed_token = hashlib.sha256(token_data.encode()).hexdigest()[:32]
    
    full_token = f"{device_id}:{signed_token}"
    token_hash = hash_token(full_token)
    
    # Store device token info
    with _device_tokens_lock:
        _device_tokens[device_id] = {
            'token_hash': token_hash,
            'permissions': permissions,
            'created_at': datetime.utcnow().isoformat() + "Z"
        }
    
    logger.info(f"DEVICE_TOKEN_CREATED | device_id={device_id} | permissions={permissions}")
    return full_token


def revoke_device_token(device_id: str) -> bool:
    """
    Revoke a device token (removes from storage).
    
    PHASE 2: Tokens are revocable without restart.
    """
    with _device_tokens_lock:
        if device_id in _device_tokens:
            del _device_tokens[device_id]
            logger.info(f"DEVICE_TOKEN_REVOKED | device_id={device_id}")
            return True
        return False


async def require_device_token_or_api_key(
    request: Request,
    required_permission: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """
    PHASE 2: Validate either device token or API key.
    
    Device token format: <device_id>:<signed_token>
    Supports scoped permissions: start, stop, kill, read
    """
    request_id = request_id_ctx.get()
    client_ip = get_remote_address(request)
    
    # First check traditional API key (backward compatible)
    if x_api_key and x_api_key == API_KEY and ENABLE_AUTH:
        logger.info(
            f"AUTH_SUCCESS | request_id={request_id} | "
            f"client={client_ip} | endpoint={request.url.path} | type=api_key"
        )
        return True, None
    
    # Check Authorization Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        
        # Check if it's a device token (format: device_id:signed_token)
        if ':' in token and ENABLE_DEVICE_TOKENS:
            parts = token.split(':', 1)
            if len(parts) == 2:
                device_id, signed_token = parts
                if validate_device_token(device_id, token, required_permission):
                    logger.info(
                        f"AUTH_SUCCESS | request_id={request_id} | "
                        f"client={client_ip} | endpoint={request.url.path} | "
                        f"type=device_token | device_id={device_id} | permission={required_permission}"
                    )
                    return True, device_id
        
        # Check if it's traditional API key
        if token == API_KEY and ENABLE_AUTH:
            logger.info(
                f"AUTH_SUCCESS | request_id={request_id} | "
                f"client={client_ip} | endpoint={request.url.path} | type=api_key"
            )
            return True, None
    
    # No valid auth found
    logger.warning(
        f"AUTH_FAILURE | request_id={request_id} | "
        f"client={client_ip} | endpoint={request.url.path} | "
        f"reason=invalid_or_missing_token | required_permission={required_permission}"
    )
    raise HTTPException(
        status_code=401,
        detail=f"Invalid or missing token (required permission: {required_permission})"
    )


# ============================================================================
# PRODUCTION HARDENING: Rate Limiting Setup
# ============================================================================

# Custom key function that exempts KILL endpoint
def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key - returns empty string for KILL to exempt it."""
    # SAFETY: KILL endpoint is NEVER rate limited
    if request.url.path == "/kill":
        return ""  # Empty key = no rate limiting
    return get_remote_address(request)


# Create FastAPI app
app = FastAPI(
    title="Sentinel X Control Plane",
    description="Rork API for controlling and monitoring Sentinel X",
    version="1.0.0"
)

# Initialize rate limiter with custom key function
limiter = Limiter(key_func=get_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware (allow Rork mobile app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include shadow backtesting endpoints
try:
    from sentinel_x.api.shadow_endpoints import router as shadow_router, get_backtest_summary
    app.include_router(shadow_router)
except ImportError as e:
    logger.warning(f"Could not import shadow endpoints: {e}")
    get_backtest_summary = None

# Include shadow control endpoints (PHASE 4 - SHADOW CONTROL API)
try:
    from sentinel_x.api.shadow_control import router as shadow_control_router
    app.include_router(shadow_control_router)
except ImportError as e:
    logger.warning(f"Could not import shadow control endpoints: {e}")


# ============================================================================
# PRODUCTION HARDENING: Request Logging Middleware (Enhanced)
# ============================================================================

@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next):
    """
    Enhanced request logging with structured data.
    Assigns request_id, logs caller, action, timing, and result.
    """
    # Generate unique request ID
    req_id = str(uuid.uuid4())[:8]
    request_id_ctx.set(req_id)
    
    start_time = time.time()
    client_ip = get_remote_address(request)
    endpoint = request.url.path
    method = request.method
    
    # Capture state before for control endpoints
    state_before = None
    if endpoint in ["/start", "/stop", "/kill"] and _engine:
        state_before = get_state().value
    
    # Log request
    logger.info(
        f"REQUEST | request_id={req_id} | "
        f"method={method} | "
        f"endpoint={endpoint} | "
        f"client={client_ip} | "
        f"state_before={state_before}"
    )
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Capture state after for control endpoints
        state_after = None
        if endpoint in ["/start", "/stop", "/kill"] and _engine:
            state_after = get_state().value
        
        # Log response
        log_level = "INFO" if response.status_code < 400 else "WARNING"
        log_msg = (
            f"RESPONSE | request_id={req_id} | "
            f"method={method} | "
            f"endpoint={endpoint} | "
            f"status={response.status_code} | "
            f"time={process_time:.3f}s | "
            f"client={client_ip}"
        )
        if state_before is not None:
            log_msg += f" | state_before={state_before} | state_after={state_after}"
        
        if response.status_code < 400:
            logger.info(log_msg)
        else:
            logger.warning(log_msg)
        
        # Warn on slow requests
        if process_time > CONTROL_ENDPOINT_TIMEOUT:
            logger.warning(
                f"SLOW_REQUEST | request_id={req_id} | "
                f"endpoint={endpoint} | "
                f"time={process_time:.3f}s | "
                f"threshold={CONTROL_ENDPOINT_TIMEOUT}s"
            )
        
        return response
    
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(
            f"ERROR | request_id={req_id} | "
            f"method={method} | "
            f"endpoint={endpoint} | "
            f"error={str(e)} | "
            f"time={process_time:.3f}s | "
            f"client={client_ip}",
            exc_info=True
        )
        raise


# ============================================================================
# PHASE 2: SCHEMA DRIFT IMMUNITY - Safe Attribute Access
# ============================================================================

def safe_get(obj: Any, field: str, default: Any = None) -> Any:
    """
    PHASE 2 — SCHEMA DRIFT IMMUNITY
    
    Safe attribute access that prevents AttributeError from engine refactors.
    
    API must tolerate:
    - Engine restarting
    - Partial initialization
    - Watchdog recovery
    - Version mismatches
    
    Args:
        obj: Object to access (may be None or partial)
        field: Attribute name to access
        default: Default value if attribute doesn't exist
    
    Returns:
        Attribute value or default if missing/None
    """
    if obj is None:
        return default
    try:
        return getattr(obj, field, default)
    except (AttributeError, TypeError):
        return default


# ============================================================================
# PRODUCTION HARDENING: Status Robustness Helpers
# ============================================================================

def get_monotonic_uptime() -> float:
    """
    Get uptime with monotonicity guarantee.
    Uptime never decreases between calls.
    """
    global _last_reported_uptime
    
    if not _engine:
        return 0.0
    
    with _uptime_lock:
        # ALWAYS-ON: Engine is always running (loop continues until killed)
        # Uptime increases continuously while engine exists
        current_mode = get_engine_mode()
        if current_mode != EngineMode.KILLED:
            # PHASE 2: Use safe_get to prevent AttributeError
            started_at = safe_get(_engine, "started_at", None)
            if started_at:
                current_uptime = time.time() - started_at
            else:
                current_uptime = 0.0
            # Ensure monotonicity
            if current_uptime > _last_reported_uptime:
                _last_reported_uptime = current_uptime
            return _last_reported_uptime
        else:
            # When killed, return last known uptime (frozen at kill time)
            return _last_reported_uptime


def derive_engine_state() -> tuple[str, str]:
    """
    Derive engine state with robustness guarantees.
    
    Returns:
        Tuple of (state, mode) - NEVER returns UNKNOWN if engine exists
    """
    # Case 1: No engine reference
    if _engine is None:
        return ("STOPPED", "STOPPED")
    
    # CONTROL PLANE: Use EngineMode from global manager (authoritative)
    current_mode = get_engine_mode()
    
    # Case 2: Kill switch active or EngineMode KILLED
    if is_killed() or current_mode == EngineMode.KILLED:
        return ("STOPPED", "KILLED")
    
    # Case 3: Engine paused
    if current_mode == EngineMode.PAUSED:
        return ("STOPPED", "PAUSED")
    
    # Case 4: Engine running - use authoritative EngineMode
    try:
        state = get_state()
        engine_mode_value = current_mode.value
        return (state.value, engine_mode_value)
    except Exception:
        # Fallback: if we can't get state, engine exists but use safe default
        return ("RUNNING", "RESEARCH")


# ============================================================================
# PHASE 5: STATUS SNAPSHOT EXTRACTION (Side-effect free, thread-safe, read-only)
# ============================================================================

def build_status_snapshot(engine: Any = None) -> dict:
    """
    PHASE 2 — STATUS SNAPSHOT BUILDER (RORK UI CONTRACT)
    
    Build a status snapshot for Rork mobile monitoring.
    
    RULE: REST and WebSocket MUST call engine.get_status_snapshot()
    
    PROPERTIES:
    - Side-effect free (no mutations)
    - Thread-safe (read-only operations)
    - Read-only (no engine state changes)
    - Uses engine.get_status_snapshot() as source of truth
    - NULL-safe (never raises AttributeError)
    
    This function can be called from:
    - HTTP endpoints (get_status)
    - WebSocket streams (/ws/health)
    - Background tasks
    - Multiple threads concurrently
    
    SECURITY LOCKS:
    - READ-ONLY mobile/UI
    - NO nested objects (flat schema)
    - NULL-safe (handles None gracefully)
    
    Args:
        engine: Engine instance (if None, uses global _engine)
    
    Returns:
        Dictionary matching Rork UI contract schema
    """
    try:
        # PHASE 2: Use provided engine or global
        if engine is None:
            engine = _engine
        
        # PHASE 2: REST and WebSocket MUST call engine.get_status_snapshot()
        # Use engine's canonical status snapshot as source of truth
        if engine and hasattr(engine, 'get_status_snapshot'):
            try:
                snapshot = engine.get_status_snapshot()
                
                # Add additional fields for backward compatibility
                try:
                    uptime_seconds = get_monotonic_uptime()
                except Exception:
                    uptime_seconds = None
                
                # Transform engine_state -> engine_status for backward compatibility
                engine_status = snapshot.get("engine_state", "UNKNOWN")
                engine_mode = snapshot.get("mode", "UNKNOWN")
                
                # Build final snapshot matching Rork UI contract
                status_dict = {
                    "engine_status": engine_status,
                    "engine_mode": engine_mode,
                    "loop_tick": snapshot.get("loop_tick"),
                    "loop_tick_age": snapshot.get("loop_tick_age"),
                    "heartbeat_age": snapshot.get("heartbeat_age"),
                    "heartbeat_ts": snapshot.get("heartbeat_ts"),
                    "loop_phase": snapshot.get("loop_phase", "UNKNOWN"),
                    "broker": snapshot.get("broker", "UNKNOWN"),
                    "health": snapshot.get("health", "GREEN"),
                    "uptime_seconds": uptime_seconds,
                    "mobile_read_only": True,
                    "trading_controls": "DISABLED"
                }
                
                # PHASE 5 — SHADOW STATE EXPOSITION (UI DEPENDS ON THIS)
                # Add shadow state to status snapshot
                try:
                    from sentinel_x.core.shadow_registry import get_shadow_controller
                    
                    shadow_controller = get_shadow_controller()
                    state_snapshot = shadow_controller.get_state_dict()
                    
                    status_dict["shadow_mode"] = state_snapshot["shadow_enabled"]
                    status_dict["shadow_state"] = {
                        "mode": state_snapshot["mode"],
                        "trading_window": state_snapshot["trading_window"],
                        "last_transition": state_snapshot["last_transition"],
                        "reason": state_snapshot["reason"]
                    }
                    
                except Exception as e:
                    logger.debug(f"Error adding shadow state to status: {e}")
                    # Non-fatal - continue without shadow state
                    status_dict["shadow_mode"] = False
                    status_dict["shadow_state"] = {
                        "mode": "DISABLED",
                        "trading_window": "UNKNOWN",
                        "last_transition": None,
                        "reason": None
                    }
                
                # Add shadow backtest metrics (PHASE 1 - SHADOW BACKTESTING)
                # Only include metrics if shadow mode is enabled
                if status_dict.get("shadow_mode", False) and get_backtest_summary:
                    try:
                        from sentinel_x.strategies.templates import get_all_strategy_templates
                        from sentinel_x.strategies.shadow_executor import get_shadow_executor
                        
                        shadow_backtest = {}
                        templates = get_all_strategy_templates()
                        shadow_executor = get_shadow_executor()
                        
                        # Get shadow executor metrics (from memory registry)
                        executor_metrics = shadow_executor.get_strategy_metrics()
                        
                        # Get shadow executor metrics (from memory registry)
                        for template in templates[:10]:  # Limit to 10 strategies to avoid blocking
                            try:
                                strategy_id = template.id
                                
                                # Get executor metrics (real-time)
                                exec_metrics = executor_metrics.get(strategy_id, {})
                                
                                # Get backtest summary (historical) if available
                                summary_pnl = 0.0
                                summary_sharpe = 0.0
                                summary_max_drawdown = 0.0
                                summary_trade_count = 0
                                summary_win_rate = 0.0
                                summary_total_return = 0.0
                                
                                if get_backtest_summary:
                                    try:
                                        summary = get_backtest_summary(strategy_id)
                                        if summary:
                                            summary_pnl = getattr(summary, 'pnl', 0.0)
                                            summary_sharpe = getattr(summary, 'sharpe', 0.0)
                                            summary_max_drawdown = getattr(summary, 'max_drawdown', 0.0)
                                            summary_trade_count = getattr(summary, 'trade_count', 0)
                                            summary_win_rate = getattr(summary, 'win_rate', 0.0)
                                            summary_total_return = getattr(summary, 'total_return', 0.0)
                                    except Exception:
                                        pass  # Use defaults if summary not available
                                
                                # Combine metrics (prefer executor metrics, fall back to summary)
                                shadow_backtest[strategy_id] = {
                                    "strategy_id": strategy_id,
                                    "mode": "SHADOW",
                                    "metrics": {
                                        "pnl": exec_metrics.get("pnl", summary_pnl),
                                        "sharpe": exec_metrics.get("sharpe", summary_sharpe),
                                        "max_drawdown": exec_metrics.get("max_drawdown", summary_max_drawdown),
                                        "trade_count": exec_metrics.get("trade_count", summary_trade_count),
                                        "signals_count": exec_metrics.get("signals_count", 0),
                                        "win_rate": exec_metrics.get("win_rate", summary_win_rate),
                                        "total_return": exec_metrics.get("total_return", summary_total_return),
                                        "last_update": exec_metrics.get("last_update", datetime.utcnow().isoformat() + "Z")
                                    }
                                }
                            except Exception as e:
                                logger.debug(f"Error getting shadow metrics for {template.id}: {e}")
                                # Continue with other strategies
                                continue
                        
                        if shadow_backtest:
                            status_dict["strategies_detailed"] = shadow_backtest
                            
                    except Exception as e:
                        logger.debug(f"Error adding shadow backtest metrics to status: {e}")
                        # Non-fatal - continue without shadow_backtest metrics
                        pass
                
                return status_dict
            except Exception as e:
                logger.debug(f"Error calling engine.get_status_snapshot(): {e}")
                # Fall through to degraded response
        
        # Fallback: degraded status if engine not available
        # PHASE 5 — Include shadow state in fallback
        fallback_status = {
            "engine_status": "UNKNOWN",
            "engine_mode": "UNKNOWN",
            "loop_tick": None,
            "loop_tick_age": None,
            "heartbeat_age": None,
            "heartbeat_ts": None,
            "loop_phase": "ERROR",
            "broker": "UNKNOWN",
            "health": "RED",
            "uptime_seconds": None,
            "mobile_read_only": True,
            "trading_controls": "DISABLED",
            "degraded": True
        }
        
        # Add shadow state to fallback (non-fatal)
        try:
            from sentinel_x.core.shadow_registry import get_shadow_controller
            shadow_controller = get_shadow_controller()
            state_snapshot = shadow_controller.get_state_dict()
            fallback_status["shadow_mode"] = state_snapshot["shadow_enabled"]
            fallback_status["shadow_state"] = {
                "mode": state_snapshot["mode"],
                "trading_window": state_snapshot["trading_window"],
                "last_transition": state_snapshot["last_transition"],
                "reason": state_snapshot["reason"]
            }
        except Exception:
            fallback_status["shadow_mode"] = False
            fallback_status["shadow_state"] = {
                "mode": "DISABLED",
                "trading_window": "UNKNOWN",
                "last_transition": None,
                "reason": None
            }
        
        return fallback_status
        
    except Exception as e:
        # On error, return degraded status payload matching Rork UI contract
        logger.exception("Status failure")
        error_status = {
            "engine_status": "UNKNOWN",
            "engine_mode": "UNKNOWN",
            "loop_tick": None,
            "loop_tick_age": None,
            "heartbeat_age": None,
            "heartbeat_ts": None,
            "loop_phase": "ERROR",
            "broker": "UNKNOWN",
            "health": "RED",
            "uptime_seconds": None,
            "mobile_read_only": True,
            "trading_controls": "DISABLED",
            "degraded": True,
            "reason": str(e)
        }
        
        # Add shadow state to error status (non-fatal)
        try:
            from sentinel_x.core.shadow_registry import get_shadow_controller
            shadow_controller = get_shadow_controller()
            state_snapshot = shadow_controller.get_state_dict()
            error_status["shadow_mode"] = state_snapshot["shadow_enabled"]
            error_status["shadow_state"] = {
                "mode": state_snapshot["mode"],
                "trading_window": state_snapshot["trading_window"],
                "last_transition": state_snapshot["last_transition"],
                "reason": state_snapshot["reason"]
            }
        except Exception:
            error_status["shadow_mode"] = False
            error_status["shadow_state"] = {
                "mode": "DISABLED",
                "trading_window": "UNKNOWN",
                "last_transition": None,
                "reason": None
            }
        
        return error_status


# ============================================================================
# PHASE 1: WebSocket Metrics Aggregation
# ============================================================================

async def aggregate_live_metrics() -> dict:
    """
    Aggregate live metrics from multiple sources for WebSocket streaming.
    
    Returns:
        Dictionary with equity, pnl, positions, strategies, uptime, state, mode
    """
    try:
        # Get account info (equity)
        equity = None
        if _order_router:
            account = _order_router.get_account()
            if account:
                equity = account.get('equity') or account.get('portfolio_value')
        
        # Get positions (PnL, count)
        total_pnl = 0.0
        open_positions = 0
        if _order_router:
            positions = _order_router.get_positions()
            if positions:
                total_pnl = sum(p.get('unrealized_pnl', 0.0) for p in positions)
                open_positions = len(positions)
        
        # Get active strategies count
        active_strategies = 0
        if _strategy_manager:
            strategies = _strategy_manager.list_strategies()
            active_strategies = len([s for s in strategies if s.get('status') == 'ACTIVE'])
        
        # Get engine state and uptime
        state, mode = derive_engine_state()
        uptime = get_monotonic_uptime()
        
        return {
            "equity": equity,
            "pnl": total_pnl,
            "open_positions": open_positions,
            "active_strategies": active_strategies,
            "engine_uptime": uptime,
            "state": state,
            "mode": mode,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error aggregating metrics: {e}", exc_info=True)
        # Return safe defaults
        state, mode = derive_engine_state()
        return {
            "equity": None,
            "pnl": 0.0,
            "open_positions": 0,
            "active_strategies": 0,
            "engine_uptime": get_monotonic_uptime(),
            "state": state,
            "mode": mode,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


async def broadcast_metrics():
    """Broadcast metrics to all connected WebSocket clients."""
    if not _websocket_connections:
        return
    
    try:
        metrics = await aggregate_live_metrics()
        message = json.dumps(metrics)
        
        # Broadcast to all connected clients
        disconnected = set()
        connections_copy = set(_websocket_connections)  # Copy to avoid modification during iteration
        
        for websocket in connections_copy:
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.debug(f"WebSocket send error: {e}")
                disconnected.add(websocket)
        
        # Remove disconnected clients
        if disconnected:
            with _websocket_lock:
                _websocket_connections -= disconnected
    
    except Exception as e:
        logger.error(f"Error broadcasting metrics: {e}", exc_info=True)


# ============================================================================
# ENDPOINTS
# ============================================================================

# Health check (no auth required)
@app.get("/")
async def root():
    """Root endpoint - health check."""
    return {"service": "Sentinel X Control Plane", "version": "1.0.0"}


# ============================================================================
# PHASE 3 — HEALTH SNAPSHOT GENERATOR (READ-ONLY, NON-BLOCKING)
# ============================================================================
# REGRESSION LOCK — Health streaming only
# DO NOT add control messages
# DO NOT attach to execution path
# SAFETY: WebSocket is read-only
# SAFETY: Engine loop never blocks on API
# ============================================================================

def get_health_snapshot() -> dict:
    """
    PHASE 3 — ENGINE-SIDE BROADCAST SIGNAL
    
    Generate lightweight health snapshot from existing heartbeat state.
    
    SAFETY GUARANTEES:
    - Reads existing heartbeat + loop tick state
    - No new locks
    - No sleeps
    - No waits
    - Safe to call at any time
    - Never blocks engine loop
    
    Returns:
        Health snapshot dict with:
        - status: RUNNING | STALE | FROZEN
        - mode: EngineMode value (TRAINING | PAPER | RESEARCH | LIVE | PAUSED | KILLED)
        - loop_phase: Current engine phase
        - loop_tick: Loop tick counter
        - loop_tick_age: Age of last loop tick (seconds)
        - heartbeat_age: Age of last heartbeat (seconds)
        - broker: Broker type (ALPACA_PAPER | PAPER | TRADOVATE | NONE)
        - watchdog: Watchdog state (OK | STALE | FROZEN)
        - timestamp: Monotonic timestamp (seconds)
    
    SAFETY: Read-only, non-blocking, never raises
    REGRESSION LOCK: Health streaming only - DO NOT add control messages
    """
    try:
        from sentinel_x.monitoring.heartbeat import read_heartbeat
        import time as time_module
        from sentinel_x.core.engine_mode import get_engine_mode
        
        # Read heartbeat (source of truth)
        heartbeat = read_heartbeat()
        
        # Get engine mode (authoritative)
        engine_mode = get_engine_mode()
        mode_value = engine_mode.value
        
        # Get loop tick and phase from heartbeat
        loop_tick = heartbeat.get('loop_tick', 0) if heartbeat else 0
        loop_phase = heartbeat.get('loop_phase', 'UNKNOWN') if heartbeat else 'UNKNOWN'
        
        # Calculate heartbeat age and loop tick age (monotonic time)
        now_mono = time_module.monotonic()
        heartbeat_monotonic = heartbeat.get('heartbeat_monotonic') if heartbeat else None
        last_loop_tick_ts = heartbeat.get('last_loop_tick_ts') if heartbeat else None
        
        heartbeat_age = (now_mono - heartbeat_monotonic) if heartbeat_monotonic else 999.9
        loop_tick_age = (now_mono - last_loop_tick_ts) if last_loop_tick_ts else 999.9
        
        # Determine status based on heartbeat age (same logic as /health endpoint)
        if loop_tick_age < 10.0:
            status = "RUNNING"
            watchdog = "OK"
        elif heartbeat_age >= 10.0 and loop_tick_age < 30.0:
            status = "STALE"
            watchdog = "STALE"
        else:
            status = "FROZEN"
            watchdog = "FROZEN"
        
        # PHASE 1: Detect state transitions and emit notifications (non-blocking)
        # SAFETY: Alerts fire at most once per transition, no retries, no engine coupling
        try:
            with _status_lock:
                previous_status = _previous_engine_status
                
                # Detect transitions: RUNNING → FROZEN, FROZEN → RUNNING
                if previous_status is not None:
                    if previous_status == "RUNNING" and status == "FROZEN":
                        # RUNNING → FROZEN transition
                        from sentinel_x.monitoring.notifications import send_engine_frozen_notification
                        safe_emit(send_engine_frozen_notification(heartbeat_age, loop_tick_age))
                    elif previous_status == "FROZEN" and status == "RUNNING":
                        # FROZEN → RUNNING transition (recovered)
                        from sentinel_x.monitoring.notifications import send_engine_recovered_notification
                        safe_emit(send_engine_recovered_notification(heartbeat_age, loop_tick_age))
                
                # Update previous status (only for RUNNING and FROZEN states for transition detection)
                if status in ("RUNNING", "FROZEN"):
                    _previous_engine_status = status
        except Exception as e:
            # SAFETY: Notification failures must NOT affect engine
            logger.debug(f"Error detecting state transition (non-fatal): {e}")
        
        # Get broker name (safe defaults)
        broker_name = "NONE"
        if _order_router and _order_router.active_executor:
            broker_name_attr = getattr(_order_router.active_executor, 'name', 'unknown')
            if broker_name_attr == 'alpaca' or 'alpaca' in broker_name_attr.lower():
                broker_name = "ALPACA_PAPER"
            elif broker_name_attr == 'paper':
                broker_name = "PAPER"
            elif broker_name_attr == 'tradovate':
                broker_name = "TRADOVATE"
        
        return {
            "status": status,
            "mode": mode_value,
            "loop_phase": loop_phase,
            "loop_tick": loop_tick,
            "loop_tick_age": round(loop_tick_age, 1),
            "heartbeat_age": round(heartbeat_age, 1),
            "broker": broker_name,
            "watchdog": watchdog,
            "timestamp": now_mono  # Monotonic timestamp
        }
    except Exception as e:
        # SAFETY: Never raise, always return safe defaults
        logger.debug(f"Error getting health snapshot (non-fatal): {e}")
        import time as time_module
        return {
            "status": "FROZEN",
            "mode": "UNKNOWN",
            "loop_phase": "UNKNOWN",
            "loop_tick": 0,
            "loop_tick_age": 999.9,
            "heartbeat_age": 999.9,
            "broker": "NONE",
            "watchdog": "FROZEN",
            "timestamp": time_module.monotonic() if hasattr(time_module, 'monotonic') else time_module.time()
        }


# ============================================================================
# PHASE 5 — WEBSOCKET HEALTH BROADCASTING (NON-BLOCKING, ISOLATED)
# ============================================================================
# REGRESSION LOCK — Health streaming only
# DO NOT add control messages
# DO NOT attach to execution path
# SAFETY: WebSocket is read-only
# SAFETY: Engine loop never blocks on API
# SAFETY: WebSocket failures must NOT affect engine
# ============================================================================

async def broadcast_health_snapshots():
    """
    PHASE 6-7 — WEBSOCKET STREAMING WITH REPLAY BUFFER
    
    Background task that broadcasts status snapshots to all connected clients.
    
    PHASE 7: Historical replay buffer integration
    - Stores snapshots in ring buffer (last 60-120 snapshots)
    - Enables mobile reconnects to catch up
    
    SAFETY GUARANTEES:
    - Runs in API event loop (not engine thread)
    - Non-blocking (uses asyncio.sleep)
    - Isolated from engine loop
    - Engine loop NEVER awaits WebSocket
    - Engine state is READ-only
    - No shared mutable writes
    
    Rules:
    - Sends status snapshot at fixed interval (1s)
    - Stores snapshot in replay buffer before broadcasting
    - If client disconnects → clean up silently
    - If send fails → drop client
    - If no clients connected → still store snapshots for replay
    
    SAFETY: WebSocket is read-only
    REGRESSION LOCK: DO NOT add control messages
    """
    while True:
        try:
            await asyncio.sleep(1.0)  # Fixed interval: 1 second
            
            # PHASE 5: Generate status snapshot using build_status_snapshot (side-effect free, thread-safe)
            # PHASE 7: Store in replay buffer for historical replay
            # PHASE 8: Detect state transitions and emit push notifications
            try:
                snapshot = build_status_snapshot(_engine)
                
                # PHASE 8: Detect transitions: RUNNING → FROZEN, FROZEN → RECOVERED
                # Mark events idempotent (fire at most once per transition)
                # Do NOT spam notifications
                try:
                    current_status = snapshot.get("status")
                    heartbeat_age = snapshot.get("heartbeat_age")
                    
                    with _status_lock:
                        previous_status = _previous_engine_status
                        
                        # Detect transitions: RUNNING → FROZEN, FROZEN → RUNNING (RECOVERED)
                        if previous_status is not None:
                            if previous_status == "RUNNING" and current_status == "FROZEN":
                                # RUNNING → FROZEN transition (frozen)
                                logger.warning(
                                    f"ENGINE_FROZEN | heartbeat_age={heartbeat_age} | "
                                    f"transition={previous_status}→{current_status}"
                                )
                                # Emit push notification (non-blocking, fire-and-forget)
                                try:
                                    from sentinel_x.monitoring.notifications import send_engine_frozen_notification
                                    safe_emit(send_engine_frozen_notification(heartbeat_age or 999.9, heartbeat_age or 999.9))
                                except Exception:
                                    pass  # Notification failure must not affect engine
                            
                            elif previous_status == "FROZEN" and current_status == "RUNNING":
                                # FROZEN → RUNNING transition (recovered)
                                logger.info(
                                    f"ENGINE_RECOVERED | heartbeat_age={heartbeat_age} | "
                                    f"transition={previous_status}→{current_status}"
                                )
                                # Emit push notification (non-blocking, fire-and-forget)
                                try:
                                    from sentinel_x.monitoring.notifications import send_engine_recovered_notification
                                    safe_emit(send_engine_recovered_notification(heartbeat_age or 0.0, heartbeat_age or 0.0))
                                except Exception:
                                    pass  # Notification failure must not affect engine
                        
                        # Update previous status (only for RUNNING and FROZEN states for transition detection)
                        # Idempotent: only track transitions for RUNNING and FROZEN
                        if current_status in ("RUNNING", "FROZEN"):
                            _previous_engine_status = current_status
                except Exception as e:
                    # SAFETY: Notification failures must NOT affect engine
                    logger.debug(f"Error detecting state transition (non-fatal): {e}")
                
                # Add timestamp for replay buffer
                snapshot_with_ts = {
                    **snapshot,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "timestamp_monotonic": time.monotonic()
                }
                
                # PHASE 7: Store in replay buffer (thread-safe) - MEMORY ONLY — NO DB, NO DISK
                with _replay_buffer_lock:
                    health_buffer.append(snapshot_with_ts)
                
            except Exception as e:
                logger.error(f"Error building status snapshot (non-fatal): {e}", exc_info=True)
                continue  # Skip this iteration if snapshot build fails
            
            # Check if any clients connected
            with _health_websocket_lock:
                if not _health_websocket_connections:
                    continue  # No clients, skip (but snapshot already stored for replay)
                connections_copy = set(_health_websocket_connections)  # Copy to avoid modification during iteration
            
            # Broadcast to all connected clients
            message = json.dumps(snapshot_with_ts)
            disconnected = set()
            for ws in connections_copy:
                try:
                    await ws.send_text(message)
                except Exception as e:
                    # Send failed → drop client
                    logger.debug(f"Health WebSocket send failed, dropping client: {e}")
                    disconnected.add(ws)
            
            # Clean up disconnected clients
            if disconnected:
                with _health_websocket_lock:
                    _health_websocket_connections -= disconnected
                    
        except Exception as e:
            # SAFETY: WebSocket failures must NOT affect engine
            logger.error(f"Error in health broadcast loop (non-fatal): {e}", exc_info=True)
            await asyncio.sleep(1.0)  # Continue after error


# PHASE 3: READ-ONLY OBSERVABILITY ENDPOINTS
# ============================================================================
# PHASE 1-2 — MOBILE STATE ENDPOINT (RORK SCHEMA)
# ============================================================================
# REGRESSION LOCK — OBSERVABILITY ONLY
# MOBILE READ-ONLY GUARANTEE
# PUSH IS ALERT-ONLY
# METRICS ARE OBSERVABILITY-ONLY
# LIVE CONTROL NOT ENABLED
# ============================================================================

@app.get("/mobile/state")
async def get_mobile_state():
    """
    PHASE 1-2 — RORK-SPECIFIC MOBILE SCHEMA ENDPOINT
    
    Returns mobile-optimized state in Rork schema format (v1).
    
    Endpoint: GET /mobile/state
    Purpose: Provide complete mobile state snapshot for Rork UI
    Schema: SentinelXMobileState (v1)
    
    Data includes:
    - engine: EngineStatus (mode, state, loop_tick, heartbeat_age, etc.)
    - broker: BrokerStatus (broker_type, connected, degraded)
    - strategies: StrategySummary[] (per-strategy PnL, win_rate, status)
    - portfolio: PortfolioSummary (equity, total_pnl, open_positions)
    - risk: RiskSnapshot (max_drawdown, current_drawdown)
    - system: SystemHealth (watchdog state)
    - timestamps: TimeInfo (server_time, server_time_iso)
    
    Rules:
    - Schema is read-only
    - Missing fields allowed (graceful degradation)
    - Versioned for backward compatibility
    - Defensive copying (immutable payloads)
    - No engine mutation
    - Safe defaults when unavailable
    
    SAFETY: Read-only, non-blocking, never raises
    """
    try:
        mobile_state = get_rork_mobile_state()
        return mobile_state
    except Exception as e:
        logger.error(f"Error getting mobile state (non-fatal): {e}", exc_info=True)
        # Return safe defaults on error
        from sentinel_x.api.rork_adapter import _get_safe_default_mobile_state
        return _get_safe_default_mobile_state()


@app.get("/health")
async def get_health():
    """
    PHASE 3: Canonical Sentinel X API health endpoint (read-only).
    
    MOBILE CONTRACT:
    - Returns engine status, loop tick, heartbeat age, broker type
    - Safe to call even when engine is not running (returns defaults)
    - No auth required (observability endpoint)
    - No execution triggers
    
    Expected schema:
    {
      "status": "RUNNING" | "STALE" | "FROZEN",
      "mode": "TRAINING" | "PAPER" | "RESEARCH" | "LIVE" | "PAUSED" | "KILLED",
      "loop_phase": "LOOP_START" | "STRATEGY_EVAL" | "ROUTING" | "BROKER_SUBMIT" | "IDLE",
      "loop_tick": int,
      "heartbeat_age": float (seconds),
      "loop_tick_age": float (seconds),
      "broker": "ALPACA_PAPER" | "PAPER" | "TRADOVATE" | "NONE",
      "watchdog": "OK" | "STALE" | "FROZEN",
      "timestamp": string (ISO format)
    }
    
    SAFETY: Uses get_health_snapshot() which never raises
    REGRESSION LOCK: Health endpoint is read-only
    """
    try:
        # PHASE 2: REST and WebSocket MUST call engine.get_status_snapshot()
        # Use engine's canonical status snapshot as source of truth
        if _engine and hasattr(_engine, 'get_status_snapshot'):
            try:
                snapshot = _engine.get_status_snapshot()
                
                # Transform engine snapshot to health endpoint format
                # Map engine_state to status, health to watchdog
                engine_status = snapshot.get("engine_state", "UNKNOWN")
                if engine_status == "RUNNING":
                    status = "RUNNING"
                    watchdog = "OK"
                elif engine_status == "STOPPED":
                    status = "FROZEN"
                    watchdog = "FROZEN"
                else:
                    status = "STALE"
                    watchdog = "STALE"
                
                # Use health field from snapshot if available
                health = snapshot.get("health", "GREEN")
                if health == "RED":
                    status = "FROZEN"
                    watchdog = "FROZEN"
                elif health == "YELLOW":
                    status = "STALE"
                    watchdog = "STALE"
                
                health_snapshot = {
                    "status": status,
                    "mode": snapshot.get("mode", "UNKNOWN"),
                    "loop_phase": snapshot.get("loop_phase", "UNKNOWN"),
                    "loop_tick": snapshot.get("loop_tick", 0),
                    "heartbeat_age": snapshot.get("heartbeat_age"),
                    "loop_tick_age": snapshot.get("loop_tick_age"),
                    "broker": snapshot.get("broker", "NONE"),
                    "watchdog": watchdog,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
                
                return health_snapshot
            except Exception as e:
                logger.debug(f"Error calling engine.get_status_snapshot() (falling back): {e}")
                # Fall through to fallback method
        
        # Fallback: Use get_health_snapshot() if engine method unavailable
        health_snapshot = get_health_snapshot()
        
        # Convert monotonic timestamp to ISO format for mobile
        import time as time_module
        from datetime import datetime
        
        # Add ISO timestamp (UTC) for mobile compatibility
        health_snapshot["timestamp"] = datetime.utcnow().isoformat() + "Z"
        
        return health_snapshot
    except Exception as e:
        logger.error(f"Error getting health (non-fatal): {e}", exc_info=True)
        # Return safe defaults on error
        import time as time_module
        from datetime import datetime
        return {
            "status": "FROZEN",
            "mode": "UNKNOWN",
            "loop_phase": "UNKNOWN",
            "loop_tick": 0,
            "heartbeat_age": 999.9,
            "loop_tick_age": 999.9,
            "broker": "NONE",
            "watchdog": "FROZEN",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/strategies")
async def get_strategies():
    """
    PHASE 3: Canonical Sentinel X API strategies endpoint (read-only).
    
    MOBILE CONTRACT:
    - Returns list of strategies with minimal performance metrics
    - Safe to call even when no strategies exist (returns empty list)
    - No auth required (observability endpoint)
    - No execution triggers
    
    Expected schema:
    [
      {
        "id": "strategy_name",
        "status": "ACTIVE" | "INACTIVE" | "DISABLED",
        "pnl": float (optional),
        "win_rate": float (optional, 0.0-1.0),
        "last_tick": int (loop_tick when strategy last executed)
      }
    ]
    """
    try:
        from sentinel_x.monitoring.heartbeat import read_heartbeat
        import time
        
        strategies_list = []
        
        # Get strategies from strategy manager
        if _strategy_manager:
            try:
                strategies = _strategy_manager.list_strategies()
                heartbeat = read_heartbeat()
                strategy_heartbeats = heartbeat.get('strategy_heartbeats', {}) if heartbeat else {}
                now_mono = time.monotonic()
                
                for strategy in strategies:
                    strategy_name = strategy.get('name', 'unknown')
                    strategy_status = strategy.get('status', 'INACTIVE')
                    
                    # Get last tick from heartbeat
                    last_tick = 0
                    if strategy_name in strategy_heartbeats:
                        strategy_data = strategy_heartbeats[strategy_name]
                        last_tick = strategy_data.get('tick_count', 0)
                    
                    # Get PnL (optional, may not be available)
                    pnl = strategy.get('realized_pnl') or strategy.get('pnl') or 0.0
                    
                    # Get win rate (optional, may not be available)
                    wins = strategy.get('wins', 0)
                    losses = strategy.get('losses', 0)
                    total_trades = wins + losses
                    win_rate = (wins / total_trades) if total_trades > 0 else None
                    
                    strategies_list.append({
                        "id": strategy_name,
                        "status": strategy_status.upper() if strategy_status else "INACTIVE",
                        "pnl": float(pnl) if pnl is not None else None,
                        "win_rate": round(win_rate, 2) if win_rate is not None else None,
                        "last_tick": last_tick
                    })
            except Exception as e:
                logger.debug(f"Error getting strategies from manager (non-fatal): {e}")
        
        return strategies_list
    except Exception as e:
        logger.error(f"Error getting strategies (non-fatal): {e}", exc_info=True)
        # Return empty list on error (safe default)
        return []


# ============================================================================
# PHASE 5: STATUS ENDPOINT (Using snapshot builder)
# ============================================================================

@app.get("/status")
async def get_status():
    """
    PHASE 3 — STATUS ENDPOINT (RORK UI CONTRACT)
    
    Get system status (read-only, no auth required).
    
    SINGLE SOURCE OF TRUTH for engine state.
    Uses build_status_snapshot() for side-effect free, thread-safe snapshot.
    
    SAFETY: This endpoint MUST always return HTTP 200.
    Missing engine fields must NEVER raise exceptions.
    
    SECURITY LOCKS:
    - NO POST endpoints (GET only)
    - MOBILE READ-ONLY GUARANTEE
    - NO execution hooks reachable
    - MUST NEVER return non-200
    
    Returns:
        Dict matching exact Rork UI contract schema (always HTTP 200)
    """
    try:
        snapshot = build_status_snapshot(_engine)
        return snapshot
    except Exception as e:
        # MUST NEVER return non-200
        logger.exception("Status failure")
        return {
            "engine_status": "UNKNOWN",
            "engine_mode": "UNKNOWN",
            "loop_tick": None,
            "loop_tick_age": None,
            "heartbeat_age": None,
            "loop_phase": "ERROR",
            "broker": "UNKNOWN",
            "uptime_seconds": None,
            "mobile_read_only": True,
            "trading_controls": "DISABLED",
            "degraded": True,
            "reason": str(e)
        }


# ============================================================================
# PHASE 8 — SECURE REMOTE PAUSE (FUTURE-PROOF)
# ============================================================================
# SAFETY: mobile pause disabled — LIVE prep only
# This endpoint is prepared for future use but currently disabled
# Always returns HTTP 403 Forbidden
# ============================================================================

@app.post("/pause_request")
async def pause_request():
    """
    PHASE 8 — SECURE REMOTE PAUSE (FUTURE-PROOF)
    
    Remote pause request endpoint (PREP ONLY — NO ENABLEMENT).
    
    SAFETY: mobile pause disabled — LIVE prep only
    
    REGRESSION LOCK — Rork API contract
    REGRESSION LOCK — monitoring only
    """
    # SAFETY: mobile pause disabled — LIVE prep only
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=403,
        content={"error": "Not enabled"}
    )


# ============================================================================
# PHASE 5: RORK CONTROL CONTRACT (LOCKED)
# ============================================================================
# 
# The ONLY valid Rork → Engine commands:
# 
# POST /engine/start → set mode = PAPER
# POST /engine/stop → set mode = TRAINING
# POST /engine/kill → immediate order cancel + PAPER→TRAINING
# GET /engine/status → returns: mode, uptime, equity, open_positions, 
#                      training_active (bool), paper_active (bool)
# 
# Buttons MUST NOT:
# • Start/stop threads
# • Call brokers
# • Touch execution directly
# 
# Rork is CONTROL ONLY.
# Engine is AUTHORITATIVE.
# 
# DO NOT CHANGE WITHOUT ARCHITECT REVIEW
# ============================================================================

# PHASE 7: MUTATION ENDPOINT - Requires API key auth (UI cannot access without auth)
@app.post("/engine/start", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(RATE_LIMIT_START_STOP)
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def engine_start(request: Request):
    """
    PHASE 5: Set EngineMode = PAPER (enable paper trading).
    
    RORK CONTROL CONTRACT:
    - Sets EngineMode = PAPER
    - Does NOT start/stop threads
    - Does NOT call brokers
    - Only changes execution permissions
    
    Idempotent: Setting PAPER when already PAPER = no-op + 200
    """
    return await control_start(request)


# PHASE 7: MUTATION ENDPOINT - Requires API key auth (UI cannot access without auth)
@app.post("/engine/stop", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(RATE_LIMIT_START_STOP)
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def engine_stop(request: Request):
    """
    PHASE 5: Set EngineMode = RESEARCH (return to training mode).
    
    RORK CONTROL CONTRACT:
    - Sets EngineMode = RESEARCH
    - Does NOT halt engine
    - Does NOT pause research
    - Returns to RESEARCH mode (training/backtesting permissions)
    
    Idempotent: Setting RESEARCH when already RESEARCH = no-op + 200
    """
    return await control_stop(request)


# PHASE 7: MUTATION ENDPOINT - Requires API key auth (UI cannot access without auth)
@app.post("/engine/kill", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def engine_kill(request: Request):
    """
    PHASE 5: Set EngineMode = KILLED and call emergency_kill().
    
    RORK CONTROL CONTRACT:
    - Sets EngineMode = KILLED
    - Cancels all orders immediately
    - Forces TRAINING mode
    - Cannot crash engine
    
    KILL bypasses operation lock (safety override).
    """
    return await control_kill(request)


@app.get("/engine/status")
async def engine_status():
    """
    PHASE 5: Get engine status with all required fields.
    
    Returns:
        mode: EngineMode (RESEARCH, PAPER, LIVE, PAUSED, KILLED)
        uptime: Engine uptime in seconds (monotonic)
        equity: Current equity (from account)
        open_positions: Count of open positions
        training_active: bool (True if mode == RESEARCH)
        paper_active: bool (True if mode == PAPER)
    """
    request_id = request_id_ctx.get()
    
    # Get EngineMode (authoritative)
    engine_mode = get_engine_mode()
    mode_value = engine_mode.value
    
    # Get uptime (monotonic, never decreases)
    uptime = get_monotonic_uptime()
    
    # Get equity
    equity = None
    if _order_router:
        account = _order_router.get_account()
        if account:
            equity = account.get('equity') or account.get('portfolio_value')
    
    # Get open positions count
    open_positions = 0
    if _order_router:
        positions = _order_router.get_positions()
        open_positions = len(positions) if positions else 0
    
    # Training/Paper active flags
    training_active = (engine_mode == EngineMode.RESEARCH)
    paper_active = (engine_mode == EngineMode.PAPER)
    
    logger.debug(
        f"ENGINE_STATUS | request_id={request_id} | "
        f"mode={mode_value} | uptime={uptime:.1f}s | "
        f"equity={equity} | positions={open_positions}"
    )
    
    return {
        "mode": mode_value,
        "uptime": uptime,
        "equity": equity,
        "open_positions": open_positions,
        "training_active": training_active,
        "paper_active": paper_active,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


# ============================================================================
# CONTROL ENDPOINTS (Auth required, rate limited, with timeouts)
# ============================================================================

# ============================================================================
# LEGACY ENDPOINTS (DEPRECATED - Redirect to control plane endpoints)
# ============================================================================

@app.post("/start", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(RATE_LIMIT_START_STOP)
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def start_engine_legacy(request: Request):
    """
    LEGACY ENDPOINT - Redirects to /control/start
    
    DEPRECATED: Use /control/start instead.
    This endpoint is kept for backwards compatibility but redirects to the control plane.
    """
    logger.warning("Legacy /start endpoint called - redirecting to /control/start")
    return await control_start(request)


@app.post("/stop", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(RATE_LIMIT_START_STOP)
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def stop_engine_legacy(request: Request):
    """
    LEGACY ENDPOINT - Redirects to /control/stop
    
    DEPRECATED: Use /control/stop instead.
    This endpoint is kept for backwards compatibility but redirects to the control plane.
    """
    logger.warning("Legacy /stop endpoint called - redirecting to /control/stop")
    return await control_stop(request)


@app.post("/kill", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def kill_switch_endpoint(request: Request):
    """
    Trigger kill switch immediately.
    
    SAFETY GUARANTEES:
    - KILL is NEVER rate limited (bypasses all rate limits)
    - KILL bypasses operation lock (does not wait)
    - KILL works even during engine exceptions
    - Irreversible without full process restart
    """
    request_id = request_id_ctx.get()
    client_ip = get_remote_address(request)
    state_before = get_state().value if _engine else "N/A"
    
    # SAFETY: Try to acquire lock but DO NOT block - KILL always proceeds
    lock_acquired = _operation_lock.acquire(blocking=False)
    if not lock_acquired:
        logger.warning(
            f"KILL_BYPASS_LOCK | request_id={request_id} | "
            f"client={client_ip} | reason=kill_overrides_lock"
        )
    
    try:
        logger.critical(
            f"KILL_TRIGGERED | request_id={request_id} | "
            f"client={client_ip} | state_before={state_before}"
        )
        
        # Create kill file - this is the authoritative kill mechanism
        kill_switch_obj = KillSwitch()
        kill_switch_obj.create_kill_file()
        
        # Set EngineMode to KILLED (engine loop will detect and exit)
        set_engine_mode(EngineMode.KILLED, reason="kill endpoint")
        
        # Engine loop will detect KILLED mode and exit safely
        state_after = get_state().value if _engine else "STOPPED"
        
        logger.critical(
            f"KILL_OK | request_id={request_id} | "
            f"client={client_ip} | state_before={state_before} | state_after={state_after} | "
            f"message=system_shutting_down"
        )
        
        # PHASE 3: Audit log
        log_audit_event("KILL", request_id, metadata={"state_before": state_before, "state_after": state_after})
        
        # PHASE 4: Push notification (fire-and-forget)
        safe_emit(send_kill_notification(request_id))
        
        return ActionResponse(ok=True, message="Kill switch activated. Engine shutting down.")
    
    except Exception as e:
        # SAFETY: Even on error, try to create kill file
        logger.critical(
            f"KILL_ERROR | request_id={request_id} | "
            f"client={client_ip} | error={str(e)} | "
            f"attempting_fallback_kill",
            exc_info=True
        )
        try:
            KillSwitch().create_kill_file()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Kill switch error (file may still be created): {str(e)}")
    finally:
        if lock_acquired:
            _operation_lock.release()


# ============================================================================
# PHASE 5: DASHBOARD ENDPOINTS (Read-only, no auth required)
# ============================================================================

@app.get("/dashboard/heartbeat")
async def get_dashboard_heartbeat():
    """
    Get heartbeat data for dashboard.
    
    Returns last-known heartbeat timestamp and engine state.
    Safe when engine is not running (returns defaults).
    """
    try:
        state, mode = derive_engine_state()
        uptime = get_monotonic_uptime()
        heartbeat_ts = None
        
        # SAFETY: Guarded access to prevent AttributeError
        try:
            hb_ts = getattr(_engine, "last_heartbeat_ts", None) if _engine else None
            heartbeat_age = (time.time() - hb_ts) if hb_ts else None
            # Note: last_heartbeat_ts is monotonic time, not epoch time
            # Cannot convert to datetime directly - leave as None for safety
        except Exception:
            # SAFETY: Never crash - gracefully degrade
            hb_ts = None
            heartbeat_age = None
        
        return {
            "state": state,
            "mode": mode,
            "uptime": uptime,
            "heartbeat_ts": heartbeat_ts,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting dashboard heartbeat: {e}", exc_info=True)
        # Return safe defaults - never crash
        return {
            "state": "STOPPED",
            "mode": "UNKNOWN",
            "uptime": 0.0,
            "heartbeat_ts": None,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/dashboard/equity")
async def get_dashboard_equity(limit: int = 500):
    """
    Get equity curve data for dashboard.
    
    Returns equity snapshots from metrics store (historical).
    Safe when DB is empty or metrics store unavailable.
    
    Args:
        limit: Maximum number of snapshots to return (default: 500)
    """
    try:
        from sentinel_x.monitoring.metrics_store import get_metrics_store
        
        metrics_store = get_metrics_store()
        conn = sqlite3.connect(metrics_store.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT timestamp, equity, benchmark_equity, drawdown, max_drawdown, 
                   cumulative_return, benchmark_return, relative_alpha
            FROM equity_snapshots
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        snapshots = [
            {
                "timestamp": row['timestamp'],
                "equity": row['equity'],
                "benchmark_equity": row['benchmark_equity'],
                "drawdown": row['drawdown'],
                "max_drawdown": row['max_drawdown'],
                "cumulative_return": row['cumulative_return'],
                "benchmark_return": row['benchmark_return'],
                "relative_alpha": row['relative_alpha']
            }
            for row in rows
        ]
        
        return {
            "snapshots": snapshots,
            "count": len(snapshots),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting dashboard equity: {e}", exc_info=True)
        # Return safe defaults - never crash
        return {
            "snapshots": [],
            "count": 0,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/dashboard/pnl")
async def get_dashboard_pnl():
    """
    Get PnL data for dashboard.
    
    Returns realized, unrealized, and total PnL by strategy.
    Safe when PnL engine is not initialized.
    """
    try:
        from sentinel_x.monitoring.pnl import get_pnl_engine
        
        pnl_engine = get_pnl_engine()
        if pnl_engine:
            metrics = pnl_engine.get_all_metrics()
            return {
                "total_realized": metrics.get('total_realized', 0.0),
                "total_unrealized": metrics.get('total_unrealized', 0.0),
                "total_pnl": metrics.get('total_pnl', 0.0),
                "by_strategy": metrics.get('by_strategy', {}),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        else:
            return {
                "total_realized": 0.0,
                "total_unrealized": 0.0,
                "total_pnl": 0.0,
                "by_strategy": {},
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
    except Exception as e:
        logger.error(f"Error getting dashboard PnL: {e}", exc_info=True)
        # Return safe defaults - never crash
        return {
            "total_realized": 0.0,
            "total_unrealized": 0.0,
            "total_pnl": 0.0,
            "by_strategy": {},
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/dashboard/strategies")
async def get_dashboard_strategies(sort_by: str = "composite_score"):
    """
    PHASE 5: Get strategy data for dashboard (read-only).
    
    SAFETY: dashboard is read-only
    SAFETY: no execution dependency
    REGRESSION LOCK — OBSERVABILITY ONLY
    
    Returns strategy list with rankings and performance.
    Safe when strategy manager is not initialized.
    
    Args:
        sort_by: Sort key ("composite_score", "realized_pnl", "sharpe", "drawdown")
    
    Returns:
        Dict with strategies list, count, and timestamp
    """
    try:
        from sentinel_x.monitoring.dashboard import get_strategy_dashboard
        
        dashboard = get_strategy_dashboard()
        performances = dashboard.get_all_strategies_performance()
        
        # Sort by requested metric (display only - no control)
        if sort_by == "composite_score":
            performances.sort(key=lambda x: -x.composite_score)
        elif sort_by == "realized_pnl":
            performances.sort(key=lambda x: -x.realized_pnl)
        elif sort_by == "sharpe":
            performances.sort(key=lambda x: -(x.sharpe if x.sharpe is not None else -999))
        elif sort_by == "drawdown":
            performances.sort(key=lambda x: x.max_drawdown)
        else:
            performances.sort(key=lambda x: -x.composite_score)
        
        strategy_views = [
            {
                "name": p.strategy_name,
                "lifecycle_state": p.lifecycle_state,
                "status": p.status,
                "composite_score": p.composite_score,
                "trades_count": p.trades_count,
                "win_rate": p.win_rate,
                "expectancy": p.expectancy,
                "sharpe": p.sharpe,
                "max_drawdown": p.max_drawdown,
                "realized_pnl": p.realized_pnl,
                "unrealized_pnl": p.unrealized_pnl,
                "total_pnl": p.total_pnl,
                "capital_weight": p.capital_weight,
                "ranking": p.ranking,
                "last_trade_time": p.last_trade_time.isoformat() if p.last_trade_time else None,
                "last_heartbeat": p.last_heartbeat.isoformat() if p.last_heartbeat else None,
                "consecutive_losses": p.consecutive_losses,
                "promotion_eligible": p.promotion_eligible,
                "demotion_evaluation": p.demotion_evaluation,
                "last_disable_reason": p.last_disable_reason
            }
            for p in performances
        ]
        
        return {
            "strategies": strategy_views,
            "count": len(strategy_views),
            "sort_by": sort_by,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting dashboard strategies: {e}", exc_info=True)
        # Return safe defaults - never crash
        return {
            "strategies": [],
            "count": 0,
            "sort_by": sort_by,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "error": str(e)
        }


@app.get("/dashboard/alerts")
async def get_dashboard_alerts(limit: int = 100):
    """
    Get alerts for dashboard.
    
    Returns recent alerts from metrics store.
    Safe when DB is empty or metrics store unavailable.
    
    Args:
        limit: Maximum number of alerts to return (default: 100)
    """
    try:
        from sentinel_x.monitoring.metrics_store import get_metrics_store
        
        metrics_store = get_metrics_store()
        conn = sqlite3.connect(metrics_store.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT alert_type, severity, message, strategy, broker, mode, 
                   metadata_json, timestamp
            FROM alerts
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        alerts = []
        for row in rows:
            metadata = {}
            if row['metadata_json']:
                try:
                    metadata = json.loads(row['metadata_json'])
                except Exception:
                    pass
            
            alerts.append({
                "alert_type": row['alert_type'],
                "severity": row['severity'],
                "message": row['message'],
                "strategy": row['strategy'],
                "broker": row['broker'],
                "mode": row['mode'],
                "metadata": metadata,
                "timestamp": row['timestamp']
            })
        
        return {
            "alerts": alerts,
            "count": len(alerts),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting dashboard alerts: {e}", exc_info=True)
        # Return safe defaults - never crash
        return {
            "alerts": [],
            "count": 0,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/health/ui", response_model=UIHealthResponse)
async def get_ui_health():
    """
    PHASE 7: Comprehensive read-only UI health and observability endpoint.
    
    UI IS OBSERVER ONLY - This endpoint exposes all read-only health data:
    - engine_mode: Current engine mode
    - broker_connected: True/false broker connection status
    - broker_type: ALPACA_PAPER / TRADOVATE / PAPER / NONE
    - last_execution_status: Status of last order execution (if any)
    - last_error: Last error message from engine (if any)
    
    UI RESTRICTIONS:
    - UI must NEVER execute trades (all trade endpoints require API key auth)
    - UI must NEVER arm brokers (no arming endpoints exist)
    - UI must NEVER mutate engine state (only EngineMode changes via /control/* endpoints)
    
    ASSERTION:
    - UI failure cannot affect engine (engine has zero dependencies on UI state)
    - All endpoints return safe defaults on error (never crash)
    """
    try:
        from sentinel_x.core.engine_mode import get_engine_mode, get_engine_mode_manager
        
        # Get current engine mode
        current_mode = get_engine_mode()
        engine_mode_str = current_mode.value
        
        # Get last error from engine mode manager
        mode_manager = get_engine_mode_manager()
        last_error = mode_manager.get_last_error()
        
        # Get broker information
        broker_connected = False
        broker_type = "NONE"
        
        engine = get_engine()
        if engine and engine.order_router:
            router = engine.order_router
            
            # Check active executor
            if router.active_executor:
                executor_name = getattr(router.active_executor, 'name', 'unknown')
                # Normalize broker type names
                if executor_name == "alpaca":
                    broker_type = "ALPACA_PAPER"
                elif executor_name == "tradovate":
                    broker_type = "TRADOVATE"
                elif executor_name == "paper":
                    broker_type = "PAPER"
                else:
                    broker_type = executor_name.upper()
                
                # Check if connected
                if hasattr(router.active_executor, 'connected'):
                    broker_connected = router.active_executor.connected
                elif hasattr(router.active_executor, 'health_check'):
                    try:
                        health = router.active_executor.health_check()
                        broker_connected = health.get('connected', False)
                    except Exception:
                        broker_connected = False
            else:
                # Check if any executor is registered but not active
                if router.alpaca_executor:
                    broker_type = "ALPACA_PAPER"
                    broker_connected = getattr(router.alpaca_executor, 'connected', False)
                elif router.paper_executor:
                    broker_type = "PAPER"
                    broker_connected = True  # Paper executor is always "connected"
        
        # Get last execution status from execution metrics tracker
        last_execution_status = None
        try:
            from sentinel_x.execution.execution_metrics import get_execution_metrics_tracker
            tracker = get_execution_metrics_tracker()
            
            # Get the most recent execution record from any strategy
            if hasattr(tracker, 'execution_records') and tracker.execution_records:
                # Find the most recent execution record across all strategies
                most_recent_record = None
                most_recent_time = None
                
                for strategy_name, records in tracker.execution_records.items():
                    if records:
                        latest = records[-1]  # Last record in deque
                        if latest.submitted_at:
                            if most_recent_time is None or latest.submitted_at > most_recent_time:
                                most_recent_time = latest.submitted_at
                                most_recent_record = latest
                        elif latest.created_at:
                            if most_recent_time is None or latest.created_at > most_recent_time:
                                most_recent_time = latest.created_at
                                most_recent_record = latest
                
                if most_recent_record:
                    last_execution_status = most_recent_record.status.value
        except Exception as e:
            logger.debug(f"Error getting last execution status (non-fatal): {e}")
        
        return UIHealthResponse(
            engine_mode=engine_mode_str,
            broker_connected=broker_connected,
            broker_type=broker_type,
            last_execution_status=last_execution_status,
            last_error=last_error
        )
        
    except Exception as e:
        logger.error(f"Error getting UI health: {e}", exc_info=True)
        # Return safe defaults - never crash
        return UIHealthResponse(
            engine_mode="UNKNOWN",
            broker_connected=False,
            broker_type="NONE",
            last_execution_status=None,
            last_error=str(e) if e else None
        )


@app.get("/health/broker", response_model=BrokerHealthResponse)
async def get_broker_health():
    """
    Get read-only broker health surface for UI observation.
    
    REGRESSION LOCK:
    - UI must never trigger execution
    - UI must never arm LIVE
    - UI is observer-only
    
    This endpoint provides safe, read-only broker status information
    without any execution or arming capabilities.
    
    Returns:
        BrokerHealthResponse with broker connection status, name, engine mode, and training status
    """
    try:
        from sentinel_x.core.engine_mode import get_engine_mode
        
        # Get current engine mode
        current_mode = get_engine_mode()
        engine_mode_str = current_mode.value
        
        # Determine training_active flag
        training_active = current_mode in (EngineMode.TRAINING, EngineMode.PAPER)
        
        # Get broker information from router
        broker_connected = False
        broker_name = "none"
        
        engine = get_engine()
        if engine and engine.order_router:
            router = engine.order_router
            
            # Check active executor
            if router.active_executor:
                broker_name = getattr(router.active_executor, 'name', 'unknown')
                # Check if connected
                if hasattr(router.active_executor, 'connected'):
                    broker_connected = router.active_executor.connected
                elif hasattr(router.active_executor, 'health_check'):
                    try:
                        health = router.active_executor.health_check()
                        broker_connected = health.get('connected', False)
                    except Exception:
                        broker_connected = False
            else:
                # Check if any executor is registered
                if router.alpaca_executor:
                    broker_name = "alpaca"
                    broker_connected = getattr(router.alpaca_executor, 'connected', False)
                elif router.paper_executor:
                    broker_name = "paper"
                    broker_connected = True  # Paper executor is always "connected"
        
        return BrokerHealthResponse(
            broker_connected=broker_connected,
            broker_name=broker_name,
            engine_mode=engine_mode_str,
            training_active=training_active
        )
        
    except Exception as e:
        logger.error(f"Error getting broker health: {e}", exc_info=True)
        # Return safe defaults - never crash
        return BrokerHealthResponse(
            broker_connected=False,
            broker_name="unknown",
            engine_mode="UNKNOWN",
            training_active=False
        )


@app.get("/health/brokers")
async def broker_health():
    """
    Get broker connectivity health status (read-only).
    
    PHASE 4: UI Health Visibility - exposes broker status without execution capability.
    
    RULES:
    - UI must not mutate state
    - UI must not trigger execution
    - UI must not expose credentials
    - Health checks must NEVER raise exceptions
    
    Returns:
        Dictionary mapping mode to health status:
        {
            "PAPER": {
                "connected": True,
                "broker": "alpaca_paper",
                "mode_bound": "PAPER",
                "live_locked": True
            },
            ...
        }
    """
    try:
        engine = get_engine()
        if not engine:
            return {"status": "no_engine"}
        
        router = engine.order_router
        if not router:
            return {"status": "no_router"}
        
        # Get executor health from router
        health = router.get_executor_health()
        
        # Get current engine mode (normalized)
        from sentinel_x.core.engine_mode import get_engine_mode
        current_mode = get_engine_mode()
        
        # Get armed brokers list
        armed_brokers = getattr(router, '_armed_brokers', [])
        
        # Build connected status dict
        connected = {}
        for mode_str, status in health.items():
            broker_name = status.get('broker', 'unknown').replace('_paper', '').replace('_simulated', '')
            connected[broker_name] = status.get('connected', False)
        
        # Determine training and live brokers
        training_broker = "alpaca" if "alpaca" in armed_brokers else None
        live_broker = "tradovate"  # Tradovate is LIVE-only broker
        
        # Check if LIVE is unlocked (requires multiple env vars)
        import os
        live_unlock = os.getenv("SENTINEL_LIVE_UNLOCK", "").lower() == "true"
        live_confirm = os.getenv("SENTINEL_LIVE_CONFIRM", "") == "YES_I_UNDERSTAND"
        tradovate_account_id = os.getenv("SENTINEL_TRADOVATE_ACCOUNT_ID", "")
        live_locked = not (live_unlock and live_confirm and tradovate_account_id)
        
        return {
            "engine_mode": current_mode.value,
            "training_broker": training_broker,
            "live_broker": live_broker,
            "connected": connected,
            "live_locked": live_locked
        }
        
    except Exception as e:
        logger.error(f"Error getting broker health: {e}", exc_info=True)
        # Return safe defaults - never crash
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/dashboard/brokers")
async def get_dashboard_brokers():
    """
    Get broker state data for dashboard.
    
    Returns broker snapshots with equity, cash, positions.
    Safe when order router is not initialized.
    """
    try:
        if not _order_router:
            return {
                "brokers": [],
                "count": 0,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        
        brokers = []
        
        # Get account info
        account = _order_router.get_account()
        if account:
            brokers.append({
                "broker": account.get('broker', 'unknown'),
                "mode": account.get('mode', 'PAPER'),
                "equity": account.get('equity') or account.get('portfolio_value'),
                "cash": account.get('cash') or account.get('buying_power'),
                "positions_count": len(_order_router.get_positions() or []),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
        
        return {
            "brokers": brokers,
            "count": len(brokers),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting dashboard brokers: {e}", exc_info=True)
        # Return safe defaults - never crash
        return {
            "brokers": [],
            "count": 0,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


# ============================================================================
# READ-ONLY ENDPOINTS (No auth required)
# ============================================================================

@app.get("/strategies", response_model=StrategiesResponse)
async def get_strategies():
    """List all strategies with status and scores (read-only)."""
    if not _strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    try:
        strategies_list = _strategy_manager.list_strategies()
        strategy_views = [
            StrategyView(
                name=s['name'],
                status=s['status'],
                lifecycle_state=s.get('lifecycle_state', 'TRAINING'),
                score=s.get('score'),
                capital_weight=s.get('capital_weight'),
                ranking=s.get('ranking'),
                last_disable_reason=s.get('last_disable_reason'),
                promotion_eligible=s.get('promotion_eligible'),
                demotion_evaluation=s.get('demotion_evaluation')
            )
            for s in strategies_list
        ]
        return StrategiesResponse(strategies=strategy_views, count=len(strategy_views))
    except Exception as e:
        logger.error(f"API: Error getting strategies: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get strategies: {str(e)}")


@app.get("/metrics")
async def get_metrics():
    """
    PHASE 3: Canonical Sentinel X API metrics endpoint (read-only).
    
    MOBILE CONTRACT:
    - Returns aggregated live metrics (equity, PnL, uptime)
    - Safe to call even when no data available (returns defaults)
    - No auth required (observability endpoint)
    - No execution triggers
    
    Expected schema:
    {
      "equity": float | null,
      "daily_pnl": float,
      "uptime_seconds": float
    }
    """
    try:
        # Get equity (from account)
        equity = None
        daily_pnl = 0.0
        
        if _order_router:
            try:
                account = _order_router.get_account()
                if account:
                    equity = account.get('equity') or account.get('portfolio_value')
                    
                    # Calculate daily PnL (simplified - would need daily tracking for accurate)
                    # For now, use unrealized PnL from positions
                    positions = _order_router.get_positions()
                    if positions:
                        daily_pnl = sum(p.get('unrealized_pnl', 0.0) for p in positions)
            except Exception as e:
                logger.debug(f"Error getting account/positions for metrics (non-fatal): {e}")
        
        # Get uptime (monotonic)
        uptime_seconds = get_monotonic_uptime()
        
        return {
            "equity": float(equity) if equity is not None else None,
            "daily_pnl": round(float(daily_pnl), 2),
            "uptime_seconds": round(uptime_seconds, 1),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting metrics (non-fatal): {e}", exc_info=True)
        # Return safe defaults on error
        return {
            "equity": None,
            "daily_pnl": 0.0,
            "uptime_seconds": 0.0,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/risk")
async def get_risk():
    """
    PHASE 3: Canonical Sentinel X API risk endpoint (read-only).
    
    MOBILE CONTRACT:
    - Returns risk limits (display only)
    - No auth required (observability endpoint)
    - No execution triggers
    
    Expected schema:
    {
      "max_drawdown": "server_managed" | float,
      "max_daily_loss": "server_managed" | float,
      "risk_state": "NORMAL" | "WARNING" | "CRITICAL"
    }
    """
    try:
        # Risk limits are server-managed (no mobile control)
        # SAFETY: Mobile is read-only, never exposes actual limits
        
        risk_state = "NORMAL"  # Default to normal
        
        # Check if any warnings exist (optional)
        try:
            from sentinel_x.intelligence.governance import get_governance
            governance = get_governance()
            if governance.has_violations():
                risk_state = "WARNING"
        except Exception:
            pass  # Governance check is optional
        
        return {
            "max_drawdown": "server_managed",
            "max_daily_loss": "server_managed",
            "risk_state": risk_state,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting risk (non-fatal): {e}", exc_info=True)
        # Return safe defaults on error
        return {
            "max_drawdown": "server_managed",
            "max_daily_loss": "server_managed",
            "risk_state": "NORMAL",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/funding")
async def get_funding():
    """
    PHASE 3: Canonical Sentinel X API funding endpoint (read-only).
    
    MOBILE CONTRACT:
    - Returns funding information (read-only)
    - Displays current equity
    - Can submit funding requests (server-validated, future phase)
    - No auth required for read-only view
    - No execution triggers
    
    Expected schema:
    {
      "current_equity": float | null,
      "can_add_funds": bool,
      "can_withdraw": bool,
      "cooldown_active": bool
    }
    """
    try:
        # Get current equity (from account)
        current_equity = None
        
        if _order_router:
            try:
                account = _order_router.get_account()
                if account:
                    current_equity = account.get('equity') or account.get('portfolio_value')
            except Exception as e:
                logger.debug(f"Error getting account for funding (non-fatal): {e}")
        
        # PHASE 2: Funding capabilities (read-only for now)
        # Funding actions require server-side validation (future phase)
        can_add_funds = True  # Always allowed (server validates)
        can_withdraw = True   # Always allowed (server validates)
        cooldown_active = False  # No cooldown for now (future phase)
        
        return {
            "current_equity": float(current_equity) if current_equity is not None else None,
            "can_add_funds": can_add_funds,
            "can_withdraw": can_withdraw,
            "cooldown_active": cooldown_active,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting funding (non-fatal): {e}", exc_info=True)
        # Return safe defaults on error
        return {
            "current_equity": None,
            "can_add_funds": False,
            "can_withdraw": False,
            "cooldown_active": False,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/account")
async def get_account():
    """Get account information (read-only)."""
    if not _order_router:
        raise HTTPException(status_code=503, detail="Order router not initialized")
    
    try:
        account = _order_router.get_account()
        if not account:
            return {"error": "Account information not available"}
        return account
    except Exception as e:
        logger.error(f"API: Error getting account: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get account: {str(e)}")


@app.get("/positions", response_model=PositionsResponse)
async def get_positions():
    """Get current trading positions (read-only)."""
    if not _order_router:
        raise HTTPException(status_code=503, detail="Order router not initialized")
    
    try:
        positions_list = _order_router.get_positions()
        position_views = [
            PositionView(
                symbol=p['symbol'],
                qty=p['qty'],
                avg_price=p['avg_price'],
                current_price=p.get('current_price'),
                unrealized_pnl=p.get('unrealized_pnl', 0.0),
                entry_time=p.get('entry_time') or datetime.now()
            )
            for p in positions_list
        ]
        total_pnl = sum(p.get('unrealized_pnl', 0.0) for p in positions_list)
        return PositionsResponse(positions=position_views, count=len(position_views), total_pnl=total_pnl)
    except Exception as e:
        logger.error(f"API: Error getting positions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get positions: {str(e)}")




# Strategy-based test order trigger endpoint
# PHASE 7: MUTATION ENDPOINT - Requires API key auth (UI cannot access without auth)
@app.post("/test-order", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def fire_test_order():
    """
    PHASE 7: MUTATION ENDPOINT - UI FORBIDDEN
    
    Arm TestStrategy to fire exactly once on next trading tick.
    Used for integration testing only.
    
    SECURITY: Requires API key authentication - UI cannot access without auth.
    UI must use read-only health endpoints (/health/ui, /status).
    """
    request_id = request_id_ctx.get()
    
    if not _strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")

    try:
        _strategy_manager.activate_only("TestStrategy")
        logger.info(f"TEST_STRATEGY_ARMED | request_id={request_id} | strategy=TestStrategy")
        
        # Emit event
        event_bus = get_event_bus()
        await event_bus.publish({
            "type": "control",
            "action": "test_order_armed",
            "strategy": "TestStrategy",
        })
        
        return {
            "status": "ok",
            "message": "TestStrategy armed (fires once)"
        }
    except Exception as e:
        logger.error(f"Failed to arm TestStrategy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PHASE 5: Control API Endpoints
# ============================================================================

@app.post("/control/start", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(RATE_LIMIT_START_STOP)
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def control_start(request: Request):
    """
    Set EngineMode = PAPER (enable paper trading).
    
    CONTROL PLANE RULE: This endpoint NEVER starts or stops the engine.
    It ONLY changes execution permissions via EngineMode.
    
    Behavior:
    - Sets EngineMode = PAPER
    - Does NOT boot engine
    - Does NOT spawn threads
    - Only enables paper execution permissions
    
    Idempotent: Setting PAPER when already PAPER = no-op + 200
    """
    request_id = request_id_ctx.get()
    client_ip = get_remote_address(request)
    
    if not _engine:
        logger.error(
            f"CONTROL_START_FAIL | request_id={request_id} | "
            f"client={client_ip} | reason=engine_not_initialized"
        )
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    # Prevent concurrent operations
    if not _operation_lock.acquire(blocking=False):
        logger.warning(
            f"CONTROL_START_BLOCKED | request_id={request_id} | "
            f"client={client_ip} | reason=concurrent_operation"
        )
        return ActionResponse(ok=False, message="Another operation is in progress. Please wait.")
    
    try:
        current_mode = get_engine_mode()
        
        # SAFETY: Kill switch always wins - cannot change mode if killed
        if is_killed():
            logger.warning(
                f"CONTROL_START_REJECTED | request_id={request_id} | "
                f"client={client_ip} | reason=kill_switch_active"
            )
            return ActionResponse(ok=False, message="Cannot change mode: Kill switch is active")
        
        # IDEMPOTENCY: Already in PAPER mode = no-op
        if current_mode == EngineMode.PAPER:
            logger.info(
                f"CONTROL_START_NOOP | request_id={request_id} | "
                f"client={client_ip} | reason=already_paper_mode"
            )
            return ActionResponse(ok=True, message="Engine already in PAPER mode")
        
        # Set EngineMode to PAPER
        logger.info(
            f"CONTROL_START_EXEC | request_id={request_id} | "
            f"client={client_ip} | mode_before={current_mode.value}"
        )
        set_engine_mode(EngineMode.PAPER, reason="control_start endpoint")
        mode_after = get_engine_mode()
        
        # Update executor to reflect mode change
        if _order_router:
            _order_router.config.trade_mode = "PAPER"
            _order_router.update_executor()
        
        logger.info(
            f"CONTROL_START_OK | request_id={request_id} | "
            f"client={client_ip} | mode_before={current_mode.value} | mode_after={mode_after.value}"
        )
        log_audit_event("CONTROL_START", request_id, metadata={"mode_before": current_mode.value, "mode_after": mode_after.value})
        return ActionResponse(ok=True, message="EngineMode set to PAPER (paper trading enabled)")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"CONTROL_START_ERROR | request_id={request_id} | "
            f"client={client_ip} | error={str(e)}",
            exc_info=True
        )
        get_engine_mode_manager().set_last_error(str(e))
        raise HTTPException(status_code=500, detail=f"Failed to set EngineMode: {str(e)}")
    finally:
        _operation_lock.release()


@app.post("/control/stop", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(RATE_LIMIT_START_STOP)
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def control_stop(request: Request):
    """
    PHASE 1: STOP action - cancels orders and transitions to TRAINING.
    
    Behavior:
    - Cancels all open orders immediately
    - Transitions engine to TRAINING mode (RESEARCH)
    - Does NOT shut down event loop
    - Engine continues running in TRAINING mode
    
    Idempotent: Setting RESEARCH when already RESEARCH = no-op + 200
    """
    request_id = request_id_ctx.get()
    client_ip = get_remote_address(request)
    
    if not _engine:
        logger.error(
            f"CONTROL_STOP_FAIL | request_id={request_id} | "
            f"client={client_ip} | reason=engine_not_initialized"
        )
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    # Prevent concurrent operations
    if not _operation_lock.acquire(blocking=False):
        logger.warning(
            f"CONTROL_STOP_BLOCKED | request_id={request_id} | "
            f"client={client_ip} | reason=concurrent_operation"
        )
        return ActionResponse(ok=False, message="Another operation is in progress. Please wait.")
    
    try:
        current_mode = get_engine_mode()
        
        # SAFETY: Kill switch always wins - cannot change mode if killed
        if is_killed():
            logger.warning(
                f"CONTROL_STOP_REJECTED | request_id={request_id} | "
                f"client={client_ip} | reason=kill_switch_active"
            )
            return ActionResponse(ok=False, message="Cannot change mode: Kill switch is active")
        
        # IDEMPOTENCY: Already in RESEARCH mode = no-op
        if current_mode == EngineMode.RESEARCH:
            logger.info(
                f"CONTROL_STOP_NOOP | request_id={request_id} | "
                f"client={client_ip} | reason=already_research_mode"
            )
            return ActionResponse(ok=True, message="Engine already in TRAINING mode")
        
        # PHASE 1: Cancel all open orders before transitioning
        canceled_count = 0
        try:
            if _order_router:
                canceled_count = _order_router.cancel_all_orders()
                if canceled_count > 0:
                    logger.info(f"Canceled {canceled_count} orders on STOP")
        except Exception as e:
            logger.error(f"Error canceling orders on STOP: {e}", exc_info=True)
            # Continue - order cancellation failure doesn't block mode transition
        
        # Set EngineMode to RESEARCH (TRAINING mode)
        logger.info(
            f"CONTROL_STOP_EXEC | request_id={request_id} | "
            f"client={client_ip} | mode_before={current_mode.value} | canceled_orders={canceled_count}"
        )
        set_engine_mode(EngineMode.RESEARCH, reason="control_stop endpoint")
        mode_after = get_engine_mode()
        
        logger.info(
            f"CONTROL_STOP_OK | request_id={request_id} | "
            f"client={client_ip} | mode_before={current_mode.value} | mode_after={mode_after.value}"
        )
        log_audit_event("CONTROL_STOP", request_id, metadata={
            "mode_before": current_mode.value, 
            "mode_after": mode_after.value,
            "canceled_orders": canceled_count
        })
        return ActionResponse(ok=True, message=f"EngineMode set to TRAINING (canceled {canceled_count} orders)")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"CONTROL_STOP_ERROR | request_id={request_id} | "
            f"client={client_ip} | error={str(e)}",
            exc_info=True
        )
        get_engine_mode_manager().set_last_error(str(e))
        raise HTTPException(status_code=500, detail=f"Failed to set EngineMode: {str(e)}")
    finally:
        _operation_lock.release()


@app.post("/control/kill", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def control_kill(request: Request):
    """
    PHASE 1: EMERGENCY_KILL - stops all executions immediately.
    
    Behavior:
    - Stops all executions immediately
    - Cancels all open orders
    - Transitions engine to TRAINING mode (not KILLED)
    - Engine loop continues in TRAINING mode
    - Cannot crash engine
    
    KILL SWITCH RULE: Stops executions but training loop remains alive.
    KILL bypasses operation lock (safety override).
    """
    request_id = request_id_ctx.get()
    client_ip = get_remote_address(request)
    
    if not _engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    # SAFETY: Try to acquire lock but DO NOT block - KILL always proceeds
    lock_acquired = _operation_lock.acquire(blocking=False)
    if not lock_acquired:
        logger.warning(
            f"CONTROL_KILL_BYPASS_LOCK | request_id={request_id} | "
            f"client={client_ip} | reason=kill_overrides_lock"
        )
    
    try:
        current_mode = get_engine_mode()
        
        logger.critical(
            f"CONTROL_KILL_TRIGGERED | request_id={request_id} | "
            f"client={client_ip} | mode_before={current_mode.value}"
        )
        
        # PHASE 1: Cancel all orders immediately
        canceled_count = 0
        try:
            if _order_router:
                canceled_count = _order_router.cancel_all_orders()
                if canceled_count > 0:
                    logger.info(f"Canceled {canceled_count} orders on EMERGENCY_KILL")
        except Exception as e:
            logger.error(f"Error canceling orders on KILL: {e}", exc_info=True)
            # Continue - order cancellation failure doesn't block kill
        
        # PHASE 1: Set EngineMode to TRAINING (not KILLED) - loop continues
        # KILL stops execution but training continues
        set_engine_mode(EngineMode.RESEARCH, reason="control_kill endpoint - emergency stop")
        
        # Call emergency_kill() - this also sets mode to TRAINING
        if _engine:
            _engine.emergency_kill()
        
        mode_after = get_engine_mode()
        
        logger.critical(
            f"CONTROL_KILL_OK | request_id={request_id} | "
            f"client={client_ip} | mode_before={current_mode.value} | mode_after={mode_after.value} | "
            f"canceled_orders={canceled_count} | message=executions_stopped_training_continues"
        )
        
        log_audit_event("CONTROL_KILL", request_id, metadata={
            "mode_before": current_mode.value, 
            "mode_after": mode_after.value,
            "canceled_orders": canceled_count
        })
        
        # Emit event
        event_bus = get_event_bus()
        safe_emit(event_bus.publish({
            "type": "control",
            "action": "kill",
        }))
        
        # Push notification (fire-and-forget)
        safe_emit(send_kill_notification(request_id))
        
        return ActionResponse(ok=True, message=f"Emergency kill activated. Executions stopped, engine continues in TRAINING mode (canceled {canceled_count} orders).")
    
    except Exception as e:
        # SAFETY: Even on error, try to create kill file and set mode
        logger.critical(
            f"CONTROL_KILL_ERROR | request_id={request_id} | "
            f"client={client_ip} | error={str(e)} | "
            f"attempting_fallback_kill",
            exc_info=True
        )
        try:
            set_engine_mode(EngineMode.KILLED, reason="emergency_fallback")
            KillSwitch().create_kill_file()
        except Exception:
            pass
        get_engine_mode_manager().set_last_error(str(e))
        raise HTTPException(status_code=500, detail=f"Kill switch error (mode/file may still be set): {str(e)}")
    finally:
        if lock_acquired:
            _operation_lock.release()


@app.post("/control/mode", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def control_mode(request: Request):
    """
    Set engine mode (RESEARCH/PAPER/LIVE/PAUSED).
    
    PHASE 2: Uses set_mode() - authoritative mode change.
    """
    request_id = request_id_ctx.get()
    
    try:
        body = await request.json()
        mode_str = body.get("mode", "").upper()
        
        # Map to EngineMode enum
        mode_map = {
            "RESEARCH": EngineMode.RESEARCH,
            "PAPER": EngineMode.PAPER,
            "LIVE": EngineMode.LIVE,
            "PAUSED": EngineMode.PAUSED,
        }
        
        if mode_str not in mode_map:
            raise HTTPException(status_code=400, detail=f"Mode must be one of: {', '.join(mode_map.keys())}")
        
        target_mode = mode_map[mode_str]
        
        if not _engine:
            raise HTTPException(status_code=503, detail="Engine not initialized")
        
        # Safety: Require confirmation for LIVE mode
        if target_mode == EngineMode.LIVE:
            confirm = body.get("confirm", False)
            if not confirm:
                raise HTTPException(status_code=400, detail="LIVE mode requires explicit confirmation")
        
        # CONTROL PLANE: Use global EngineModeManager (authoritative)
        mode_before = get_engine_mode()
        set_engine_mode(target_mode, reason="control_mode endpoint")
        mode_after = get_engine_mode()
        
        # Update config for backwards compatibility
        # PHASE 2: Use safe_get to prevent AttributeError
        config = safe_get(_engine, "config", None)
        if config:
            try:
                if target_mode == EngineMode.PAPER:
                    config.trade_mode = "PAPER"
                elif target_mode == EngineMode.LIVE:
                    config.trade_mode = "LIVE"
            except Exception:
                pass  # Non-critical - config update is backwards compatibility only
        
        if _order_router:
            _order_router.update_executor()
        
        # Emit event
        event_bus = get_event_bus()
        safe_emit(event_bus.publish({
            "type": "control",
            "action": "mode_changed",
            "mode": mode_after.value,
            "mode_before": mode_before,
        }))
        
        logger.info(f"MODE_CHANGED | request_id={request_id} | mode_before={mode_before} | mode_after={mode_after}")
        return ActionResponse(ok=True, message=f"Engine mode changed to {mode_after}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MODE_ERROR | request_id={request_id} | error={str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/control/strategy/activate", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def control_strategy_activate(request: Request):
    """Activate a strategy."""
    request_id = request_id_ctx.get()
    
    if not _strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    try:
        body = await request.json()
        strategy_name = body.get("strategy")
        
        if not strategy_name:
            raise HTTPException(status_code=400, detail="strategy name required")
        
        _strategy_manager.activate_only(strategy_name)
        
        # Emit event
        event_bus = get_event_bus()
        await event_bus.publish({
            "type": "control",
            "action": "strategy_activated",
            "strategy": strategy_name,
        })
        
        logger.info(f"STRATEGY_ACTIVATED | request_id={request_id} | strategy={strategy_name}")
        return ActionResponse(ok=True, message=f"Strategy {strategy_name} activated")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"STRATEGY_ACTIVATE_ERROR | request_id={request_id} | error={str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/control/strategy/deactivate", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def control_strategy_deactivate(request: Request):
    """Deactivate a strategy."""
    request_id = request_id_ctx.get()
    
    if not _strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    try:
        body = await request.json()
        strategy_name = body.get("strategy")
        
        if not strategy_name:
            raise HTTPException(status_code=400, detail="strategy name required")
        
        from sentinel_x.intelligence.strategy_manager import StrategyStatus
        _strategy_manager.status[strategy_name] = StrategyStatus.DISABLED
        
        # Emit event
        event_bus = get_event_bus()
        await event_bus.publish({
            "type": "control",
            "action": "strategy_deactivated",
            "strategy": strategy_name,
        })
        
        logger.info(f"STRATEGY_DEACTIVATED | request_id={request_id} | strategy={strategy_name}")
        return ActionResponse(ok=True, message=f"Strategy {strategy_name} deactivated")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"STRATEGY_DEACTIVATE_ERROR | request_id={request_id} | error={str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SHADOW CONTROL: Enable/Disable Shadow Mode
# ============================================================================

@app.post("/control/shadow/enable", response_model=ShadowStatusResponse, dependencies=[Depends(require_api_key)])
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def control_shadow_enable(request: Request):
    """
    Enable shadow mode.
    
    SAFETY: SHADOW MODE ONLY - never triggers order execution
    SAFETY: Engine continues running during state change
    
    Request body (optional):
    {
        "reason": "Optional reason for enabling"
    }
    
    Returns:
        ShadowStatusResponse with current state (always 200 OK unless internal error)
    """
    request_id = request_id_ctx.get()
    client_ip = get_remote_address(request)
    
    try:
        # Parse request body (optional)
        reason = None
        try:
            if request.headers.get("content-type") == "application/json":
                body = await request.json()
                reason = body.get("reason") if body else None
        except Exception:
            pass  # Body parsing is optional
        
        controller = get_shadow_controller()
        controller.enable(reason=reason)
        state_dict = controller.get_state_dict()
        
        logger.info(
            f"SHADOW_ENABLE_OK | request_id={request_id} | "
            f"client={client_ip} | reason={reason or 'none'}"
        )
        
        return ShadowStatusResponse(
            enabled=True,
            timestamp=datetime.utcnow().isoformat() + "Z",
            mode=state_dict["mode"],
            trading_window=state_dict["trading_window"],
            last_transition=state_dict["last_transition"],
            reason=state_dict["reason"]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"SHADOW_ENABLE_ERROR | request_id={request_id} | "
            f"client={client_ip} | error={str(e)}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Error enabling shadow mode: {str(e)}")


@app.post("/control/shadow/disable", response_model=ShadowStatusResponse, dependencies=[Depends(require_api_key)])
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def control_shadow_disable(request: Request):
    """
    Disable shadow mode.
    
    SAFETY: Engine continues running during state change
    
    Request body (optional):
    {
        "reason": "Optional reason for disabling"
    }
    
    Returns:
        ShadowStatusResponse with current state (always 200 OK unless internal error)
    """
    request_id = request_id_ctx.get()
    client_ip = get_remote_address(request)
    
    try:
        # Parse request body (optional)
        reason = None
        try:
            if request.headers.get("content-type") == "application/json":
                body = await request.json()
                reason = body.get("reason") if body else None
        except Exception:
            pass  # Body parsing is optional
        
        controller = get_shadow_controller()
        controller.disable(reason=reason)
        state_dict = controller.get_state_dict()
        
        logger.info(
            f"SHADOW_DISABLE_OK | request_id={request_id} | "
            f"client={client_ip} | reason={reason or 'none'}"
        )
        
        return ShadowStatusResponse(
            enabled=False,
            timestamp=datetime.utcnow().isoformat() + "Z",
            mode=state_dict["mode"],
            trading_window=state_dict["trading_window"],
            last_transition=state_dict["last_transition"],
            reason=state_dict["reason"]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"SHADOW_DISABLE_ERROR | request_id={request_id} | "
            f"client={client_ip} | error={str(e)}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Error disabling shadow mode: {str(e)}")


# ============================================================================
# PHASE 5: Metrics API Endpoints
# ============================================================================

@app.get("/metrics/pnl")
async def get_pnl_metrics():
    """Get current PnL metrics (read-only, cached)."""
    try:
        from sentinel_x.monitoring.pnl import get_pnl_engine
        pnl_engine = get_pnl_engine()
        metrics = pnl_engine.get_all_metrics()
        return metrics
    except Exception as e:
        logger.error(f"Error getting PnL metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# PHASE 5-6: Capital allocation endpoint (read-only, simulated)
@app.get("/dashboard/allocation")
async def get_capital_allocation():
    """
    PHASE 6: Get simulated capital allocation (read-only, advisory only).
    
    SAFETY: allocation is simulated only
    SAFETY: no execution influence
    REGRESSION LOCK — OBSERVABILITY ONLY
    
    UI labels MUST say:
    "SIMULATED CAPITAL ALLOCATION — NO EXECUTION EFFECT"
    
    Returns:
    - Capital allocation snapshot
    - Per-strategy recommended weights
    - Allocation model used
    - Governance warnings (if any)
    """
    try:
        from sentinel_x.intelligence.capital_allocator import get_capital_allocator
        
        allocator = get_capital_allocator()
        
        # Compute allocation from strategy manager (read-only)
        snapshot = allocator.allocate_from_strategy_manager()
        
        if not snapshot:
            return {
                'error': 'Allocation not available',
                'label': 'SIMULATED CAPITAL ALLOCATION — NO EXECUTION EFFECT',
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }
        
        # Return snapshot as dict (read-only)
        return snapshot.to_dict()
        
    except Exception as e:
        logger.error(f"Error getting capital allocation: {e}", exc_info=True)
        return {
            'error': str(e),
            'label': 'SIMULATED CAPITAL ALLOCATION — NO EXECUTION EFFECT',
            'timestamp': datetime.utcnow().isoformat() + "Z"
        }


# PHASE 5: System performance endpoint (read-only)
@app.get("/dashboard/system")
async def get_system_dashboard():
    """
    PHASE 5: Get global system performance dashboard (read-only).
    
    SAFETY: dashboard is read-only
    SAFETY: no execution dependency
    REGRESSION LOCK — OBSERVABILITY ONLY
    
    Returns:
    - Total strategies
    - Active vs disabled count
    - Total PnL
    - System drawdown
    - Training duration
    - Engine mode
    """
    try:
        from sentinel_x.monitoring.dashboard import get_strategy_dashboard
        
        dashboard = get_strategy_dashboard()
        system_perf = dashboard.get_system_performance()
        
        # Get capital allocation (read-only, simulated)
        capital_allocation = None
        try:
            from sentinel_x.monitoring.dashboard import get_strategy_dashboard
            dashboard = get_strategy_dashboard()
            capital_allocation = dashboard.get_capital_allocation()
        except Exception as e:
            logger.debug(f"Error getting capital allocation for system dashboard (non-fatal): {e}")
        
        return {
            'total_strategies': system_perf.total_strategies,
            'active_strategies': system_perf.active_strategies,
            'disabled_strategies': system_perf.disabled_strategies,
            'training_strategies': system_perf.training_strategies,
            'total_realized_pnl': system_perf.total_realized_pnl,
            'total_unrealized_pnl': system_perf.total_unrealized_pnl,
            'total_pnl': system_perf.total_pnl,
            'system_drawdown': system_perf.system_drawdown,
            'system_max_drawdown': system_perf.system_max_drawdown,
            'training_duration_seconds': system_perf.training_duration_seconds,
            'engine_mode': system_perf.engine_mode,
            'capital_allocation': capital_allocation,  # PHASE 6: Simulated capital allocation
            'timestamp': system_perf.last_update.isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting system dashboard: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics/strategies")
async def get_strategy_metrics():
    """
    PHASE 5: Get strategy performance metrics (read-only).
    
    SAFETY: dashboard is read-only
    SAFETY: no execution dependency
    """
    if not _strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    try:
        from sentinel_x.monitoring.pnl import get_pnl_engine
        pnl_engine = get_pnl_engine()
        
        strategies_list = _strategy_manager.list_strategies()
        result = []
        
        for strategy_info in strategies_list:
            strategy_name = strategy_info['name']
            pnl_metrics = pnl_engine.get_strategy_metrics(strategy_name)
            
            result.append({
                'name': strategy_name,
                'status': strategy_info['status'],
                'score': strategy_info.get('score'),
                'trades_count': pnl_metrics['trades_count'],
                'wins': pnl_metrics['wins'],
                'losses': pnl_metrics['losses'],
                'win_rate': pnl_metrics['win_rate'],
                'avg_return': pnl_metrics['avg_return'],
                'realized_pnl': pnl_metrics['realized_pnl'],
                'max_drawdown': pnl_metrics['max_drawdown'],
                'last_trade_ts': pnl_metrics['last_trade_ts'],
            })
        
        return {'strategies': result}
    except Exception as e:
        logger.error(f"Error getting strategy metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics/brokers")
async def get_broker_metrics():
    """Get broker information and status."""
    try:
        from sentinel_x.execution.broker_manager import get_broker_manager
        broker_manager = get_broker_manager()
        
        brokers = broker_manager.list_brokers()
        active_broker = broker_manager.get_active_broker()
        
        result = {
            'brokers': brokers,
            'active_broker': broker_manager.active_broker_name,
        }
        
        # Add account info for active broker
        if active_broker:
            try:
                account = active_broker.get_account()
                positions = active_broker.get_positions()
                
                result['active_broker_info'] = {
                    'name': active_broker.name,
                    'mode': active_broker.mode,
                    'account': account,
                    'positions_count': len(positions) if positions else 0,
                }
            except Exception as e:
                logger.error(f"Error getting active broker info: {e}", exc_info=True)
                result['active_broker_info'] = {'error': str(e)}
        
        return result
    except Exception as e:
        logger.error(f"Error getting broker metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# PHASE 2: Equity curve endpoints
@app.get("/metrics/equity")
async def get_equity_metrics():
    """Get equity curve and benchmark comparison."""
    try:
        from sentinel_x.monitoring.equity import get_equity_engine
        equity_engine = get_equity_engine()
        
        current_metrics = equity_engine.get_current_metrics()
        equity_curve = equity_engine.get_equity_curve(limit=1000)
        
        return {
            'current': current_metrics,
            'curve': equity_curve
        }
    except Exception as e:
        logger.error(f"Error getting equity metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# PHASE 4-5: Strategy ranking with performance (DISPLAY ONLY)
@app.get("/strategies/ranking")
async def get_strategy_ranking(sort_by: str = "composite_score"):
    """
    PHASE 4-5: Get strategy ranking (display only, read-only).
    
    SAFETY: ranking does NOT affect lifecycle
    SAFETY: rankings do NOT affect promotion logic
    SAFETY: purely informational
    REGRESSION LOCK — OBSERVABILITY ONLY
    
    Sort by:
    - composite_score (default)
    - realized_pnl
    - sharpe
    - drawdown (inverse - lower is better)
    
    Args:
        sort_by: Sort key ("composite_score", "realized_pnl", "sharpe", "drawdown")
    """
    try:
        from sentinel_x.monitoring.dashboard import get_strategy_dashboard
        
        dashboard = get_strategy_dashboard()
        rankings = dashboard.get_strategy_rankings(sort_by=sort_by)
        
        return {
            'rankings': [
                {
                    'strategy_name': r.strategy_name,
                    'rank': r.rank,
                    'composite_score': r.composite_score,
                    'realized_pnl': r.realized_pnl,
                    'sharpe': r.sharpe,
                    'max_drawdown': r.max_drawdown,
                    'lifecycle_state': r.lifecycle_state
                }
                for r in rankings
            ],
            'sort_by': sort_by,
            'count': len(rankings),
            'timestamp': datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Error getting strategy ranking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PHASE 6: Strategy Performance Dashboard (READ-ONLY)
# ============================================================================

@app.get("/dashboard/strategies/{strategy_name}/history")
async def get_strategy_lifecycle_history(strategy_name: str):
    """
    PHASE 8: Get strategy lifecycle history (audit trail, read-only).
    
    SAFETY: dashboard is read-only
    SAFETY: no execution dependency
    REGRESSION LOCK — OBSERVABILITY ONLY
    
    Exposes:
    - Promotion / demotion history
    - Strategy lifecycle transitions
    - Timestamped metric snapshots
    
    Purpose:
    - Explainability
    - Debugging
    - Future compliance
    """
    try:
        from sentinel_x.monitoring.dashboard import get_strategy_dashboard
        
        dashboard = get_strategy_dashboard()
        history = dashboard.get_strategy_lifecycle_history(strategy_name)
        
        if not history:
            raise HTTPException(status_code=404, detail=f"Strategy not found or no history: {strategy_name}")
        
        return {
            'strategy_name': strategy_name,
            'lifecycle_history': history,
            'count': len(history),
            'timestamp': datetime.utcnow().isoformat() + "Z"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting lifecycle history for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dashboard/strategies/{strategy_name}")
async def get_strategy_dashboard(strategy_name: str):
    """
    PHASE 5-6: Get per-strategy performance dashboard (read-only).
    
    SAFETY: dashboard is read-only
    SAFETY: no execution dependency
    REGRESSION LOCK — OBSERVABILITY ONLY
    
    Returns:
    - Equity curve
    - Drawdown
    - Win/loss statistics
    - Sharpe ratio
    - Expectancy
    - PnL contribution
    - Lifecycle state
    - Promotion readiness score
    - Last trade time
    - Last heartbeat
    """
    try:
        from sentinel_x.monitoring.dashboard import get_strategy_dashboard
        
        dashboard = get_strategy_dashboard()
        performance = dashboard.get_strategy_performance(strategy_name)
        
        if not performance:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_name}")
        
        # Get equity curve (if available, read-only)
        equity_curve = []
        try:
            from sentinel_x.monitoring.equity import get_equity_engine
            equity_engine = get_equity_engine()
            equity_curve = equity_engine.get_strategy_equity_curve(strategy_name, limit=1000)
        except Exception as e:
            logger.debug(f"Equity curve not available for {strategy_name}: {e}")
        
        # Build response (read-only snapshot)
        return {
            'name': performance.strategy_name,
            'lifecycle_state': performance.lifecycle_state,
            'status': performance.status,
            'composite_score': performance.composite_score,
            'trades_count': performance.trades_count,
            'win_rate': performance.win_rate,
            'expectancy': performance.expectancy,
            'sharpe': performance.sharpe,
            'max_drawdown': performance.max_drawdown,
            'realized_pnl': performance.realized_pnl,
            'unrealized_pnl': performance.unrealized_pnl,
            'total_pnl': performance.total_pnl,
            'capital_weight': performance.capital_weight,
            'ranking': performance.ranking,
            'last_trade_time': performance.last_trade_time.isoformat() if performance.last_trade_time else None,
            'last_heartbeat': performance.last_heartbeat.isoformat() if performance.last_heartbeat else None,
            'consecutive_losses': performance.consecutive_losses,
            'promotion_eligible': performance.promotion_eligible,
            'demotion_evaluation': performance.demotion_evaluation,
            'last_disable_reason': performance.last_disable_reason,
            'equity_curve': equity_curve,
            'timestamp': datetime.utcnow().isoformat() + "Z"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy dashboard for {strategy_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dashboard/strategies")
async def get_all_strategies_dashboard():
    """
    PHASE 6: Get global strategy dashboard (read-only).
    
    Returns:
    - Strategy ranking
    - Capital weights (simulated, TRAINING only)
    - Active vs disabled count
    - Lifecycle state distribution
    - Global performance summary
    """
    if not _strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    try:
        # Get strategy ranking with performance
        rankings = _strategy_manager.get_strategy_ranking_with_performance()
        
        # Calculate capital weights (simulated, TRAINING only)
        try:
            from sentinel_x.intelligence.capital_allocator import get_capital_allocator, AllocatorMode
            from sentinel_x.intelligence.capital_allocator import AllocatorConstraints
            
            allocator = get_capital_allocator(
                mode=AllocatorMode.EQUAL_WEIGHT,
                constraints=AllocatorConstraints(max_capital_per_strategy=0.25)
            )
            
            active_strategy_names = [name for name, s in _strategy_manager.strategies.items() 
                                   if _strategy_manager.status.get(name) == StrategyStatus.ACTIVE]
            
            # Build strategy metrics dict for allocator
            strategy_metrics = {}
            for name in active_strategy_names:
                perf = _strategy_manager.get_rolling_performance(name)
                strategy_metrics[name] = {
                    'win_rate': perf.get('win_rate', 0.0),
                    'trades_count': perf.get('trades_count', 0),
                    'realized_pnl': perf.get('pnl', 0.0),
                }
            
            # PHASE 6: Get capital allocation (simulated, advisory only)
            # SAFETY: allocator output is never consumed by execution paths
            # SAFETY: allocation is simulated only - no execution effect
            # REGRESSION LOCK — CAPITAL ALLOCATION
            allocations = allocator.allocate(active_strategy_names, strategy_metrics)
            capital_weights = {a.strategy_name: a.capital_fraction for a in allocations}  # Display only
        except Exception as e:
            logger.debug(f"Error calculating capital weights: {e}")
            capital_weights = {}
        
        # Count active vs disabled
        active_count = sum(1 for s in _strategy_manager.status.values() if s == StrategyStatus.ACTIVE)
        disabled_count = sum(1 for s in _strategy_manager.status.values() if s == StrategyStatus.DISABLED)
        auto_disabled_count = sum(1 for s in _strategy_manager.status.values() if s == StrategyStatus.AUTO_DISABLED)
        
        # Lifecycle state distribution
        lifecycle_dist = {}
        for state in _strategy_manager.strategy_states.values():
            state_str = state.value if hasattr(state, 'value') else str(state)
            lifecycle_dist[state_str] = lifecycle_dist.get(state_str, 0) + 1
        
        # Global performance summary
        try:
            from sentinel_x.monitoring.pnl import get_pnl_engine
            pnl_engine = get_pnl_engine()
            global_metrics = pnl_engine.get_all_metrics()
            total_pnl = global_metrics.get('realized_pnl', 0.0)
            total_trades = global_metrics.get('total_trades', 0)
        except Exception as e:
            logger.debug(f"Error getting global metrics: {e}")
            total_pnl = 0.0
            total_trades = 0
        
        return {
            'rankings': rankings,
            'capital_weights': capital_weights,  # PHASE 6: TRAINING only (simulated, advisory only, NO EXECUTION EFFECT)
            'status_distribution': {
                'active': active_count,
                'disabled': disabled_count,
                'auto_disabled': auto_disabled_count,
                'total': len(_strategy_manager.strategies)
            },
            'lifecycle_distribution': lifecycle_dist,
            'global_performance': {
                'total_pnl': total_pnl,
                'total_trades': total_trades,
                'active_strategies': active_count,
            }
        }
    except Exception as e:
        logger.error(f"Error getting all strategies dashboard: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PHASE 4: Shadow vs Live Comparison Endpoints (OBSERVATIONAL ONLY)
# ============================================================================


# ============================================================================
# PHASE 1: WebSocket Metrics Streaming
# ============================================================================

@app.websocket("/ws/metrics")
async def websocket_metrics(websocket: WebSocket):
    """
    WebSocket endpoint for real-time metrics streaming.
    
    PHASE 1: Server pushes updates every 1s
    - No auth required (metrics are read-only)
    - Client reconnects automatically
    - Stream continues even if engine paused
    """
    await websocket.accept()
    request_id = str(uuid.uuid4())[:8]
    
    # Add to connections set
    with _websocket_lock:
        _websocket_connections.add(websocket)
    
    logger.info(f"WS_CONNECT | request_id={request_id} | client={websocket.client}")
    
    try:
        # Send initial metrics immediately
        initial_metrics = await aggregate_live_metrics()
        await websocket.send_json(initial_metrics)
        
        # Stream updates every 1 second
        while True:
            await asyncio.sleep(1.0)
            # Get fresh metrics and send to this client only
            metrics = await aggregate_live_metrics()
            await websocket.send_json(metrics)
    
    except WebSocketDisconnect:
        logger.info(f"WS_DISCONNECT | request_id={request_id} | client={websocket.client}")
    except Exception as e:
        logger.error(f"WS_ERROR | request_id={request_id} | error={str(e)}", exc_info=True)
    finally:
        # Remove from connections
        with _websocket_lock:
            _websocket_connections.discard(websocket)


# ============================================================================
# ============================================================================
# PHASE 4 — WEBSOCKET ENDPOINT /ws/health (READ-ONLY, NON-BLOCKING)
# ============================================================================
# REGRESSION LOCK — Health streaming only
# DO NOT add control messages
# DO NOT attach to execution path
# SAFETY: WebSocket is read-only
# SAFETY: Engine loop never blocks on API
# SAFETY: Ignore incoming messages - WebSocket is read-only
#
# SECURITY LOCKS:
# - NO POST endpoints exposed
# - NO WS inbound messages processed
# - MOBILE READ-ONLY GUARANTEE
# - NO execution hooks reachable
# ============================================================================

@app.websocket("/ws/health")
async def ws_health(websocket: WebSocket):
    """
    PHASE 3 — WEBSOCKET HEALTH STREAM (READ-ONLY, NON-BLOCKING)
    
    WebSocket endpoint for real-time status streaming with historical replay.
    
    RULES:
    - READ-ONLY
    - NO engine awaits
    - NO blocking calls
    
    REGRESSION LOCK — Rork API contract
    REGRESSION LOCK — monitoring only
    """
    await websocket.accept()
    try:
        # Replay historical buffer (PHASE 7)
        with _replay_buffer_lock:
            for snap in list(health_buffer):
                await websocket.send_json(snap)
        
        # Stream live updates every 1 second
        while True:
            if _engine:
                snapshot = _engine.get_status_snapshot()
                
                # Store in replay buffer (PHASE 7 - MEMORY ONLY — NO DB, NO DISK)
                with _replay_buffer_lock:
                    health_buffer.append(snapshot)
                
                await websocket.send_json(snapshot)
            
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS health error")


# ============================================================================
# PHASE 4 — WEBSOCKET ENDPOINT /ws/strategies (READ-ONLY, NON-BLOCKING)
# ============================================================================
# REGRESSION LOCK — Strategy telemetry streaming only
# DO NOT add control messages
# DO NOT mutate strategy state
# SAFETY: WebSocket is read-only
# ============================================================================

@app.websocket("/ws/strategies")
async def ws_strategies(websocket: WebSocket):
    """
    PHASE 4 — WEBSOCKET STRATEGY PNL STREAM (READ-ONLY, NON-BLOCKING)
    
    WebSocket endpoint for real-time per-strategy telemetry.
    
    RULE: Empty list is valid
    
    REGRESSION LOCK — Rork API contract
    REGRESSION LOCK — monitoring only
    """
    await websocket.accept()
    try:
        while True:
            strategies = []
            
            # Get strategies from engine's strategy manager
            if _engine and hasattr(_engine, 'strategy_manager') and _engine.strategy_manager:
                strategy_manager = _engine.strategy_manager
                
                # Access strategies list (may be a dict or list)
                if hasattr(strategy_manager, 'strategies'):
                    strategies_list = strategy_manager.strategies
                    if isinstance(strategies_list, dict):
                        strategies_list = list(strategies_list.values())
                    
                    for s in strategies_list:
                        try:
                            strategies.append({
                                "strategy_id": getattr(s, 'name', 'unknown'),
                                "status": "ACTIVE" if getattr(s, 'enabled', False) else "PAUSED",
                                "pnl": getattr(s, 'pnl_realized', 0.0) + getattr(s, 'pnl_unrealized', 0.0),
                                "drawdown": getattr(s, 'max_drawdown', 0.0),
                                "trades": getattr(s, 'trades', 0),
                                "last_tick_ts": getattr(s, 'last_update_ts', None),
                            })
                        except Exception:
                            continue  # Skip invalid strategies
            
            await websocket.send_json(strategies)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS strategies error")


@app.websocket("/ws/shadow-vs-live")
async def websocket_shadow_vs_live(websocket: WebSocket):
    """
    WebSocket endpoint for real-time Shadow vs Live comparison streaming.
    
    SHADOW COMPARISON: Streams comparison data every 1s
    - Per-strategy PnL delta
    - Aggregate shadow vs execution equity
    - Slippage distribution
    - Execution latency histogram
    - Divergence alerts
    
    If WebSocket fails: Log and continue engine execution (non-blocking)
    """
    await websocket.accept()
    request_id = str(uuid.uuid4())[:8]
    
    # Add to connections set
    with _shadow_websocket_lock:
        _shadow_websocket_connections.add(websocket)
    
    logger.info(f"WS_SHADOW_CONNECT | request_id={request_id} | client={websocket.client}")
    
    try:
        shadow_manager = get_shadow_comparison_manager()
        
        # Send initial comparison immediately
        initial_summary = shadow_manager.get_comparison_summary()
        await websocket.send_json(initial_summary)
        
        # Stream updates every 1 second
        while True:
            await asyncio.sleep(1.0)
            
            try:
                # Get fresh comparison summary
                summary = shadow_manager.get_comparison_summary()
                await websocket.send_json(summary)
            except Exception as e:
                logger.error(f"Error sending shadow comparison update: {e}", exc_info=True)
                # Continue - don't disconnect on single send failure
    
    except WebSocketDisconnect:
        logger.info(f"WS_SHADOW_DISCONNECT | request_id={request_id} | client={websocket.client}")
    except Exception as e:
        logger.error(f"WS_SHADOW_ERROR | request_id={request_id} | error={str(e)}", exc_info=True)
        # Log error but continue - WebSocket failures never affect engine
    finally:
        # Remove from connections
        with _shadow_websocket_lock:
            _shadow_websocket_connections.discard(websocket)


@app.websocket("/ws/strategy-pnl")
async def ws_strategy_pnl(websocket: WebSocket):
    """
    PHASE 3 — STRATEGY PNL WEBSOCKET (READ-ONLY)
    
    WebSocket endpoint for real-time per-strategy PnL streaming.
    
    Endpoint: WS /ws/strategy-pnl
    Purpose: Stream strategy PnL metrics every 2 seconds
    Schema: Rork Strategy PnL Schema (locked)
    
    RULES:
    - READ-ONLY (no trading control)
    - NO engine awaits
    - NO exceptions propagate
    - On connect: Replay last 300 snapshots from buffer
    - Then: Stream live updates every 2s
    
    SAFETY GUARANTEES:
    - WebSocket is read-only
    - WebSocket is non-blocking
    - Failure of WebSocket must NOT affect engine
    - Engine loop NEVER awaits WebSocket
    - All exceptions caught and logged
    """
    await websocket.accept()
    request_id = str(uuid.uuid4())[:8]
    
    # Add to connections set
    with _strategy_websocket_lock:
        _strategy_websocket_connections.add(websocket)
    
    logger.info(f"WS_STRATEGY_PNL_CONNECT | request_id={request_id} | client={websocket.client}")
    
    try:
        # PHASE 3: Replay recent history from buffer
        try:
            with _strategy_pnl_lock:
                # Get snapshot of buffer (thread-safe copy)
                replay_snapshots = list(_strategy_pnl_buffer)
            
            # Send replay snapshots (oldest first)
            for snap in replay_snapshots:
                try:
                    await websocket.send_json(snap)
                except Exception:
                    # If send fails during replay, client may have disconnected
                    break
            
            logger.debug(f"WS_STRATEGY_PNL_REPLAY | request_id={request_id} | count={len(replay_snapshots)}")
        except Exception as e:
            logger.debug(f"WS_STRATEGY_PNL_REPLAY_ERROR | request_id={request_id} | error={str(e)}")
            # Non-critical - continue with live streaming even if replay fails
        
        # Stream live updates every 2 seconds
        # SAFETY: This loop only waits and sends, never blocks engine
        while True:
            await asyncio.sleep(2.0)  # Fixed interval: 2 seconds
            
            try:
                # PHASE 2: Get strategy metrics from strategy manager
                if _strategy_manager:
                    strategies_metrics = _strategy_manager.get_strategy_metrics()
                else:
                    strategies_metrics = {}
                
                # Build snapshot
                snap = {
                    "timestamp": time.time(),
                    "strategies": strategies_metrics
                }
                
                # PHASE 3: Store in buffer (thread-safe)
                with _strategy_pnl_lock:
                    _strategy_pnl_buffer.append(snap)
                
                # Send to client
                await websocket.send_json(snap)
                
            except WebSocketDisconnect:
                # Client disconnected
                break
            except Exception as e:
                # SAFETY: Log error but continue - WebSocket failures never affect engine
                logger.debug(f"WS_STRATEGY_PNL_ERROR | request_id={request_id} | error={str(e)}")
                # Continue - don't disconnect on single send failure
    
    except WebSocketDisconnect:
        logger.info(f"WS_STRATEGY_PNL_DISCONNECT | request_id={request_id} | client={websocket.client}")
    except Exception as e:
        logger.exception(f"WS_STRATEGY_PNL_ERROR | request_id={request_id} | error={str(e)}")
        # SAFETY: WebSocket errors never affect engine
    finally:
        # PHASE 3: On disconnect, cleanly release resources
        with _strategy_websocket_lock:
            _strategy_websocket_connections.discard(websocket)
        logger.debug(f"WS_STRATEGY_PNL_CLEANUP | request_id={request_id}")


@app.websocket("/ws/strategy-performance")
async def ws_strategy_performance(websocket: WebSocket):
    """
    PHASE 3 — MOBILE VISUALIZATION: Strategy Performance WebSocket (READ-ONLY)
    
    WebSocket endpoint for real-time strategy performance charts on mobile.
    
    Endpoint: WS /ws/strategy-performance
    Purpose: Stream strategy performance data including time-series PnL every 2 seconds
    Schema: Rork Strategy Performance Schema (strict contract)
    
    RULES:
    - READ-ONLY (no trading control, no execution paths)
    - NO engine awaits
    - NO exceptions propagate
    - Safe if no strategies exist (returns empty dict)
    - Updates every 2 seconds
    - Timeseries may be empty (UI must handle gracefully)
    
    SAFETY GUARANTEES:
    - WebSocket is read-only
    - WebSocket is non-blocking
    - Failure of WebSocket must NOT affect engine
    - Engine loop NEVER awaits WebSocket
    - All exceptions caught and logged
    - Memory bounded (max 1000 points per strategy)
    
    REGRESSION LOCK — mobile charts are read-only
    REGRESSION LOCK — no persistence
    """
    await websocket.accept()
    request_id = str(uuid.uuid4())[:8]
    
    logger.info(f"WS_STRATEGY_PERFORMANCE_CONNECT | request_id={request_id} | client={websocket.client}")
    
    try:
        # Stream live updates every 2 seconds
        # SAFETY: This loop only waits and sends, never blocks engine
        while True:
            await asyncio.sleep(2.0)  # Fixed interval: 2 seconds (as per PHASE 9 limits)
            
            try:
                # PHASE 3: Get strategy performance from strategy manager
                if _strategy_manager:
                    try:
                        strategies_perf = _strategy_manager.get_strategy_performance()
                    except Exception as e:
                        # SAFETY: If get_strategy_performance fails, use empty dict
                        logger.debug(f"Error getting strategy performance: {e}")
                        strategies_perf = {}
                else:
                    strategies_perf = {}
                
                # Build payload according to strict schema contract (PHASE 4)
                payload = {
                    "timestamp": time.time(),
                    "strategies": strategies_perf  # Dict[str, Dict] with allocation_weight, trades, pnl_total, timeseries
                }
                
                # Send to client
                await websocket.send_json(payload)
                
            except WebSocketDisconnect:
                # Client disconnected
                break
            except Exception as e:
                # SAFETY: Log error but continue - WebSocket failures never affect engine
                logger.debug(f"WS_STRATEGY_PERFORMANCE_ERROR | request_id={request_id} | error={str(e)}")
                # Continue - don't disconnect on single send failure
    
    except WebSocketDisconnect:
        logger.info(f"WS_STRATEGY_PERFORMANCE_DISCONNECT | request_id={request_id} | client={websocket.client}")
    except Exception as e:
        logger.exception(f"WS_STRATEGY_PERFORMANCE_ERROR | request_id={request_id} | error={str(e)}")
        # SAFETY: WebSocket errors never affect engine
    finally:
        logger.debug(f"WS_STRATEGY_PERFORMANCE_CLEANUP | request_id={request_id}")


@app.get("/shadow/comparison")
async def get_shadow_comparison():
    """
    Get Shadow vs Live comparison summary (read-only).
    
    Returns:
        - Per-strategy PnL deltas
        - Aggregate shadow vs execution equity
        - Slippage distribution
        - Execution latency histogram
        - Divergence alerts count
    """
    try:
        shadow_manager = get_shadow_comparison_manager()
        summary = shadow_manager.get_comparison_summary()
        return summary
    except Exception as e:
        logger.error(f"Error getting shadow comparison: {e}", exc_info=True)
        # Return safe defaults - never crash
        return {
            'strategy_deltas': {},
            'aggregate_shadow_pnl': 0.0,
            'aggregate_execution_pnl': 0.0,
            'aggregate_pnl_delta': 0.0,
            'slippage': {'avg': 0.0, 'max': 0.0, 'count': 0},
            'execution_latency': {'avg_ms': 0.0, 'max_ms': 0.0, 'count': 0},
            'divergence_alerts_count': 0,
            'timestamp': datetime.utcnow().isoformat() + "Z"
        }


@app.get("/shadow/export")
async def export_shadow_comparison(
    format: str = "json",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Export shadow comparison data for audit (read-only, append-only records).
    
    Supports CSV and JSON formats.
    All records are immutable and timestamped.
    """
    try:
        shadow_manager = get_shadow_comparison_manager()
        
        if format.lower() == "csv":
            # Export as CSV
            return StreamingResponse(
                _generate_csv_export(shadow_manager, start_date, end_date),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=shadow_comparison_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
                }
            )
        else:
            # Export as JSON
            return StreamingResponse(
                _generate_json_export(shadow_manager, start_date, end_date),
                media_type="application/json",
                headers={
                    "Content-Disposition": f"attachment; filename=shadow_comparison_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
                }
            )
    except Exception as e:
        logger.error(f"Error exporting shadow comparison: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


def _generate_csv_export(manager, start_date: Optional[str], end_date: Optional[str]):
    """Generate CSV export (generator for streaming)."""
    try:
        conn = sqlite3.connect(manager.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Yield CSV header
        yield "id,strategy,symbol,timestamp,shadow_pnl,execution_pnl,pnl_delta,slippage,execution_latency_ms\n"
        
        # Query comparison snapshots
        query = "SELECT * FROM comparison_snapshots WHERE 1=1"
        params = []
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)
        query += " ORDER BY timestamp ASC"
        
        cursor.execute(query, params)
        
        for row in cursor.fetchall():
            yield f"{row['id']},{row['strategy']},{row['symbol']},{row['timestamp']},{row['shadow_pnl']},{row['execution_pnl']},{row['pnl_delta']},{row['slippage']},{row['execution_latency_ms']}\n"
        
        conn.close()
    except Exception as e:
        logger.error(f"Error generating CSV export: {e}", exc_info=True)
        yield f"ERROR: {str(e)}\n"


def _generate_json_export(manager, start_date: Optional[str], end_date: Optional[str]):
    """Generate JSON export (generator for streaming)."""
    try:
        conn = sqlite3.connect(manager.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Query comparison snapshots
        query = "SELECT * FROM comparison_snapshots WHERE 1=1"
        params = []
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)
        query += " ORDER BY timestamp ASC"
        
        cursor.execute(query, params)
        
        # Yield JSON array start
        yield '{"snapshots":[\n'
        
        first = True
        for row in cursor.fetchall():
            if not first:
                yield ",\n"
            first = False
            yield json.dumps(dict(row))
        
        # Yield JSON array end
        yield '\n],"export_timestamp":"' + datetime.utcnow().isoformat() + 'Z"}\n'
        
        conn.close()
    except Exception as e:
        logger.error(f"Error generating JSON export: {e}", exc_info=True)
        yield json.dumps({"error": str(e)}) + "\n"


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    WebSocket endpoint for real-time event streaming.
    
    Streams all events from event bus:
    - heartbeat
    - strategy_tick
    - order
    - error
    - broker_state
    
    No auth required for local dev.
    Auto-reconnects safe.
    """
    await websocket.accept()
    request_id = str(uuid.uuid4())[:8]
    
    logger.info(f"WS_EVENTS_CONNECT | request_id={request_id} | client={websocket.client}")
    
    event_bus = get_event_bus()
    subscriber_queue = None
    
    try:
        # Subscribe to event bus
        subscriber_queue = await event_bus.subscribe()
        
        # Stream events
        while True:
            try:
                event = await asyncio.wait_for(subscriber_queue.get(), timeout=30.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"type": "keepalive", "timestamp": datetime.utcnow().isoformat() + "Z"})
            except WebSocketDisconnect:
                break
    
    except WebSocketDisconnect:
        logger.info(f"WS_EVENTS_DISCONNECT | request_id={request_id} | client={websocket.client}")
    except Exception as e:
        logger.error(f"WS_EVENTS_ERROR | request_id={request_id} | error={str(e)}", exc_info=True)
    finally:
        # Unsubscribe from event bus
        if subscriber_queue:
            await event_bus.unsubscribe(subscriber_queue)


# ============================================================================
# PHASE 1-12: Synthesis Agent API Endpoints (Governance & Control)
# ============================================================================

@app.post("/synthesis/run-cycle", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
@with_timeout(300.0)  # 5 minutes timeout for synthesis
async def run_synthesis_cycle(request: Request):
    """
    PHASE 11: Trigger synthesis cycle manually.
    
    SAFETY: Synthesis agent NEVER executes trades or modifies EngineMode.
    Runs asynchronously, non-blocking.
    
    Returns immediately - cycle runs in background.
    """
    request_id = request_id_ctx.get()
    
    try:
        synthesis_agent = get_synthesis_agent(_storage, _strategy_manager)
        
        # PHASE 4: Run synthesis cycle asynchronously (non-blocking) with loop safety
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(synthesis_agent.run_synthesis_cycle())
        except RuntimeError:
            # No running loop - run in background thread
            import threading
            threading.Thread(
                target=lambda: asyncio.run(synthesis_agent.run_synthesis_cycle()),
                daemon=True
            ).start()
        
        log_audit_event(
            event_type="SYNTHESIS_CYCLE_TRIGGERED",
            request_id=request_id,
            metadata={
                "trigger": "manual",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        logger.info(f"SYNTHESIS_CYCLE_TRIGGERED | request_id={request_id}")
        
        return {
            "status": "ok",
            "message": "Synthesis cycle started (running in background)"
        }
    except Exception as e:
        logger.error(f"Error triggering synthesis cycle: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start synthesis cycle: {str(e)}")


@app.get("/synthesis/strategies")
async def list_generated_strategies():
    """
    PHASE 8: List generated strategies with governance data.
    
    Returns:
    - Generated strategies
    - Rationale text
    - Performance metrics
    - Promotion readiness score
    - Failure modes
    - Lifecycle state
    """
    try:
        if not _strategy_manager:
            raise HTTPException(status_code=503, detail="Strategy manager not initialized")
        
        synthesis_agent = get_synthesis_agent(_storage, _strategy_manager)
        
        # Get all strategies
        strategies_list = _strategy_manager.list_strategies()
        
        # Filter and enrich with synthesis data
        generated_strategies = []
        for strategy_info in strategies_list:
            strategy_name = strategy_info['name']
            
            # Check if generated (by name pattern or metadata)
            lifecycle_state = _strategy_manager.get_lifecycle_state(strategy_name)
            is_generated = (
                strategy_name.startswith("Synthetic") or
                strategy_name in synthesis_agent.hypotheses or
                lifecycle_state == "CANDIDATE"
            )
            
            if not is_generated:
                continue
            
            # Get hypothesis if available
            hypothesis = synthesis_agent.hypotheses.get(strategy_name)
            
            # Get lifecycle state (already retrieved above)
            
            # Get promotion readiness score
            promotion_score = _strategy_manager.calculate_promotion_readiness_score(strategy_name)
            
            # Get performance metrics
            perf = _strategy_manager.get_rolling_performance(strategy_name)
            
            # Get latest evaluation
            latest_eval = None
            for key, eval_obj in _strategy_manager.evaluations.items():
                if eval_obj.strategy_name == strategy_name:
                    if latest_eval is None or eval_obj.timestamp > latest_eval.timestamp:
                        latest_eval = eval_obj
            
            strategy_data = {
                "name": strategy_name,
                "status": strategy_info['status'],
                "lifecycle_state": lifecycle_state if lifecycle_state else "UNKNOWN",
                "description": hypothesis.description if hypothesis else "Generated strategy",
                "rationale": hypothesis.rationale if hypothesis else "Generated by synthesis agent",
                "target_market_regime": hypothesis.target_market_regime if hypothesis else "unknown",
                "failure_modes": hypothesis.failure_modes if hypothesis else [],
                "promotion_readiness_score": {
                    "overall_score": promotion_score.get("overall_score", 0.0),
                    "performance_score": promotion_score.get("performance_score", 0.0),
                    "risk_score": promotion_score.get("risk_score", 0.0),
                    "stability_score": promotion_score.get("stability_score", 0.0),
                    "regime_robustness_score": promotion_score.get("regime_robustness_score", 0.0)
                },
                "performance_metrics": {
                    "sharpe": latest_eval.sharpe if latest_eval else perf.get('sharpe', 0.0),
                    "win_rate": latest_eval.win_rate if latest_eval else perf.get('win_rate', 0.0),
                    "expectancy": latest_eval.expectancy if latest_eval else 0.0,
                    "max_drawdown": latest_eval.max_drawdown if latest_eval else perf.get('drawdown', 0.0),
                    "trades_count": perf.get('trades_count', 0),
                    "pnl": perf.get('pnl', 0.0)
                },
                "generated_at": hypothesis.generated_at.isoformat() if hypothesis else None,
                "code_hash": synthesis_agent.generated_code_hashes.get(strategy_name)
            }
            
            generated_strategies.append(strategy_data)
        
        return {
            "strategies": generated_strategies,
            "count": len(generated_strategies),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
    except Exception as e:
        logger.error(f"Error listing generated strategies: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list generated strategies: {str(e)}")


@app.post("/synthesis/strategies/{strategy_name}/approve-paper", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def approve_strategy_for_paper(request: Request, strategy_name: str):
    """
    PHASE 8: Approve strategy for PAPER testing (requires human intent).
    
    SAFETY: Only promotes to PAPER_APPROVED, never to LIVE.
    Requires explicit approval - no auto-promotion.
    """
    request_id = request_id_ctx.get()
    
    try:
        if not _strategy_manager:
            raise HTTPException(status_code=503, detail="Strategy manager not initialized")
        
        if strategy_name not in _strategy_manager.strategies:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_name}")
        
        # Get current lifecycle state
        current_state = _strategy_manager.get_lifecycle_state(strategy_name)
        
        # Safety: Only allow promotion from CANDIDATE or SHADOW_TESTING
        if current_state not in ("CANDIDATE", "SHADOW_TESTING", "training"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot promote strategy from {current_state} to PAPER_APPROVED"
            )
        
        # Promote to PAPER_APPROVED
        _strategy_manager.set_lifecycle_state(strategy_name, "PAPER_APPROVED")
        
        # Enable strategy (set status to ACTIVE for shadow trading)
        _strategy_manager.status[strategy_name] = StrategyStatus.ACTIVE
        
        # Log approval
        log_audit_event(
            event_type="SYNTHESIS_STRATEGY_APPROVED_PAPER",
            request_id=request_id,
            metadata={
                "strategy_name": strategy_name,
                "from_state": current_state,
                "to_state": "PAPER_APPROVED",
                "approved_by": "human",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        logger.info(f"Strategy approved for PAPER: {strategy_name} | request_id={request_id}")
        
        return {
            "status": "ok",
            "message": f"Strategy {strategy_name} approved for PAPER testing"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving strategy for PAPER: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to approve strategy: {str(e)}")


@app.post("/synthesis/strategies/{strategy_name}/reject", response_model=ActionResponse, dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
@with_timeout(CONTROL_ENDPOINT_TIMEOUT)
async def reject_strategy(request: Request, strategy_name: str):
    """
    PHASE 8: Reject strategy (archives it).
    
    SAFETY: Sets lifecycle to ARCHIVED, disables strategy.
    """
    request_id = request_id_ctx.get()
    
    try:
        if not _strategy_manager:
            raise HTTPException(status_code=503, detail="Strategy manager not initialized")
        
        if strategy_name not in _strategy_manager.strategies:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_name}")
        
        # Archive strategy
        _strategy_manager.set_lifecycle_state(strategy_name, "ARCHIVED")
        _strategy_manager.status[strategy_name] = StrategyStatus.DISABLED
        
        # Log rejection
        log_audit_event(
            event_type="SYNTHESIS_STRATEGY_REJECTED",
            request_id=request_id,
            metadata={
                "strategy_name": strategy_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        logger.info(f"Strategy rejected (archived): {strategy_name} | request_id={request_id}")
        
        return {
            "status": "ok",
            "message": f"Strategy {strategy_name} rejected and archived"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting strategy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to reject strategy: {str(e)}")


@app.get("/synthesis/promotion-scores")
async def get_promotion_scores():
    """
    PHASE 7: Get promotion readiness scores for all generated strategies.
    
    Returns informational scores - promotion requires governance rules.
    """
    try:
        if not _strategy_manager:
            raise HTTPException(status_code=503, detail="Strategy manager not initialized")
        
        synthesis_agent = get_synthesis_agent(_storage, _strategy_manager)
        
        # Get all generated strategies
        strategies_list = _strategy_manager.list_strategies()
        generated_strategy_names = [
            s['name'] for s in strategies_list
            if s['name'].startswith("Synthetic") or
            _strategy_manager.get_lifecycle_state(s['name']) == "CANDIDATE"
        ]
        
        # Calculate scores
        scores = []
        for strategy_name in generated_strategy_names:
            score = _strategy_manager.calculate_promotion_readiness_score(strategy_name)
            lifecycle_state = _strategy_manager.get_lifecycle_state(strategy_name)
            
            scores.append({
                "strategy_name": strategy_name,
                "lifecycle_state": lifecycle_state if lifecycle_state else "UNKNOWN",
                "promotion_readiness_score": score,
                "timestamp": score.get("timestamp", datetime.utcnow()).isoformat() if isinstance(score.get("timestamp"), datetime) else datetime.utcnow().isoformat()
            })
        
        return {
            "scores": scores,
            "count": len(scores),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
    except Exception as e:
        logger.error(f"Error getting promotion scores: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get promotion scores: {str(e)}")


# ============================================================================
# PHASE 5: Execution Quality Metrics API Endpoints (UI Visibility)
# ============================================================================

@app.get("/execution/metrics/{strategy_name}")
async def get_execution_metrics(strategy_name: str, window_hours: int = 24):
    """
    PHASE 5: Get execution quality metrics for a strategy (read-only).
    
    Returns:
    - ExecutionQualityScore
    - Slippage trend
    - Latency histogram
    - Promotion readiness
    
    UI is READ-ONLY.
    """
    try:
        if not _strategy_manager:
            raise HTTPException(status_code=503, detail="Strategy manager not initialized")
        
        if strategy_name not in _strategy_manager.strategies:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_name}")
        
        metrics_tracker = get_execution_metrics_tracker()
        execution_metrics = metrics_tracker.calculate_metrics(
            strategy_name,
            window_hours=window_hours
        )
        
        # Get promotion readiness score
        promotion_score = _strategy_manager.calculate_promotion_readiness_score(strategy_name)
        
        # Calculate slippage trend (simplified - would need historical data)
        slippage_trend = {
            "current": execution_metrics.avg_slippage_bps,
            "variance": execution_metrics.slippage_variance,
            "max": execution_metrics.max_slippage_bps,
            "direction": "stable"  # Placeholder - would analyze trend
        }
        
        # Latency histogram (simplified - would need distribution)
        latency_histogram = {
            "avg_ms": execution_metrics.avg_latency_ms,
            "std_ms": execution_metrics.latency_std_ms,
            "max_ms": execution_metrics.max_latency_ms,
            "percentiles": {
                "p50": execution_metrics.avg_latency_ms,  # Placeholder
                "p95": execution_metrics.avg_latency_ms + execution_metrics.latency_std_ms * 2,
                "p99": execution_metrics.avg_latency_ms + execution_metrics.latency_std_ms * 3
            }
        }
        
        return {
            "strategy_name": strategy_name,
            "execution_quality_score": execution_metrics.execution_quality_score,
            "slippage": {
                "avg_bps": execution_metrics.avg_slippage_bps,
                "variance": execution_metrics.slippage_variance,
                "max_bps": execution_metrics.max_slippage_bps,
                "trend": slippage_trend
            },
            "latency": {
                "avg_ms": execution_metrics.avg_latency_ms,
                "std_ms": execution_metrics.latency_std_ms,
                "max_ms": execution_metrics.max_latency_ms,
                "histogram": latency_histogram
            },
            "fill_metrics": {
                "fill_ratio": execution_metrics.fill_ratio,
                "total_requests": execution_metrics.total_requests,
                "total_fills": execution_metrics.total_fills,
                "total_partial_fills": execution_metrics.total_partial_fills,
                "missed_fills": execution_metrics.missed_fills
            },
            "cancel_rate": execution_metrics.cancel_rate,
            "shadow_divergence_bps": execution_metrics.shadow_divergence_bps,
            "promotion_readiness": {
                "overall_score": promotion_score.get("overall_score", 0.0),
                "execution_passes_gates": promotion_score.get("execution_passes_gates", False),
                "execution_gate_reasons": promotion_score.get("execution_gate_reasons", [])
            },
            "window": {
                "start": execution_metrics.window_start.isoformat() + "Z",
                "end": execution_metrics.window_end.isoformat() + "Z",
                "hours": window_hours
            },
            "timestamp": execution_metrics.calculated_at.isoformat() + "Z"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting execution metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get execution metrics: {str(e)}")


@app.get("/execution/metrics")
async def list_execution_metrics(window_hours: int = 24):
    """
    PHASE 5: List execution quality metrics for all strategies (read-only).
    
    Returns execution metrics for all active strategies.
    UI is READ-ONLY.
    """
    try:
        if not _strategy_manager:
            raise HTTPException(status_code=503, detail="Strategy manager not initialized")
        
        strategies_list = _strategy_manager.list_strategies()
        metrics_tracker = get_execution_metrics_tracker()
        
        all_metrics = []
        for strategy_info in strategies_list:
            strategy_name = strategy_info['name']
            
            try:
                execution_metrics = metrics_tracker.calculate_metrics(
                    strategy_name,
                    window_hours=window_hours
                )
                
                # Get promotion readiness
                promotion_score = _strategy_manager.calculate_promotion_readiness_score(strategy_name)
                
                all_metrics.append({
                    "strategy_name": strategy_name,
                    "status": strategy_info['status'],
                    "execution_quality_score": execution_metrics.execution_quality_score,
                    "slippage": {
                        "avg_bps": execution_metrics.avg_slippage_bps,
                        "variance": execution_metrics.slippage_variance
                    },
                    "latency": {
                        "avg_ms": execution_metrics.avg_latency_ms,
                        "std_ms": execution_metrics.latency_std_ms
                    },
                    "fill_ratio": execution_metrics.fill_ratio,
                    "promotion_readiness": {
                        "overall_score": promotion_score.get("overall_score", 0.0),
                        "execution_passes_gates": promotion_score.get("execution_passes_gates", False)
                    }
                })
            except Exception as e:
                logger.debug(f"Error getting metrics for {strategy_name} (non-fatal): {e}")
                continue
        
        return {
            "metrics": all_metrics,
            "count": len(all_metrics),
            "window_hours": window_hours,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
    except Exception as e:
        logger.error(f"Error listing execution metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list execution metrics: {str(e)}")


# ============================================================================
# LIFECYCLE EVENTS
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Log API startup with hardening status."""
    global _health_broadcast_task
    
    logger.info("=" * 60)
    logger.info("Sentinel X Control Plane (Rork API) starting...")
    logger.info("=" * 60)
    
    # Start event bus
    event_bus = get_event_bus()
    await event_bus.start()
    logger.info("Event bus started")
    
    # PHASE 5: Start health WebSocket broadcast task
    # SAFETY: Runs in API event loop, isolated from engine
    _health_broadcast_task = asyncio.create_task(broadcast_health_snapshots())
    logger.info("Health WebSocket broadcast task started")
    
    # Adaptive Shadow Engine v0.1 — internal loop (shadow only, updates /shadow/status)
    try:
        from sentinel_x.core.adaptive_shadow_engine import start_adaptive_shadow_engine
        start_adaptive_shadow_engine()
        logger.info("Adaptive shadow engine thread started")
    except Exception as e:
        logger.warning("Could not start adaptive shadow engine: %s", e)
    
    # Log hardening configuration
    logger.info("Production Hardening Status:")
    logger.info(f"  - Authentication: {'ENABLED (mutating endpoints)' if ENABLE_AUTH else 'DISABLED'}")
    logger.info(f"  - Rate Limiting: ENABLED (START/STOP: {RATE_LIMIT_START_STOP})")
    logger.info(f"  - KILL Rate Limit: EXEMPT (safety override)")
    logger.info(f"  - Request Timeout: {CONTROL_ENDPOINT_TIMEOUT}s")
    logger.info(f"  - Operation Locking: ENABLED")
    logger.info(f"  - Structured Logging: ENABLED (request_id tracking)")
    logger.info(f"  - Status Robustness: ENABLED (no UNKNOWN, monotonic uptime)")
    logger.info(f"  - Event Bus: ENABLED")
    logger.info(f"  - Health WebSocket: ENABLED (read-only, non-blocking)")
    
    if ENABLE_AUTH:
        logger.info("API key authentication enabled for /start, /stop, /kill")
        logger.info("Read-only endpoints (/status, /strategies, etc.) do not require auth")
    else:
        logger.warning("API key authentication DISABLED (set API_KEY and ENABLE_API_AUTH=true to enable)")


@app.on_event("shutdown")
async def shutdown_event():
    """Log API shutdown."""
    global _health_broadcast_task
    
    logger.info("Sentinel X Control Plane (Rork API) shutting down...")
    
    # PHASE 5: Stop health WebSocket broadcast task
    if _health_broadcast_task and not _health_broadcast_task.done():
        _health_broadcast_task.cancel()
        try:
            await _health_broadcast_task
        except asyncio.CancelledError:
            pass
        logger.info("Health WebSocket broadcast task stopped")
    
    # Stop event bus
    event_bus = get_event_bus()
    await event_bus.stop()
    logger.info("Event bus stopped")


# ============================================================================
# PHASE 2: Device Token Management Endpoints
# ============================================================================

@app.post("/admin/devices/tokens")
async def create_device_token(
    request: Request,
    device_id: str,
    permissions: List[str],
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """
    Create a device token with scoped permissions.
    
    PHASE 2: Requires admin API key.
    Permissions: start, stop, kill, read, all
    """
    # Check admin auth
    request_id = request_id_ctx.get()
    if not x_api_key or x_api_key != API_KEY or not ENABLE_AUTH:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    
    try:
        token = create_device_token(device_id, permissions)
        logger.info(f"DEVICE_TOKEN_CREATED | request_id={request_id} | device_id={device_id}")
        return {
            "device_id": device_id,
            "token": token,  # Return once only
            "permissions": permissions,
            "message": "Token created. Store securely - it will not be shown again."
        }
    except Exception as e:
        logger.error(f"Error creating device token: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/admin/devices/tokens/{device_id}")
async def revoke_device_token(
    request: Request,
    device_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """Revoke a device token."""
    request_id = request_id_ctx.get()
    if not x_api_key or x_api_key != API_KEY or not ENABLE_AUTH:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    
    success = revoke_device_token(device_id)
    if success:
        logger.info(f"DEVICE_TOKEN_REVOKED | request_id={request_id} | device_id={device_id}")
        return {"message": f"Token revoked for device {device_id}"}
    else:
        raise HTTPException(status_code=404, detail="Device token not found")


# ============================================================================
# PHASE 3: Audit Log Export Endpoint
# ============================================================================

@app.get("/audit/export")
async def export_audit(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Export audit log (read-only, optional auth).
    
    PHASE 3: Returns JSON Lines format with checksums.
    Supports date filtering and streaming for large exports.
    """
    request_id = request_id_ctx.get()
    logger.info(f"AUDIT_EXPORT | request_id={request_id} | start={start_date} | end={end_date}")
    
    # Get checksum for tamper-evident verification
    checksum = get_audit_log_checksum()
    
    async def generate():
        # Yield checksum header
        yield json.dumps({"checksum": checksum, "format": "jsonl"}) + "\n"
        # Yield audit entries
        for entry in export_audit_log(start_date, end_date):
            yield entry
    
    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": "attachment; filename=audit_export.jsonl",
            "X-Audit-Checksum": checksum
        }
    )


# ============================================================================
# PHASE 1: Shadow Backtesting Endpoints
# ============================================================================

@app.get("/shadow/strategies", response_model=List[Dict])
async def get_shadow_strategies():
    """
    Get all shadow strategy templates.
    
    SAFETY: SHADOW MODE ONLY - read-only, never triggers execution
    """
    request_id = request_id_ctx.get()
    logger.info(f"SHADOW_STRATEGIES | request_id={request_id}")
    
    try:
        from sentinel_x.strategies.templates import get_all_strategy_templates
        
        templates = get_all_strategy_templates()
        strategies = []
        
        for template in templates:
            strategies.append({
                "id": template.id,
                "name": template.name,
                "asset": template.asset,
                "type": template.type,
                "parameters": template.parameters,
                "mode": template.mode
            })
        
        return strategies
    except Exception as e:
        logger.error(f"Error getting shadow strategies: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting shadow strategies: {str(e)}")


@app.get("/shadow/strategies/{strategy_id}", response_model=Dict)
async def get_shadow_strategy(strategy_id: str):
    """
    Get shadow strategy template by ID.
    
    SAFETY: SHADOW MODE ONLY - read-only, never triggers execution
    """
    request_id = request_id_ctx.get()
    logger.info(f"SHADOW_STRATEGY | request_id={request_id} | strategy_id={strategy_id}")
    
    try:
        from sentinel_x.strategies.templates import get_strategy_template
        
        template = get_strategy_template(strategy_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        
        return {
            "id": template.id,
            "name": template.name,
            "asset": template.asset,
            "type": template.type,
            "parameters": template.parameters,
            "mode": template.mode
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting shadow strategy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting shadow strategy: {str(e)}")


@app.post("/shadow/strategies/{strategy_id}/backtest", response_model=BacktestResultView)
async def run_shadow_backtest(
    strategy_id: str,
    request: Request
):
    """
    Run shadow backtest for a strategy.
    
    SAFETY: SHADOW MODE ONLY - never triggers live execution
    SAFETY: never submits paper orders
    
    Request body (optional):
    {
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-31T23:59:59Z",
        "initial_capital": 100000.0
    }
    """
    request_id = request_id_ctx.get()
    logger.info(f"SHADOW_BACKTEST | request_id={request_id} | strategy_id={strategy_id}")
    
    try:
        from sentinel_x.strategies.templates import get_strategy_template
        from sentinel_x.backtest.simulator import run_backtest
        from sentinel_x.backtest.data_loader import load_price_history
        
        # Get strategy template
        template = get_strategy_template(strategy_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        
        # Parse request body
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        
        start_date_str = body.get("start_date")
        end_date_str = body.get("end_date")
        initial_capital = body.get("initial_capital", 100000.0)
        
        # Parse dates (default to last 30 days)
        from datetime import datetime, timedelta
        if end_date_str:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        else:
            end_date = datetime.now()
        
        if start_date_str:
            start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
        else:
            start_date = end_date - timedelta(days=30)
        
        # Load price history
        price_data = load_price_history(template.asset, start_date, end_date)
        if not price_data:
            raise HTTPException(
                status_code=404,
                detail=f"No price data available for {template.asset} in date range"
            )
        
        # Run backtest
        history = {template.asset: price_data}
        result = run_backtest(template, history, initial_capital=initial_capital, start_date=start_date, end_date=end_date)
        
        # Convert to response
        return BacktestResultView(
            strategy_id=result.strategy_id,
            strategy_name=result.strategy_name,
            asset=result.asset,
            start_date=result.start_date,
            end_date=result.end_date,
            pnl=result.pnl,
            sharpe=result.sharpe,
            max_drawdown=result.max_drawdown,
            trades=result.trades,
            win_rate=result.win_rate,
            total_return=result.total_return
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running shadow backtest: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error running shadow backtest: {str(e)}")


@app.get("/shadow/strategies/{strategy_id}/performance", response_model=BacktestResultView)
async def get_shadow_performance(
    strategy_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Get shadow backtesting performance for a strategy.
    
    SAFETY: SHADOW MODE ONLY - read-only, never triggers execution
    
    Query parameters:
    - start_date: ISO format date string (optional, defaults to 30 days ago)
    - end_date: ISO format date string (optional, defaults to now)
    """
    request_id = request_id_ctx.get()
    logger.info(f"SHADOW_PERFORMANCE | request_id={request_id} | strategy_id={strategy_id}")
    
    try:
        from sentinel_x.strategies.templates import get_strategy_template
        from sentinel_x.backtest.simulator import run_backtest
        from sentinel_x.backtest.data_loader import load_price_history
        
        # Get strategy template
        template = get_strategy_template(strategy_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        
        # Parse dates
        from datetime import datetime, timedelta
        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        else:
            end_dt = datetime.now()
        
        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        else:
            start_dt = end_dt - timedelta(days=30)
        
        # Load price history
        price_data = load_price_history(template.asset, start_dt, end_dt)
        if not price_data:
            raise HTTPException(
                status_code=404,
                detail=f"No price data available for {template.asset} in date range"
            )
        
        # Run backtest
        history = {template.asset: price_data}
        result = run_backtest(template, history, start_date=start_dt, end_date=end_dt)
        
        # Convert to response
        return BacktestResultView(
            strategy_id=result.strategy_id,
            strategy_name=result.strategy_name,
            asset=result.asset,
            start_date=result.start_date,
            end_date=result.end_date,
            pnl=result.pnl,
            sharpe=result.sharpe,
            max_drawdown=result.max_drawdown,
            trades=result.trades,
            win_rate=result.win_rate,
            total_return=result.total_return
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting shadow performance: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting shadow performance: {str(e)}")
