"""
Position Count Rule

PHASE 2 — MAX OPEN POSITIONS
PHASE 3 — PORTFOLIO-AWARE

Enforces maximum number of concurrent positions.
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


def check_max_open_positions(
    ctx: RiskContext,
    config: RiskConfig,
    broker_registry: BrokerRegistry
) -> RiskDecision:
    """
    PHASE 2 — MAX OPEN POSITIONS CHECK
    PHASE 3 — PORTFOLIO-AWARE
    
    Check if adding this position would exceed max open positions.
    
    Args:
        request: Execution request
        config: Risk configuration
        broker_registry: Broker registry (for existing positions)
        
    Returns:
        Risk decision
    """
    try:
        # PHASE 3: Get existing positions from broker registry
        aggregated_positions = broker_registry.aggregate_positions()
        existing_exposure = aggregated_positions.get("total_exposure_by_symbol", {})
        
        # PHASE 3: Count existing positions (non-zero exposure)
        current_position_count = sum(
            1 for exposure in existing_exposure.values()
            if abs(exposure.get("total_shares", 0.0)) > 0
        )
        
        # PHASE 3: Check if this would create a new position
        symbol = ctx.symbol
        symbol_exposure = existing_exposure.get(symbol, {})
        symbol_shares = abs(symbol_exposure.get("total_shares", 0.0))
        
        if symbol_shares == 0:
            # This would create a new position
            new_position_count = current_position_count + 1
        else:
            # This modifies an existing position
            new_position_count = current_position_count
        
        # PHASE 2: Check max open positions
        if new_position_count > config.max_open_positions:
            return RiskDecision(
                approved=False,
                reason=f"Position count would exceed limit: {new_position_count} > {config.max_open_positions}",
                violated_rule=RiskRule.MAX_OPEN_POSITIONS,
                context={
                    "current_position_count": current_position_count,
                    "new_position_count": new_position_count,
                    "limit": config.max_open_positions,
                    "symbol": symbol,
                    "is_new_position": symbol_shares == 0,
                }
            )
        
        # PHASE 2: Position count check passed
        return RiskDecision(
            approved=True,
            reason="Position count within limit",
            violated_rule=None,
            context={
                "current_position_count": current_position_count,
                "new_position_count": new_position_count,
            }
        )
        
    except Exception as e:
        # PHASE 2: Fail closed - reject on error
        logger.error(f"Position count check error: {e}", exc_info=True)
        return RiskDecision(
            approved=False,
            reason=f"Position count check failed: {str(e)}",
            violated_rule=RiskRule.MAX_OPEN_POSITIONS,
            context={"error": str(e)}
        )
