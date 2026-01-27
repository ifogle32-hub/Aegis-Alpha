"""Pydantic schemas for Sentinel X API (v1 stable)."""

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

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class StatusResponse(BaseModel):
    """
    PHASE 4 — RORK SCHEMA LOCK (STABLE CONTRACT)
    
    System status response - SINGLE SOURCE OF TRUTH for Rork mobile.
    
    RULES:
    - Never rename fields (breaking change)
    - Missing values MUST be null
    - Never return 500 due to missing data
    - All fields are required (use null if missing)
    """
    # PHASE 4: Rork Schema Lock - Required fields
    status: str = Field(..., description="Engine status: RUNNING|STALE|FROZEN")
    mode: str = Field(..., description="Engine mode: TRAINING|SHADOW|LIVE|RESEARCH|PAPER|PAUSED|KILLED")
    loop_tick: Optional[int] = Field(None, description="Current loop tick counter (monotonic)")
    heartbeat_age: Optional[float] = Field(None, description="Heartbeat age in seconds (null if unavailable)")
    loop_phase: str = Field(default="UNKNOWN", description="Current loop phase (INIT, LOOP_START, STRATEGY_EVAL, etc.)")
    uptime: Optional[float] = Field(None, description="Engine uptime in seconds (monotonic, null if unavailable)")
    health: str = Field(default="HEALTHY", description="System health: HEALTHY|DEGRADED")
    mobile_read_only: bool = Field(default=True, description="Mobile is read-only (always true)")
    trading_controls: str = Field(default="DISABLED", description="Trading controls status: DISABLED (mobile cannot control)")
    
    # PHASE 3: Observability hardening fields
    status_reason: Optional[str] = Field(None, description="Reason for status (error message, degradation reason, etc.)")
    degraded: bool = Field(default=False, description="True if status is degraded due to errors")
    
    # Legacy/Backward compatibility fields
    active_strategies: int = Field(default=0, description="Count of active strategies")
    broker_connectivity: bool = Field(default=False, description="Broker connection status")
    shadow_trading: bool = Field(default=True, description="Shadow trading enabled (always true)")
    last_error: Optional[str] = Field(None, description="Last error message (if any)")
    state: Optional[str] = Field(None, description="Legacy bot state (deprecated, use 'status')")
    heartbeat_ts: Optional[datetime] = Field(None, description="Last heartbeat timestamp (deprecated, use heartbeat_age)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "RUNNING",
                "mode": "TRAINING",
                "loop_tick": 12345,
                "heartbeat_age": 0.5,
                "loop_phase": "STRATEGY_EVAL",
                "uptime": 3600.5,
                "health": "HEALTHY",
                "mobile_read_only": True,
                "trading_controls": "DISABLED",
                "status_reason": None,
                "degraded": False,
                "active_strategies": 3,
                "broker_connectivity": True,
                "shadow_trading": True,
                "last_error": None,
                "state": "RUNNING",
                "heartbeat_ts": None
            }
        }


class StrategyView(BaseModel):
    """
    PHASE 7: Strategy view schema with lifecycle and governance info.
    
    SAFETY: read-only observability surface
    SAFETY: auditability required for all decisions
    """
    name: str = Field(..., description="Strategy name")
    status: str = Field(..., description="Strategy status (ACTIVE/DISABLED/AUTO_DISABLED)")
    lifecycle_state: str = Field(..., description="Lifecycle state (TRAINING/DISABLED/SHADOW/APPROVED)")
    score: Optional[float] = Field(None, description="Latest composite score")
    capital_weight: Optional[float] = Field(None, description="Capital allocation weight (0.0-1.0)")
    ranking: Optional[int] = Field(None, description="Ranking position (1-based, lower is better)")
    last_disable_reason: Optional[str] = Field(None, description="Reason for last disable/demotion")
    promotion_eligible: Optional[bool] = Field(None, description="Whether strategy is eligible for promotion")
    demotion_evaluation: Optional[bool] = Field(None, description="Whether strategy meets demotion conditions")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Momentum",
                "status": "ACTIVE",
                "lifecycle_state": "TRAINING",
                "score": 0.75,
                "capital_weight": 0.25,
                "ranking": 1,
                "last_disable_reason": None,
                "promotion_eligible": True,
                "demotion_evaluation": False
            }
        }


class MetricsView(BaseModel):
    """Metrics view schema."""
    sharpe: float = Field(..., description="Sharpe ratio")
    drawdown: float = Field(..., description="Maximum drawdown")
    expectancy: float = Field(..., description="Trade expectancy")
    score: float = Field(..., description="Composite score")
    strategy: str = Field(..., description="Strategy name")
    symbol: str = Field(..., description="Trading symbol")
    timestamp: datetime = Field(..., description="Metrics timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "sharpe": 1.5,
                "drawdown": 0.05,
                "expectancy": 10.5,
                "score": 2.45,
                "strategy": "Momentum",
                "symbol": "AAPL",
                "timestamp": "2024-01-07T12:00:00"
            }
        }


class PositionView(BaseModel):
    """Position view schema."""
    symbol: str = Field(..., description="Trading symbol")
    qty: float = Field(..., description="Position quantity (positive=long, negative=short)")
    avg_price: float = Field(..., description="Average entry price")
    current_price: Optional[float] = Field(None, description="Current price")
    unrealized_pnl: float = Field(..., description="Unrealized P&L")
    entry_time: datetime = Field(..., description="Entry timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "AAPL",
                "qty": 10.0,
                "avg_price": 150.0,
                "current_price": 152.5,
                "unrealized_pnl": 25.0,
                "entry_time": "2024-01-07T10:00:00"
            }
        }


class ActionResponse(BaseModel):
    """Action response schema."""
    ok: bool = Field(..., description="Action success status")
    message: str = Field(..., description="Response message")
    
    class Config:
        json_schema_extra = {
            "example": {
                "ok": True,
                "message": "Engine started successfully"
            }
        }


class StrategiesResponse(BaseModel):
    """Strategies list response."""
    strategies: List[StrategyView] = Field(..., description="List of strategies")
    count: int = Field(..., description="Total count")
    
    class Config:
        json_schema_extra = {
            "example": {
                "strategies": [
                    {"name": "Momentum", "status": "ACTIVE", "score": 2.45},
                    {"name": "MeanReversion", "status": "DISABLED", "score": 0.5}
                ],
                "count": 2
            }
        }


class MetricsResponse(BaseModel):
    """Metrics response schema."""
    metrics: List[MetricsView] = Field(..., description="List of metrics")
    count: int = Field(..., description="Total count")
    
    class Config:
        json_schema_extra = {
            "example": {
                "metrics": [
                    {
                        "sharpe": 1.5,
                        "drawdown": 0.05,
                        "expectancy": 10.5,
                        "score": 2.45,
                        "strategy": "Momentum",
                        "symbol": "AAPL",
                        "timestamp": "2024-01-07T12:00:00"
                    }
                ],
                "count": 1
            }
        }


class PositionsResponse(BaseModel):
    """Positions response schema."""
    positions: List[PositionView] = Field(..., description="List of positions")
    count: int = Field(..., description="Total count")
    total_pnl: float = Field(..., description="Total unrealized P&L")
    
    class Config:
        json_schema_extra = {
            "example": {
                "positions": [
                    {
                        "symbol": "AAPL",
                        "qty": 10.0,
                        "avg_price": 150.0,
                        "current_price": 152.5,
                        "unrealized_pnl": 25.0,
                        "entry_time": "2024-01-07T10:00:00"
                    }
                ],
                "count": 1,
                "total_pnl": 25.0
            }
        }


class BrokerHealthResponse(BaseModel):
    """
    Read-only broker health surface for UI observation.
    
    REGRESSION LOCK:
    - UI must never trigger execution
    - UI must never arm LIVE
    - UI is observer-only
    """
    broker_connected: bool = Field(..., description="Broker connection status")
    broker_name: str = Field(..., description="Active broker name (alpaca, tradovate, paper, or none)")
    engine_mode: str = Field(..., description="Current engine mode (RESEARCH, TRAINING, PAPER, LIVE, PAUSED, KILLED)")
    training_active: bool = Field(..., description="True if TRAINING mode is active")
    
    class Config:
        json_schema_extra = {
            "example": {
                "broker_connected": True,
                "broker_name": "alpaca",
                "engine_mode": "TRAINING",
                "training_active": True
            }
        }


class UIHealthResponse(BaseModel):
    """
    PHASE 7: Comprehensive read-only UI health and observability surface.
    
    UI RESTRICTIONS (ENFORCED):
    - UI must NEVER execute trades (all trade endpoints require API key auth)
    - UI must NEVER arm brokers (no arming endpoints exist)
    - UI must NEVER mutate engine state (only EngineMode changes via control endpoints)
    
    ASSERTION:
    - UI failure cannot affect engine (engine has zero dependencies on UI state)
    """
    engine_mode: str = Field(..., description="Current engine mode (RESEARCH, TRAINING, PAPER, LIVE, PAUSED, KILLED)")
    broker_connected: bool = Field(..., description="Broker connection status (true/false)")
    broker_type: str = Field(..., description="Active broker type (ALPACA_PAPER, TRADOVATE, PAPER, or NONE)")
    last_execution_status: Optional[str] = Field(None, description="Status of last execution (FILLED, REJECTED, etc.)")
    last_error: Optional[str] = Field(None, description="Last error message if any (from engine mode manager)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "engine_mode": "TRAINING",
                "broker_connected": True,
                "broker_type": "ALPACA_PAPER",
                "last_execution_status": "FILLED",
                "last_error": None
            }
        }


# ============================================================================
# PHASE 5 — RORK SCHEMA ALIGNMENT (PYDANTIC MODELS)
# ============================================================================
# REGRESSION LOCK — Rork API contract
# DO NOT modify without Rork UI alignment
# ============================================================================

class EngineStatus(BaseModel):
    """
    PHASE 5 — RORK ENGINE STATUS (STABLE CONTRACT)
    
    Single canonical engine status object matching Rork schema.
    Used by both REST and WebSocket endpoints.
    
    FAIL FAST: If schema mismatch occurs → log + continue (do NOT crash engine)
    """
    engine_state: str = Field(..., description="Engine state: RUNNING|STOPPED")
    mode: str = Field(..., description="Engine mode: TRAINING|SHADOW|LIVE")
    loop_phase: str = Field(..., description="Current loop phase: LOOP_START|STRATEGY_EVAL|ORDER_SUBMIT|...")
    heartbeat_ts: Optional[float] = Field(None, description="Heartbeat timestamp (monotonic)")
    heartbeat_age: Optional[float] = Field(None, description="Heartbeat age in seconds")
    loop_tick: Optional[int] = Field(None, description="Current loop tick counter")
    loop_tick_age: Optional[float] = Field(None, description="Loop tick age in seconds")
    broker: str = Field(..., description="Broker name: ALPACA_PAPER|TRADOVATE|PAPER|NONE|UNKNOWN")
    health: str = Field(..., description="Health status: GREEN|YELLOW|RED")
    reason: Optional[str] = Field(None, description="Health reason/status explanation")
    
    class Config:
        json_schema_extra = {
            "example": {
                "engine_state": "RUNNING",
                "mode": "TRAINING",
                "loop_phase": "STRATEGY_EVAL",
                "heartbeat_ts": 12345.678,
                "heartbeat_age": 0.5,
                "loop_tick": 12345,
                "loop_tick_age": 0.5,
                "broker": "ALPACA_PAPER",
                "health": "GREEN",
                "reason": "Healthy"
            }
        }


class StrategyStatus(BaseModel):
    """
    PHASE 5 — RORK STRATEGY STATUS (STABLE CONTRACT)
    
    Per-strategy status for Rork mobile monitoring.
    Used by /ws/strategies WebSocket stream.
    
    RULES:
    - Read-only (no strategy mutation)
    - Safe if no strategies exist (empty array)
    """
    strategy_id: str = Field(..., description="Strategy identifier/name")
    status: str = Field(..., description="Strategy status: ACTIVE|PAUSED|CANDIDATE")
    pnl: float = Field(..., description="Realized PnL (cumulative)")
    drawdown: float = Field(..., description="Maximum drawdown observed")
    trades: int = Field(..., description="Total number of trades")
    last_tick_ts: Optional[float] = Field(None, description="Last tick timestamp (monotonic)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "strategy_id": "MomentumStrategy",
                "status": "ACTIVE",
                "pnl": 1250.50,
                "drawdown": 0.05,
                "trades": 42,
                "last_tick_ts": 12345.678
            }
        }


class PortfolioSnapshot(BaseModel):
    """
    PHASE 5 — RORK PORTFOLIO SNAPSHOT (STABLE CONTRACT)
    
    Portfolio state snapshot for Rork mobile monitoring.
    """
    equity: Optional[float] = Field(None, description="Total portfolio equity")
    positions_count: int = Field(0, description="Number of open positions")
    total_pnl: float = Field(0.0, description="Total unrealized PnL")
    timestamp: Optional[float] = Field(None, description="Snapshot timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "equity": 100250.50,
                "positions_count": 3,
                "total_pnl": 250.50,
                "timestamp": 12345.678
            }
        }


class KillSwitchState(BaseModel):
    """
    PHASE 5 — RORK KILL SWITCH STATE (STABLE CONTRACT)
    
    Kill switch state for Rork mobile monitoring.
    """
    active: bool = Field(..., description="Kill switch active status")
    reason: Optional[str] = Field(None, description="Kill switch activation reason")
    timestamp: Optional[float] = Field(None, description="Kill switch activation timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "active": False,
                "reason": None,
                "timestamp": None
            }
        }


class BacktestResultView(BaseModel):
    """
    PHASE 1: Shadow backtesting result schema.
    
    SAFETY: SHADOW MODE ONLY - read-only results
    """
    strategy_id: str = Field(..., description="Strategy identifier")
    strategy_name: str = Field(..., description="Strategy name")
    asset: str = Field(..., description="Trading symbol")
    start_date: datetime = Field(..., description="Backtest start date")
    end_date: datetime = Field(..., description="Backtest end date")
    pnl: float = Field(..., description="Cumulative PnL")
    sharpe: float = Field(..., description="Rolling Sharpe Ratio")
    max_drawdown: float = Field(..., description="Maximum drawdown (0.0-1.0)")
    trades: int = Field(..., description="Total trade count")
    win_rate: float = Field(..., description="Win rate (0.0-1.0)")
    total_return: float = Field(..., description="Total return percentage")
    
    class Config:
        json_schema_extra = {
            "example": {
                "strategy_id": "nvda_momentum",
                "strategy_name": "NVDA Momentum",
                "asset": "NVDA",
                "start_date": "2024-01-01T00:00:00Z",
                "end_date": "2024-01-31T23:59:59Z",
                "pnl": 1523.45,
                "sharpe": 1.25,
                "max_drawdown": 0.15,
                "trades": 42,
                "win_rate": 0.65,
                "total_return": 0.152
            }
        }

