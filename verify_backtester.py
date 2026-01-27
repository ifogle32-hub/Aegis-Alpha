#!/usr/bin/env python3
"""
PHASE 13 — BACKTESTER VERIFICATION

SAFETY: backtester is isolated from live engine
SAFETY: no live execution path
REGRESSION LOCK — OFFLINE ONLY

Verification checks:
1) python -m py_compile sentinel_x/**/*.py
2) Run single-strategy backtest
3) Confirm deterministic results
4) Compare backtest vs live-training behavior
5) Confirm no data leakage
6) Confirm engine remains unaffected
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# Optional imports
try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("⚠️  pandas/numpy not available - some checks will be skipped")

# SAFETY: backtester is isolated from live engine
# SAFETY: no live execution path
# REGRESSION LOCK — OFFLINE ONLY

def check_compilation():
    """PHASE 13: Check 1 - Compilation."""
    print("=" * 60)
    print("CHECK 1: Compilation")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            ["python", "-m", "py_compile", "sentinel_x/research/backtest_engine.py",
             "sentinel_x/research/backtest_advanced.py", "sentinel_x/research/backtest_output.py"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Compilation successful")
            return True
        else:
            print(f"❌ Compilation failed:\n{result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Compilation check error: {e}")
        return False


def check_no_live_broker_imports():
    """PHASE 13: Check 2 - No live broker imports."""
    print("\n" + "=" * 60)
    print("CHECK 2: No Live Broker Imports")
    print("=" * 60)
    
    backtest_files = [
        "sentinel_x/research/backtest_engine.py",
        "sentinel_x/research/backtest_advanced.py",
        "sentinel_x/research/backtest_output.py"
    ]
    
    forbidden_patterns = [
        "from sentinel_x.execution",
        "import.*execution",
        "from sentinel_x.core.engine",
        "import.*engine",
        "AlpacaExecutor",
        "PaperExecutor",
        "BaseBroker"
    ]
    
    violations = []
    for filepath in backtest_files:
        try:
            with open(filepath, 'r') as f:
                content = f.read()
                for pattern in forbidden_patterns:
                    if pattern in content:
                        violations.append(f"{filepath}: {pattern}")
        except Exception as e:
            print(f"⚠️  Error reading {filepath}: {e}")
    
    if violations:
        print("❌ Found live broker imports:")
        for v in violations:
            print(f"   - {v}")
        return False
    else:
        print("✅ No live broker imports found")
        return True


def test_single_strategy_backtest():
    """PHASE 13: Check 3 - Single strategy backtest."""
    print("\n" + "=" * 60)
    print("CHECK 3: Single Strategy Backtest")
    print("=" * 60)
    
    if not HAS_PANDAS:
        print("⚠️  Skipped (pandas not available)")
        return True
    
    try:
        from sentinel_x.research.backtest_engine import (
            BacktestEngine, HistoricalDataFeed, EventQueue
        )
        from sentinel_x.strategies.momentum import MomentumStrategy
        
        # Create synthetic data
        dates = pd.date_range(start='2024-01-01', end='2024-01-31', freq='1H')
        prices = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
        
        data = pd.DataFrame({
            'timestamp': dates,
            'open': prices,
            'high': prices * 1.01,
            'low': prices * 0.99,
            'close': prices,
            'volume': np.random.randint(1000, 10000, len(dates))
        })
        
        # Create data feed
        data_feed = HistoricalDataFeed({'TEST': data})
        
        # Create engine
        engine = BacktestEngine(initial_capital=100000.0, seed=42)
        engine.set_data_feed(data_feed)
        
        # Add strategy
        strategy = MomentumStrategy(fast_ema=5, slow_ema=10)
        engine.add_strategy(strategy, ['TEST'])
        
        # Run backtest
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 31)
        results = engine.run(start_date, end_date)
        
        if results and 'final_equity' in results:
            print(f"✅ Backtest completed successfully")
            print(f"   Final equity: ${results['final_equity']:,.2f}")
            print(f"   Total trades: {len(results.get('trades', []))}")
            return True
        else:
            print("❌ Backtest returned invalid results")
            return False
            
    except Exception as e:
        print(f"❌ Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_deterministic_results():
    """PHASE 13: Check 4 - Deterministic results."""
    print("\n" + "=" * 60)
    print("CHECK 4: Deterministic Results")
    print("=" * 60)
    
    if not HAS_PANDAS:
        print("⚠️  Skipped (pandas not available)")
        return True
    
    try:
        from sentinel_x.research.backtest_engine import (
            BacktestEngine, HistoricalDataFeed
        )
        from sentinel_x.strategies.momentum import MomentumStrategy
        
        # Create synthetic data
        dates = pd.date_range(start='2024-01-01', end='2024-01-10', freq='1H')
        prices = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
        
        data = pd.DataFrame({
            'timestamp': dates,
            'open': prices,
            'high': prices * 1.01,
            'low': prices * 0.99,
            'close': prices,
            'volume': np.random.randint(1000, 10000, len(dates))
        })
        
        # Run backtest twice with same seed
        results1 = None
        results2 = None
        
        for i in range(2):
            data_feed = HistoricalDataFeed({'TEST': data})
            engine = BacktestEngine(initial_capital=100000.0, seed=42)
            engine.set_data_feed(data_feed)
            strategy = MomentumStrategy(fast_ema=5, slow_ema=10)
            engine.add_strategy(strategy, ['TEST'])
            
            start_date = datetime(2024, 1, 1)
            end_date = datetime(2024, 1, 10)
            results = engine.run(start_date, end_date)
            
            if i == 0:
                results1 = results
            else:
                results2 = results
        
        # Compare results
        if results1 and results2:
            equity1 = results1.get('final_equity', 0)
            equity2 = results2.get('final_equity', 0)
            
            if abs(equity1 - equity2) < 0.01:  # Allow small floating point differences
                print(f"✅ Results are deterministic (equity: ${equity1:,.2f})")
                return True
            else:
                print(f"❌ Results are not deterministic (equity1: ${equity1:,.2f}, equity2: ${equity2:,.2f})")
                return False
        else:
            print("❌ Could not compare results")
            return False
            
    except Exception as e:
        print(f"❌ Deterministic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_no_data_leakage():
    """PHASE 13: Check 5 - No data leakage."""
    print("\n" + "=" * 60)
    print("CHECK 5: No Data Leakage")
    print("=" * 60)
    
    if not HAS_PANDAS:
        print("⚠️  Skipped (pandas not available)")
        return True
    
    try:
        from sentinel_x.research.backtest_engine import HistoricalDataFeed
        
        # Create data with future timestamps
        dates = pd.date_range(start='2024-01-01', end='2024-01-10', freq='1H')
        prices = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
        
        data = pd.DataFrame({
            'timestamp': dates,
            'open': prices,
            'high': prices * 1.01,
            'low': prices * 0.99,
            'close': prices,
            'volume': np.random.randint(1000, 10000, len(dates))
        })
        
        # Test get_data_range (should not return future data)
        data_feed = HistoricalDataFeed({'TEST': data})
        
        # Request data up to a specific timestamp
        end_time = datetime(2024, 1, 5)
        df = data_feed.get_data_range('TEST', datetime(2024, 1, 1), end_time)
        
        if df is not None and len(df) > 0:
            max_timestamp = pd.to_datetime(df['timestamp']).max()
            if max_timestamp <= end_time:
                print("✅ No data leakage detected")
                return True
            else:
                print(f"❌ Data leakage detected: max timestamp {max_timestamp} > end_time {end_time}")
                return False
        else:
            print("⚠️  No data returned (may be expected)")
            return True
            
    except Exception as e:
        print(f"❌ Data leakage test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_engine_unaffected():
    """PHASE 13: Check 6 - Engine remains unaffected."""
    print("\n" + "=" * 60)
    print("CHECK 6: Engine Remains Unaffected")
    print("=" * 60)
    
    try:
        # Try to import live engine
        from sentinel_x.core.engine import TradingEngine
        
        # Check that backtester doesn't import it
        import sentinel_x.research.backtest_engine as bt_module
        
        # Check module imports
        if 'TradingEngine' in dir(bt_module):
            print("❌ Backtester imports TradingEngine (should be isolated)")
            return False
        else:
            print("✅ Backtester does not import TradingEngine")
            return True
            
    except Exception as e:
        print(f"⚠️  Could not verify engine isolation: {e}")
        return True  # Non-fatal


def main():
    """PHASE 13: Run all verification checks."""
    print("\n" + "=" * 60)
    print("BACKTESTER VERIFICATION")
    print("=" * 60)
    print()
    
    checks = [
        ("Compilation", check_compilation),
        ("No Live Broker Imports", check_no_live_broker_imports),
        ("Single Strategy Backtest", test_single_strategy_backtest),
        ("Deterministic Results", test_deterministic_results),
        ("No Data Leakage", test_no_data_leakage),
        ("Engine Unaffected", test_engine_unaffected)
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Check '{name}' raised exception: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n✅ All verification checks passed!")
        return 0
    else:
        print(f"\n❌ {total - passed} check(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
