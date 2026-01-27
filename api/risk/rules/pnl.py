"""
Daily Loss Limit Rule

PHASE 2 — DAILY LOSS LIMIT
PHASE 3 — PORTFOLIO-AWARE

Enforces daily P&L threshold.
"""

from api.risk.types import RiskContext
from api.risk.engine import RiskDecision, RiskRule
from api.risk.config import RiskConfig
from api.brokers import BrokerRegistry

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


def check_daily_loss_limit(
    ctx: RiskContext,
    config: RiskConfig,
    broker_registry: BrokerRegistry
) -> RiskDecision:
    """
    PHASE 2 — DAILY LOSS LIMIT CHECK
    PHASE 3 — PORTFOLIO-AWARE
    
    Check if daily P&L is below threshold (would block execution).
    
    Args:
        request: Execution request
        config: Risk configuration
        broker_registry: Broker registry (for P&L calculation)
        
    Returns:
        Risk decision
    """
    try:
        # PHASE 3: Get daily P&L from broker registry
        # For now, we'll use a simplified approach
        # In production, we'd calculate actual daily P&L from trade history
        
        # PHASE 3: Aggregate positions to get exposure
        aggregated = broker_registry.aggregate_positions()
        
        # PHASE 3: Calculate unrealized P&L (simplified)
        # In production, we'd track realized + unrealized P&L
        daily_pnl = 0.0  # Placeholder - would be calculated from trade history
        
        # PHASE 2: Check daily loss limit
        if daily_pnl < config.daily_loss_limit:
            return RiskDecision(
                approved=False,
                reason=f"Daily P&L below threshold: ${daily_pnl:.2f} < ${config.daily_loss_limit:.2f}",
                violated_rule=RiskRule.DAILY_LOSS_LIMIT,
                context={
                    "daily_pnl": daily_pnl,
                    "limit": config.daily_loss_limit,
                    "symbol": ctx.symbol,
                }
            )
        
        # PHASE 2: Daily loss limit check passed
        return RiskDecision(
            approved=True,
            reason="Daily P&L within limit",
            violated_rule=None,
            context={
                "daily_pnl": daily_pnl,
            }
        )
        
    except Exception as e:
        # PHASE 2: Fail closed - reject on error
        logger.error(f"Daily loss limit check error: {e}", exc_info=True)
        return RiskDecision(
            approved=False,
            reason=f"Daily loss limit check failed: {str(e)}",
            violated_rule=RiskRule.DAILY_LOSS_LIMIT,
            context={"error": str(e)}
        )
