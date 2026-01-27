"""
PHASE 5 — RORK SCHEMA ALIGNMENT (PYDANTIC MODELS)

Rork-facing schema definitions for mobile monitoring.

REGRESSION LOCK — Rork API contract
REGRESSION LOCK — monitoring only
"""

from pydantic import BaseModel
from typing import Optional, List


class EngineStatus(BaseModel):
    """PHASE 5 — RORK ENGINE STATUS (STABLE CONTRACT)"""
    engine_state: str
    mode: str
    loop_phase: str
    heartbeat_ts: Optional[float]
    heartbeat_age: Optional[float]
    loop_tick: int
    loop_tick_age: Optional[float]
    broker: str
    health: str


class StrategyStatus(BaseModel):
    """PHASE 5 — RORK STRATEGY STATUS (STABLE CONTRACT)"""
    strategy_id: str
    status: str
    pnl: float
    drawdown: float
    trades: int
    last_tick_ts: Optional[float]
