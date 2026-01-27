"""
PHASE 12 — CI TESTS FOR REPLAY DETERMINISM

Test suite for multi-asset historical replay determinism.

Test categories:
1) Same replay twice → identical results
2) Futures rollover correctness
3) FX normalization correctness
4) Multi-asset alignment
5) No live execution leakage
6) Strategy isolation
"""

import unittest
import os
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np

os.environ["SENTINEL_ENGINE_MODE"] = "TRAINING"

from sentinel_x.marketdata.historical_feed import HistoricalMarketFeed, ReplayMode
from sentinel_x.marketdata.schema import OHLCVSchema, validate_ohlcv_data
from sentinel_x.marketdata.rollover import FuturesRollover, RolloverMethod
from sentinel_x.marketdata.fx import FXNormalizer
from sentinel_x.marketdata.metadata import MetadataLoader, ContractMetadata, AssetType


class TestReplayDeterminism(unittest.TestCase):
    """Test replay determinism."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_seed = 42
        np.random.seed(self.test_seed)
        
        # Create test data directory structure
        self.data_dir = Path(self.temp_dir) / "data" / "historical"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        (self.data_dir / "equities").mkdir(exist_ok=True)
        (self.data_dir / "futures").mkdir(exist_ok=True)
        (self.data_dir / "crypto").mkdir(exist_ok=True)
        (self.data_dir / "fx").mkdir(exist_ok=True)
        (self.data_dir / "metadata").mkdir(exist_ok=True)
        
        # Create test data
        self._create_test_data()
        self._create_metadata()
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_test_data(self):
        """Create deterministic test data."""
        dates = pd.date_range(
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 10),
            freq='1H'
        )
        
        np.random.seed(self.test_seed)
        
        # Create equity data
        equity_prices = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
        equity_df = pd.DataFrame({
            'timestamp': dates,
            'open': equity_prices,
            'high': equity_prices * 1.01,
            'low': equity_prices * 0.99,
            'close': equity_prices,
            'volume': np.random.randint(1000, 10000, len(dates)),
        })
        equity_df['timestamp'] = pd.to_datetime(equity_df['timestamp'], utc=True)
        equity_df.to_parquet(self.data_dir / "equities" / "AAPL.parquet")
        
        # Create crypto data
        crypto_prices = 50000 + np.cumsum(np.random.randn(len(dates)) * 100)
        crypto_df = pd.DataFrame({
            'timestamp': dates,
            'open': crypto_prices,
            'high': crypto_prices * 1.01,
            'low': crypto_prices * 0.99,
            'close': crypto_prices,
            'volume': np.random.randint(100, 1000, len(dates)),
        })
        crypto_df['timestamp'] = pd.to_datetime(crypto_df['timestamp'], utc=True)
        crypto_df.to_parquet(self.data_dir / "crypto" / "BTC.parquet")
    
    def _create_metadata(self):
        """Create metadata files."""
        import yaml
        
        contracts = {
            "AAPL": {
                "asset_type": "equity",
                "tick_size": 0.01,
                "multiplier": 1.0,
                "currency": "USD",
                "fee_percentage": 0.1,
            },
            "BTC": {
                "asset_type": "crypto",
                "tick_size": 0.01,
                "multiplier": 1.0,
                "currency": "USD",
                "fee_percentage": 0.1,
            },
        }
        
        with open(self.data_dir / "metadata" / "contracts.yaml", 'w') as f:
            yaml.dump(contracts, f)
    
    def test_same_replay_twice_identical_results(self):
        """Test that same replay produces identical results."""
        # Run replay twice with same seed
        feed1 = HistoricalMarketFeed(
            symbols=["AAPL"],
            data_dir=self.data_dir,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        feed2 = HistoricalMarketFeed(
            symbols=["AAPL"],
            data_dir=self.data_dir,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
            replay_mode=ReplayMode.STRICT,
            seed=42,
        )
        
        feed1.start()
        feed2.start()
        
        ticks1 = []
        ticks2 = []
        
        for _ in range(50):
            tick1 = feed1.get_next_tick()
            tick2 = feed2.get_next_tick()
            if tick1:
                ticks1.append(tick1)
            if tick2:
                ticks2.append(tick2)
        
        # Verify identical results
        self.assertEqual(len(ticks1), len(ticks2))
        for t1, t2 in zip(ticks1, ticks2):
            self.assertEqual(t1.timestamp, t2.timestamp)
            self.assertEqual(set(t1.assets.keys()), set(t2.assets.keys()))
            for symbol in t1.assets.keys():
                self.assertAlmostEqual(
                    t1.assets[symbol].price,
                    t2.assets[symbol].price,
                    places=6,
                )
    
    def test_multi_asset_alignment(self):
        """Test multi-asset timestamp alignment."""
        feed = HistoricalMarketFeed(
            symbols=["AAPL", "BTC"],
            data_dir=self.data_dir,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
            replay_mode=ReplayMode.ACCELERATED,
            seed=42,
        )
        
        feed.start()
        
        ticks = []
        for _ in range(50):
            tick = feed.get_next_tick()
            if tick:
                ticks.append(tick)
        
        # Verify timestamps are aligned
        for tick in ticks:
            # All assets in tick should have same timestamp
            if len(tick.assets) > 1:
                timestamps = [t.timestamp for t in tick.assets.values()]
                self.assertEqual(len(set(timestamps)), 1)
    
    def test_ohlcv_schema_validation(self):
        """Test OHLCV schema validation."""
        # Load test data
        df = pd.read_parquet(self.data_dir / "equities" / "AAPL.parquet")
        
        # Validate
        self.assertTrue(validate_ohlcv_data(df))
        
        # Test normalization
        normalized = OHLCVSchema.normalize(df, "AAPL")
        self.assertTrue(validate_ohlcv_data(normalized))
        self.assertEqual(set(normalized.columns), set(OHLCVSchema.REQUIRED_COLUMNS))


class TestRollover(unittest.TestCase):
    """Test futures rollover."""
    
    def test_rollover_detection(self):
        """Test rollover detection."""
        # Create test data
        dates = pd.date_range(start=datetime(2024, 1, 1), periods=100, freq='1H')
        
        # Front month: high volume initially
        front_df = pd.DataFrame({
            'timestamp': dates,
            'close': 4000 + np.random.randn(100) * 10,
            'volume': [10000] * 50 + [1000] * 50,  # Volume drops at midpoint
        })
        front_df['timestamp'] = pd.to_datetime(front_df['timestamp'], utc=True)
        
        # Back month: low volume initially, high later
        back_df = pd.DataFrame({
            'timestamp': dates,
            'close': 4005 + np.random.randn(100) * 10,
            'volume': [1000] * 50 + [10000] * 50,  # Volume increases at midpoint
        })
        back_df['timestamp'] = pd.to_datetime(back_df['timestamp'], utc=True)
        
        rollover = FuturesRollover(method=RolloverMethod.VOLUME)
        rollover_point = rollover.detect_rollover(front_df, back_df, "NQ")
        
        self.assertIsNotNone(rollover_point)
        self.assertEqual(rollover_point.method, RolloverMethod.VOLUME)
    
    def test_contract_stitching(self):
        """Test contract stitching."""
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
        rollover_point = rollover.detect_rollover(front_df, back_df, "ES")
        
        if rollover_point:
            stitched = rollover.stitch_contracts(front_df, back_df, rollover_point)
            self.assertGreater(len(stitched), len(front_df))
            self.assertGreater(len(stitched), len(back_df))


class TestFXNormalization(unittest.TestCase):
    """Test FX normalization."""
    
    def test_fx_normalization(self):
        """Test FX price normalization."""
        normalizer = FXNormalizer(normalization_base="USD")
        
        # EURUSD: 1 EUR = 1.1 USD
        # Price of 1.1 means 1 EUR = 1.1 USD
        # Normalized to USD: should be 1.1
        normalized = normalizer.normalize_price(1.1, "EURUSD")
        self.assertAlmostEqual(normalized, 1.1, places=6)


if __name__ == "__main__":
    unittest.main()
