"""
PHASE 2 — RORK DATA ADAPTER LAYER

Server-side adapter that converts internal Sentinel X state → Rork schema.

Adapter guarantees:
- Immutable payloads
- Defensive copying
- No engine mutation
- Safe defaults when unavailable

MOBILE READ-ONLY GUARANTEE
PUSH IS ALERT-ONLY
METRICS ARE OBSERVABILITY-ONLY
LIVE CONTROL NOT ENABLED

REGRESSION LOCK — OBSERVABILITY ONLY
CONTROL REQUESTS ARE NON-ACTUATING
DO NOT ENABLE LIVE WITHOUT GOVERNANCE REVIEW
"""

import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.heartbeat import read_heartbeat
from sentinel_x.monitoring.broker_status import get_broker_status
from sentinel_x.monitoring.health import get_system_health
from sentinel_x.monitoring.pnl import get_pnl_engine
from sentinel_x.monitoring.equity import get_equity_engine
from sentinel_x.core.engine_mode import get_engine_mode, EngineMode
from sentinel_x.core.engine import get_engine

# Schema version
SCHEMA_VERSION = "v1"


def get_rork_mobile_state() -> Dict[str, Any]:
    """
    PHASE 2 — RORK DATA ADAPTER LAYER
    
    Convert internal Sentinel X state → Rork mobile schema (v1).
    
    Returns:
        SentinelXMobileState dict with all mobile-optimized data.
    
    Rules:
        - Schema is read-only
        - Missing fields allowed (graceful degradation)
        - Versioned for backward compatibility
        - Defensive copying (no direct object sharing)
        - Immutable payloads
        - No engine mutation
        - Safe defaults when unavailable
    
    SAFETY: Read-only, non-blocking, never raises
    """
    try:
        # Get health snapshot (read-only, non-blocking)
        health = get_health_snapshot()
        
        # Get broker status (read-only, non-blocking)
        broker_status = get_broker_status()
        
        # Get engine mode
        engine_mode = get_engine_mode()
        mode_value = engine_mode.value
        
        # Normalize mode for mobile schema (TRAINING → TRAINING, LIVE → LIVE_DISABLED if not enabled)
        mobile_mode = mode_value
        if mode_value == "LIVE":
            # Mobile schema: LIVE mode is always shown as LIVE_DISABLED (safety guarantee)
            mobile_mode = "LIVE_DISABLED"
        elif mode_value == "PAPER":
            # Normalize PAPER to TRAINING for mobile
            mobile_mode = "TRAINING"
        elif mode_value == "RESEARCH":
            mobile_mode = "TRAINING"
        
        # Build EngineStatus
        engine_status: Dict[str, Any] = {
            "mode": mobile_mode,
            "state": health.get("status", "STOPPED"),
            "loop_tick": health.get("loop_tick", 0),
            "heartbeat_age": health.get("heartbeat_age", 999.9),
            "loop_tick_age": health.get("loop_tick_age", 999.9),
            "uptime_sec": 0.0,  # Will be calculated below
        }
        
        # Add optional loop_phase if available
        if "loop_phase" in health:
            engine_status["loop_phase"] = health["loop_phase"]
        
        # Calculate uptime (safe, non-blocking)
        engine = get_engine()
        if engine and hasattr(engine, 'started_at'):
            try:
                uptime_sec = time.time() - engine.started_at
                engine_status["uptime_sec"] = max(0.0, uptime_sec)
            except Exception:
                pass  # Safe default: 0.0
        
        # Build BrokerStatus
        broker_name = broker_status.get("broker_name", "none").upper()
        broker_type = "NONE"
        if broker_name == "ALPACA" or "ALPACA" in broker_name:
            broker_type = "ALPACA_PAPER"
        elif broker_name == "PAPER":
            broker_type = "PAPER"
        elif broker_name == "TRADOVATE":
            broker_type = "TRADOVATE"
        
        broker_status_mobile: Dict[str, Any] = {
            "broker_type": broker_type,
            "connected": broker_status.get("connected", False),
        }
        
        # Add optional broker fields
        if "degraded" in broker_status:
            broker_status_mobile["degraded"] = broker_status["degraded"]
        if "last_successful_call_ts" in broker_status and broker_status["last_successful_call_ts"]:
            broker_status_mobile["last_successful_call_ts"] = broker_status["last_successful_call_ts"]
        
        # Build StrategySummary[] from strategy manager and PnL engine
        strategies_list: List[Dict[str, Any]] = []
        
        try:
            # Get strategy manager (safe import, may return None)
            try:
                from sentinel_x.intelligence.strategy_manager import get_strategy_manager
                strategy_manager = get_strategy_manager(None)  # Pass None for storage (optional)
            except Exception:
                strategy_manager = None
            
            # Get strategy list from strategy manager
            if strategy_manager:
                strategy_list = strategy_manager.list_strategies()
                
                # Get PnL engine for strategy metrics
                pnl_engine = get_pnl_engine()
                all_pnl_metrics = pnl_engine.get_all_metrics() if pnl_engine else {}
                by_strategy_pnl = all_pnl_metrics.get("by_strategy", {})
                
                # Build strategy summaries
                for strategy in strategy_list:
                    strategy_id = strategy.get("name", "unknown")
                    status_raw = strategy.get("status", "DISABLED")
                    
                    # Map strategy status to mobile schema
                    mobile_status = "DISABLED"
                    if status_raw == "ACTIVE":
                        mobile_status = "ACTIVE"
                    elif status_raw in ("PAUSED", "AUTO_DISABLED"):
                        mobile_status = "PAUSED"
                    
                    # Get PnL metrics for this strategy
                    strategy_pnl = by_strategy_pnl.get(strategy_id, {})
                    
                    # Build strategy summary
                    strategy_summary: Dict[str, Any] = {
                        "strategy_id": strategy_id,
                        "status": mobile_status,
                        "pnl": strategy_pnl.get("realized_pnl", 0.0),
                        "drawdown": -abs(strategy_pnl.get("max_drawdown", 0.0)),  # Negative for drawdown
                        "win_rate": strategy_pnl.get("win_rate", 0.0),
                        "trades_today": strategy_pnl.get("trades_count", 0),
                    }
                    
                    # Add optional fields
                    if "last_trade_ts" in strategy_pnl and strategy_pnl["last_trade_ts"]:
                        # Convert ISO timestamp to monotonic if possible (approximate)
                        try:
                            last_trade_dt = datetime.fromisoformat(strategy_pnl["last_trade_ts"].replace("Z", "+00:00"))
                            strategy_summary["last_trade_ts"] = last_trade_dt.timestamp()
                        except Exception:
                            pass
                    
                    if "composite_score" in strategy:
                        strategy_summary["composite_score"] = strategy.get("composite_score")
                    if "ranking" in strategy:
                        strategy_summary["ranking"] = strategy.get("ranking")
                    
                    strategies_list.append(strategy_summary)
        
        except Exception as e:
            logger.debug(f"Error building strategy summaries (non-fatal): {e}")
            # Safe default: empty list
        
        # Build PortfolioSummary from PnL and equity engines
        portfolio_summary: Dict[str, Any] = {
            "equity": None,
            "total_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "open_positions": 0,
        }
        
        try:
            # Get PnL metrics
            pnl_engine = get_pnl_engine()
            if pnl_engine:
                all_metrics = pnl_engine.get_all_metrics()
                portfolio_summary["realized_pnl"] = all_metrics.get("total_realized", 0.0)
                portfolio_summary["unrealized_pnl"] = all_metrics.get("total_unrealized", 0.0)
                portfolio_summary["total_pnl"] = all_metrics.get("total_pnl", 0.0)
            
            # Get equity
            equity_engine = get_equity_engine()
            if equity_engine:
                current_metrics = equity_engine.get_current_metrics()
                portfolio_summary["equity"] = current_metrics.get("equity")
            
            # Get open positions count (safe access via engine)
            engine = get_engine()
            if engine and engine.order_router and engine.order_router.active_executor:
                try:
                    positions = engine.order_router.get_positions()
                    if positions:
                        portfolio_summary["open_positions"] = len(positions)
                except Exception:
                    pass  # Safe default: 0
            
            # Get buying power from broker status
            if "buying_power" in broker_status and broker_status["buying_power"]:
                portfolio_summary["buying_power"] = broker_status["buying_power"]
        
        except Exception as e:
            logger.debug(f"Error building portfolio summary (non-fatal): {e}")
            # Safe defaults already set
        
        # Build RiskSnapshot from equity engine
        risk_snapshot: Dict[str, Any] = {
            "max_drawdown": 0.0,
            "current_drawdown": 0.0,
        }
        
        try:
            equity_engine = get_equity_engine()
            if equity_engine:
                current_metrics = equity_engine.get_current_metrics()
                risk_snapshot["max_drawdown"] = -abs(current_metrics.get("max_drawdown", 0.0))  # Negative for drawdown
                risk_snapshot["current_drawdown"] = -abs(current_metrics.get("drawdown", 0.0))  # Negative for drawdown
        
        except Exception as e:
            logger.debug(f"Error building risk snapshot (non-fatal): {e}")
            # Safe defaults already set
        
        # Build SystemHealth
        system_health: Dict[str, Any] = {
            "watchdog": health.get("watchdog", "FROZEN"),
        }
        
        # Optional system health fields (not available in current implementation)
        # These can be added later if system metrics are available
        
        # Build TimeInfo
        now_mono = time.monotonic()
        now_iso = datetime.utcnow().isoformat() + "Z"
        
        time_info: Dict[str, Any] = {
            "server_time": now_mono,
            "server_time_iso": now_iso,
        }
        
        # Build root SentinelXMobileState
        mobile_state: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "engine": engine_status,
            "broker": broker_status_mobile,
            "strategies": strategies_list,
            "portfolio": portfolio_summary,
            "risk": risk_snapshot,
            "system": system_health,
            "timestamps": time_info,
        }
        
        return mobile_state
    
    except Exception as e:
        # SAFETY: Never raise, always return safe defaults
        logger.error(f"Error building Rork mobile state (non-fatal): {e}", exc_info=True)
        return _get_safe_default_mobile_state()


def _get_safe_default_mobile_state() -> Dict[str, Any]:
    """Get safe default mobile state when errors occur."""
    return {
        "schema_version": SCHEMA_VERSION,
        "engine": {
            "mode": "TRAINING",
            "state": "STOPPED",
            "loop_tick": 0,
            "heartbeat_age": 999.9,
            "loop_tick_age": 999.9,
            "uptime_sec": 0.0,
        },
        "broker": {
            "broker_type": "NONE",
            "connected": False,
        },
        "strategies": [],
        "portfolio": {
            "equity": None,
            "total_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "open_positions": 0,
        },
        "risk": {
            "max_drawdown": 0.0,
            "current_drawdown": 0.0,
        },
        "system": {
            "watchdog": "FROZEN",
        },
        "timestamps": {
            "server_time": time.monotonic(),
            "server_time_iso": datetime.utcnow().isoformat() + "Z",
        },
    }
