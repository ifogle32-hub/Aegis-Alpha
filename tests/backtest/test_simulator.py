"""
PHASE 1 — TESTS FOR SHADOW BACKTESTING SIMULATOR

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Tests for shadow backtesting simulator as specified in requirements.
"""

import pytest
from datetime import datetime, timedelta
from typing import List, Dict

from sentinel_x.backtest.types import PriceBar
from sentinel_x.backtest.simulator import run_backtest, BacktestResult
from sentinel_x.strategies.templates import StrategyDefinition, get_strategy_template


def test_empty_history():
    """Test backtest with empty history returns zero PnL."""
    # Create a minimal strategy definition
    strat = StrategyDefinition(
        id="test_strategy",
        name="Test Strategy",
        asset="NONE",
        type="test",
        parameters={},
        signal_function=lambda data, params: []
    )
    
    # Run backtest with empty history
    history: Dict[str, List[PriceBar]] = {}
    result = run_backtest(strat, history)
    
    # Verify result structure
    assert isinstance(result, BacktestResult)
    assert result.strategy_id == "test_strategy"
    assert result.pnl == 0
    assert result.trades == 0


def test_simple_momentum():
    """Test simple momentum strategy backtest."""
    # Get a real strategy template
    strat = get_strategy_template("nvda_momentum")
    if strat is None:
        pytest.skip("nvda_momentum strategy template not found")
    
    # Create fake price data for testing
    base_time = datetime.now() - timedelta(days=30)
    price_data: List[PriceBar] = []
    
    # Generate synthetic price data with upward trend
    base_price = 100.0
    for i in range(100):  # 100 bars
        # Upward trend with some volatility
        price = base_price + i * 0.5 + (i % 10) * 0.1
        price_data.append(PriceBar(
            timestamp=base_time + timedelta(hours=i),
            open=price,
            high=price * 1.02,
            low=price * 0.98,
            close=price,
            volume=1000.0
        ))
    
    # Run backtest
    history = {"NVDA": price_data}
    result = run_backtest(strat, history, initial_capital=100000.0)
    
    # Verify result structure
    assert isinstance(result, BacktestResult)
    assert result.strategy_id == "nvda_momentum"
    assert result.asset == "NVDA"
    assert isinstance(result.pnl, float)
    assert isinstance(result.sharpe, float)
    assert isinstance(result.max_drawdown, float)
    assert isinstance(result.trades, int)
    assert result.trades >= 0  # Use trades field (maps to trade_count in API response)
    
    # Verify metrics are within reasonable ranges
    assert -1000000.0 <= result.pnl <= 1000000.0
    assert -10.0 <= result.sharpe <= 10.0
    assert 0.0 <= result.max_drawdown <= 1.0


def test_backtest_result_structure():
    """Test that BacktestResult has required fields."""
    # Create a backtest result with required fields
    result = BacktestResult(
        strategy_id="test",
        strategy_name="Test Strategy",
        asset="TEST",
        start_date=datetime.now(),
        end_date=datetime.now(),
        pnl=100.0,
        sharpe=1.0,
        max_drawdown=0.1,
        trades=10,
        win_rate=0.6,
        total_return=0.1,
        equity_curve=[100000.0, 100100.0],
        signals=[]
    )
    
    # Verify required fields exist (matching user's requirements)
    assert hasattr(result, 'strategy_id')
    assert hasattr(result, 'pnl')
    assert hasattr(result, 'sharpe')
    assert hasattr(result, 'max_drawdown')
    assert hasattr(result, 'trades')  # Maps to trade_count in API response
    
    # Verify values
    assert result.strategy_id == "test"
    assert result.pnl == 100.0
    assert result.sharpe == 1.0
    assert result.max_drawdown == 0.1
    assert result.trades == 10


def test_multiple_strategies():
    """Test running backtests for multiple strategies."""
    # Get strategy templates
    strategies = [
        get_strategy_template("nvda_momentum"),
        get_strategy_template("aapl_swing"),
        get_strategy_template("msft_mean_reversion")
    ]
    
    # Filter out None values
    strategies = [s for s in strategies if s is not None]
    if len(strategies) == 0:
        pytest.skip("No strategy templates found")
    
    # Create synthetic price data
    base_time = datetime.now() - timedelta(days=30)
    results = []
    
    for strat in strategies:
        # Generate price data for each asset
        price_data: List[PriceBar] = []
        base_price = 100.0
        
        for i in range(50):  # 50 bars
            price = base_price + i * 0.3
            price_data.append(PriceBar(
                timestamp=base_time + timedelta(hours=i),
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1000.0
            ))
        
        # Run backtest
        history = {strat.asset: price_data}
        try:
            result = run_backtest(strat, history, initial_capital=100000.0)
            results.append(result)
        except Exception as e:
            pytest.fail(f"Backtest failed for {strat.id}: {e}")
    
    # Verify all results are valid
    assert len(results) > 0
    for result in results:
        assert isinstance(result, BacktestResult)
        assert isinstance(result.pnl, float)
        assert isinstance(result.sharpe, float)
        assert isinstance(result.max_drawdown, float)
        assert isinstance(result.trades, int)
        assert result.trades >= 0
        assert 0.0 <= result.max_drawdown <= 1.0
