"""
Symbol Allowlist Rule

PHASE 2 — SYMBOL ALLOWLIST

Enforces symbol allowlist (trade only approved symbols).
"""

from api.risk.types import RiskContext
from api.risk.engine import RiskDecision, RiskRule
from api.risk.config import RiskConfig

try:
    from sentinel_x.monitoring.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


def check_symbol_allowlist(
    ctx: RiskContext,
    config: RiskConfig
) -> RiskDecision:
    """
    PHASE 2 — SYMBOL ALLOWLIST CHECK
    
    Check if symbol is in allowlist.
    
    Args:
        request: Execution request
        config: Risk configuration
        
    Returns:
        Risk decision
    """
    try:
        symbol = ctx.symbol.upper()  # Normalize to uppercase
        
        # PHASE 2: Check if symbol is in allowlist
        if symbol not in config.allowed_symbols:
            return RiskDecision(
                approved=False,
                reason=f"Symbol not in allowlist: {symbol}",
                violated_rule=RiskRule.SYMBOL_ALLOWLIST,
                context={
                    "symbol": symbol,
                    "allowed_symbols": config.allowed_symbols,
                }
            )
        
        # PHASE 2: Symbol allowlist check passed
        return RiskDecision(
            approved=True,
            reason="Symbol in allowlist",
            violated_rule=None,
            context={
                "symbol": symbol,
            }
        )
        
    except Exception as e:
        # PHASE 2: Fail closed - reject on error
        logger.error(f"Symbol allowlist check error: {e}", exc_info=True)
        return RiskDecision(
            approved=False,
            reason=f"Symbol allowlist check failed: {str(e)}",
            violated_rule=RiskRule.SYMBOL_ALLOWLIST,
            context={"error": str(e)}
        )
