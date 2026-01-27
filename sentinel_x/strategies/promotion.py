"""
PHASE 5 — STRATEGY PROMOTION ENGINE

Deterministic, safety-locked strategy promotion engine.
ONLY adjusts allocation_weight - never changes strategy lifecycle or enabled state.

REGRESSION LOCK:
- Strategy promotion is allocation-only
- Promotion affects ALLOCATION ONLY
- Demotion never deletes strategies
- NO strategy enable/disable here
- NO strategy creation here
- NO order sizing changes
- ONLY allocation_weight adjustment

SAFETY LOCKS:
- NO trading behavior changes
- NO LIVE trading unlocks
- NO strategy auto-creation
- Promotion runs in TRAINING mode ONLY
"""

from typing import List
from sentinel_x.monitoring.logger import logger


class StrategyPromotionEngine:
    """
    PHASE 5 — STRATEGY PROMOTION ENGINE
    
    Deterministic promotion engine that adjusts allocation weights only.
    
    SAFETY LOCKS:
    - NO strategy enable/disable
    - NO strategy creation
    - NO order sizing changes
    - ONLY allocation_weight adjustment
    
    REGRESSION LOCK:
    - Promotion affects ALLOCATION ONLY
    - Demotion never deletes strategies
    - WebSockets are READ-ONLY
    - All logic is deterministic and auditable
    """
    
    def __init__(self):
        """
        Initialize promotion engine with conservative thresholds.
        
        SAFETY: Conservative thresholds ensure gradual weight adjustments
        """
        self.min_trades = 30  # Minimum trades required for promotion evaluation
        self.min_win_rate = 0.55  # Minimum win rate (55%)
        self.max_drawdown = -0.15  # Maximum drawdown allowed (-15%)
        
        logger.info(
            f"StrategyPromotionEngine initialized: "
            f"min_trades={self.min_trades}, "
            f"min_win_rate={self.min_win_rate}, "
            f"max_drawdown={self.max_drawdown}"
        )
    
    def evaluate(self, strategies: List) -> None:
        """
        PHASE 5 — Evaluate strategies and adjust allocation weights.
        
        SAFETY LOCKS:
        - NO strategy enable/disable
        - NO strategy creation
        - NO order sizing changes
        - ONLY allocation_weight adjustment
        
        Rules:
        - Strategies with min_trades >= 30 are evaluated
        - If win_rate >= 0.55 and pnl > 0: increase weight by 10% (max 3.0)
        - Otherwise: decrease weight by 10% (min 0.2)
        - Drawdown check: if drawdown > 0.15, decrease weight
        
        Args:
            strategies: List of strategy instances (BaseStrategy)
        
        Returns:
            None (modifies strategies in-place, allocation_weight only)
        """
        try:
            allocations_adjusted = {}
            
            for strat in strategies:
                try:
                    # PHASE 5: Skip strategies with insufficient trades
                    if not hasattr(strat, 'trades') or strat.trades < self.min_trades:
                        continue
                    
                    # PHASE 5: Calculate metrics (safe attribute access)
                    trades = getattr(strat, 'trades', 0)
                    wins = getattr(strat, 'wins', 0)
                    losses = getattr(strat, 'losses', 0)
                    pnl_realized = getattr(strat, 'pnl_realized', 0.0)
                    pnl_unrealized = getattr(strat, 'pnl_unrealized', 0.0)
                    current_weight = getattr(strat, 'allocation_weight', 1.0)
                    
                    # Calculate derived metrics
                    pnl_total = pnl_realized + pnl_unrealized
                    win_rate = (wins / trades) if trades > 0 else 0.0
                    
                    # Calculate drawdown (simplified: use max unrealized loss as proxy)
                    # For a more accurate drawdown, we'd need equity curve history
                    drawdown = abs(min(pnl_unrealized, 0.0)) / max(abs(pnl_total), 1.0) if pnl_total != 0 else 0.0
                    
                    # PHASE 5: Promotion logic (deterministic, allocation-only)
                    new_weight = current_weight
                    
                    # Check drawdown first (safety check)
                    if drawdown > self.max_drawdown:
                        # High drawdown: decrease weight
                        new_weight = max(current_weight * 0.9, 0.2)
                    elif win_rate >= self.min_win_rate and pnl_total > 0:
                        # Good performance: increase weight
                        new_weight = min(current_weight * 1.1, 3.0)
                    else:
                        # Below threshold: decrease weight
                        new_weight = max(current_weight * 0.9, 0.2)
                    
                    # PHASE 7: Safety locks - ONLY adjust allocation_weight
                    # NO strategy enable/disable
                    # NO strategy creation
                    # NO order sizing changes
                    if new_weight != current_weight:
                        strat.allocation_weight = new_weight
                        allocations_adjusted[strat.name] = {
                            'old_weight': current_weight,
                            'new_weight': new_weight,
                            'win_rate': win_rate,
                            'pnl_total': pnl_total,
                            'drawdown': drawdown
                        }
                
                except Exception as e:
                    # SAFETY: Skip broken strategies, continue with others
                    logger.debug(f"Error evaluating strategy {getattr(strat, 'name', 'unknown')}: {e}")
                    continue
            
            # PHASE 8: Log promotion cycle results (observability)
            if allocations_adjusted:
                logger.info(
                    "Strategy promotion cycle complete",
                    extra={
                        "allocations": {
                            name: metrics['new_weight']
                            for name, metrics in allocations_adjusted.items()
                        },
                        "adjustments": allocations_adjusted
                    }
                )
        
        except Exception as e:
            # SAFETY: Promotion engine failure must NOT affect trading
            logger.error(f"Error in promotion engine evaluation: {e}", exc_info=True)
