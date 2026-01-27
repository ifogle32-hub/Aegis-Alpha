"""
PHASE 7: Auto-Generation Governance Limits

Add hard caps:
- Max strategies
- Max variants per seed
- Max trades per strategy
- Global risk ceiling

If breached:
- Disable generation
- Log violation
- Continue training safely

SAFETY: Training-only
SAFETY: No execution behavior modified
REGRESSION LOCK — DO NOT EXPAND WITHOUT REVIEW
"""
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime
from sentinel_x.monitoring.logger import logger


@dataclass
class GovernanceLimits:
    """
    PHASE 3-7: Governance limits for auto-generation.
    
    Hard caps to prevent runaway strategy generation.
    
    PHASE 3: Auto-generation governance limits
    - MAX_SEED_STRATEGIES: Max seed strategies to track
    - MAX_VARIANTS_PER_SEED: Max variants per seed strategy
    - MAX_TOTAL_STRATEGIES: Max total strategies (hard cap)
    """
    max_strategies: int = 100  # Max total strategies
    max_variants_per_seed: int = 10  # Max variants per seed strategy
    max_trades_per_strategy: int = 1000  # Max trades per strategy (rolling window)
    global_risk_ceiling: float = 0.5  # Max total risk allocation (50%)
    max_position_size: float = 0.1  # Max position size per strategy (10%)
    max_daily_loss: float = 0.05  # Max daily loss per strategy (5%)
    max_seed_strategies: int = 10  # PHASE 3: Max seed strategies to track


class StrategyGovernance:
    """
    PHASE 7: Strategy Governance Manager
    
    Enforces hard caps on strategy generation and trading.
    If breached: disables generation, logs violation, continues safely.
    """
    
    def __init__(self, limits: Optional[GovernanceLimits] = None):
        """
        Initialize governance manager.
        
        Args:
            limits: GovernanceLimits (default: conservative)
        """
        self.limits = limits or GovernanceLimits()
        self.violations: list = []  # Track governance violations
        
        logger.info(f"StrategyGovernance initialized: "
                   f"max_strategies={self.limits.max_strategies}, "
                   f"max_variants_per_seed={self.limits.max_variants_per_seed}, "
                   f"max_trades_per_strategy={self.limits.max_trades_per_strategy}")
    
    def check_strategy_count(self, current_count: int) -> tuple:
        """
        Check if strategy count is within limits.
        
        Args:
            current_count: Current number of strategies
            
        Returns:
            (is_allowed, violation_message)
        """
        if current_count >= self.limits.max_strategies:
            violation = f"Max strategies limit breached: {current_count} >= {self.limits.max_strategies}"
            self._log_violation(violation)
            return False, violation
        return True, None
    
    def check_variant_count(self, seed_name: str, variant_count: int) -> tuple:
        """
        Check if variant count for seed is within limits.
        
        Args:
            seed_name: Seed strategy name
            variant_count: Current variant count for seed
            
        Returns:
            (is_allowed, violation_message)
        """
        if variant_count >= self.limits.max_variants_per_seed:
            violation = f"Max variants per seed breached: {seed_name} has {variant_count} >= {self.limits.max_variants_per_seed}"
            self._log_violation(violation)
            return False, violation
        return True, None
    
    def check_trades_per_strategy(self, strategy_name: str, trade_count: int) -> tuple:
        """
        Check if trade count for strategy is within limits.
        
        Args:
            strategy_name: Strategy name
            trade_count: Current trade count (rolling window)
            
        Returns:
            (is_allowed, violation_message)
        """
        if trade_count >= self.limits.max_trades_per_strategy:
            violation = f"Max trades per strategy breached: {strategy_name} has {trade_count} >= {self.limits.max_trades_per_strategy}"
            self._log_violation(violation)
            return False, violation
        return True, None
    
    def check_risk_ceiling(self, total_risk_allocation: float) -> tuple:
        """
        Check if total risk allocation is within global ceiling.
        
        Args:
            total_risk_allocation: Total risk allocation (sum of all strategies)
            
        Returns:
            (is_allowed, violation_message)
        """
        if total_risk_allocation > self.limits.global_risk_ceiling:
            violation = f"Global risk ceiling breached: {total_risk_allocation:.2%} > {self.limits.global_risk_ceiling:.2%}"
            self._log_violation(violation)
            return False, violation
        return True, None
    
    def check_position_size(self, position_size: float) -> tuple:
        """
        Check if position size is within limits.
        
        Args:
            position_size: Position size as fraction of capital
            
        Returns:
            (is_allowed, violation_message)
        """
        if position_size > self.limits.max_position_size:
            violation = f"Position size limit breached: {position_size:.2%} > {self.limits.max_position_size:.2%}"
            self._log_violation(violation)
            return False, violation
        return True, None
    
    def check_daily_loss(self, daily_loss: float) -> tuple:
        """
        Check if daily loss is within limits.
        
        Args:
            daily_loss: Daily loss as fraction of capital
            
        Returns:
            (is_allowed, violation_message)
        """
        if daily_loss > self.limits.max_daily_loss:
            violation = f"Daily loss limit breached: {daily_loss:.2%} > {self.limits.max_daily_loss:.2%}"
            self._log_violation(violation)
            return False, violation
        return True, None
    
    def _log_violation(self, violation: str) -> None:
        """
        Log governance violation.
        
        SAFETY: Logs violation but continues training safely.
        No blocking, no auto-restarts, no execution behavior modified.
        
        Args:
            violation: Violation message
        """
        timestamp = datetime.utcnow().isoformat()
        violation_record = {
            'timestamp': timestamp,
            'violation': violation,
            'limits': {
                'max_strategies': self.limits.max_strategies,
                'max_variants_per_seed': self.limits.max_variants_per_seed,
                'max_trades_per_strategy': self.limits.max_trades_per_strategy,
                'global_risk_ceiling': self.limits.global_risk_ceiling,
                'max_position_size': self.limits.max_position_size,
                'max_daily_loss': self.limits.max_daily_loss,
            }
        }
        self.violations.append(violation_record)
        
        logger.warning(f"GOVERNANCE VIOLATION: {violation}")
        logger.info(f"Generation disabled due to governance limit. Training continues safely.")
    
    def get_violations(self) -> list:
        """Get list of governance violations."""
        return self.violations.copy()
    
    def has_violations(self) -> bool:
        """Check if any violations occurred."""
        return len(self.violations) > 0
    
    def check_seed_count(self, seed_count: int) -> tuple:
        """
        PHASE 3: Check if seed strategy count is within limits.
        
        Args:
            seed_count: Current seed strategy count
            
        Returns:
            (is_allowed, violation_message)
        """
        if seed_count >= self.limits.max_seed_strategies:
            violation = f"Max seed strategies limit breached: {seed_count} >= {self.limits.max_seed_strategies}"
            self._log_violation(violation)
            return False, violation
        return True, None
    
    def can_generate(self, current_strategy_count: int, seed_name: Optional[str] = None,
                     variant_count: Optional[int] = None, seed_count: Optional[int] = None) -> tuple:
        """
        PHASE 3: Check if generation is allowed (all checks).
        
        Args:
            current_strategy_count: Current total strategy count
            seed_name: Seed strategy name (optional)
            variant_count: Variant count for seed (optional)
            seed_count: Current seed strategy count (optional)
            
        Returns:
            (is_allowed, violation_message)
        """
        # Check strategy count
        allowed, violation = self.check_strategy_count(current_strategy_count)
        if not allowed:
            return False, violation
        
        # PHASE 3: Check seed count if provided
        if seed_count is not None:
            allowed, violation = self.check_seed_count(seed_count)
            if not allowed:
                return False, violation
        
        # Check variant count if seed provided
        if seed_name is not None and variant_count is not None:
            allowed, violation = self.check_variant_count(seed_name, variant_count)
            if not allowed:
                return False, violation
        
        return True, None


# Global governance instance
_governance: Optional[StrategyGovernance] = None


def get_governance(limits: Optional[GovernanceLimits] = None) -> StrategyGovernance:
    """Get global governance instance."""
    global _governance
    if _governance is None:
        _governance = StrategyGovernance(limits)
    return _governance
