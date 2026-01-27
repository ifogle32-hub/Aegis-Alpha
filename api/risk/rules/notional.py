"""
Notional Value Rule

PHASE 2 — MAX NOTIONAL VALUE

Enforces per-order notional cap.
"""

from api.risk.types import RiskContext
from api.risk.engine import RiskDecision, RiskRule
from api.risk.config import RiskConfig

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


def check_notional_value(
    ctx: RiskContext,
    config: RiskConfig
) -> RiskDecision:
    """
    PHASE 2 — NOTIONAL VALUE CHECK
    
    Check if order notional value exceeds limit.
    
    For market orders, we use a conservative estimate (could fetch current price).
    For limit orders, we use the limit_price.
    
    Args:
        ctx: Risk context
        config: Risk configuration
        
    Returns:
        Risk decision
    """
    try:
        # PHASE 2: Calculate order notional value
        # Use the pre-calculated notional from context, or calculate from qty and price
        if ctx.order_type == "limit" and ctx.limit_price:
            # Limit order: use limit price
            notional_value = ctx.qty * ctx.limit_price
        elif ctx.notional > 0:
            # Use pre-calculated notional
            notional_value = ctx.notional
        else:
            # Market order: reject if no price estimate available
            # In production, we'd fetch current market price
            # For now, reject market orders without price
            return RiskDecision(
                approved=False,
                reason="Market orders require price estimation - not implemented",
                violated_rule=RiskRule.NOTIONAL_VALUE,
                context={
                    "order_type": ctx.order_type,
                    "symbol": ctx.symbol,
                }
            )
        
        # PHASE 2: Check max notional per order
        if notional_value > config.max_notional_per_order:
            return RiskDecision(
                approved=False,
                reason=f"Order notional value exceeds limit: ${notional_value:.2f} > ${config.max_notional_per_order:.2f}",
                violated_rule=RiskRule.NOTIONAL_VALUE,
                context={
                    "symbol": ctx.symbol,
                    "qty": ctx.qty,
                    "price": ctx.limit_price if ctx.order_type == "limit" else None,
                    "notional_value": notional_value,
                    "limit": config.max_notional_per_order,
                }
            )
        
        # PHASE 2: Notional value check passed
        return RiskDecision(
            approved=True,
            reason="Notional value within limit",
            violated_rule=None,
            context={
                "notional_value": notional_value,
            }
        )
        
    except Exception as e:
        # PHASE 2: Fail closed - reject on error
        logger.error(f"Notional value check error: {e}", exc_info=True)
        return RiskDecision(
            approved=False,
            reason=f"Notional value check failed: {str(e)}",
            violated_rule=RiskRule.NOTIONAL_VALUE,
            context={"error": str(e)}
        )
