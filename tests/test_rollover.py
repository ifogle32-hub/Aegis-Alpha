"""
PHASE 12 — ROLLOVER TESTS

Test futures rollover correctness.
"""

import unittest
from datetime import datetime
import pandas as pd
import numpy as np

from sentinel_x.marketdata.rollover import FuturesRollover, RolloverMethod, RolloverPoint


class TestRollover(unittest.TestCase):
    """Test futures rollover."""
    
    def test_volume_based_rollover(self):
        """Test volume-based rollover detection."""
        dates = pd.date_range(start=datetime(2024, 1, 1), periods=100, freq='1H')
        
        # Front month: high volume initially, drops at midpoint
        front_df = pd.DataFrame({
            'timestamp': dates,
            'close': 4000 + np.random.randn(100) * 10,
            'volume': [10000] * 50 + [1000] * 50,
        })
        front_df['timestamp'] = pd.to_datetime(front_df['timestamp'], utc=True)
        
        # Back month: low volume initially, increases at midpoint
        back_df = pd.DataFrame({
            'timestamp': dates,
            'close': 4005 + np.random.randn(100) * 10,
            'volume': [1000] * 50 + [10000] * 50,
        })
        back_df['timestamp'] = pd.to_datetime(back_df['timestamp'], utc=True)
        
        rollover = FuturesRollover(method=RolloverMethod.VOLUME)
        rollover_point = rollover.detect_rollover(front_df, back_df, "NQ")
        
        self.assertIsNotNone(rollover_point)
        self.assertEqual(rollover_point.method, RolloverMethod.VOLUME)
        self.assertIsNotNone(rollover_point.timestamp)
    
    def test_contract_stitching_no_gaps(self):
        """Test that stitched contracts have no gaps."""
        dates1 = pd.date_range(start=datetime(2024, 1, 1), periods=50, freq='1H')
        dates2 = pd.date_range(start=datetime(2024, 1, 3), periods=50, freq='1H')
        
        front_df = pd.DataFrame({
            'timestamp': dates1,
            'close': 4000 + np.arange(50),
            'volume': 1000,
        })
        front_df['timestamp'] = pd.to_datetime(front_df['timestamp'], utc=True)
        
        back_df = pd.DataFrame({
            'timestamp': dates2,
            'close': 4050 + np.arange(50),
            'volume': 1000,
        })
        back_df['timestamp'] = pd.to_datetime(back_df['timestamp'], utc=True)
        
        rollover = FuturesRollover()
        rollover_point = RolloverPoint(
            timestamp=datetime(2024, 1, 2, 12, 0),
            from_contract="NQ_front",
            to_contract="NQ_back",
            rollover_price=4025.0,
            method=RolloverMethod.VOLUME,
        )
        
        stitched = rollover.stitch_contracts(front_df, back_df, rollover_point)
        
        # Verify no gaps in timestamps
        timestamps = pd.to_datetime(stitched['timestamp'])
        time_diffs = timestamps.diff().dropna()
        
        # All time differences should be consistent (1H)
        expected_diff = pd.Timedelta(hours=1)
        self.assertTrue((time_diffs == expected_diff).all() or len(time_diffs) == 0)


if __name__ == "__main__":
    unittest.main()
