"""
API Response Contracts and Schemas

PHASE 3 — SENTINEL API CONTRACT (LOCKED)

Defines response schemas for all API endpoints.
All endpoints must return valid JSON, never 404.

Note: Using plain dicts for simplicity - no external validation dependencies.
"""

from typing import Dict, Any, List

# Type hints for documentation (not enforced at runtime)
# SystemInfo: Dict[str, str] with keys: name, node_id, version, environment
# EngineInfo: Dict[str, Any] with keys: state, loop_tick, heartbeat_age_ms, shadow_mode, trading_window
# KillSwitchInfo: Dict[str, Any] with keys: status, armed
# RiskConfig: Dict[str, float | int] with keys: max_drawdown_pct, daily_loss_limit_pct, position_limit
# PerformanceStats: Dict[str, float] with keys: equity, pnl
# SecurityInfo: Dict[str, str] with keys: auth, mobile_controls, kill_switch


# Default responses for contract stubs
def default_strategies_response() -> List[Dict[str, Any]]:
    """Default strategies response"""
    return []


def default_risk_config_response() -> Dict[str, Any]:
    """Default risk config response"""
    return {
        "max_drawdown_pct": 5.0,
        "daily_loss_limit_pct": 2.0,
        "position_limit": 5,
    }


def default_capital_allocations_response() -> List[Dict[str, Any]]:
    """Default capital allocations response"""
    return []


def default_capital_transfers_response() -> List[Dict[str, Any]]:
    """Default capital transfers response"""
    return []


def default_performance_stats_response() -> Dict[str, Any]:
    """Default performance stats response"""
    return {"equity": 100000.0, "pnl": 0.0}


def default_performance_equity_response() -> List[Dict[str, Any]]:
    """Default performance equity response"""
    return []


def default_performance_pnl_response() -> List[Dict[str, Any]]:
    """Default performance PnL response"""
    return []


def default_alerts_response() -> List[Dict[str, Any]]:
    """Default alerts response"""
    return []


def default_research_jobs_response() -> List[Dict[str, Any]]:
    """Default research jobs response"""
    return []


def default_security_info_response() -> Dict[str, Any]:
    """Default security info response"""
    return {
        "auth": "none",
        "mobile_controls": "disabled",
        "kill_switch": "local-only",
    }
