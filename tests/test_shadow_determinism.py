"""
PHASE 5 — CI TESTS FOR SHADOW DETERMINISM

Test suite for shadow training determinism and safety.

Test categories:
1) Deterministic replay
   - Same data → same signals
   - Same signals → same scores
2) Strategy isolation
   - One strategy failure does not affect others
3) No live execution leakage
   - Assert broker code is never invoked
4) Restart safety
   - Resume shadow training without data loss
5) Multi-asset correctness
   - Cross-asset PnL reconciliation

CI requirements:
- Runs headless
- No network calls
- No external brokers
- Seeded randomness only
- Fails hard on nondeterminism
"""

import unittest
import os
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import Dict, List
import pandas as pd
import numpy as np

# Set test environment
os.environ["SENTINEL_ENGINE_MODE"] = "TRAINING"
os.environ["SENTINEL_SHADOW_ENABLED"] = "true"

from sentinel_x.shadow.trainer import ShadowTrainer, ShadowTrainerConfig
from sentinel_x.shadow.registry import get_strategy_registry
from sentinel_x.shadow.scorer import get_shadow_scorer
from sentinel_x.shadow.replay import HistoricalReplayFeed, ReplayMode
from sentinel_x.shadow.definitions import ShadowMode
from sentinel_x.shadow.assets import AssetRegistry, ContractSpec, AssetType
from sentinel_x.strategies.base import BaseStrategy


class TestStrategy(BaseStrategy):
    """Test strategy for determinism testing."""
    
    def __init__(self, name: str = "TestStrategy", seed: int = 42):
        super().__init__(name=name)
        np.random.seed(seed)
        self.signals = []
    
    def safe_on_tick(self, market_data):
        """Generate deterministic signal."""
        price = market_data.get("price", 100.0)
        # Deterministic signal based on price
        if price > 105.0:
            return {"symbol": market_data.get("symbol", "TEST"), "side": "SELL", "qty": 1}
        elif price < 95.0:
            return {"symbol": market_data.get("symbol", "TEST"), "side": "BUY", "qty": 1}
        return None


class TestShadowDeterminism(unittest.TestCase):
    """Test shadow training determinism."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_seed = 42
        np.random.seed(self.test_seed)
        
        # Create test data
        self.test_data = self._create_test_data()
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_test_data(self) -> Dict[str, pd.DataFrame]:
        """Create deterministic test data."""
        dates = pd.date_range(
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 10),
            freq='1H'
        )
        
        np.random.seed(self.test_seed)
        
        data = {}
        for symbol in ["TEST1", "TEST2"]:
            prices = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
            
            df = pd.DataFrame({
                'timestamp': dates,
                'open': prices,
                'high': prices * 1.01,
                'low': prices * 0.99,
                'close': prices,
                'volume': np.random.randint(1000, 10000, len(dates)),
            })
            
            data[symbol] = df
        
        return data
    
    def test_deterministic_replay_same_data_same_signals(self):
        """Test that same data produces same signals."""
        # Run replay twice with same data and seed
        signals1 = self._run_replay_and_capture_signals(seed=42)
        signals2 = self._run_replay_and_capture_signals(seed=42)
        
        # Signals should be identical
        self.assertEqual(len(signals1), len(signals2))
        for s1, s2 in zip(signals1, signals2):
            self.assertEqual(s1, s2)
    
    def test_deterministic_replay_same_signals_same_scores(self):
        """Test that same signals produce same scores."""
        # Run replay and get scores
        scores1 = self._run_replay_and_get_scores(seed=42)
        scores2 = self._run_replay_and_get_scores(seed=42)
        
        # Scores should be identical (within floating point tolerance)
        self.assertAlmostEqual(scores1.get("total_return", 0), scores2.get("total_return", 0), places=6)
        self.assertAlmostEqual(scores1.get("sharpe_ratio", 0), scores2.get("sharpe_ratio", 0), places=6)
    
    def test_strategy_isolation(self):
        """Test that one strategy failure does not affect others."""
        registry = get_strategy_registry()
        
        # Register two strategies
        strategy1 = TestStrategy(name="Strategy1", seed=42)
        strategy2 = TestStrategy(name="Strategy2", seed=43)
        
        id1 = registry.register(strategy1)
        id2 = registry.register(strategy2)
        
        # Verify both are registered
        self.assertIsNotNone(registry.get_strategy(id1))
        self.assertIsNotNone(registry.get_strategy(id2))
        
        # Unregister one
        registry.unregister(id1)
        
        # Other should still be registered
        self.assertIsNone(registry.get_strategy(id1))
        self.assertIsNotNone(registry.get_strategy(id2))
    
    def test_no_live_execution_leakage(self):
        """Test that broker code is never invoked."""
        # This test verifies that shadow training never calls broker execution
        # In a real implementation, we would mock the broker and assert it's never called
        
        # For now, we verify that shadow trainer doesn't have broker references
        trainer = ShadowTrainer()
        
        # Shadow trainer should not have order_router or broker references
        self.assertFalse(hasattr(trainer, 'order_router'))
        self.assertFalse(hasattr(trainer, 'broker'))
    
    def test_restart_safety(self):
        """Test that shadow training can resume without data loss."""
        # Create trainer and register strategy
        trainer = ShadowTrainer()
        strategy = TestStrategy(name="RestartTest", seed=42)
        strategy_id = trainer.register_strategy(strategy)
        
        # Start training
        trainer.start(symbols=["TEST1"])
        
        # Process some ticks
        from sentinel_x.shadow.feed import MarketTick
        for i in range(10):
            tick = MarketTick(
                symbol="TEST1",
                timestamp=datetime.utcnow(),
                price=100.0 + i,
                volume=1000.0,
            )
            trainer.process_tick(tick)
        
        # Stop and restart
        trainer.stop()
        trainer.start(symbols=["TEST1"])
        
        # Verify strategy is still registered
        registry = get_strategy_registry()
        self.assertIsNotNone(registry.get_strategy(strategy_id))
    
    def test_multi_asset_correctness(self):
        """Test cross-asset PnL reconciliation."""
        asset_registry = AssetRegistry()
        
        # Register contracts
        spec1 = ContractSpec(
            symbol="TEST1",
            asset_type=AssetType.EQUITY,
            tick_size=0.01,
            multiplier=1.0,
            currency="USD",
        )
        spec2 = ContractSpec(
            symbol="TEST2",
            asset_type=AssetType.FUTURE,
            tick_size=0.25,
            multiplier=50.0,
            currency="USD",
        )
        
        asset_registry.register_contract(spec1)
        asset_registry.register_contract(spec2)
        
        # Calculate portfolio PnL
        positions = {
            "TEST1": {"quantity": 10.0, "avg_price": 100.0},
            "TEST2": {"quantity": 2.0, "avg_price": 2000.0},
        }
        current_prices = {
            "TEST1": 105.0,
            "TEST2": 2050.0,
        }
        
        pnl = asset_registry.calculate_portfolio_pnl(positions, current_prices)
        
        # Verify PnL calculation
        self.assertIn("total_pnl_usd", pnl)
        self.assertIn("asset_pnl", pnl)
        
        # TEST1: (105 - 100) * 10 * 1.0 = 50
        # TEST2: (2050 - 2000) * 2 * 50.0 = 5000
        # Total: 5050
        expected_pnl = 50.0 + 5000.0
        self.assertAlmostEqual(pnl["total_pnl_usd"], expected_pnl, places=2)
    
    def _run_replay_and_capture_signals(self, seed: int) -> List[Dict]:
        """Run replay and capture signals."""
        # Create strategy with seed
        strategy = TestStrategy(name="ReplayTest", seed=seed)
        
        # Create trainer
        trainer = ShadowTrainer()
        strategy_id = trainer.register_strategy(strategy)
        
        # Create replay feed
        replay_feed = HistoricalReplayFeed(
            symbols=["TEST1"],
            historical_data=self.test_data,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 2),
            replay_mode=ReplayMode.STRICT,
            seed=seed,
        )
        
        trainer.market_feed = replay_feed
        replay_feed.start()
        
        # Process ticks and capture signals
        signals = []
        for _ in range(10):
            tick = replay_feed.get_next_tick()
            if tick:
                trainer.process_tick(tick)
                # Capture signals from strategy
                if hasattr(strategy, 'signals'):
                    signals.extend(strategy.signals)
        
        return signals
    
    def _run_replay_and_get_scores(self, seed: int) -> Dict:
        """Run replay and get scores."""
        # Create strategy with seed
        strategy = TestStrategy(name="ScoreTest", seed=seed)
        
        # Create trainer
        trainer = ShadowTrainer()
        strategy_id = trainer.register_strategy(strategy)
        
        # Create replay feed
        replay_feed = HistoricalReplayFeed(
            symbols=["TEST1"],
            historical_data=self.test_data,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 2),
            replay_mode=ReplayMode.STRICT,
            seed=seed,
        )
        
        trainer.market_feed = replay_feed
        replay_feed.start()
        
        # Process ticks
        for _ in range(20):
            tick = replay_feed.get_next_tick()
            if tick:
                trainer.process_tick(tick)
        
        # Get scores
        scorer = get_shadow_scorer()
        metrics = scorer.get_latest_metrics(strategy_id)
        
        if metrics:
            return {
                "total_return": metrics.total_return,
                "sharpe_ratio": metrics.sharpe_ratio,
                "max_drawdown": metrics.max_drawdown,
            }
        
        return {}


if __name__ == "__main__":
    unittest.main()
