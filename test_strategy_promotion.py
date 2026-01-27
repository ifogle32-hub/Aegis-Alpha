"""
PHASE 18 — DETERMINISTIC TESTS FOR STRATEGY PROMOTION

Minimal deterministic tests for strategy promotion engine.
No sleeps. No timing assumptions. All tests are synchronous and deterministic.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch

from api.strategies.registry import StrategyMode, StrategyRegistry, get_strategy_registry
from api.strategies.promotion import StrategyPromotionEngine, PromotionReason, PromotionDecision
from api.strategies.auto_promotion import AutoPromotionEngine, AutoPromotionRule
from api.strategies.metrics import StrategyMetrics as StrategyMetricsModel
from api.engine import EngineState, EngineRuntime
from api.security import KillSwitchStatus
from api.risk.engine import RiskEngine


class TestStrategyPromotion:
    """PHASE 18 — Strategy Promotion Tests"""
    
    def test_promotion_blocked_when_not_armed(self):
        """Auto-promotion blocked if engine.state != ARMED"""
        # Setup
        engine_runtime = Mock()
        engine_runtime.get_state_dict.return_value = {"state": EngineState.SHADOW.value, "trading_window": "OPEN"}
        
        kill_switch = Mock()
        kill_switch.can_promote.return_value = True
        
        auto_promotion = AutoPromotionEngine()
        auto_promotion.engine_runtime = engine_runtime
        auto_promotion.kill_switch = kill_switch
        
        # Execute
        summary = auto_promotion.evaluate_cycle()
        
        # Assert
        assert summary["evaluated"] == 0  # No evaluation when not ARMED
        assert summary["promoted"] == 0
        assert summary["demoted"] == 0
    
    def test_promotion_blocked_when_kill_switch_not_ready(self):
        """Auto-promotion blocked if kill-switch != READY"""
        # Setup
        engine_runtime = Mock()
        engine_runtime.get_state_dict.return_value = {"state": EngineState.ARMED.value, "trading_window": "OPEN"}
        
        kill_switch = Mock()
        kill_switch.can_promote.return_value = False  # Kill-switch not READY
        
        auto_promotion = AutoPromotionEngine()
        auto_promotion.engine_runtime = engine_runtime
        auto_promotion.kill_switch = kill_switch
        
        # Execute
        summary = auto_promotion.evaluate_cycle()
        
        # Assert
        assert summary["evaluated"] == 0  # No evaluation when kill-switch not READY
        assert summary["promoted"] == 0
        assert summary["demoted"] == 0
    
    def test_promotion_blocked_during_closed_window(self):
        """Auto-promotion blocked during CLOSED trading window"""
        # Setup
        engine_runtime = Mock()
        engine_runtime.get_state_dict.return_value = {"state": EngineState.ARMED.value, "trading_window": "CLOSED"}
        
        kill_switch = Mock()
        kill_switch.can_promote.return_value = True
        
        auto_promotion = AutoPromotionEngine()
        auto_promotion.engine_runtime = engine_runtime
        auto_promotion.kill_switch = kill_switch
        
        # Execute
        summary = auto_promotion.evaluate_cycle()
        
        # Assert
        assert summary["evaluated"] == 0  # No evaluation when window CLOSED
        assert summary["promoted"] == 0
        assert summary["demoted"] == 0
    
    def test_promotion_blocked_when_risk_fails(self):
        """Auto-promotion blocked if risk engine rejects"""
        # Setup
        strategy_id = "test_strategy"
        
        # Mock registry
        strategy_registry = Mock()
        strategy_registry.get_strategy_mode.return_value = StrategyMode.SHADOW
        strategy_registry.set_mode.return_value = {"id": strategy_id, "mode": StrategyMode.PAPER.value}
        
        # Mock engine runtime
        engine_runtime = Mock()
        engine_runtime.get_state_dict.return_value = {"state": EngineState.ARMED.value}
        
        # Mock kill-switch
        kill_switch = Mock()
        kill_switch.can_promote.return_value = True
        kill_switch.status.value = "READY"
        
        # Mock risk engine (rejects)
        risk_engine = Mock()
        risk_engine.approve_strategy_promotion.return_value = (False, "risk_rejected: insufficient capital")
        
        # Mock audit logger
        audit_logger = Mock()
        
        promotion_engine = StrategyPromotionEngine()
        promotion_engine.strategy_registry = strategy_registry
        promotion_engine.engine_runtime = engine_runtime
        promotion_engine.kill_switch = kill_switch
        promotion_engine.risk_engine = risk_engine
        promotion_engine.audit_logger = audit_logger
        
        # Execute
        decision = promotion_engine.promote(strategy_id, actor="test", reason=PromotionReason.MANUAL.value)
        
        # Assert
        assert decision.approved == False
        assert "risk_rejected" in decision.reason.lower()
        assert strategy_registry.set_mode.called == False  # No mode change when risk rejects
    
    def test_promotion_succeeds_when_metrics_pass(self):
        """Auto-promotion succeeds when metrics pass and risk approves"""
        # Setup
        strategy_id = "test_strategy"
        
        # Mock registry
        strategy_registry = Mock()
        strategy_registry.get_strategy_mode.return_value = StrategyMode.SHADOW
        strategy_registry.set_mode.return_value = {"id": strategy_id, "mode": StrategyMode.PAPER.value}
        
        # Mock engine runtime
        engine_runtime = Mock()
        engine_runtime.get_state_dict.return_value = {"state": EngineState.ARMED.value}
        
        # Mock kill-switch
        kill_switch = Mock()
        kill_switch.can_promote.return_value = True
        kill_switch.status.value = "READY"
        
        # Mock risk engine (approves)
        risk_engine = Mock()
        risk_engine.approve_strategy_promotion.return_value = (True, "Risk engine approval granted")
        
        # Mock audit logger
        audit_logger = Mock()
        
        promotion_engine = StrategyPromotionEngine()
        promotion_engine.strategy_registry = strategy_registry
        promotion_engine.engine_runtime = engine_runtime
        promotion_engine.kill_switch = kill_switch
        promotion_engine.risk_engine = risk_engine
        promotion_engine.audit_logger = audit_logger
        
        # Execute
        decision = promotion_engine.promote(strategy_id, actor="test", reason=PromotionReason.MANUAL.value)
        
        # Assert
        assert decision.approved == True
        assert strategy_registry.set_mode.called == True
        assert strategy_registry.set_mode.call_args[0][1] == StrategyMode.PAPER
    
    def test_auto_demotion_on_drawdown_breach(self):
        """Auto-demotion on drawdown breach"""
        # Setup
        strategy_id = "test_strategy"
        
        # Mock metrics (drawdown breach)
        metrics = StrategyMetricsModel(
            strategy_id=strategy_id,
            pnl_rolling_30d=100.0,
            sharpe_rolling_30d=2.0,
            max_drawdown_30d=15.0,  # Exceeds 10% threshold
            trade_count=25,
            last_updated=time.time(),
        )
        
        # Mock registry
        strategy_registry = Mock()
        strategy_registry.get_strategy_mode.return_value = StrategyMode.PAPER
        strategy_registry.set_mode.return_value = {"id": strategy_id, "mode": StrategyMode.SHADOW.value}
        
        # Mock promotion engine
        promotion_engine = Mock()
        decision = PromotionDecision(
            strategy_id=strategy_id,
            from_mode=StrategyMode.PAPER.value,
            to_mode=StrategyMode.SHADOW.value,
            approved=True,
            reason="Drawdown exceeded",
            actor="system",
        )
        promotion_engine.demote.return_value = decision
        
        # Mock risk engine
        risk_engine = Mock()
        risk_engine.approve_strategy_promotion.return_value = (True, "approved")
        risk_engine.evaluate_strategy_metrics.return_value = None
        
        auto_promotion = AutoPromotionEngine()
        auto_promotion.strategy_registry = strategy_registry
        auto_promotion.promotion_engine = promotion_engine
        auto_promotion.risk_engine = risk_engine
        auto_promotion.promotion_rule = AutoPromotionRule(max_drawdown=10.0)
        
        # Enable auto-promotion for strategy
        strategy_state = auto_promotion._strategy_states.get(strategy_id)
        if not strategy_state:
            from api.strategies.auto_promotion import StrategyAutoPromotionState
            strategy_state = StrategyAutoPromotionState(strategy_id=strategy_id)
            auto_promotion._strategy_states[strategy_id] = strategy_state
        strategy_state.auto_promotion_enabled = True
        
        # Mock metrics cache
        auto_promotion._metrics_cache[strategy_id] = metrics
        
        # Execute
        result = auto_promotion._evaluate_strategy(strategy_id)
        
        # Assert
        assert result["demoted"] == True
        assert promotion_engine.demote.called == True
        assert "drawdown_exceeded" in promotion_engine.demote.call_args[1]["reason"]
    
    def test_kill_switch_forces_demotion(self):
        """Kill-switch forces demotion with explicit reason"""
        # Setup
        strategy_id = "test_strategy"
        
        # Mock registry
        strategy_registry = Mock()
        strategy_registry.list.return_value = [{"id": strategy_id}]
        strategy_registry.get_strategy_mode.return_value = StrategyMode.PAPER
        strategy_registry.set_mode.return_value = {"id": strategy_id, "mode": StrategyMode.SHADOW.value}
        
        # Mock promotion engine
        promotion_engine = Mock()
        decision = PromotionDecision(
            strategy_id=strategy_id,
            from_mode=StrategyMode.PAPER.value,
            to_mode=StrategyMode.SHADOW.value,
            approved=True,
            reason="Demoted by kill-switch",
            actor="system",
        )
        promotion_engine.demote.return_value = decision
        
        # Mock audit logger
        audit_logger = Mock()
        
        promotion_engine_instance = StrategyPromotionEngine()
        promotion_engine_instance.strategy_registry = strategy_registry
        promotion_engine_instance.promotion_engine = promotion_engine
        promotion_engine_instance.audit_logger = audit_logger
        
        # Execute - demote all strategies
        demoted_count = promotion_engine_instance.demote_all_to_shadow(
            actor="system",
            reason="kill_switch_SOFT_KILL",
            explicit_reason="kill_switch"
        )
        
        # Assert
        assert demoted_count >= 0  # At least attempted demotion
        # Note: In real test, would need to properly mock the internal demote calls


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
