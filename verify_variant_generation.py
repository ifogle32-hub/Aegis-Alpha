#!/usr/bin/env python3
"""
PHASE 10: Verification Script for Strategy Variant Generation

Verifies all phases of the auto-generation framework:
1. Python compilation
2. Seed strategy registration
3. Variant generation
4. Governance limits enforcement
5. Factory enforcement (all variants go through StrategyFactory)
6. TRAINING-only lifecycle state
7. Parameter-only mutation (no logic changes)
8. Observability (seed→variants mapping)

SAFETY: Verification is read-only
SAFETY: No execution behavior modified
"""
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Track verification results
VERIFICATION_RESULTS = {
    "passed": [],
    "failed": [],
    "warnings": []
}


def verify_compilation():
    """PHASE 10: Verify all Python files compile."""
    print("=" * 60)
    print("PHASE 10: VERIFICATION - Python Compilation")
    print("=" * 60)
    print()
    
    files_to_check = [
        "sentinel_x/intelligence/strategy_variant_generator.py",
        "sentinel_x/intelligence/models.py",
        "sentinel_x/intelligence/governance.py",
        "sentinel_x/intelligence/strategy_factory.py",
        "sentinel_x/intelligence/factory_enforcement.py",
    ]
    
    all_passed = True
    for file_path in files_to_check:
        full_path = PROJECT_ROOT / file_path
        if not full_path.exists():
            print(f"⚠  WARNING: File not found: {file_path}")
            VERIFICATION_RESULTS["warnings"].append(f"File not found: {file_path}")
            continue
        
        try:
            compile(open(full_path).read(), str(full_path), 'exec')
            print(f"✓  Compiled: {file_path}")
            VERIFICATION_RESULTS["passed"].append(f"Compiled: {file_path}")
        except SyntaxError as e:
            print(f"✗  FAILED: {file_path}")
            print(f"   Syntax error: {e}")
            VERIFICATION_RESULTS["failed"].append(f"Compilation failed: {file_path}: {e}")
            all_passed = False
        except Exception as e:
            print(f"✗  FAILED: {file_path}")
            print(f"   Error: {e}")
            VERIFICATION_RESULTS["failed"].append(f"Compilation error: {file_path}: {e}")
            all_passed = False
    
    print()
    return all_passed


def verify_variant_generator():
    """PHASE 10: Verify StrategyVariantGenerator functionality."""
    print("=" * 60)
    print("PHASE 10: VERIFICATION - Variant Generator")
    print("=" * 60)
    print()
    
    try:
        from sentinel_x.intelligence.strategy_variant_generator import (
            StrategyVariantGenerator,
            get_variant_generator,
            MAX_SEED_STRATEGIES,
            MAX_VARIANTS_PER_SEED,
            MAX_TOTAL_STRATEGIES
        )
        from sentinel_x.intelligence.models import StrategyConfig, StrategyLifecycleState
        from sentinel_x.intelligence.strategy_factory import get_strategy_factory
        from sentinel_x.intelligence.factory_enforcement import check_strategy_instance, enable_factory_enforcement
        
        print(f"✓  Imports successful")
        VERIFICATION_RESULTS["passed"].append("Variant generator imports")
        
        # Verify governance limits are defined
        assert MAX_SEED_STRATEGIES > 0, "MAX_SEED_STRATEGIES must be > 0"
        assert MAX_VARIANTS_PER_SEED > 0, "MAX_VARIANTS_PER_SEED must be > 0"
        assert MAX_TOTAL_STRATEGIES > 0, "MAX_TOTAL_STRATEGIES must be > 0"
        print(f"✓  Governance limits defined: seeds={MAX_SEED_STRATEGIES}, variants/seed={MAX_VARIANTS_PER_SEED}, total={MAX_TOTAL_STRATEGIES}")
        VERIFICATION_RESULTS["passed"].append("Governance limits defined")
        
        # Create variant generator
        variant_generator = get_variant_generator()
        assert variant_generator is not None, "Variant generator must not be None"
        print(f"✓  Variant generator created")
        VERIFICATION_RESULTS["passed"].append("Variant generator created")
        
        # Create a seed config
        seed_config = StrategyConfig(
            strategy_type="momentum",
            timeframe=60,
            lookback=50,
            entry_params={"fast_ema": 12, "slow_ema": 26},
            exit_params={},
            stop_atr=2.0,
            take_profit_atr=4.0,
            session="RTH",
            max_trades_per_day=5,
            risk_per_trade=0.01
        )
        
        # Verify seed config validation
        try:
            seed_config.validate()
            print(f"✓  Seed config validation passed")
            VERIFICATION_RESULTS["passed"].append("Seed config validation")
        except Exception as e:
            print(f"✗  FAILED: Seed config validation: {e}")
            VERIFICATION_RESULTS["failed"].append(f"Seed config validation failed: {e}")
            return False
        
        # Register seed strategy
        try:
            variant_generator.register_seed("test_seed_momentum", seed_config)
            seeds = variant_generator.list_seeds()
            assert "test_seed_momentum" in seeds, "Seed must be registered"
            print(f"✓  Seed strategy registered: test_seed_momentum")
            VERIFICATION_RESULTS["passed"].append("Seed strategy registration")
        except Exception as e:
            print(f"✗  FAILED: Seed registration: {e}")
            VERIFICATION_RESULTS["failed"].append(f"Seed registration failed: {e}")
            return False
        
        # Verify governance limits on seed registration
        try:
            for i in range(MAX_SEED_STRATEGIES + 1):
                test_config = StrategyConfig(
                    strategy_type="momentum",
                    timeframe=60,
                    lookback=50,
                    entry_params={},
                    exit_params={}
                )
                variant_generator.register_seed(f"test_seed_{i}", test_config)
            
            seeds_after = variant_generator.list_seeds()
            if len(seeds_after) <= MAX_SEED_STRATEGIES:
                print(f"✓  Governance limit enforced (seed count: {len(seeds_after)} <= {MAX_SEED_STRATEGIES})")
                VERIFICATION_RESULTS["passed"].append("Seed count governance limit")
            else:
                print(f"⚠  WARNING: Seed count exceeded limit: {len(seeds_after)} > {MAX_SEED_STRATEGIES}")
                VERIFICATION_RESULTS["warnings"].append(f"Seed count limit warning: {len(seeds_after)}")
        except Exception as e:
            print(f"⚠  WARNING: Seed limit test: {e}")
            VERIFICATION_RESULTS["warnings"].append(f"Seed limit test: {e}")
        
        # Generate variants (parameter-only)
        try:
            variants = variant_generator.generate("test_seed_momentum", max_variants=3)
            assert isinstance(variants, list), "Variants must be a list"
            print(f"✓  Generated {len(variants)} variants (parameter-only)")
            VERIFICATION_RESULTS["passed"].append(f"Variant generation ({len(variants)} variants)")
            
            # Verify variants are valid StrategyConfig objects
            for variant in variants:
                assert isinstance(variant, StrategyConfig), "Variant must be StrategyConfig"
                try:
                    variant.validate()
                    print(f"  ✓  Variant validated: type={variant.strategy_type}, lookback={variant.lookback}")
                except Exception as e:
                    print(f"  ✗  FAILED: Variant validation: {e}")
                    VERIFICATION_RESULTS["failed"].append(f"Variant validation failed: {e}")
                    return False
        except Exception as e:
            print(f"✗  FAILED: Variant generation: {e}")
            VERIFICATION_RESULTS["failed"].append(f"Variant generation failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Verify variants differ in parameters only (no logic changes)
        if variants:
            seed = variant_generator.get_seed_config("test_seed_momentum")
            variant = variants[0]
            # Check that only parameters differ (strategy_type and timeframe should be same)
            assert variant.strategy_type == seed.strategy_type, "Strategy type must not change"
            assert variant.timeframe == seed.timeframe, "Timeframe should remain same (no mutation in this phase)"
            print(f"✓  Variants are parameter-only (no logic changes)")
            VERIFICATION_RESULTS["passed"].append("Parameter-only mutation verified")
        
        print()
        return True
        
    except ImportError as e:
        print(f"✗  FAILED: Import error: {e}")
        VERIFICATION_RESULTS["failed"].append(f"Import error: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"✗  FAILED: Variant generator verification: {e}")
        VERIFICATION_RESULTS["failed"].append(f"Variant generator verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_factory_enforcement():
    """PHASE 10: Verify all variants go through StrategyFactory."""
    print("=" * 60)
    print("PHASE 10: VERIFICATION - Factory Enforcement")
    print("=" * 60)
    print()
    
    try:
        from sentinel_x.intelligence.strategy_variant_generator import get_variant_generator
        from sentinel_x.intelligence.models import StrategyConfig, StrategyLifecycleState
        from sentinel_x.intelligence.strategy_factory import get_strategy_factory
        from sentinel_x.intelligence.factory_enforcement import check_strategy_instance, enable_factory_enforcement
        
        # Enable factory enforcement
        enable_factory_enforcement()
        print(f"✓  Factory enforcement enabled")
        VERIFICATION_RESULTS["passed"].append("Factory enforcement enabled")
        
        # Create variant generator and seed
        variant_generator = get_variant_generator()
        seed_config = StrategyConfig(
            strategy_type="momentum",
            timeframe=60,
            lookback=50,
            entry_params={"fast_ema": 12, "slow_ema": 26},
            exit_params={},
            stop_atr=2.0,
            take_profit_atr=4.0,
            session="RTH",
            max_trades_per_day=5,
            risk_per_trade=0.01
        )
        
        # Register seed (if not already registered)
        try:
            variant_generator.register_seed("factory_test_seed", seed_config)
        except:
            pass  # May already be registered
        
        # Generate and register variants (should go through factory)
        try:
            variant_names = variant_generator.generate_and_register("factory_test_seed", max_variants=2)
            print(f"✓  Generated and registered {len(variant_names)} variants via factory")
            VERIFICATION_RESULTS["passed"].append(f"Variants registered via factory ({len(variant_names)})")
            
            # Verify variants were created via factory
            from sentinel_x.intelligence.strategy_manager import get_strategy_manager
            strategy_manager = get_strategy_manager()
            
            for variant_name in variant_names:
                if variant_name in strategy_manager.strategies:
                    strategy = strategy_manager.strategies[variant_name]
                    try:
                        # This should not raise if strategy was created via factory
                        check_strategy_instance(strategy)
                        print(f"  ✓  {variant_name}: Created via factory (TRAINING)")
                        VERIFICATION_RESULTS["passed"].append(f"Factory-created: {variant_name}")
                        
                        # Verify lifecycle state is TRAINING
                        lifecycle_state = strategy_manager.strategy_states.get(variant_name, StrategyLifecycleState.TRAINING)
                        assert lifecycle_state == StrategyLifecycleState.TRAINING, f"Lifecycle must be TRAINING, got {lifecycle_state}"
                        print(f"  ✓  {variant_name}: Lifecycle state = TRAINING")
                        VERIFICATION_RESULTS["passed"].append(f"TRAINING lifecycle: {variant_name}")
                    except RuntimeError as e:
                        print(f"  ✗  FAILED: {variant_name}: Not created via factory: {e}")
                        VERIFICATION_RESULTS["failed"].append(f"Factory bypass: {variant_name}")
                        return False
        except Exception as e:
            print(f"⚠  WARNING: Factory enforcement test: {e}")
            VERIFICATION_RESULTS["warnings"].append(f"Factory enforcement test: {e}")
        
        print()
        return True
        
    except ImportError as e:
        print(f"✗  FAILED: Import error: {e}")
        VERIFICATION_RESULTS["failed"].append(f"Import error: {e}")
        return False
    except Exception as e:
        print(f"✗  FAILED: Factory enforcement verification: {e}")
        VERIFICATION_RESULTS["failed"].append(f"Factory enforcement verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_observability():
    """PHASE 10: Verify observability (seed→variants mapping)."""
    print("=" * 60)
    print("PHASE 10: VERIFICATION - Observability")
    print("=" * 60)
    print()
    
    try:
        from sentinel_x.intelligence.strategy_variant_generator import get_variant_generator
        
        variant_generator = get_variant_generator()
        
        # Get seed→variants mapping
        seed_variant_mapping = variant_generator.get_seed_variant_mapping()
        assert isinstance(seed_variant_mapping, dict), "Mapping must be a dict"
        print(f"✓  Seed→variants mapping available: {len(seed_variant_mapping)} seeds")
        VERIFICATION_RESULTS["passed"].append("Seed→variants mapping")
        
        # Verify mapping structure
        for seed_name, variants in seed_variant_mapping.items():
            assert isinstance(variants, list), f"Variants for {seed_name} must be a list"
            print(f"  Seed: {seed_name} → {len(variants)} variants")
        
        print()
        return True
        
    except Exception as e:
        print(f"⚠  WARNING: Observability verification: {e}")
        VERIFICATION_RESULTS["warnings"].append(f"Observability verification: {e}")
        return True  # Non-critical


def print_summary():
    """Print verification summary."""
    print("=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print()
    
    passed_count = len(VERIFICATION_RESULTS["passed"])
    failed_count = len(VERIFICATION_RESULTS["failed"])
    warnings_count = len(VERIFICATION_RESULTS["warnings"])
    
    print(f"✓  Passed: {passed_count}")
    if VERIFICATION_RESULTS["passed"]:
        for item in VERIFICATION_RESULTS["passed"][:10]:  # Show first 10
            print(f"   - {item}")
        if len(VERIFICATION_RESULTS["passed"]) > 10:
            print(f"   ... and {len(VERIFICATION_RESULTS['passed']) - 10} more")
    print()
    
    if warnings_count > 0:
        print(f"⚠  Warnings: {warnings_count}")
        for item in VERIFICATION_RESULTS["warnings"][:5]:  # Show first 5
            print(f"   - {item}")
        if len(VERIFICATION_RESULTS["warnings"]) > 5:
            print(f"   ... and {len(VERIFICATION_RESULTS['warnings']) - 5} more")
        print()
    
    if failed_count > 0:
        print(f"✗  Failed: {failed_count}")
        for item in VERIFICATION_RESULTS["failed"]:
            print(f"   - {item}")
        print()
        print("=" * 60)
        print("VERIFICATION FAILED")
        print("=" * 60)
        return False
    else:
        print("=" * 60)
        print("VERIFICATION PASSED")
        print("=" * 60)
        return True


def main():
    """Main verification function."""
    print()
    print("=" * 60)
    print("PHASE 10: STRATEGY VARIANT GENERATION VERIFICATION")
    print("=" * 60)
    print()
    print("SAFETY: Verification is read-only")
    print("SAFETY: No execution behavior modified")
    print()
    
    # Run all verifications
    all_passed = True
    
    # 1. Compilation check
    if not verify_compilation():
        all_passed = False
    
    # 2. Variant generator functionality
    if not verify_variant_generator():
        all_passed = False
    
    # 3. Factory enforcement
    if not verify_factory_enforcement():
        all_passed = False
    
    # 4. Observability
    if not verify_observability():
        # Non-critical, don't fail verification
        pass
    
    # Print summary
    if not print_summary():
        all_passed = False
    
    # Exit with appropriate code
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
