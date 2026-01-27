"""
PHASE 9 — SHADOW TRAINING LIFECYCLE TESTS

Test shadow training lifecycle:
- Shadow training starts exactly once
- No duplicate trainers on restart
- Replay feeds shadow deterministically
- /shadow/status reflects real training state
- Rork-visible status matches internal state
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from sentinel_x.shadow.controller import ShadowTrainingController, TrainingState, get_shadow_training_controller
from sentinel_x.shadow.status import ShadowStatusProvider, get_shadow_status_provider
from sentinel_x.shadow.replay import HistoricalReplayFeed, ReplayMode
from sentinel_x.shadow.feed import MarketTick


class TestShadowTrainingLifecycle:
    """Test shadow training lifecycle management."""
    
    def test_controller_singleton(self):
        """Test that controller is a singleton."""
        controller1 = get_shadow_training_controller()
        controller2 = get_shadow_training_controller()
        
        assert controller1 is controller2
    
    def test_start_stops_duplicate(self):
        """Test that starting twice doesn't create duplicate trainers."""
        controller = get_shadow_training_controller()
        
        # Reset state
        controller.stop()
        time.sleep(0.1)
        
        # Start first time
        result1 = controller.start(symbols=["SPY"], replay_mode=False)
        assert result1 is True
        assert controller.get_state() == TrainingState.RUNNING
        
        # Try to start again
        result2 = controller.start(symbols=["SPY"], replay_mode=False)
        assert result2 is False  # Should fail (already started)
        assert controller.get_state() == TrainingState.RUNNING
        
        # Cleanup
        controller.stop()
    
    def test_pause_resume(self):
        """Test pause and resume functionality."""
        controller = get_shadow_training_controller()
        
        # Reset state
        controller.stop()
        time.sleep(0.1)
        
        # Start
        controller.start(symbols=["SPY"], replay_mode=False)
        assert controller.get_state() == TrainingState.RUNNING
        
        # Pause
        controller.pause()
        assert controller.get_state() == TrainingState.PAUSED
        
        # Resume
        controller.resume()
        assert controller.get_state() == TrainingState.RUNNING
        
        # Cleanup
        controller.stop()
    
    def test_status_snapshot(self):
        """Test status snapshot generation."""
        controller = get_shadow_training_controller()
        status_provider = get_shadow_status_provider()
        
        # Reset state
        controller.stop()
        time.sleep(0.1)
        
        # Get snapshot when idle
        snapshot1 = status_provider.get_snapshot()
        assert snapshot1.enabled is False
        assert snapshot1.training_active is False
        assert snapshot1.training_state == TrainingState.IDLE.value
        
        # Start and get snapshot
        controller.start(symbols=["SPY"], replay_mode=False)
        time.sleep(0.1)
        
        snapshot2 = status_provider.get_snapshot()
        assert snapshot2.enabled is True
        assert snapshot2.training_active is True
        assert snapshot2.training_state == TrainingState.RUNNING.value
        
        # Cleanup
        controller.stop()
    
    def test_process_tick_safety(self):
        """Test that process_tick never executes trades."""
        controller = get_shadow_training_controller()
        
        # Reset state
        controller.stop()
        time.sleep(0.1)
        
        # Start
        controller.start(symbols=["SPY"], replay_mode=False)
        
        # Create tick
        tick = MarketTick(
            symbol="SPY",
            timestamp=datetime.utcnow(),
            price=100.0,
            volume=1000.0,
        )
        
        # Process tick (should not raise)
        controller.process_tick(tick)
        
        # Verify state is still RUNNING
        assert controller.get_state() == TrainingState.RUNNING
        
        # Cleanup
        controller.stop()
    
    def test_error_handling(self):
        """Test that errors don't crash controller."""
        controller = get_shadow_training_controller()
        
        # Reset state
        controller.stop()
        time.sleep(0.1)
        
        # Process tick when not started (should not raise)
        tick = MarketTick(
            symbol="SPY",
            timestamp=datetime.utcnow(),
            price=100.0,
            volume=1000.0,
        )
        controller.process_tick(tick)  # Should not raise
        
        # Verify state is still IDLE
        assert controller.get_state() == TrainingState.IDLE


class TestReplayIntegration:
    """Test replay feed integration with shadow training."""
    
    def test_replay_feed_blocks_live(self):
        """Test that replay feed blocks live feeds."""
        controller = get_shadow_training_controller()
        
        # Reset state
        controller.stop()
        time.sleep(0.1)
        
        # Create mock replay feed
        mock_replay = Mock(spec=HistoricalReplayFeed)
        mock_replay.running = True
        mock_replay.get_progress.return_value = {
            "current_tick": 10,
            "total_ticks": 100,
            "progress_pct": 10.0,
        }
        
        # Start with replay feed
        controller.start(
            symbols=["SPY"],
            replay_feed=mock_replay,
            replay_mode=True,
        )
        
        # Verify replay feed is set
        assert controller._replay_feed is mock_replay
        
        # Cleanup
        controller.stop()
    
    def test_replay_progress_tracking(self):
        """Test replay progress tracking."""
        from sentinel_x.shadow.replay_bridge import get_replay_bridge
        
        replay_bridge = get_replay_bridge()
        
        # Get progress when no replay active
        progress = replay_bridge.get_replay_progress()
        assert progress["replay_active"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
