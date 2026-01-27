"""
PHASE 1 — TESTS FOR SHADOW BACKTESTING SIMULATOR

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Tests for shadow backtesting simulator skeleton.
"""

import pytest
from datetime import datetime, timedelta
from typing import List, Dict

from sentinel_x.backtest.types import PriceBar, Signal
from sentinel_x.backtest.simulator import ShadowBacktestSimulator, BacktestResult, Trade, run_backtest
from sentinel_x.backtest.data_loader import load_price_history
from sentinel_x.strategies.templates import (
    StrategyDefinition,
    get_strategy_template,
    generate_nvda_momentum_signal
)


class TestPriceBar:
    """Tests for PriceBar dataclass."""
    
    def test_price_bar_creation(self):
        """Test creating a valid PriceBar."""
        bar = PriceBar(
            timestamp=datetime.now(),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000.0
        )
        assert bar.open == 100.0
        assert bar.high == 105.0
        assert bar.low == 95.0
        assert bar.close == 102.0
        assert bar.volume == 1000.0
    
    def test_price_bar_validation_negative_prices(self):
        """Test PriceBar validation rejects negative prices."""
        with pytest.raises(ValueError):
            PriceBar(
                timestamp=datetime.now(),
                open=-100.0,
                high=105.0,
                low=95.0,
                close=102.0,
                volume=1000.0
            )
    
    def test_price_bar_validation_low_above_high(self):
        """Test PriceBar validation rejects low > high."""
        with pytest.raises(ValueError):
            PriceBar(
                timestamp=datetime.now(),
                open=100.0,
                high=95.0,
                low=105.0,
                close=102.0,
                volume=1000.0
            )


class TestSignal:
    """Tests for Signal dataclass."""
    
    def test_signal_creation(self):
        """Test creating a valid Signal."""
        signal = Signal(
            strategy_id="test_strategy",
            timestamp=datetime.now(),
            symbol="NVDA",
            side="BUY",
            confidence=0.8,
            price=100.0
        )
        assert signal.strategy_id == "test_strategy"
        assert signal.symbol == "NVDA"
        assert signal.side == "BUY"
        assert signal.confidence == 0.8
        assert signal.price == 100.0
    
    def test_signal_validation_invalid_side(self):
        """Test Signal validation rejects invalid side."""
        with pytest.raises(ValueError):
            Signal(
                strategy_id="test_strategy",
                timestamp=datetime.now(),
                symbol="NVDA",
                side="INVALID",
                confidence=0.8
            )
    
    def test_signal_validation_confidence_range(self):
        """Test Signal validation rejects confidence outside 0-1."""
        with pytest.raises(ValueError):
            Signal(
                strategy_id="test_strategy",
                timestamp=datetime.now(),
                symbol="NVDA",
                side="BUY",
                confidence=1.5
            )


class TestStrategyTemplates:
    """Tests for strategy template functions."""
    
    def test_nvda_momentum_signal_empty_data(self):
        """Test momentum signal with insufficient data returns empty."""
        price_data = []
        params = {"lookback": 20, "fast_ema": 12, "slow_ema": 26, "threshold": 1.5}
        signals = generate_nvda_momentum_signal(price_data, params)
        assert signals == []
    
    def test_nvda_momentum_signal_returns_list(self):
        """Test momentum signal returns list of Signal objects."""
        # Create minimal price data
        base_time = datetime.now()
        price_data = []
        for i in range(30):
            price = 100.0 + i * 0.1
            price_data.append(PriceBar(
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1000.0
            ))
        
        params = {"lookback": 20, "fast_ema": 12, "slow_ema": 26, "threshold": 1.5}
        signals = generate_nvda_momentum_signal(price_data, params)
        assert isinstance(signals, list)
        assert all(isinstance(s, Signal) for s in signals)
        for signal in signals:
            assert signal.side in ("BUY", "SELL")
            assert 0.0 <= signal.confidence <= 1.0
    
    def test_get_strategy_template(self):
        """Test getting strategy template by ID."""
        template = get_strategy_template("nvda_momentum")
        assert template is not None
        assert template.id == "nvda_momentum"
        assert template.mode == "SHADOW"
    
    def test_get_strategy_template_not_found(self):
        """Test getting non-existent strategy template returns None."""
        template = get_strategy_template("nonexistent")
        assert template is None


class TestShadowBacktestSimulator:
    """Tests for ShadowBacktestSimulator."""
    
    def test_simulator_initialization(self):
        """Test simulator initializes correctly."""
        simulator = ShadowBacktestSimulator(
            initial_capital=100000.0,
            slippage_pct=0.001,
            fee_pct=0.001
        )
        assert simulator.initial_capital == 100000.0
        assert simulator.slippage_pct == 0.001
        assert simulator.fee_pct == 0.001
    
    def test_simulator_empty_data(self):
        """Test simulator handles empty price data."""
        simulator = ShadowBacktestSimulator()
        strategy = get_strategy_template("nvda_momentum")
        assert strategy is not None
        
        history = {"NVDA": []}
        result = simulator.run_backtest(strategy, history)
        
        assert isinstance(result, BacktestResult)
        assert result.strategy_id == "nvda_momentum"
        assert result.pnl == 0.0
        assert result.trades == 0
    
    def test_simulator_trivial_data(self):
        """Test simulator runs on trivial price data."""
        simulator = ShadowBacktestSimulator(initial_capital=100000.0)
        strategy = get_strategy_template("nvda_momentum")
        assert strategy is not None
        
        # Create minimal price data
        base_time = datetime.now()
        price_data = []
        for i in range(50):
            price = 100.0 + i * 0.1
            price_data.append(PriceBar(
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1000.0
            ))
        
        history = {"NVDA": price_data}
        result = simulator.run_backtest(strategy, history)
        
        assert isinstance(result, BacktestResult)
        assert result.strategy_id == "nvda_momentum"
        assert result.asset == "NVDA"
        assert isinstance(result.pnl, float)
        assert isinstance(result.sharpe, float)
        assert isinstance(result.max_drawdown, float)
        assert isinstance(result.trades, int)
        assert result.trades >= 0
        assert 0.0 <= result.max_drawdown <= 1.0
        assert 0.0 <= result.win_rate <= 1.0
        assert len(result.equity_curve) > 0
        assert isinstance(result.signals, list)
    
    def test_simulator_metrics_calculation(self):
        """Test simulator calculates metrics correctly."""
        simulator = ShadowBacktestSimulator(initial_capital=100000.0)
        strategy = get_strategy_template("aapl_swing")
        assert strategy is not None
        
        # Create price data with clear trend
        base_time = datetime.now()
        price_data = []
        for i in range(100):
            # Upward trend
            price = 150.0 + i * 0.5
            price_data.append(PriceBar(
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=price * 1.02,
                low=price * 0.98,
                close=price,
                volume=5000.0
            ))
        
        history = {"AAPL": price_data}
        result = simulator.run_backtest(strategy, history)
        
        # Verify all metrics are floats
        assert isinstance(result.pnl, float)
        assert isinstance(result.sharpe, float)
        assert isinstance(result.max_drawdown, float)
        assert isinstance(result.total_return, float)
        
        # Verify metrics are within reasonable ranges
        assert -1000000.0 <= result.pnl <= 1000000.0  # Reasonable PnL range
        assert -10.0 <= result.sharpe <= 10.0  # Reasonable Sharpe range
        assert 0.0 <= result.max_drawdown <= 1.0  # Drawdown as percentage
        assert -1.0 <= result.total_return <= 10.0  # Total return reasonable


class TestTrade:
    """Tests for Trade dataclass."""
    
    def test_trade_creation(self):
        """Test creating a Trade."""
        trade = Trade(
            entry_time=datetime.now(),
            exit_time=None,
            entry_price=100.0,
            exit_price=None,
            side="BUY",
            quantity=10.0
        )
        assert trade.is_open
        assert trade.pnl is None
    
    def test_trade_close_long(self):
        """Test closing a long trade calculates PnL correctly."""
        trade = Trade(
            entry_time=datetime.now(),
            exit_time=None,
            entry_price=100.0,
            exit_price=None,
            side="BUY",
            quantity=10.0
        )
        trade.close(110.0, datetime.now())
        assert not trade.is_open
        assert trade.pnl == 100.0  # (110 - 100) * 10
    
    def test_trade_close_short(self):
        """Test closing a short trade calculates PnL correctly."""
        trade = Trade(
            entry_time=datetime.now(),
            exit_time=None,
            entry_price=100.0,
            exit_price=None,
            side="SELL",
            quantity=10.0
        )
        trade.close(90.0, datetime.now())
        assert not trade.is_open
        assert trade.pnl == 100.0  # (100 - 90) * 10


class TestDataLoader:
    """Tests for data loader functions."""
    
    def test_load_price_history_synthetic(self):
        """Test loading synthetic price history."""
        start = datetime.now() - timedelta(days=1)
        end = datetime.now()
        
        # This should generate synthetic data
        price_bars = load_price_history("NVDA", start, end)
        
        assert isinstance(price_bars, list)
        assert len(price_bars) > 0
        assert all(isinstance(bar, PriceBar) for bar in price_bars)
        
        # Verify timestamps are in range
        for bar in price_bars:
            assert start <= bar.timestamp <= end


class TestIntegration:
    """Integration tests for shadow backtesting."""
    
    def test_end_to_end_backtest(self):
        """Test complete end-to-end backtest flow."""
        # Get strategy template
        strategy = get_strategy_template("nvda_momentum")
        assert strategy is not None
        
        # Generate synthetic price data
        start = datetime.now() - timedelta(days=7)
        end = datetime.now()
        price_data = load_price_history("NVDA", start, end)
        
        # Ensure we have enough data
        assert len(price_data) > 50, "Need at least 50 bars for backtest"
        
        # Run backtest
        history = {"NVDA": price_data}
        result = run_backtest(strategy, history, initial_capital=100000.0)
        
        # Verify result structure
        assert isinstance(result, BacktestResult)
        assert result.strategy_id == "nvda_momentum"
        assert result.asset == "NVDA"
        assert result.start_date <= result.end_date
        assert len(result.equity_curve) > 0
        assert result.equity_curve[0] == 100000.0  # Initial capital
        assert isinstance(result.signals, list)
        
        # Verify all metrics are calculated
        assert isinstance(result.pnl, float)
        assert isinstance(result.sharpe, float)
        assert isinstance(result.max_drawdown, float)
        assert isinstance(result.trades, int)
        assert isinstance(result.win_rate, float)
        assert isinstance(result.total_return, float)
    
    def test_multiple_strategy_backtest(self):
        """Test running backtests for multiple strategies."""
        strategies = [
            get_strategy_template("nvda_momentum"),
            get_strategy_template("aapl_swing"),
            get_strategy_template("msft_mean_reversion")
        ]
        
        # Filter out None values
        strategies = [s for s in strategies if s is not None]
        assert len(strategies) > 0
        
        start = datetime.now() - timedelta(days=7)
        end = datetime.now()
        
        results = []
        for strategy in strategies:
            price_data = load_price_history(strategy.asset, start, end)
            if len(price_data) > 50:  # Ensure enough data
                history = {strategy.asset: price_data}
                result = run_backtest(strategy, history)
                results.append(result)
        
        # Verify all results are valid
        assert len(results) > 0
        for result in results:
            assert isinstance(result, BacktestResult)
            assert result.trades >= 0
            assert 0.0 <= result.max_drawdown <= 1.0
