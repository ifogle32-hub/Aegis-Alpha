"""
Trading Window Rule

PHASE 2 — TRADING WINDOW

Enforces trading window (block outside allowed hours).
"""

import time
from datetime import datetime, timezone
from api.risk.types import RiskContext
from api.risk.engine import RiskDecision, RiskRule
from api.risk.config import RiskConfig, TradingWindow

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


def check_trading_window(
    ctx: RiskContext,
    config: RiskConfig
) -> RiskDecision:
    """
    PHASE 2 — TRADING WINDOW CHECK
    
    Check if current time is within allowed trading window.
    
    Args:
        request: Execution request
        config: Risk configuration
        
    Returns:
        Risk decision
    """
    try:
        # PHASE 2: Get current time (ET timezone)
        # For simplicity, we'll use local time and assume ET
        # In production, use pytz for proper timezone handling
        now = datetime.now()
        
        # Get current hour (0-23) and minute
        current_hour = now.hour
        current_minute = now.minute
        current_time_minutes = current_hour * 60 + current_minute
        
        # PHASE 2: Check trading window
        if config.trading_window == TradingWindow.ALWAYS:
            # Always allow
            return RiskDecision(
                approved=True,
                reason="Trading window: always open",
                violated_rule=None,
                context={
                    "trading_window": config.trading_window.value,
                    "current_time": current_time_minutes,
                }
            )
        elif config.trading_window == TradingWindow.MARKET_HOURS:
            # Market hours: 9:30 AM - 4:00 PM ET
            # 9:30 AM = 9*60 + 30 = 570 minutes
            # 4:00 PM = 16*60 = 960 minutes
            market_open = 570
            market_close = 960
            
            if market_open <= current_time_minutes <= market_close:
                return RiskDecision(
                    approved=True,
                    reason="Within market hours",
                    violated_rule=None,
                    context={
                        "trading_window": config.trading_window.value,
                        "current_time": current_time_minutes,
                    }
                )
            else:
                return RiskDecision(
                    approved=False,
                    reason=f"Outside market hours: current time {current_hour:02d}:{current_minute:02d} ET, market hours 9:30 AM - 4:00 PM ET",
                    violated_rule=RiskRule.TRADING_WINDOW,
                    context={
                        "trading_window": config.trading_window.value,
                        "current_time": current_time_minutes,
                        "market_open": market_open,
                        "market_close": market_close,
                    }
                )
        elif config.trading_window == TradingWindow.EXTENDED_HOURS:
            # Extended hours: 4:00 AM - 8:00 PM ET
            # 4:00 AM = 4*60 = 240 minutes
            # 8:00 PM = 20*60 = 1200 minutes
            extended_open = 240
            extended_close = 1200
            
            if extended_open <= current_time_minutes <= extended_close:
                return RiskDecision(
                    approved=True,
                    reason="Within extended hours",
                    violated_rule=None,
                    context={
                        "trading_window": config.trading_window.value,
                        "current_time": current_time_minutes,
                    }
                )
            else:
                return RiskDecision(
                    approved=False,
                    reason=f"Outside extended hours: current time {current_hour:02d}:{current_minute:02d} ET, extended hours 4:00 AM - 8:00 PM ET",
                    violated_rule=RiskRule.TRADING_WINDOW,
                    context={
                        "trading_window": config.trading_window.value,
                        "current_time": current_time_minutes,
                        "extended_open": extended_open,
                        "extended_close": extended_close,
                    }
                )
        else:
            # Unknown trading window - reject for safety
            return RiskDecision(
                approved=False,
                reason=f"Unknown trading window: {config.trading_window}",
                violated_rule=RiskRule.TRADING_WINDOW,
                context={
                    "trading_window": config.trading_window.value if hasattr(config.trading_window, 'value') else str(config.trading_window),
                }
            )
        
    except Exception as e:
        # PHASE 2: Fail closed - reject on error
        logger.error(f"Trading window check error: {e}", exc_info=True)
        return RiskDecision(
            approved=False,
            reason=f"Trading window check failed: {str(e)}",
            violated_rule=RiskRule.TRADING_WINDOW,
            context={"error": str(e)}
        )
