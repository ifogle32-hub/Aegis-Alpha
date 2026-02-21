"""
Sentinel X v0.1 — Monitor API (FastAPI).
GET /status, /heartbeat, /portfolio, /metrics, /strategy. JSON only. No write endpoints.
"""
import json
from pathlib import Path

from fastapi import FastAPI

from sentinel_x_v01.config import get_config

app = FastAPI(title="Sentinel X v0.1 Monitor", version="0.1")


def _read_json(path: str, default: dict):
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


@app.get("/status")
def get_status():
    """Engine status from state file and heartbeat."""
    cfg = get_config()
    state = _read_json(cfg.state_path, {})
    heartbeat = _read_json(cfg.heartbeat_path, {})
    return {
        "status": "running" if heartbeat.get("status") == "running" else "unknown",
        "symbol": state.get("symbol", cfg.symbol),
        "ts": heartbeat.get("ts"),
    }


@app.get("/heartbeat")
def get_heartbeat():
    """Latest heartbeat."""
    cfg = get_config()
    heartbeat = _read_json(cfg.heartbeat_path, {})
    return heartbeat


@app.get("/portfolio")
def get_portfolio():
    """Capital, position, PnL."""
    cfg = get_config()
    state = _read_json(cfg.state_path, {})
    return {
        "capital": state.get("capital", cfg.initial_capital),
        "position": state.get("position", 0),
        "entry_price": state.get("entry_price"),
        "realized_pnl": state.get("realized_pnl", 0),
        "unrealized_pnl": state.get("unrealized_pnl", 0),
    }


@app.get("/metrics")
def get_metrics():
    """Aggregate metrics (capital, PnL)."""
    cfg = get_config()
    state = _read_json(cfg.state_path, {})
    return {
        "capital": state.get("capital", cfg.initial_capital),
        "realized_pnl": state.get("realized_pnl", 0),
        "unrealized_pnl": state.get("unrealized_pnl", 0),
    }


@app.get("/strategy")
def get_strategy():
    """Strategy/learner state."""
    cfg = get_config()
    state = _read_json(cfg.state_path, {})
    return {
        "symbol": state.get("symbol", cfg.symbol),
        "signal_threshold": state.get("signal_threshold", 0.5),
        "position_multiplier": state.get("position_multiplier", 1.0),
        "momentum_window": cfg.momentum_window,
        "vol_lookback": cfg.vol_lookback,
    }
