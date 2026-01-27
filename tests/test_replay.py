"""
PHASE 5 — REPLAY TESTS

Test historical replay engine determinism and correctness.
"""

import unittest
import os
from datetime import datetime
import pandas as pd
import numpy as np

os.environ["SENTINEL_ENGINE_MODE"] = "TRAINING"

from sentinel_x.shadow.replay import HistoricalReplayFeed, ReplayMode
from sentinel_x.shadow.feed import MarketTick


class TestReplay(unittest.TestCase):
    """Test historical replay engine."""
    
    def setUp(self):
        """Set up test data."""
        dates = pd.date_range(
            start=datetime(2024, 1, 1, 9, 0),
            end=datetime(2024, 1, 1, 16, 0),
            freq='1H'
        )
        
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
        
        self.test_data = {
            "TEST": pd.DataFrame({
                'timestamp': dates,
                'open': prices,
                'high': prices * 1.01,
                'low': prices * 0.99,
                'close': prices,
                'volume': np.random.randint(1000, 10000, len(dates)),
            })
        }
    
    def test_tick_accurate_timestamps(self):
        """Test that replay produces tick-accurate timestamps."""
        feed = HistoricalReplayFeed(
            symbols=["TEST"],
            historical_data=self.test_data,
            start_date=datetime(2024, 1, 1, 9, 0),
            end_date=datetime(2024, 1, 1, 12, 0),
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        feed.start()
        
        ticks = []
        for _ in range(10):
            tick = feed.get_next_tick()
            if tick:
                ticks.append(tick)
        
        # Verify timestamps are in order
        for i in range(1, len(ticks)):
            self.assertLessEqual(ticks[i-1].timestamp, ticks[i].timestamp)
    
    def test_deterministic_ordering(self):
        """Test that replay produces deterministic ordering."""
        feed1 = HistoricalReplayFeed(
            symbols=["TEST"],
            historical_data=self.test_data,
            start_date=datetime(2024, 1, 1, 9, 0),
            end_date=datetime(2024, 1, 1, 12, 0),
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        feed2 = HistoricalReplayFeed(
            symbols=["TEST"],
            historical_data=self.test_data,
            start_date=datetime(2024, 1, 1, 9, 0),
            end_date=datetime(2024, 1, 1, 12, 0),
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        feed1.start()
        feed2.start()
        
        ticks1 = []
        ticks2 = []
        
        for _ in range(10):
            tick1 = feed1.get_next_tick()
            tick2 = feed2.get_next_tick()
            if tick1:
                ticks1.append(tick1)
            if tick2:
                ticks2.append(tick2)
        
        # Verify same ordering
        self.assertEqual(len(ticks1), len(ticks2))
        for t1, t2 in zip(ticks1, ticks2):
            self.assertEqual(t1.timestamp, t2.timestamp)
            self.assertEqual(t1.symbol, t2.symbol)
            self.assertAlmostEqual(t1.price, t2.price, places=6)
    
    def test_rewind(self):
        """Test rewind functionality."""
        feed = HistoricalReplayFeed(
            symbols=["TEST"],
            historical_data=self.test_data,
            start_date=datetime(2024, 1, 1, 9, 0),
            end_date=datetime(2024, 1, 1, 12, 0),
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        feed.start()
        
        # Process some ticks
        for _ in range(5):
            feed.get_next_tick()
        
        # Rewind
        feed.rewind()
        
        # Get first tick again
        tick = feed.get_next_tick()
        self.assertIsNotNone(tick)
        self.assertEqual(tick.timestamp, datetime(2024, 1, 1, 9, 0))
    
    def test_pause_resume(self):
        """Test pause/resume functionality."""
        feed = HistoricalReplayFeed(
            symbols=["TEST"],
            historical_data=self.test_data,
            start_date=datetime(2024, 1, 1, 9, 0),
            end_date=datetime(2024, 1, 1, 12, 0),
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        feed.start()
        
        # Process some ticks
        tick1 = feed.get_next_tick()
        
        # Pause
        feed.pause()
        tick2 = feed.get_next_tick()  # Should return None when paused
        self.assertIsNone(tick2)
        
        # Resume
        feed.resume()
        tick3 = feed.get_next_tick()  # Should continue
        self.assertIsNotNone(tick3)
    
    def test_step_mode(self):
        """Test step mode."""
        feed = HistoricalReplayFeed(
            symbols=["TEST"],
            historical_data=self.test_data,
            start_date=datetime(2024, 1, 1, 9, 0),
            end_date=datetime(2024, 1, 1, 12, 0),
            replay_mode=ReplayMode.STEP,
            seed=42,
        )
        
        feed.start()
        
        # get_next_tick should return None in STEP mode
        tick1 = feed.get_next_tick()
        self.assertIsNone(tick1)
        
        # step() should return ticks
        tick2 = feed.step()
        self.assertIsNotNone(tick2)
        
        tick3 = feed.step()
        self.assertIsNotNone(tick3)
        
        # Verify ordering
        self.assertLessEqual(tick2.timestamp, tick3.timestamp)
    
    def test_windowed_replay(self):
        """Test windowed replay (date ranges)."""
        feed = HistoricalReplayFeed(
            symbols=["TEST"],
            historical_data=self.test_data,
            start_date=datetime(2024, 1, 1, 9, 0),
            end_date=datetime(2024, 1, 1, 12, 0),
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        # Set new window
        feed.set_window(
            start_date=datetime(2024, 1, 1, 10, 0),
            end_date=datetime(2024, 1, 1, 11, 0),
        )
        
        feed.start()
        
        ticks = []
        for _ in range(10):
            tick = feed.get_next_tick()
            if tick:
                ticks.append(tick)
        
        # Verify all ticks are in window
        for tick in ticks:
            self.assertGreaterEqual(tick.timestamp, datetime(2024, 1, 1, 10, 0))
            self.assertLessEqual(tick.timestamp, datetime(2024, 1, 1, 11, 0))
    
    def test_multi_symbol_synchronized(self):
        """Test multi-symbol synchronized replay."""
        # Create data for multiple symbols
        dates = pd.date_range(
            start=datetime(2024, 1, 1, 9, 0),
            end=datetime(2024, 1, 1, 12, 0),
            freq='1H'
        )
        
        data = {}
        for symbol in ["SYM1", "SYM2"]:
            np.random.seed(42)
            prices = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
            data[symbol] = pd.DataFrame({
                'timestamp': dates,
                'open': prices,
                'high': prices * 1.01,
                'low': prices * 0.99,
                'close': prices,
                'volume': np.random.randint(1000, 10000, len(dates)),
            })
        
        feed = HistoricalReplayFeed(
            symbols=["SYM1", "SYM2"],
            historical_data=data,
            start_date=datetime(2024, 1, 1, 9, 0),
            end_date=datetime(2024, 1, 1, 12, 0),
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        feed.start()
        
        ticks = []
        for _ in range(20):
            tick = feed.get_next_tick()
            if tick:
                ticks.append(tick)
        
        # Verify symbols are interleaved by timestamp
        for i in range(1, len(ticks)):
            if ticks[i-1].timestamp == ticks[i].timestamp:
                # Same timestamp, symbols should be in order
                self.assertLessEqual(ticks[i-1].symbol, ticks[i].symbol)
            else:
                # Timestamps should be in order
                self.assertLessEqual(ticks[i-1].timestamp, ticks[i].timestamp)


if __name__ == "__main__":
    unittest.main()
