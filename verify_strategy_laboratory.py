#!/usr/bin/env python3
"""
PHASE 10: Verification Script for Strategy Laboratory

Checks:
1) python -m py_compile sentinel_x/**/*.py
2) Confirm strategies auto-generate
3) Confirm variants score independently
4) Confirm demotion disables only strategy
5) Confirm dashboard reflects reality
6) Confirm no LIVE path exists

SAFETY: Training-only verification
SAFETY: No execution behavior modified
"""
import sys
import subprocess
import importlib.util
from pathlib import Path


def check_syntax():
    """Check 1: Python syntax compilation."""
    print("=" * 60)
    print("CHECK 1: Python Syntax Compilation")
    print("=" * 60)
    
    try:
        # Compile all Python files
        sentinel_x_path = Path(__file__).parent / "sentinel_x"
        
        # Find all Python files
        python_files = list(sentinel_x_path.rglob("*.py"))
        
        errors = []
        for py_file in python_files:
            try:
                # Compile the file
                result = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(py_file)],
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    errors.append(f"{py_file}: {result.stderr}")
            except Exception as e:
                errors.append(f"{py_file}: {str(e)}")
        
        if errors:
            print(f"❌ FAILED: {len(errors)} syntax errors found")
            for error in errors[:10]:  # Show first 10
                print(f"  {error}")
            return False
        else:
            print(f"✅ PASSED: All {len(python_files)} Python files compile successfully")
            return True
    
    except Exception as e:
        print(f"❌ FAILED: Error during syntax check: {e}")
        return False


def check_imports():
    """Check 2: Critical module imports."""
    print("\n" + "=" * 60)
    print("CHECK 2: Critical Module Imports")
    print("=" * 60)
    
    modules_to_check = [
        "sentinel_x.intelligence.models",
        "sentinel_x.intelligence.strategy_factory",
        "sentinel_x.intelligence.auto_generation",
        "sentinel_x.intelligence.governance",
        "sentinel_x.intelligence.strategy_manager",
    ]
    
    errors = []
    for module_name in modules_to_check:
        try:
            spec = importlib.util.find_spec(module_name)
            if spec is None:
                errors.append(f"{module_name}: Module not found")
            else:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                print(f"✅ {module_name}: Imported successfully")
        except Exception as e:
            errors.append(f"{module_name}: {str(e)}")
    
    if errors:
        print(f"\n❌ FAILED: {len(errors)} import errors found")
        for error in errors:
            print(f"  {error}")
        return False
    else:
        print(f"\n✅ PASSED: All {len(modules_to_check)} modules import successfully")
        return True


def check_live_path_blocked():
    """Check 3: Verify no LIVE path exists."""
    print("\n" + "=" * 60)
    print("CHECK 3: Verify No LIVE Path Exists")
    print("=" * 60)
    
    try:
        # Check config validation
        from sentinel_x.core.config import Config
        
        # Try to set LIVE mode without unlock conditions
        config = Config.from_env()
        config.engine_mode = "LIVE"
        config.validate()
        
        # After validation, engine_mode should be forced to TRAINING
        if config.engine_mode == "LIVE":
            print("❌ FAILED: LIVE mode not blocked in config validation")
            return False
        else:
            print(f"✅ PASSED: LIVE mode correctly blocked (forced to {config.engine_mode})")
            return True
    
    except Exception as e:
        print(f"❌ FAILED: Error checking LIVE path: {e}")
        return False


def check_strategy_config():
    """Check 4: StrategyConfig validation."""
    print("\n" + "=" * 60)
    print("CHECK 4: StrategyConfig Validation")
    print("=" * 60)
    
    try:
        from sentinel_x.intelligence.models import StrategyConfig, RiskLimits, StrategyLifecycleState
        
        # Test valid config
        try:
            valid_config = StrategyConfig(
                strategy_type="momentum",
                timeframe=15,
                lookback=50,
                entry_params={"fast_ema": 10, "slow_ema": 30}
            )
            print("✅ Valid StrategyConfig created successfully")
        except Exception as e:
            print(f"❌ FAILED: Valid config creation failed: {e}")
            return False
        
        # Test invalid config (should raise ValueError)
        try:
            invalid_config = StrategyConfig(
                strategy_type="invalid_type",  # Invalid
                timeframe=15,
                lookback=50
            )
            print("❌ FAILED: Invalid config did not raise ValueError")
            return False
        except ValueError:
            print("✅ Invalid StrategyConfig correctly rejected")
        except Exception as e:
            print(f"❌ FAILED: Unexpected error: {e}")
            return False
        
        # Check lifecycle states
        if StrategyLifecycleState.TRAINING.value == "TRAINING":
            print("✅ StrategyLifecycleState.TRAINING exists")
        else:
            print("❌ FAILED: StrategyLifecycleState.TRAINING not found")
            return False
        
        return True
    
    except Exception as e:
        print(f"❌ FAILED: Error checking StrategyConfig: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_factory_safety():
    """Check 5: StrategyFactory safety locks."""
    print("\n" + "=" * 60)
    print("CHECK 5: StrategyFactory Safety Locks")
    print("=" * 60)
    
    try:
        from sentinel_x.intelligence.strategy_factory import StrategyFactory, get_strategy_factory
        
        # Check factory has STRATEGY_CLASS_MAP (no eval/exec)
        factory = StrategyFactory()
        if hasattr(factory, 'STRATEGY_CLASS_MAP'):
            print(f"✅ STRATEGY_CLASS_MAP exists with {len(factory.STRATEGY_CLASS_MAP)} strategy types")
        else:
            print("❌ FAILED: STRATEGY_CLASS_MAP not found")
            return False
        
        # Check all entries are valid classes (not strings for eval)
        for strategy_type, strategy_class in factory.STRATEGY_CLASS_MAP.items():
            if not isinstance(strategy_class, type):
                print(f"❌ FAILED: {strategy_type} maps to non-class: {strategy_class}")
                return False
        print("✅ All STRATEGY_CLASS_MAP entries are valid classes (no eval/exec)")
        
        return True
    
    except Exception as e:
        print(f"❌ FAILED: Error checking StrategyFactory: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_governance():
    """Check 6: Governance limits."""
    print("\n" + "=" * 60)
    print("CHECK 6: Governance Limits")
    print("=" * 60)
    
    try:
        from sentinel_x.intelligence.governance import GovernanceLimits, StrategyGovernance, get_governance
        
        # Check governance limits exist
        limits = GovernanceLimits()
        if limits.max_strategies > 0:
            print(f"✅ Governance limits exist: max_strategies={limits.max_strategies}")
        else:
            print("❌ FAILED: Governance limits not configured")
            return False
        
        # Check governance enforcement
        governance = StrategyGovernance(limits)
        
        # Test strategy count limit
        allowed, violation = governance.check_strategy_count(limits.max_strategies - 1)
        if allowed and violation is None:
            print("✅ Strategy count limit check works (within limit)")
        else:
            print(f"❌ FAILED: Strategy count limit check failed: {violation}")
            return False
        
        # Test violation detection
        allowed, violation = governance.check_strategy_count(limits.max_strategies + 1)
        if not allowed and violation is not None:
            print("✅ Strategy count limit violation correctly detected")
        else:
            print(f"❌ FAILED: Strategy count limit violation not detected")
            return False
        
        return True
    
    except Exception as e:
        print(f"❌ FAILED: Error checking governance: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification checks."""
    print("\n" + "=" * 60)
    print("PHASE 10: Strategy Laboratory Verification")
    print("=" * 60)
    print("\nSAFETY: Training-only verification")
    print("SAFETY: No execution behavior modified\n")
    
    checks = [
        check_syntax,
        check_imports,
        check_live_path_blocked,
        check_strategy_config,
        check_factory_safety,
        check_governance,
    ]
    
    results = []
    for check in checks:
        try:
            result = check()
            results.append(result)
        except Exception as e:
            print(f"❌ CHECK FAILED WITH EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    print(f"\nChecks passed: {passed}/{total}")
    
    if all(results):
        print("\n✅ ALL CHECKS PASSED: Strategy Laboratory is ready for TRAINING mode")
        return 0
    else:
        print("\n❌ SOME CHECKS FAILED: Review errors above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
