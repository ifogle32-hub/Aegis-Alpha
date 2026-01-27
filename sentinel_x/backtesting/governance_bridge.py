"""
PHASE 8 — GOVERNANCE BRIDGE (BACKTEST → PROMOTION)

SAFETY: OFFLINE BACKTEST ENGINE
SAFETY: promotion logic remains training-only
REGRESSION LOCK — BACKTEST GOVERNANCE BRIDGE

Wire backtest results into Promotion/Demotion logic.

Rules:
- Backtest results are ADVISORY
- Live training metrics still required
- Promotion requires BOTH:
  - backtest_score >= threshold
  - live_training_score >= threshold

Implement:
PromotionEvaluator.merge(backtest_metrics, live_metrics)

Add penalties if:
- Backtest strong but live weak
- Live strong but backtest fragile
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

# SAFETY: OFFLINE BACKTEST ENGINE
# SAFETY: promotion logic remains training-only
# REGRESSION LOCK — BACKTEST GOVERNANCE BRIDGE

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class BacktestMetrics:
    """
    PHASE 7: Backtest metrics (immutable, read-only).
    
    SAFETY: backtest metrics are advisory only
    """
    strategy_name: str
    trades_count: int
    realized_pnl: float
    win_rate: float
    expectancy: float
    sharpe: Optional[float] = None
    max_drawdown: float = 0.0
    total_return: float = 0.0
    volatility: Optional[float] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class LiveTrainingMetrics:
    """
    PHASE 8: Live training metrics (from strategy manager).
    
    SAFETY: live metrics from training-only execution
    """
    strategy_name: str
    trades_count: int
    realized_pnl: float
    win_rate: float
    expectancy: float
    sharpe: Optional[float] = None
    max_drawdown: float = 0.0
    composite_score: float = 0.0
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class MergedPromotionScore:
    """
    PHASE 8: Merged promotion score combining backtest + live metrics.
    
    SAFETY: advisory only, training-only promotion
    """
    strategy_name: str
    backtest_score: float
    live_training_score: float
    merged_score: float
    backtest_penalty: float = 0.0
    live_penalty: float = 0.0
    promotion_eligible: bool = False
    notes: List[str] = None
    
    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class PromotionEvaluator:
    """
    PHASE 8: Promotion evaluator that merges backtest + live metrics.
    
    SAFETY: offline backtesting only
    SAFETY: promotion logic remains training-only
    REGRESSION LOCK — BACKTEST GOVERNANCE BRIDGE
    
    Rules:
    - Backtest results are ADVISORY
    - Live training metrics still required
    - Promotion requires BOTH backtest_score >= threshold AND live_training_score >= threshold
    - Add penalties if backtest strong but live weak, or vice versa
    """
    
    def __init__(self,
                 backtest_threshold: float = 0.6,  # Minimum backtest score
                 live_threshold: float = 0.6,  # Minimum live training score
                 merged_threshold: float = 0.65,  # Minimum merged score
                 backtest_weight: float = 0.4,  # Weight for backtest metrics
                 live_weight: float = 0.6,  # Weight for live metrics
                 divergence_penalty: float = 0.2):  # Penalty for divergence
        """
        Initialize promotion evaluator.
        
        Args:
            backtest_threshold: Minimum backtest score for promotion consideration
            live_threshold: Minimum live training score for promotion consideration
            merged_threshold: Minimum merged score for promotion
            backtest_weight: Weight for backtest metrics in merged score
            live_weight: Weight for live metrics in merged score
            divergence_penalty: Penalty factor for backtest/live divergence
        """
        self.backtest_threshold = backtest_threshold
        self.live_threshold = live_threshold
        self.merged_threshold = merged_threshold
        self.backtest_weight = backtest_weight
        self.live_weight = live_weight
        self.divergence_penalty = divergence_penalty
        
        logger.info(f"PromotionEvaluator initialized: backtest_threshold={backtest_threshold}, "
                   f"live_threshold={live_threshold}, merged_threshold={merged_threshold}, "
                   f"backtest_weight={backtest_weight}, live_weight={live_weight}")
    
    def normalize_score(self, metrics: Dict[str, Any]) -> float:
        """
        PHASE 8: Normalize metrics into a score (0.0-1.0).
        
        SAFETY: advisory only
        """
        # Simple normalization: composite of key metrics
        win_rate = metrics.get('win_rate', 0.0)
        expectancy = max(0.0, metrics.get('expectancy', 0.0)) / 100.0  # Normalize expectancy
        sharpe = max(0.0, metrics.get('sharpe', 0.0)) / 3.0 if metrics.get('sharpe') else 0.5  # Normalize Sharpe
        drawdown_penalty = max(0.0, 1.0 - metrics.get('max_drawdown', 0.0))
        
        # Composite score
        score = (win_rate * 0.3 + expectancy * 0.3 + sharpe * 0.2 + drawdown_penalty * 0.2)
        return min(1.0, max(0.0, score))
    
    def merge(self, backtest_metrics: Optional[BacktestMetrics], 
              live_metrics: LiveTrainingMetrics) -> MergedPromotionScore:
        """
        PHASE 8: Merge backtest and live metrics into promotion score.
        
        SAFETY: advisory only
        SAFETY: promotion logic remains training-only
        
        Rules:
        - Backtest results are ADVISORY
        - Live training metrics still required
        - Promotion requires BOTH backtest_score >= threshold AND live_training_score >= threshold
        - Add penalties if backtest strong but live weak, or vice versa
        
        Args:
            backtest_metrics: Backtest metrics (optional)
            live_metrics: Live training metrics (required)
        
        Returns:
            MergedPromotionScore
        """
        strategy_name = live_metrics.strategy_name
        
        # Calculate live training score
        live_score = self.normalize_score({
            'win_rate': live_metrics.win_rate,
            'expectancy': live_metrics.expectancy,
            'sharpe': live_metrics.sharpe,
            'max_drawdown': live_metrics.max_drawdown,
            'composite_score': live_metrics.composite_score
        })
        
        # Use live composite_score if available (from strategy_manager)
        if live_metrics.composite_score > 0:
            live_score = live_metrics.composite_score / 10.0  # Normalize if composite_score is on different scale
            live_score = min(1.0, max(0.0, live_score))
        
        # Calculate backtest score (if available)
        backtest_score = 0.0
        backtest_penalty = 0.0
        live_penalty = 0.0
        notes = []
        
        if backtest_metrics:
            backtest_score = self.normalize_score({
                'win_rate': backtest_metrics.win_rate,
                'expectancy': backtest_metrics.expectancy,
                'sharpe': backtest_metrics.sharpe,
                'max_drawdown': backtest_metrics.max_drawdown
            })
            
            # PHASE 8: Check for divergence and apply penalties
            divergence = abs(backtest_score - live_score)
            
            if divergence > 0.3:  # Significant divergence
                if backtest_score > live_score:
                    # Backtest strong but live weak
                    live_penalty = self.divergence_penalty * divergence
                    notes.append(f"Live performance weaker than backtest (divergence={divergence:.2f})")
                else:
                    # Live strong but backtest fragile
                    backtest_penalty = self.divergence_penalty * divergence
                    notes.append(f"Backtest performance weaker than live (divergence={divergence:.2f})")
            
            # Check if backtest has sufficient trades
            if backtest_metrics.trades_count < 20:
                backtest_penalty += 0.1
                notes.append(f"Backtest has insufficient trades ({backtest_metrics.trades_count})")
        else:
            # No backtest metrics - apply penalty
            backtest_score = 0.0
            backtest_penalty = 0.15  # Penalty for missing backtest
            notes.append("No backtest metrics available")
        
        # Apply penalties
        adjusted_backtest_score = max(0.0, backtest_score - backtest_penalty)
        adjusted_live_score = max(0.0, live_score - live_penalty)
        
        # PHASE 8: Calculate merged score (weighted combination)
        merged_score = (adjusted_backtest_score * self.backtest_weight + 
                       adjusted_live_score * self.live_weight)
        
        # PHASE 8: Promotion eligibility requires BOTH thresholds
        backtest_meets_threshold = adjusted_backtest_score >= self.backtest_threshold
        live_meets_threshold = adjusted_live_score >= self.live_threshold
        merged_meets_threshold = merged_score >= self.merged_threshold
        
        promotion_eligible = (backtest_meets_threshold and 
                             live_meets_threshold and 
                             merged_meets_threshold)
        
        if not promotion_eligible:
            if not backtest_meets_threshold:
                notes.append(f"Backtest score {adjusted_backtest_score:.2f} < threshold {self.backtest_threshold}")
            if not live_meets_threshold:
                notes.append(f"Live score {adjusted_live_score:.2f} < threshold {self.live_threshold}")
            if not merged_meets_threshold:
                notes.append(f"Merged score {merged_score:.2f} < threshold {self.merged_threshold}")
        
        result = MergedPromotionScore(
            strategy_name=strategy_name,
            backtest_score=adjusted_backtest_score,
            live_training_score=adjusted_live_score,
            merged_score=merged_score,
            backtest_penalty=backtest_penalty,
            live_penalty=live_penalty,
            promotion_eligible=promotion_eligible,
            notes=notes
        )
        
        logger.info(f"Merged promotion score for {strategy_name}: "
                   f"backtest={adjusted_backtest_score:.2f}, live={adjusted_live_score:.2f}, "
                   f"merged={merged_score:.2f}, eligible={promotion_eligible}")
        
        return result
    
    def should_promote(self, backtest_metrics: Optional[BacktestMetrics],
                      live_metrics: LiveTrainingMetrics) -> bool:
        """
        PHASE 8: Determine if strategy should be promoted.
        
        SAFETY: advisory only
        SAFETY: promotion logic remains training-only
        
        Returns:
            True if promotion criteria are met
        """
        merged_score = self.merge(backtest_metrics, live_metrics)
        return merged_score.promotion_eligible
    
    def should_demote(self, backtest_metrics: Optional[BacktestMetrics],
                     live_metrics: LiveTrainingMetrics) -> bool:
        """
        PHASE 8: Determine if strategy should be demoted.
        
        SAFETY: advisory only
        SAFETY: demotion logic remains training-only
        
        Returns:
            True if demotion criteria are met
        """
        merged_score = self.merge(backtest_metrics, live_metrics)
        
        # Demote if merged score is very low
        demotion_threshold = 0.2
        if merged_score.merged_score < demotion_threshold:
            return True
        
        # Demote if both scores are below minimum thresholds
        if (merged_score.backtest_score < 0.3 and merged_score.live_training_score < 0.3):
            return True
        
        return False


# Global promotion evaluator instance
_promotion_evaluator: Optional[PromotionEvaluator] = None


def get_promotion_evaluator() -> Optional[PromotionEvaluator]:
    """
    PHASE 8: Get global promotion evaluator instance.
    
    SAFETY: advisory only
    """
    global _promotion_evaluator
    if _promotion_evaluator is None:
        _promotion_evaluator = PromotionEvaluator()
    return _promotion_evaluator
