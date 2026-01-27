"""
PHASE 5 — MULTI-ASSET TESTS

Test multi-asset support and cross-asset PnL reconciliation.
"""

import unittest
import os

os.environ["SENTINEL_ENGINE_MODE"] = "TRAINING"

from sentinel_x.shadow.assets import (
    AssetRegistry,
    ContractSpec,
    AssetType,
    AssetRiskLimits,
)


class TestMultiAsset(unittest.TestCase):
    """Test multi-asset support."""
    
    def setUp(self):
        """Set up asset registry."""
        self.registry = AssetRegistry()
    
    def test_contract_spec_registration(self):
        """Test contract specification registration."""
        spec = ContractSpec(
            symbol="SPY",
            asset_type=AssetType.EQUITY,
            tick_size=0.01,
            multiplier=1.0,
            currency="USD",
            fee_percentage=0.1,
        )
        
        self.registry.register_contract(spec)
        
        retrieved = self.registry.get_contract_spec("SPY")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.symbol, "SPY")
        self.assertEqual(retrieved.asset_type, AssetType.EQUITY)
    
    def test_fee_calculation(self):
        """Test fee calculation."""
        spec = ContractSpec(
            symbol="ES",
            asset_type=AssetType.FUTURE,
            tick_size=0.25,
            multiplier=50.0,
            currency="USD",
            fee_per_contract=2.0,
            fee_percentage=0.0,
        )
        
        # Trade: 2 contracts at 4000
        notional = 2 * 4000 * 50.0  # 400,000
        quantity = 2.0
        
        fee = spec.calculate_fee(notional, quantity)
        self.assertEqual(fee, 4.0)  # 2 contracts * $2.0
    
    def test_price_normalization(self):
        """Test price normalization to tick size."""
        spec = ContractSpec(
            symbol="EURUSD",
            asset_type=AssetType.FX,
            tick_size=0.0001,  # 1 pip
            multiplier=1.0,
            currency="USD",
        )
        
        # Price should be normalized to nearest pip
        normalized = spec.normalize_price(1.12345)
        self.assertEqual(normalized, 1.1234)  # Rounded to nearest pip
    
    def test_currency_normalization(self):
        """Test currency normalization."""
        self.registry.set_currency_rate("EUR", 1.1)  # 1 EUR = 1.1 USD
        self.registry.set_currency_rate("GBP", 1.25)  # 1 GBP = 1.25 USD
        
        # Convert 100 EUR to USD
        usd_amount = self.registry.normalize_currency(100.0, "EUR", "USD")
        self.assertAlmostEqual(usd_amount, 110.0, places=2)
        
        # Convert 100 GBP to EUR
        eur_amount = self.registry.normalize_currency(100.0, "GBP", "EUR")
        # 100 GBP = 125 USD = 125/1.1 EUR
        expected = 125.0 / 1.1
        self.assertAlmostEqual(eur_amount, expected, places=2)
    
    def test_cross_asset_pnl_aggregation(self):
        """Test cross-asset PnL aggregation."""
        # Register contracts
        equity_spec = ContractSpec(
            symbol="SPY",
            asset_type=AssetType.EQUITY,
            tick_size=0.01,
            multiplier=1.0,
            currency="USD",
        )
        
        future_spec = ContractSpec(
            symbol="ES",
            asset_type=AssetType.FUTURE,
            tick_size=0.25,
            multiplier=50.0,
            currency="USD",
        )
        
        crypto_spec = ContractSpec(
            symbol="BTCUSD",
            asset_type=AssetType.CRYPTO,
            tick_size=0.01,
            multiplier=1.0,
            currency="USD",
        )
        
        self.registry.register_contract(equity_spec)
        self.registry.register_contract(future_spec)
        self.registry.register_contract(crypto_spec)
        
        # Positions
        positions = {
            "SPY": {"quantity": 10.0, "avg_price": 400.0},
            "ES": {"quantity": 2.0, "avg_price": 4000.0},
            "BTCUSD": {"quantity": 0.1, "avg_price": 50000.0},
        }
        
        # Current prices
        current_prices = {
            "SPY": 410.0,  # +10 per share = +100 total
            "ES": 4050.0,  # +50 per contract * 50 multiplier * 2 contracts = +5000
            "BTCUSD": 51000.0,  # +1000 per coin * 0.1 = +100
        }
        
        # Calculate portfolio PnL
        pnl = self.registry.calculate_portfolio_pnl(positions, current_prices)
        
        # Verify PnL
        self.assertIn("total_pnl_usd", pnl)
        self.assertIn("asset_pnl", pnl)
        
        # SPY: (410 - 400) * 10 * 1.0 = 100
        # ES: (4050 - 4000) * 2 * 50.0 = 5000
        # BTCUSD: (51000 - 50000) * 0.1 * 1.0 = 100
        # Total: 5200
        expected_total = 100.0 + 5000.0 + 100.0
        self.assertAlmostEqual(pnl["total_pnl_usd"], expected_total, places=2)
        
        # Verify individual asset PnL
        self.assertAlmostEqual(pnl["asset_pnl"]["SPY"], 100.0, places=2)
        self.assertAlmostEqual(pnl["asset_pnl"]["ES"], 5000.0, places=2)
        self.assertAlmostEqual(pnl["asset_pnl"]["BTCUSD"], 100.0, places=2)
    
    def test_risk_limits_validation(self):
        """Test risk limits validation."""
        # Register contract
        spec = ContractSpec(
            symbol="TEST",
            asset_type=AssetType.EQUITY,
            tick_size=0.01,
            multiplier=1.0,
            currency="USD",
            min_trade_size=1.0,
            max_trade_size=1000.0,
        )
        self.registry.register_contract(spec)
        
        # Register risk limits
        limits = AssetRiskLimits(
            symbol="TEST",
            max_exposure=100000.0,
        )
        self.registry.register_risk_limits(limits)
        
        # Valid trade
        is_valid, reason = self.registry.validate_trade(
            symbol="TEST",
            quantity=100.0,
            price=100.0,
            current_exposure=0.0,
        )
        self.assertTrue(is_valid)
        self.assertIsNone(reason)
        
        # Trade below minimum
        is_valid, reason = self.registry.validate_trade(
            symbol="TEST",
            quantity=0.5,
            price=100.0,
            current_exposure=0.0,
        )
        self.assertFalse(is_valid)
        self.assertIsNotNone(reason)
        
        # Trade above maximum
        is_valid, reason = self.registry.validate_trade(
            symbol="TEST",
            quantity=2000.0,
            price=100.0,
            current_exposure=0.0,
        )
        self.assertFalse(is_valid)
        self.assertIsNotNone(reason)
        
        # Trade exceeds exposure limit
        is_valid, reason = self.registry.validate_trade(
            symbol="TEST",
            quantity=1000.0,
            price=200.0,  # 200,000 notional
            current_exposure=0.0,
        )
        self.assertFalse(is_valid)
        self.assertIsNotNone(reason)
    
    def test_correlation_tracking(self):
        """Test correlation tracking across assets."""
        # Update correlations
        self.registry.update_correlation("SPY", "QQQ", 0.85)
        self.registry.update_correlation("EURUSD", "GBPUSD", 0.70)
        
        # Retrieve correlations
        corr1 = self.registry.get_correlation("SPY", "QQQ")
        corr2 = self.registry.get_correlation("QQQ", "SPY")  # Should be same
        corr3 = self.registry.get_correlation("EURUSD", "GBPUSD")
        
        self.assertAlmostEqual(corr1, 0.85, places=2)
        self.assertAlmostEqual(corr2, 0.85, places=2)
        self.assertAlmostEqual(corr3, 0.70, places=2)
        
        # Non-existent correlation should return 0
        corr4 = self.registry.get_correlation("SPY", "BTCUSD")
        self.assertEqual(corr4, 0.0)


if __name__ == "__main__":
    unittest.main()
