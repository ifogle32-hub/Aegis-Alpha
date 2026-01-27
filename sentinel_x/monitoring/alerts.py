"""
PHASE 5: Alerting System (Slack / Mobile)

Alert triggers:
- First trade of session
- Strategy auto-disabled
- Kill-switch activated
- Drawdown breach
- LIVE mode armed

Channels:
- Slack webhook
- Mobile push (pluggable)

Rules:
- Rate-limited
- Never blocks engine
- Alerts include:
  – Mode (PAPER/LIVE)
  – Broker
  – Strategy
  – Timestamp
"""
import asyncio
import os
from typing import Dict, Optional
from datetime import datetime
from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.notifications import (
    send_kill_notification,
    send_first_trade_notification,
    send_strategy_auto_disabled_notification,
    send_live_mode_armed_notification,
    send_drawdown_breach_notification,
    send_drawdown_notification
)


class AlertManager:
    """
    Centralized alert manager for all alert types.
    
    Routes alerts to appropriate channels (Slack, mobile, etc.)
    """
    
    def __init__(self, slack_webhook_url: Optional[str] = None):
        """
        Initialize alert manager.
        
        Args:
            slack_webhook_url: Slack webhook URL (optional)
        """
        self.slack_webhook_url = slack_webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
        self.first_trade_sent = False  # Track first trade of session
        
        logger.info(f"AlertManager initialized: slack_webhook={'configured' if self.slack_webhook_url else 'not configured'}")
    
    async def alert_first_trade(self, symbol: str, side: str, qty: float, 
                               price: float, strategy: str, mode: str, broker: str) -> None:
        """
        Alert on first trade of session.
        
        Args:
            symbol: Trading symbol
            side: Order side
            qty: Quantity
            price: Price
            strategy: Strategy name
            mode: Trading mode (PAPER/LIVE)
            broker: Broker name
        """
        try:
            if not self.first_trade_sent:
                await send_first_trade_notification(symbol, side, qty, price, strategy, mode)
                self.first_trade_sent = True
        except Exception as e:
            logger.error(f"Error sending first trade alert: {e}", exc_info=True)
    
    async def alert_strategy_auto_disabled(self, strategy: str, reason: str) -> None:
        """
        Alert when strategy is auto-disabled.
        
        Args:
            strategy: Strategy name
            reason: Disable reason
        """
        try:
            await send_strategy_auto_disabled_notification(strategy, reason)
            
            # PHASE 7: Persist alert to metrics store
            try:
                from sentinel_x.monitoring.metrics_store import get_metrics_store, AlertRecord
                from datetime import datetime
                metrics_store = get_metrics_store()
                alert = AlertRecord(
                    alert_type="strategy_auto_disabled",
                    severity="warning",
                    message=f"Strategy {strategy} auto-disabled: {reason}",
                    timestamp=datetime.utcnow(),
                    strategy=strategy,
                    metadata={"reason": reason}
                )
                metrics_store.record_alert(alert)
            except Exception as e:
                logger.debug(f"Error persisting alert: {e}")
        except Exception as e:
            logger.error(f"Error sending strategy auto-disabled alert: {e}", exc_info=True)
    
    async def alert_kill_switch(self, request_id: str) -> None:
        """
        Alert when kill switch is activated.
        
        Args:
            request_id: Request ID that triggered kill
        """
        try:
            await send_kill_notification(request_id)
        except Exception as e:
            logger.error(f"Error sending kill switch alert: {e}", exc_info=True)
    
    async def alert_drawdown_breach(self, drawdown: float, threshold: float) -> None:
        """
        Alert when drawdown breaches threshold.
        
        Args:
            drawdown: Current drawdown (0.0-1.0)
            threshold: Threshold (0.0-1.0)
        """
        try:
            await send_drawdown_breach_notification(drawdown, threshold)
        except Exception as e:
            logger.error(f"Error sending drawdown breach alert: {e}", exc_info=True)
    
    async def alert_live_mode_armed(self) -> None:
        """Alert when LIVE mode is armed."""
        try:
            await send_live_mode_armed_notification()
        except Exception as e:
            logger.error(f"Error sending live mode armed alert: {e}", exc_info=True)
    
    def reset_session(self) -> None:
        """Reset session tracking (for new trading session)."""
        self.first_trade_sent = False


# Global alert manager instance
_alert_manager: Optional[AlertManager] = None


def get_alert_manager(slack_webhook_url: Optional[str] = None) -> AlertManager:
    """Get global alert manager instance."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager(slack_webhook_url)
    return _alert_manager
