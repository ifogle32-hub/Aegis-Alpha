"""
PHASE 2: A/B Testing Harness

Group strategies into:
- Control
- Variant A
- Variant B

Capital split explicitly per group.
Metrics tracked independently.
Test duration configurable (trades or time).

Rules:
- No A/B test may promote itself
- Promotion requires explicit operator approval
- Poor variants auto-disabled
"""
import asyncio
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.event_bus import get_event_bus
from sentinel_x.monitoring.pnl import get_pnl_engine
from sentinel_x.utils import safe_emit


class TestGroup(Enum):
    """A/B test group."""
    CONTROL = "CONTROL"
    VARIANT_A = "VARIANT_A"
    VARIANT_B = "VARIANT_B"


@dataclass
class ABTestMetrics:
    """Metrics for an A/B test group."""
    group: TestGroup
    strategies: List[str] = field(default_factory=list)
    total_pnl: float = 0.0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    capital_allocated: float = 0.0  # Capital allocated to this group
    last_update: Optional[datetime] = None


@dataclass
class ABTest:
    """A/B test configuration and state."""
    test_id: str
    control_strategies: List[str]
    variant_a_strategies: List[str]
    variant_b_strategies: List[str]
    capital_split: Dict[TestGroup, float]  # Fraction of capital per group
    duration_trades: Optional[int] = None  # Test duration in trades
    duration_time: Optional[timedelta] = None  # Test duration in time
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    active: bool = True
    metrics: Dict[TestGroup, ABTestMetrics] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize metrics for each group."""
        self.metrics[TestGroup.CONTROL] = ABTestMetrics(
            group=TestGroup.CONTROL,
            strategies=self.control_strategies
        )
        self.metrics[TestGroup.VARIANT_A] = ABTestMetrics(
            group=TestGroup.VARIANT_A,
            strategies=self.variant_a_strategies
        )
        self.metrics[TestGroup.VARIANT_B] = ABTestMetrics(
            group=TestGroup.VARIANT_B,
            strategies=self.variant_b_strategies
        )
        
        # Set capital allocations
        for group, fraction in self.capital_split.items():
            self.metrics[group].capital_allocated = fraction


class ABTestingHarness:
    """
    A/B testing harness for strategy comparison.
    
    Tracks metrics independently per group.
    No auto-promotion - requires explicit approval.
    """
    
    def __init__(self, pnl_engine=None):
        """
        Initialize A/B testing harness.
        
        Args:
            pnl_engine: PnL engine for metrics (optional)
        """
        self.tests: Dict[str, ABTest] = {}
        self.pnl_engine = pnl_engine or get_pnl_engine()
        self.event_bus = get_event_bus()
        
        logger.info("ABTestingHarness initialized")
    
    def create_test(self, test_id: str,
                   control_strategies: List[str],
                   variant_a_strategies: List[str],
                   variant_b_strategies: List[str],
                   capital_split: Optional[Dict[str, float]] = None,
                   duration_trades: Optional[int] = None,
                   duration_time: Optional[timedelta] = None) -> ABTest:
        """
        Create a new A/B test.
        
        Args:
            test_id: Unique test identifier
            control_strategies: List of control strategy names
            variant_a_strategies: List of variant A strategy names
            variant_b_strategies: List of variant B strategy names
            capital_split: Dict mapping group names to capital fractions (default: equal)
            duration_trades: Test duration in trades (optional)
            duration_time: Test duration in time (optional)
            
        Returns:
            Created ABTest instance
        """
        # Default capital split: equal (33.3% each)
        if capital_split is None:
            capital_split = {
                "CONTROL": 0.333,
                "VARIANT_A": 0.333,
                "VARIANT_B": 0.334  # Slight adjustment to sum to 1.0
            }
        
        # Convert string keys to TestGroup enum
        capital_split_enum = {}
        for group_name, fraction in capital_split.items():
            try:
                group = TestGroup(group_name)
                capital_split_enum[group] = fraction
            except ValueError:
                logger.warning(f"Invalid test group: {group_name}, skipping")
        
        # Ensure capital split sums to 1.0
        total = sum(capital_split_enum.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(f"Capital split does not sum to 1.0 (sum={total}), normalizing")
            for group in capital_split_enum:
                capital_split_enum[group] /= total
        
        test = ABTest(
            test_id=test_id,
            control_strategies=control_strategies,
            variant_a_strategies=variant_a_strategies,
            variant_b_strategies=variant_b_strategies,
            capital_split=capital_split_enum,
            duration_trades=duration_trades,
            duration_time=duration_time
        )
        
        self.tests[test_id] = test
        logger.info(f"Created A/B test: {test_id} with {len(control_strategies)} control, "
                   f"{len(variant_a_strategies)} variant A, {len(variant_b_strategies)} variant B")
        
        return test
    
    def update_metrics(self, test_id: str) -> None:
        """
        Update metrics for an A/B test.
        
        Args:
            test_id: Test identifier
        """
        try:
            if test_id not in self.tests:
                return
            
            test = self.tests[test_id]
            if not test.active:
                return
            
            # Update metrics for each group
            for group, metrics in test.metrics.items():
                # Aggregate PnL for strategies in this group
                total_pnl = 0.0
                total_trades = 0
                wins = 0
                losses = 0
                max_dd = 0.0
                
                for strategy_name in metrics.strategies:
                    try:
                        strategy_metrics = self.pnl_engine.get_strategy_metrics(strategy_name)
                        total_pnl += strategy_metrics.get('realized_pnl', 0.0)
                        total_trades += strategy_metrics.get('trades_count', 0)
                        wins += strategy_metrics.get('wins', 0)
                        losses += strategy_metrics.get('losses', 0)
                        max_dd = max(max_dd, strategy_metrics.get('max_drawdown', 0.0))
                    except Exception as e:
                        logger.debug(f"Error getting metrics for {strategy_name}: {e}")
                
                # Update metrics
                metrics.total_pnl = total_pnl
                metrics.total_trades = total_trades
                metrics.wins = wins
                metrics.losses = losses
                metrics.win_rate = wins / total_trades if total_trades > 0 else 0.0
                metrics.max_drawdown = max_dd
                metrics.last_update = datetime.utcnow()
            
            # Check if test should end
            self._check_test_completion(test)
            
            # Emit update event
            self._emit_test_update(test)
        
        except Exception as e:
            logger.error(f"Error updating A/B test metrics: {e}", exc_info=True)
    
    def _check_test_completion(self, test: ABTest) -> None:
        """Check if test should be completed."""
        if not test.active:
            return
        
        # Check duration in trades
        if test.duration_trades:
            total_trades = sum(m.total_trades for m in test.metrics.values())
            if total_trades >= test.duration_trades:
                test.active = False
                test.end_time = datetime.utcnow()
                logger.info(f"A/B test {test.test_id} completed: reached {total_trades} trades")
                return
        
        # Check duration in time
        if test.duration_time:
            elapsed = datetime.utcnow() - test.start_time
            if elapsed >= test.duration_time:
                test.active = False
                test.end_time = datetime.utcnow()
                logger.info(f"A/B test {test.test_id} completed: reached time limit")
                return
    
    def get_leader(self, test_id: str) -> Optional[TestGroup]:
        """
        Get leading group in A/B test (by total PnL).
        
        Args:
            test_id: Test identifier
            
        Returns:
            Leading group or None
        """
        try:
            if test_id not in self.tests:
                return None
            
            test = self.tests[test_id]
            if not test.active:
                return None
            
            # Find group with highest PnL
            leader = None
            max_pnl = float('-inf')
            
            for group, metrics in test.metrics.items():
                if metrics.total_pnl > max_pnl:
                    max_pnl = metrics.total_pnl
                    leader = group
            
            return leader
        
        except Exception as e:
            logger.error(f"Error getting A/B test leader: {e}", exc_info=True)
            return None
    
    def get_test_results(self, test_id: str) -> Optional[Dict]:
        """
        Get A/B test results.
        
        Args:
            test_id: Test identifier
            
        Returns:
            Test results dict or None
        """
        try:
            if test_id not in self.tests:
                return None
            
            test = self.tests[test_id]
            leader = self.get_leader(test_id)
            
            return {
                'test_id': test.test_id,
                'active': test.active,
                'start_time': test.start_time.isoformat(),
                'end_time': test.end_time.isoformat() if test.end_time else None,
                'leader': leader.value if leader else None,
                'metrics': {
                    group.value: {
                        'total_pnl': metrics.total_pnl,
                        'total_trades': metrics.total_trades,
                        'win_rate': metrics.win_rate,
                        'max_drawdown': metrics.max_drawdown,
                        'capital_allocated': metrics.capital_allocated,
                        'strategies': metrics.strategies
                    }
                    for group, metrics in test.metrics.items()
                }
            }
        
        except Exception as e:
            logger.error(f"Error getting A/B test results: {e}", exc_info=True)
            return None
    
    def list_tests(self) -> List[Dict]:
        """List all A/B tests."""
        result = []
        for test_id, test in self.tests.items():
            leader = self.get_leader(test_id)
            result.append({
                'test_id': test_id,
                'active': test.active,
                'leader': leader.value if leader else None,
                'start_time': test.start_time.isoformat(),
                'end_time': test.end_time.isoformat() if test.end_time else None
            })
        return result
    
    def _emit_test_update(self, test: ABTest) -> None:
        """Emit A/B test update event (non-blocking)."""
        try:
            leader = self.get_leader(test.test_id)
            event = {
                'type': 'ab_test_update',
                'test_id': test.test_id,
                'metrics': {
                    group.value: {
                        'total_pnl': metrics.total_pnl,
                        'total_trades': metrics.total_trades,
                        'win_rate': metrics.win_rate,
                        'max_drawdown': metrics.max_drawdown
                    }
                    for group, metrics in test.metrics.items()
                },
                'leader': leader.value if leader else None,
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }
            safe_emit(self.event_bus.publish(event))
        except Exception as e:
            logger.error(f"Error emitting A/B test update: {e}", exc_info=True)


# Global A/B testing harness instance
_ab_testing: Optional[ABTestingHarness] = None


def get_ab_testing(pnl_engine=None) -> ABTestingHarness:
    """Get global A/B testing harness instance."""
    global _ab_testing
    if _ab_testing is None:
        _ab_testing = ABTestingHarness(pnl_engine)
    return _ab_testing
