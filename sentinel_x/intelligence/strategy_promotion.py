"""
PHASE 3: Strategy Promotion Pipeline

Rules:
- Promotion criteria configurable:
  – Positive expectancy
  – Drawdown below threshold
  – Sufficient sample size
- Promotions only affect PAPER strategies
- LIVE strategies must be manually approved
- Demotions are automatic on failure

Emit events:
{
  type: "strategy_promoted",
  from,
  to,
  reason,
  timestamp
}
"""
import asyncio
from typing import Dict, Optional, List
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.event_bus import get_event_bus
from sentinel_x.monitoring.pnl import get_pnl_engine
from sentinel_x.intelligence.strategy_manager import StrategyStatus
from sentinel_x.utils import safe_emit


class PromotionLevel(Enum):
    """Strategy promotion levels."""
    DISABLED = "DISABLED"
    PAPER_TESTING = "PAPER_TESTING"  # Newly generated, testing in paper
    PAPER_ACTIVE = "PAPER_ACTIVE"    # Proven in paper, active
    LIVE_APPROVED = "LIVE_APPROVED"  # Manually approved for live


@dataclass
class PromotionCriteria:
    """Criteria for strategy promotion."""
    min_trades: int = 20  # Minimum trades for promotion
    min_win_rate: float = 0.5  # Minimum win rate
    min_expectancy: float = 0.0  # Minimum expectancy (positive)
    max_drawdown: float = 0.15  # Maximum drawdown allowed
    min_sharpe: Optional[float] = None  # Minimum Sharpe ratio (optional)
    min_profit_factor: Optional[float] = None  # Minimum profit factor (optional)


class StrategyPromotionPipeline:
    """
    Strategy promotion pipeline with configurable criteria.
    
    Promotions only affect PAPER strategies.
    LIVE requires explicit manual approval.
    """
    
    def __init__(self, criteria: Optional[PromotionCriteria] = None, pnl_engine=None):
        """
        Initialize promotion pipeline.
        
        Args:
            criteria: Promotion criteria (default: conservative)
            pnl_engine: PnL engine for metrics (optional)
        """
        self.criteria = criteria or PromotionCriteria()
        self.pnl_engine = pnl_engine or get_pnl_engine()
        self.event_bus = get_event_bus()
        
        # Track promotion history
        self.promotion_history: Dict[str, List[Dict]] = {}
        
        logger.info(f"StrategyPromotionPipeline initialized: "
                   f"min_trades={self.criteria.min_trades}, "
                   f"min_win_rate={self.criteria.min_win_rate}, "
                   f"max_drawdown={self.criteria.max_drawdown}")
    
    def check_promotion_eligibility(self, strategy_name: str) -> Dict[str, any]:
        """
        Check if strategy is eligible for promotion.
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            Dict with eligible, reason, current_level, target_level
        """
        try:
            metrics = self.pnl_engine.get_strategy_metrics(strategy_name)
            
            trades_count = metrics.get('trades_count', 0)
            win_rate = metrics.get('win_rate', 0.0)
            realized_pnl = metrics.get('realized_pnl', 0.0)
            max_drawdown = metrics.get('max_drawdown', 0.0)
            
            # Calculate expectancy (simplified: avg return per trade)
            expectancy = realized_pnl / trades_count if trades_count > 0 else 0.0
            
            # Check criteria
            eligible = True
            reasons = []
            
            if trades_count < self.criteria.min_trades:
                eligible = False
                reasons.append(f"insufficient_trades: {trades_count} < {self.criteria.min_trades}")
            
            if win_rate < self.criteria.min_win_rate:
                eligible = False
                reasons.append(f"low_win_rate: {win_rate:.2%} < {self.criteria.min_win_rate:.2%}")
            
            if expectancy < self.criteria.min_expectancy:
                eligible = False
                reasons.append(f"negative_expectancy: {expectancy:.2f} < {self.criteria.min_expectancy}")
            
            if max_drawdown > self.criteria.max_drawdown:
                eligible = False
                reasons.append(f"high_drawdown: {max_drawdown:.2%} > {self.criteria.max_drawdown:.2%}")
            
            if self.criteria.min_sharpe is not None:
                # Would need to calculate Sharpe from returns
                pass  # TODO: Add Sharpe calculation
            
            if self.criteria.min_profit_factor is not None:
                # Would need wins/losses to calculate
                wins = metrics.get('wins', 0)
                losses = metrics.get('losses', 0)
                if losses > 0:
                    profit_factor = wins / losses
                    if profit_factor < self.criteria.min_profit_factor:
                        eligible = False
                        reasons.append(f"low_profit_factor: {profit_factor:.2f} < {self.criteria.min_profit_factor}")
            
            # PHASE 4: Promotion gates MUST include execution quality
            execution_gate_passed = True
            execution_reasons = []
            try:
                from sentinel_x.execution.execution_metrics import get_execution_metrics_tracker
                metrics_tracker = get_execution_metrics_tracker()
                execution_metrics = metrics_tracker.get_latest_metrics(strategy_name)
                
                if execution_metrics:
                    # Gate 1: Stable execution metrics (slippage variance < 100 bps)
                    if execution_metrics.slippage_variance > 100.0:
                        execution_gate_passed = False
                        execution_reasons.append(f"high_slippage_variance:{execution_metrics.slippage_variance:.2f}bps")
                    
                    # Gate 2: Acceptable latency (< 500ms average, < 200ms std dev)
                    if execution_metrics.avg_latency_ms > 500.0:
                        execution_gate_passed = False
                        execution_reasons.append(f"high_latency:{execution_metrics.avg_latency_ms:.2f}ms")
                    
                    if execution_metrics.latency_std_ms > 200.0:
                        execution_gate_passed = False
                        execution_reasons.append(f"high_latency_variance:{execution_metrics.latency_std_ms:.2f}ms")
                    
                    # Gate 3: Minimum execution quality score (>= 0.7)
                    if execution_metrics.execution_quality_score < 0.7:
                        execution_gate_passed = False
                        execution_reasons.append(f"low_execution_quality:{execution_metrics.execution_quality_score:.2f}")
                else:
                    # No execution metrics available - require them for promotion
                    execution_gate_passed = False
                    execution_reasons.append("no_execution_metrics_available")
                    
            except Exception as e:
                logger.debug(f"Error checking execution gates (non-fatal): {e}")
                # If we can't check execution gates, fail open safely (don't promote)
                execution_gate_passed = False
                execution_reasons.append(f"execution_gate_check_error:{str(e)}")
            
            # PHASE 4: Execution gates are mandatory for promotion
            if not execution_gate_passed:
                eligible = False
                reasons.extend([f"execution_gate:{r}" for r in execution_reasons])
            
            return {
                'eligible': eligible,
                'reason': '; '.join(reasons) if reasons else 'all_criteria_met',
                'current_level': 'PAPER_TESTING',  # Would get from strategy manager
                'target_level': 'PAPER_ACTIVE' if eligible else None,
                'execution_gate_passed': execution_gate_passed,
                'execution_gate_reasons': execution_reasons,
                'metrics': {
                    'trades_count': trades_count,
                    'win_rate': win_rate,
                    'expectancy': expectancy,
                    'max_drawdown': max_drawdown,
                    'execution_quality_score': execution_metrics.execution_quality_score if execution_metrics else None
                }
            }
        
        except Exception as e:
            logger.error(f"Error checking promotion eligibility for {strategy_name}: {e}", exc_info=True)
            return {
                'eligible': False,
                'reason': f'error: {str(e)}',
                'current_level': None,
                'target_level': None,
                'metrics': {}
            }
    
    def promote_to_paper_active(self, strategy_name: str, 
                               strategy_manager=None) -> bool:
        """
        Promote strategy to PAPER_ACTIVE (requires eligibility check).
        
        Args:
            strategy_name: Strategy name
            strategy_manager: Strategy manager instance (optional)
            
        Returns:
            True if promoted, False otherwise
        """
        try:
            # Check eligibility
            eligibility = self.check_promotion_eligibility(strategy_name)
            if not eligibility['eligible']:
                logger.warning(f"Strategy {strategy_name} not eligible for promotion: {eligibility['reason']}")
                return False
            
            # Promote in strategy manager
            if strategy_manager:
                # Set status to ACTIVE (PAPER)
                strategy_manager.status[strategy_name] = StrategyStatus.ACTIVE
                logger.info(f"Promoted {strategy_name} to PAPER_ACTIVE")
            
            # Record promotion
            self._record_promotion(strategy_name, 'PAPER_TESTING', 'PAPER_ACTIVE', eligibility['reason'])
            
            # Emit event
            self._emit_promotion_event(strategy_name, 'PAPER_TESTING', 'PAPER_ACTIVE', eligibility['reason'])
            
            return True
        
        except Exception as e:
            logger.error(f"Error promoting strategy {strategy_name}: {e}", exc_info=True)
            return False
    
    def promote_to_live(self, strategy_name: str, 
                       strategy_manager=None,
                       require_approval: bool = True) -> bool:
        """
        Promote strategy to LIVE (requires explicit approval).
        
        Args:
            strategy_name: Strategy name
            strategy_manager: Strategy manager instance (optional)
            require_approval: Whether to require explicit approval (default: True)
            
        Returns:
            True if promoted, False otherwise
        """
        try:
            # SAFETY: LIVE promotion always requires explicit approval
            if require_approval:
                # In production, this would require operator confirmation
                # For now, we log a warning
                logger.warning(f"LIVE promotion for {strategy_name} requires explicit operator approval")
                return False
            
            # Check eligibility (stricter criteria for LIVE)
            eligibility = self.check_promotion_eligibility(strategy_name)
            if not eligibility['eligible']:
                logger.warning(f"Strategy {strategy_name} not eligible for LIVE: {eligibility['reason']}")
                return False
            
            # Promote in strategy manager
            if strategy_manager:
                # Mark as LIVE (would need LIVE status in strategy manager)
                logger.info(f"Promoted {strategy_name} to LIVE_APPROVED")
            
            # Record promotion
            self._record_promotion(strategy_name, 'PAPER_ACTIVE', 'LIVE_APPROVED', eligibility['reason'])
            
            # Emit event
            self._emit_promotion_event(strategy_name, 'PAPER_ACTIVE', 'LIVE_APPROVED', eligibility['reason'])
            
            return True
        
        except Exception as e:
            logger.error(f"Error promoting strategy {strategy_name} to LIVE: {e}", exc_info=True)
            return False
    
    def demote_strategy(self, strategy_name: str, 
                       reason: str,
                       strategy_manager=None) -> bool:
        """
        Demote strategy (automatic on failure).
        
        Args:
            strategy_name: Strategy name
            reason: Demotion reason
            strategy_manager: Strategy manager instance (optional)
            
        Returns:
            True if demoted, False otherwise
        """
        try:
            # Demote in strategy manager
            if strategy_manager:
                strategy_manager.status[strategy_name] = StrategyStatus.DISABLED
                logger.info(f"Demoted {strategy_name}: {reason}")
            
            # Record demotion
            self._record_promotion(strategy_name, 'PAPER_ACTIVE', 'DISABLED', reason)
            
            # Emit event
            self._emit_promotion_event(strategy_name, 'PAPER_ACTIVE', 'DISABLED', reason)
            
            return True
        
        except Exception as e:
            logger.error(f"Error demoting strategy {strategy_name}: {e}", exc_info=True)
            return False
    
    def _record_promotion(self, strategy_name: str, from_level: str, 
                         to_level: str, reason: str) -> None:
        """Record promotion in history."""
        if strategy_name not in self.promotion_history:
            self.promotion_history[strategy_name] = []
        
        self.promotion_history[strategy_name].append({
            'from': from_level,
            'to': to_level,
            'reason': reason,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    def _emit_promotion_event(self, strategy_name: str, from_level: str,
                             to_level: str, reason: str) -> None:
        """Emit promotion event (non-blocking)."""
        try:
            event = {
                'type': 'strategy_promoted',
                'strategy': strategy_name,
                'from': from_level,
                'to': to_level,
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }
            safe_emit(self.event_bus.publish(event))
        except Exception as e:
            logger.error(f"Error emitting promotion event: {e}", exc_info=True)
    
    def get_promotion_history(self, strategy_name: str) -> List[Dict]:
        """Get promotion history for a strategy."""
        return self.promotion_history.get(strategy_name, [])


# Global promotion pipeline instance
_promotion_pipeline: Optional[StrategyPromotionPipeline] = None


def get_promotion_pipeline(criteria: Optional[PromotionCriteria] = None,
                          pnl_engine=None) -> StrategyPromotionPipeline:
    """Get global promotion pipeline instance."""
    global _promotion_pipeline
    if _promotion_pipeline is None:
        _promotion_pipeline = StrategyPromotionPipeline(criteria, pnl_engine)
    return _promotion_pipeline
