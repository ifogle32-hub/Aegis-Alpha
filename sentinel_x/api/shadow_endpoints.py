"""
PHASE 1 — SHADOW BACKTESTING WEB SOCKET API

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Real-time WebSocket feeds for shadow strategy monitoring.
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from contextvars import ContextVar

from sentinel_x.monitoring.logger import logger
from sentinel_x.strategies.templates import get_strategy_template, get_all_strategy_templates

# Request ID context
request_id_ctx: ContextVar[str] = ContextVar('request_id', default='')

router = APIRouter(prefix="/shadow", tags=["shadow"])

# Active WebSocket connections
_active_connections: List[WebSocket] = []
_connection_lock = asyncio.Lock()


async def collect_shadow_realtime() -> Dict[str, Any]:
    """
    Collect real-time shadow data for WebSocket broadcast.
    
    SAFETY: SHADOW MODE ONLY - read-only, never triggers execution
    SAFETY: Returns disabled state if SHADOW gate is not enabled
    
    Returns:
        Dict with timestamp, signals, and metrics, or disabled state
    """
    try:
        # PHASE 7 — SHADOW GATE CHECK
        from sentinel_x.core.shadow_guards import is_shadow_enabled
        from sentinel_x.core.shadow_registry import get_shadow_state
        
        # Check if shadow mode is enabled
        if not is_shadow_enabled():
            state = get_shadow_state()
            return {
                "disabled": True,
                "reason": "Shadow mode disabled. Enable via /engine/shadow endpoint.",
                "mode": state.mode.value,
                "shadow_enabled": False,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
            }
        
        from sentinel_x.backtest.data_loader import load_price_history
        from datetime import timedelta
        
        signals = []
        metrics = {}
        
        # Get recent signals for all strategies (last 24 hours)
        templates = get_all_strategy_templates()
        end_time = datetime.now()
        start_time = end_time - timedelta(days=1)
        
        for template in templates[:10]:  # Limit to 10 strategies to avoid blocking
            try:
                # Load recent price data
                price_data = load_price_history(template.asset, start_time, end_time)
                if not price_data or len(price_data) < template.parameters.get("lookback", 20):
                    continue
                
                # Generate signals (use last 100 bars for efficiency)
                recent_data = price_data[-100:] if len(price_data) > 100 else price_data
                strategy_signals = template.signal_function(recent_data, template.parameters)
                
                # Get only recent signals (last hour)
                recent_signals = [
                    s for s in strategy_signals
                    if s.timestamp > (end_time - timedelta(hours=1))
                ]
                
                if recent_signals:
                    signals.extend([
                        {
                            "strategy_id": s.strategy_id,
                            "symbol": s.symbol,
                            "side": s.side,
                            "confidence": s.confidence,
                            "timestamp": s.timestamp.isoformat() + "Z",
                            "price": s.price
                        }
                        for s in recent_signals
                    ])
                
                # Get backtest summary metrics
                summary = get_backtest_summary(template.id)
                if summary:
                    metrics[template.id] = {
                        "strategy_id": summary.strategy_id,
                        "pnl": summary.pnl,
                        "sharpe": summary.sharpe,
                        "max_drawdown": summary.max_drawdown,
                        "trade_count": summary.trade_count,
                        "win_rate": getattr(summary, 'win_rate', 0.0),
                        "total_return": getattr(summary, 'total_return', 0.0)
                    }
            except Exception as e:
                logger.debug(f"Error collecting shadow data for {template.id}: {e}")
                continue
        
         return {
             "disabled": False,
             "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
             "signals": signals,
             "metrics": metrics,
             "mode": "SHADOW"
         }
    except Exception as e:
        logger.error(f"Error collecting shadow realtime data: {e}", exc_info=True)
        try:
            from sentinel_x.core.shadow_registry import get_shadow_state
            state = get_shadow_state()
            mode_value = state.mode.value
        except Exception:
            mode_value = "UNKNOWN"
        return {
            "disabled": True,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "signals": [],
            "metrics": {},
            "mode": mode_value
        }


def get_backtest_summary(strategy_id: str) -> Optional[Any]:
    """
    Get cached backtest summary for a strategy.
    
    SAFETY: SHADOW MODE ONLY - read-only
    SAFETY: Returns None if SHADOW gate is not enabled
    """
    try:
        # PHASE 7 — SHADOW GATE CHECK
        from sentinel_x.core.shadow_guards import is_shadow_enabled
        
        # Check if shadow mode is enabled
        if not is_shadow_enabled():
            logger.debug(f"Shadow mode disabled, skipping backtest summary for {strategy_id}")
            return None
        
        from sentinel_x.backtest.simulator import run_backtest
        from sentinel_x.backtest.data_loader import load_price_history
        from datetime import datetime, timedelta
        
        template = get_strategy_template(strategy_id)
        if not template:
            return None
        
        # Use recent data (last 7 days) for real-time summary
        end_time = datetime.now()
        start_time = end_time - timedelta(days=7)
        
        price_data = load_price_history(template.asset, start_time, end_time)
        if not price_data or len(price_data) < template.parameters.get("lookback", 20):
            return None
        
        history = {template.asset: price_data}
        result = run_backtest(template, history, start_date=start_time, end_date=end_time)
        
        # Return summary object with required attributes
        class BacktestSummary:
            def __init__(self, result):
                self.strategy_id = result.strategy_id
                self.pnl = result.pnl
                self.sharpe = result.sharpe
                self.max_drawdown = result.max_drawdown
                self.trade_count = result.trades
                self.win_rate = result.win_rate
                self.total_return = result.total_return
        
        return BacktestSummary(result)
    except Exception as e:
        logger.debug(f"Error getting backtest summary for {strategy_id}: {e}")
        return None


@router.websocket("/ws/shadow")
async def shadow_ws(ws: WebSocket):
    """
    WebSocket endpoint for real-time shadow strategy monitoring.
    
    SAFETY: SHADOW MODE ONLY - read-only, never triggers execution
    SAFETY: Never blocks execution paths
    SAFETY: Failures must NOT affect engine
    SAFETY: Returns disabled state if SHADOW gate is not enabled
    
    Broadcasts shadow signals and metrics every second.
    """
    await ws.accept()
    
    async with _connection_lock:
        _active_connections.append(ws)
    
    logger.info(f"Shadow WebSocket connection opened: {len(_active_connections)} active connections")
    
    try:
        while True:
            # Collect real-time shadow data (includes disabled check)
            data = await collect_shadow_realtime()
            
            # Send to client (includes disabled state if SHADOW is off)
            await ws.send_json(data)
            
            # Wait 1 second before next update
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        logger.info("Shadow WebSocket client disconnected")
    except Exception as e:
        logger.error(f"Error in shadow WebSocket: {e}", exc_info=True)
    finally:
        # Remove connection from active list
        async with _connection_lock:
            if ws in _active_connections:
                _active_connections.remove(ws)
        logger.info(f"Shadow WebSocket connection closed: {len(_active_connections)} active connections")


@router.get("/strategies/{strategy_id}/signals")
async def get_shadow_signals(
    strategy_id: str,
    limit: int = 100,
    hours: int = 24
):
    """
    Get recent shadow signals for a strategy.
    
    SAFETY: SHADOW MODE ONLY - read-only, never triggers execution
    SAFETY: Returns error if SHADOW gate is not enabled
    
    Query parameters:
    - limit: Maximum number of signals to return (default: 100)
    - hours: Hours of history to fetch (default: 24)
    """
    request_id = request_id_ctx.get()
    logger.info(f"SHADOW_SIGNALS | request_id={request_id} | strategy_id={strategy_id}")
    
    try:
        # PHASE 7 — SHADOW GATE CHECK
        from sentinel_x.core.shadow_guards import assert_shadow_enabled
        
        # Assert shadow mode is enabled
        try:
            assert_shadow_enabled()
        except RuntimeError as e:
            logger.warning(f"SHADOW_SIGNALS_BLOCKED | request_id={request_id} | reason={str(e)}")
            raise HTTPException(
                status_code=403,
                detail=str(e)
            )
        
        template = get_strategy_template(strategy_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        
        from sentinel_x.backtest.data_loader import load_price_history
        from datetime import datetime, timedelta
        
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        
        price_data = load_price_history(template.asset, start_time, end_time)
        if not price_data or len(price_data) < template.parameters.get("lookback", 20):
            return {"signals": [], "count": 0}
        
        # Generate signals
        strategy_signals = template.signal_function(price_data, template.parameters)
        
        # Sort by timestamp (most recent first) and limit
        strategy_signals.sort(key=lambda s: s.timestamp, reverse=True)
        strategy_signals = strategy_signals[:limit]
        
        # Convert to dict format
        signals = [
            {
                "strategy_id": s.strategy_id,
                "symbol": s.symbol,
                "side": s.side,
                "confidence": s.confidence,
                "timestamp": s.timestamp.isoformat() + "Z",
                "price": s.price
            }
            for s in strategy_signals
        ]
        
        return {"signals": signals, "count": len(signals)}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting shadow signals: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting shadow signals: {str(e)}")


@router.get("/overview")
async def get_shadow_overview():
    """
    Get shadow strategy overview metrics.
    
    SAFETY: SHADOW MODE ONLY - read-only
    SAFETY: Returns disabled state if SHADOW gate is not enabled
    
    Returns summary metrics for all shadow strategies.
    """
    request_id = request_id_ctx.get()
    logger.info(f"SHADOW_OVERVIEW | request_id={request_id}")
    
    try:
        # PHASE 7 — SHADOW GATE CHECK
        from sentinel_x.core.shadow_guards import is_shadow_enabled
        from sentinel_x.core.shadow_registry import get_shadow_state
        
        # Check if shadow mode is enabled
        if not is_shadow_enabled():
            state = get_shadow_state()
            return {
                "disabled": True,
                "reason": "Shadow mode disabled. Enable via /engine/shadow endpoint.",
                "mode": state.mode.value,
                "shadow_enabled": False,
                "strategies": {},
                "count": 0,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
            }
        
        templates = get_all_strategy_templates()
        overview = {}
        
        for template in templates:
            summary = get_backtest_summary(template.id)
            if summary:
                overview[template.id] = {
                    "strategy_id": summary.strategy_id,
                    "strategy_name": template.name,
                    "asset": template.asset,
                    "pnl": summary.pnl,
                    "sharpe": summary.sharpe,
                    "max_drawdown": summary.max_drawdown,
                    "trade_count": summary.trade_count,
                    "win_rate": summary.win_rate,
                    "total_return": summary.total_return
                }
        
        return {
            "disabled": False,
            "strategies": overview,
            "count": len(overview),
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "mode": "SHADOW"
        }
    except Exception as e:
        logger.error(f"Error getting shadow overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting shadow overview: {str(e)}")


# Export get_backtest_summary for use in rork_server.py
__all__ = ['router', 'get_backtest_summary', 'collect_shadow_realtime']
