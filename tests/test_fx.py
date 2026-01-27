"""
PHASE 12 — FX NORMALIZATION TESTS

Test FX normalization correctness.
"""

import unittest
import pandas as pd
import numpy as np

from sentinel_x.marketdata.fx import FXNormalizer
from sentinel_x.marketdata.metadata import FXMetadata, MetadataLoader


class TestFXNormalization(unittest.TestCase):
    """Test FX normalization."""
    
    def test_fx_price_normalization(self):
        """Test FX price normalization to base currency."""
        normalizer = FXNormalizer(normalization_base="USD")
        
        # EURUSD: 1 EUR = 1.1 USD
        # Price of 1.1 means 1 EUR = 1.1 USD
        # Normalized to USD: should be 1.1 (already in USD)
        normalized = normalizer.normalize_price(1.1, "EURUSD")
        self.assertAlmostEqual(normalized, 1.1, places=6)
    
    def test_fx_dataframe_normalization(self):
        """Test FX DataFrame normalization."""
        normalizer = FXNormalizer(normalization_base="USD")
        
        # Create test FX data
        dates = pd.date_range(start='2024-1-1', periods=10, freq='1H')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': 1.1 + np.random.randn(10) * 0.01,
            'high': 1.11 + np.random.randn(10) * 0.01,
            'low': 1.09 + np.random.randn(10) * 0.01,
            'close': 1.1 + np.random.randn(10) * 0.01,
            'volume': 1000,
        })
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        
        # Normalize (simplified - would need metadata)
        # For now, just verify structure is preserved
        normalized = normalizer.normalize_dataframe(df, "EURUSD")
        
        self.assertEqual(len(normalized), len(df))
        self.assertIn('close', normalized.columns)


if __name__ == "__main__":
    unittest.main()
