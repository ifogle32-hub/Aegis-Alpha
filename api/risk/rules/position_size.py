"""
Position Size Rule

PHASE 2 — MAX POSITION SIZE

Enforces per-symbol exposure limit.
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


def check_position_size(
    ctx: RiskContext,
    config: RiskConfig,
    broker_registry: BrokerRegistry
) -> RiskDecision:
    """
    PHASE 2 — POSITION SIZE CHECK
    PHASE 3 — PORTFOLIO-AWARE
    
    Check if order would exceed max position size per symbol.
    
    Args:
        ctx: Risk context
        config: Risk configuration
        broker_registry: Broker registry (for existing positions)
        
    Returns:
        Risk decision
    """
    try:
        symbol = ctx.symbol
        
        # PHASE 3: Get existing position from broker registry
        aggregated_positions = broker_registry.aggregate_positions()
        existing_exposure = aggregated_positions.get("total_exposure_by_symbol", {})
        
        # Get current position size for symbol (shares)
        current_position_size = abs(existing_exposure.get(symbol, {}).get("total_shares", 0.0))
        
        # Calculate new position size
        if ctx.side == "buy":
            new_position_size = current_position_size + ctx.qty
        else:  # "sell"
            new_position_size = abs(current_position_size - ctx.qty)
        
        # PHASE 2: Check max position size per symbol
        if new_position_size > config.max_position_size_per_symbol:
            return RiskDecision(
                approved=False,
                reason=f"Position size would exceed limit: {new_position_size:.2f} > {config.max_position_size_per_symbol:.2f} shares",
                violated_rule=RiskRule.POSITION_SIZE,
                context={
                    "symbol": symbol,
                    "current_position_size": current_position_size,
                    "requested_qty": ctx.qty,
                    "new_position_size": new_position_size,
                    "limit": config.max_position_size_per_symbol,
                }
            )
        
        # PHASE 2: Position size check passed
        return RiskDecision(
            approved=True,
            reason="Position size within limit",
            violated_rule=None,
            context={
                "symbol": symbol,
                "current_position_size": current_position_size,
                "new_position_size": new_position_size,
            }
        )
        
    except Exception as e:
        # PHASE 2: Fail closed - reject on error
        logger.error(f"Position size check error: {e}", exc_info=True)
        return RiskDecision(
            approved=False,
            reason=f"Position size check failed: {str(e)}",
            violated_rule=RiskRule.POSITION_SIZE,
            context={"error": str(e)}
        )
