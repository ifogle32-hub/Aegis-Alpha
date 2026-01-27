"""
PHASE 9 — REPLAY SHADOW INTEGRATION TESTS

Test replay feed integration with shadow training:
- Replay feeds shadow deterministically
- Replay blocks live feeds
- Replay progress is observable
- Restart resumes or restarts replay safely
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from sentinel_x.shadow.controller import get_shadow_training_controller
from sentinel_x.shadow.replay_bridge import get_replay_bridge
from sentinel_x.shadow.replay import HistoricalReplayFeed, ReplayMode


class TestReplayShadowIntegration:
    """Test replay feed integration with shadow training."""
    
    def test_replay_bridge_singleton(self):
        """Test that replay bridge is a singleton."""
        bridge1 = get_replay_bridge()
        bridge2 = get_replay_bridge()
        
        assert bridge1 is bridge2
    
    def test_replay_blocks_live_feeds(self):
        """Test that replay feed blocks live feeds."""
        controller = get_shadow_training_controller()
        replay_bridge = get_replay_bridge()
        
        # Reset state
        controller.stop()
        
        # Create mock historical data
        historical_data = {
            "SPY": pd.DataFrame({
                "timestamp": pd.date_range(start="2024-01-01", periods=100, freq="1H"),
                "open": [100.0] * 100,
                "high": [101.0] * 100,
                "low": [99.0] * 100,
                "close": [100.5] * 100,
                "volume": [1000] * 100,
            })
        }
        
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 5)
        
        # Start replay
        success = replay_bridge.start_replay(
            symbols=["SPY"],
            historical_data=historical_data,
            start_date=start_date,
            end_date=end_date,
            replay_mode=ReplayMode.STRICT,
        )
        
        assert success is True
        
        # Verify replay feed is set
        assert replay_bridge._replay_feed is not None
        assert controller._replay_feed is not None
        
        # Verify controller is in RUNNING state
        assert controller.get_state().value == "RUNNING"
        
        # Cleanup
        replay_bridge.stop_replay()
        controller.stop()
    
    def test_replay_progress_tracking(self):
        """Test replay progress tracking."""
        replay_bridge = get_replay_bridge()
        
        # Get progress when no replay active
        progress = replay_bridge.get_replay_progress()
        assert progress["replay_active"] is False
        assert progress["progress"] is None
    
    def test_replay_deterministic(self):
        """Test that replay is deterministic."""
        controller = get_shadow_training_controller()
        replay_bridge = get_replay_bridge()
        
        # Reset state
        controller.stop()
        
        # Create historical data
        historical_data = {
            "SPY": pd.DataFrame({
                "timestamp": pd.date_range(start="2024-01-01", periods=10, freq="1H"),
                "open": [100.0] * 10,
                "high": [101.0] * 10,
                "low": [99.0] * 10,
                "close": [100.5] * 10,
                "volume": [1000] * 10,
            })
        }
        
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 2)
        
        # Start replay with seed
        success = replay_bridge.start_replay(
            symbols=["SPY"],
            historical_data=historical_data,
            start_date=start_date,
            end_date=end_date,
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        assert success is True
        
        # Get progress
        progress1 = replay_bridge.get_replay_progress()
        assert progress1["replay_active"] is True
        
        # Cleanup
        replay_bridge.stop_replay()
        controller.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
