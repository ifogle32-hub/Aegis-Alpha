"""
PHASE 9 — SHADOW IMPORT REGRESSION TESTS

Tests that assert:
- Importing api.main does NOT raise ImportError
- Importing shadow.status does NOT start training
- Circular imports cannot reappear
- No threads are started at import time
- Locks are created lazily

Tests must fail if dependency direction is violated.
"""

import sys
import threading
import pytest
from unittest.mock import patch, MagicMock


def test_api_main_imports_safely():
    """
    Test that importing api.main does NOT raise ImportError.
    
    This is the critical startup path for the daemon.
    """
    try:
        # This should not raise ImportError
        import api.main
        assert True, "api.main imported successfully"
    except ImportError as e:
        pytest.fail(f"api.main import failed: {e}")


def test_shadow_status_imports_safely():
    """
    Test that importing shadow.status does NOT start training.
    
    Status provider should be safe to import without side effects.
    """
    # Track thread count before import
    initial_thread_count = threading.active_count()
    
    try:
        from sentinel_x.shadow.status import get_shadow_status_provider
        
        # Import should not create threads
        after_import_thread_count = threading.active_count()
        assert after_import_thread_count == initial_thread_count, \
            "Importing shadow.status should not create threads"
        
        # Getting provider should not start training
        provider = get_shadow_status_provider()
        assert provider is not None, "Status provider should be available"
        
        # Should be able to get snapshot without training active
        snapshot = provider.get_snapshot()
        assert snapshot is not None, "Should be able to get snapshot"
        assert snapshot.training_active is False, "Training should not be active after import"
        
    except ImportError as e:
        pytest.fail(f"shadow.status import failed: {e}")


def test_no_circular_import_trainer_heartbeat():
    """
    Test that circular imports cannot reappear between trainer and heartbeat.
    
    Dependency direction: trainer → heartbeat (one direction only)
    """
    # Import heartbeat first (should not import trainer)
    from sentinel_x.shadow.heartbeat import ShadowHeartbeatMonitor
    
    # Verify heartbeat does not have trainer in its namespace
    import sentinel_x.shadow.heartbeat as heartbeat_module
    assert not hasattr(heartbeat_module, 'ShadowTrainer'), \
        "heartbeat module should not have ShadowTrainer"
    assert not hasattr(heartbeat_module, 'get_shadow_trainer'), \
        "heartbeat module should not have get_shadow_trainer"
    
    # Import trainer (should import heartbeat)
    from sentinel_x.shadow.trainer import ShadowTrainer
    
    # Verify trainer has heartbeat
    import sentinel_x.shadow.trainer as trainer_module
    assert hasattr(trainer_module, 'ShadowHeartbeatMonitor'), \
        "trainer module should have ShadowHeartbeatMonitor"


def test_no_threads_at_import_time():
    """
    Test that no threads are started at import time.
    
    All threads must be started explicitly via methods, not during import.
    """
    initial_threads = set(threading.enumerate())
    
    # Import all shadow modules
    from sentinel_x.shadow import ShadowMode, PromotionState, TrainingState
    from sentinel_x.shadow.status import get_shadow_status_provider
    from sentinel_x.shadow.controller import get_shadow_training_controller
    from sentinel_x.shadow.heartbeat import ShadowHeartbeatMonitor
    from sentinel_x.shadow.rork import get_rork_shadow_interface
    
    # Get singletons (should not start threads)
    get_shadow_status_provider()
    get_shadow_training_controller()
    get_rork_shadow_interface()
    
    # Check thread count
    final_threads = set(threading.enumerate())
    new_threads = final_threads - initial_threads
    
    # Only allow daemon threads that might be created by other imports
    # (not shadow-specific threads)
    shadow_threads = [t for t in new_threads if 'shadow' in t.name.lower() or 'Shadow' in t.name]
    
    assert len(shadow_threads) == 0, \
        f"Import should not create shadow threads. Found: {[t.name for t in shadow_threads]}"


def test_locks_created_lazily():
    """
    Test that locks are created lazily, not at import time.
    
    Module-level locks should be None until first get_* call.
    """
    # Import modules
    from sentinel_x.shadow import status, controller, trainer, heartbeat, rork
    
    # Check that locks are None or not created at module level
    # (They should be created lazily in get_* functions)
    
    # After import, locks should be None (lazy creation)
    assert hasattr(status, '_status_provider_lock'), "status should have lock attribute"
    assert status._status_provider_lock is None, "status lock should be None until first call"
    
    assert hasattr(controller, '_controller_lock'), "controller should have lock attribute"
    assert controller._controller_lock is None, "controller lock should be None until first call"
    
    assert hasattr(trainer, '_trainer_lock'), "trainer should have lock attribute"
    assert trainer._trainer_lock is None, "trainer lock should be None until first call"
    
    assert hasattr(heartbeat, '_heartbeat_monitor_lock'), "heartbeat should have lock attribute"
    assert heartbeat._heartbeat_monitor_lock is None, "heartbeat lock should be None until first call"
    
    assert hasattr(rork, '_rork_interface_lock'), "rork should have lock attribute"
    assert rork._rork_interface_lock is None, "rork lock should be None until first call"
    
    # After first get_* call, locks should be created
    from sentinel_x.shadow.status import get_shadow_status_provider
    get_shadow_status_provider()
    
    assert status._status_provider_lock is not None, "status lock should be created after first call"


def test_dependency_direction_enforced():
    """
    Test that dependency direction is enforced.
    
    Rules:
    - trainer MAY import heartbeat
    - heartbeat MUST NOT import trainer
    - rork MUST NOT import trainer or heartbeat
    - status MUST NOT import trainer or heartbeat directly
    """
    # Import heartbeat and check it doesn't import trainer
    import sentinel_x.shadow.heartbeat as heartbeat_module
    heartbeat_imports = set(dir(heartbeat_module))
    
    assert 'ShadowTrainer' not in heartbeat_imports, \
        "heartbeat should not import ShadowTrainer"
    assert 'get_shadow_trainer' not in heartbeat_imports, \
        "heartbeat should not import get_shadow_trainer"
    
    # Import trainer and check it imports heartbeat
    import sentinel_x.shadow.trainer as trainer_module
    trainer_imports = set(dir(trainer_module))
    
    assert 'ShadowHeartbeatMonitor' in trainer_imports, \
        "trainer should import ShadowHeartbeatMonitor"
    
    # Import rork and check it doesn't import trainer or heartbeat
    import sentinel_x.shadow.rork as rork_module
    rork_imports = set(dir(rork_module))
    
    assert 'ShadowTrainer' not in rork_imports, \
        "rork should not import ShadowTrainer"
    assert 'get_shadow_trainer' not in rork_imports, \
        "rork should not import get_shadow_trainer"
    assert 'ShadowHeartbeatMonitor' not in rork_imports, \
        "rork should not import ShadowHeartbeatMonitor"
    
    # Import status and check it only imports controller
    import sentinel_x.shadow.status as status_module
    status_imports = set(dir(status_module))
    
    assert 'ShadowTrainingController' in status_imports, \
        "status should import ShadowTrainingController"
    assert 'ShadowTrainer' not in status_imports, \
        "status should not import ShadowTrainer directly"
    assert 'ShadowHeartbeatMonitor' not in status_imports, \
        "status should not import ShadowHeartbeatMonitor directly"


def test_init_py_only_exports_types():
    """
    Test that __init__.py only exports types, enums, dataclasses.
    
    No runtime objects, no get_* functions, no classes that create threads.
    """
    from sentinel_x.shadow import __all__
    
    # Check that runtime objects are NOT exported
    forbidden_exports = [
        'ShadowTrainer',
        'get_shadow_trainer',
        'ShadowHeartbeatMonitor',
        'get_shadow_heartbeat_monitor',
        'ShadowTrainingController',
        'get_shadow_training_controller',
        'RorkShadowInterface',
        'get_rork_shadow_interface',
    ]
    
    for forbidden in forbidden_exports:
        assert forbidden not in __all__, \
            f"__init__.py should not export {forbidden} (runtime object)"
    
    # Check that types/enums are exported
    allowed_exports = [
        'ShadowMode',
        'PromotionState',
        'TrainingState',
        'MarketTick',
        'ShadowStatusSnapshot',
    ]
    
    for allowed in allowed_exports:
        assert allowed in __all__, \
            f"__init__.py should export {allowed} (type/enum)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
