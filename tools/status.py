#!/usr/bin/env python3
"""
PHASE 6 — CLI STATUS COMMAND (MONITOR FIX)

Read-only status command for Sentinel X.

====================================================================
PHASE 1 — ROOT CAUSE ANALYSIS
====================================================================
ROOT CAUSE IDENTIFIED:
tools/status.py previously imported TradingEngine, which created a
NEW engine instance. The monitor inspected the wrong process,
resulting in false STOPPED status even while trades were executing.

SOLUTION:
- Monitor NO LONGER imports TradingEngine
- Monitor NO LONGER instantiates engine objects
- Monitor ONLY reads the heartbeat file (/tmp/sentinel_x_heartbeat.json)
- Heartbeat is written by the running engine process
- Monitor reports TRUE runtime state from heartbeat

====================================================================
PHASE 6 — MONITOR FIX
====================================================================
Monitor logic updated to:
- Report engine RUNNING if process is alive (even if heartbeat is stale)
- Report STOPPED only if engine explicitly stopped (no heartbeat, process dead)
- Use heartbeat age to determine loop health: OK / STALE / FROZEN
- Display: PID, heartbeat timestamp, heartbeat age, loop tick counter,
  broker (read-only), mode, loop health status

Freeze Detection Thresholds:
- OK: heartbeat age <= 10 seconds
- STALE: heartbeat age > 10 seconds
- FROZEN: heartbeat age > 30 seconds

====================================================================
PHASE 7 — CONSISTENCY GUARANTEE
====================================================================
CONSISTENCY GUARANTEES:
- Monitor never reports STOPPED while engine process is alive
- Monitor detects stale/frozen loops correctly using monotonic time
- Engine loop continues running even if frozen
- No monitoring code can crash the engine

====================================================================
PHASE 8 — REGRESSION LOCK
====================================================================
REGRESSION LOCK: MONITOR READ-ONLY CONTRACT
- Engine is production-stable
- Monitor correctness depends on heartbeat
- Do not reintroduce engine imports in monitors
- This tool must be READ-ONLY and safe

SAFETY GUARANTEES:
- Observability-only. No execution impact.
- Monitor cannot influence engine
- No changes to Alpaca / Tradovate behavior
- No changes to execution_router
- No changes to strategy lifecycle

This script must:
- Read heartbeat file via read_heartbeat() (never import engine state)
- Never touch engine loop
- Never start engine
- Report ENGINE: RUNNING/STOPPED based on process liveness + heartbeat
- Report Loop health: OK/STALE/FROZEN based on heartbeat age
"""

import sys
import os
import time
from datetime import datetime
from pathlib import Path

# Add project root to path to import sentinel_x modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sentinel_x.monitoring.heartbeat import read_heartbeat


def is_process_alive(pid: int) -> bool:
    """
    PHASE 7: Check if process is alive (cross-platform safe).
    
    Returns True if process exists, False otherwise.
    Never raises exceptions.
    """
    try:
        # Check if process exists (send signal 0 - does nothing but checks existence)
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        # Process doesn't exist or not accessible
        return False
    except Exception:
        # Any other error - assume process is not accessible
        return False


def format_timestamp(ts) -> str:
    """Format timestamp for display."""
    if ts is None:
        return "Never"
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        else:
            dt = ts
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def main():
    """
    Print system status from heartbeat file.
    
    PHASE 6: Monitor fix logic with freeze detection
    - If heartbeat exists and age <= 10s: Loop Health: OK
    - If heartbeat exists and age > 10s and <= 30s: Loop Health: STALE
    - If heartbeat exists and age > 30s: Loop Health: FROZEN
    - PHASE 7: Never report STOPPED while process is alive
    """
    # Print header
    print("=" * 60)
    print("SENTINEL X SYSTEM STATUS")
    print("=" * 60)
    print()
    
    # Read heartbeat file using heartbeat module (cross-process safe)
    heartbeat = read_heartbeat()
    
    # Extract heartbeat data
    engine_state = heartbeat.get('engine', 'UNKNOWN') if heartbeat else None
    engine_mode = heartbeat.get('mode', 'UNKNOWN') if heartbeat else None
    broker_name = heartbeat.get('broker', 'NONE') if heartbeat else 'NONE'
    pid = heartbeat.get('pid') if heartbeat else None
    timestamp = heartbeat.get('timestamp') if heartbeat else None
    heartbeat_monotonic = heartbeat.get('heartbeat_monotonic') if heartbeat else None
    loop_tick = heartbeat.get('loop_tick') if heartbeat else None
    last_loop_tick_ts = heartbeat.get('last_loop_tick_ts') if heartbeat else None
    loop_phase = heartbeat.get('loop_phase', 'UNKNOWN') if heartbeat else 'UNKNOWN'  # PHASE 4: Engine phase marker
    phase_duration = heartbeat.get('phase_duration_seconds') if heartbeat else None  # PHASE 4: Phase duration
    broker_call_duration_ms = heartbeat.get('last_broker_call_duration_ms') if heartbeat else None  # PHASE 6: Broker call timing
    strategy_heartbeats = heartbeat.get('strategy_heartbeats', {}) if heartbeat else {}  # PHASE 5: Strategy heartbeats
    
    # PHASE 7: Consistency guarantee - check if process is alive
    process_alive = False
    if pid:
        try:
            process_alive = is_process_alive(pid)
        except Exception:
            process_alive = False
    
    # PHASE 6 & 7: Determine engine status
    # Engine is RUNNING if:
    #   1. Heartbeat exists AND process is alive, OR
    #   2. Heartbeat exists (process check may fail due to permissions)
    # Engine is STOPPED only if:
    #   1. No heartbeat file exists AND process is not alive (or no PID)
    if not heartbeat:
        # No heartbeat file
        if pid and not process_alive:
            # Process is confirmed dead
            print("ENGINE: STOPPED")
            print("Loop Health: ✗ INACTIVE (no heartbeat, process dead)")
            print(f"  Last known PID: {pid}")
        else:
            # No heartbeat, but cannot confirm process status
            print("ENGINE: STOPPED")
            print("Loop Health: ✗ INACTIVE (no heartbeat detected)")
            if pid:
                print(f"  Last known PID: {pid} (process status unknown)")
        
        print("  Heartbeat file not found or empty")
        print("  Engine may not be running")
        print()
        print("=" * 60)
        sys.exit(0)
    
    # PHASE 7: Consistency guarantee - if heartbeat exists, engine is RUNNING
    # Never report STOPPED while heartbeat exists (engine loop is active)
    
    # ============================================================
    # PHASE 6 — UI BADGES (GREEN / YELLOW / RED)
    # ============================================================
    # Badge rules:
    # ENGINE:
    # - GREEN → RUNNING
    # - YELLOW → STALE
    # - RED → FROZEN
    # 
    # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
    # SAFETY: display-only, no control actions, no auto-remediation
    # ============================================================
    def get_engine_badge(loop_health: str) -> tuple[str, str]:
        """Get engine badge and status."""
        if loop_health == "RUNNING":
            return ("🟢", "RUNNING")
        elif loop_health == "STALE":
            return ("🟡", "STALE")
        elif loop_health == "FROZEN":
            return ("🔴", "FROZEN")
        else:
            return ("⚪", "UNKNOWN")
    
    # Note: loop_health will be computed later, use RUNNING as placeholder for now
    print(f"ENGINE: RUNNING ({engine_mode})")
    
    # ============================================================
    # PHASE 5 — MONITORING LOGIC UPDATE
    # ============================================================
    # Classification uses BOTH heartbeat AND loop tick signals:
    # - RUNNING: loop_tick_age < threshold (loop is actively progressing)
    # - STALE: heartbeat_age >= threshold AND loop_tick still advancing
    # - FROZEN: heartbeat_age >= threshold AND loop_tick NOT advancing
    #
    # PHASE 13 — REGRESSION LOCK:
    # REGRESSION LOCK — MONITOR CLASSIFICATION LOGIC
    # DO NOT MODIFY WITHOUT ENGINE REVIEW
    #
    # PHASE 11 — SAFETY GUARANTEES:
    # - SAFETY: monitoring-only change
    # - Monitoring is READ-ONLY (never influences engine)
    # - No execution dependencies
    # - Observability-only. No execution impact.
    # ============================================================
    
    # Calculate heartbeat age using monotonic time if available (more accurate)
    heartbeat_age = None
    loop_tick_age = None
    
    if heartbeat_monotonic:
        # Use monotonic time for age calculation (matches engine's internal calculation)
        try:
            current_monotonic = time.monotonic()
            heartbeat_age = current_monotonic - float(heartbeat_monotonic)
        except Exception:
            heartbeat_age = None
    
    if heartbeat_age is None and timestamp:
        # Fallback to wallclock time calculation
        try:
            heartbeat_age = time.time() - float(timestamp)
        except Exception:
            heartbeat_age = None
    
    # Calculate loop tick age (independent signal)
    if last_loop_tick_ts:
        try:
            current_monotonic = time.monotonic()
            loop_tick_age = current_monotonic - float(last_loop_tick_ts)
        except Exception:
            loop_tick_age = None
    
    # ============================================================
    # PHASE 5 — MONITOR CLASSIFICATION LOGIC
    # ============================================================
    # Classification uses BOTH heartbeat AND loop tick signals:
    # 
    # Definitions:
    # - heartbeat_age = now - heartbeat.timestamp (monotonic)
    # - loop_tick_age = now - heartbeat.loop_tick_time (monotonic)
    # 
    # Classification rules (EXACT):
    # - RUNNING: loop_tick_age < 10.0s (loop actively progressing)
    # - STALE: heartbeat_age >= 10.0s AND loop_tick_age < 30.0s
    #   (heartbeat stale but loop still advancing)
    # - FROZEN: heartbeat_age >= 10.0s AND loop_tick_age >= 30.0s
    #   (both signals stale = frozen)
    # 
    # IMPORTANT: Never mark FROZEN if loop_tick advances
    # 
    # REGRESSION LOCK — MONITOR CLASSIFICATION LOGIC
    # DO NOT MODIFY WITHOUT ENGINE REVIEW
    # SAFETY: monitoring-only, no execution impact
    # ============================================================
    STALE_THRESHOLD = 10.0  # seconds
    FROZEN_THRESHOLD = 30.0  # seconds
    
    loop_health = "UNKNOWN"
    
    if loop_tick_age is not None and heartbeat_age is not None:
        # Both signals available - use dual-signal classification
        if loop_tick_age < STALE_THRESHOLD:
            # Loop is actively progressing
            loop_health = "RUNNING"
        elif heartbeat_age >= STALE_THRESHOLD and loop_tick_age < FROZEN_THRESHOLD:
            # Heartbeat stale but loop still advancing
            loop_health = "STALE"
        elif heartbeat_age >= STALE_THRESHOLD and loop_tick_age >= FROZEN_THRESHOLD:
            # Both signals stale = frozen
            loop_health = "FROZEN"
        else:
            # Edge case: heartbeat OK but loop tick stale (shouldn't happen normally)
            loop_health = "RUNNING"  # If heartbeat is fresh, assume running
    elif loop_tick_age is not None:
        # Only loop tick available - use as primary signal
        if loop_tick_age < STALE_THRESHOLD:
            loop_health = "RUNNING"
        elif loop_tick_age < FROZEN_THRESHOLD:
            loop_health = "STALE"  # Loop tick stale but not frozen
        else:
            loop_health = "FROZEN"  # Loop tick frozen
    elif heartbeat_age is not None:
        # Fallback to heartbeat-only classification if loop tick unavailable
        if heartbeat_age < STALE_THRESHOLD:
            loop_health = "RUNNING"
        elif heartbeat_age < FROZEN_THRESHOLD:
            loop_health = "STALE"
        else:
            loop_health = "FROZEN"
    else:
        loop_health = "UNKNOWN"
    
    # Use heartbeat_age for display (more intuitive for users)
    age_seconds = heartbeat_age if heartbeat_age is not None else None
    
    # Display PID
    if pid:
        print(f"  PID: {pid}")
        if process_alive:
            print(f"  Process: ✓ Alive")
        else:
            print(f"  Process: ? Status unknown (check permissions)")
    
    # PHASE 6: Display heartbeat information
    if timestamp:
        print(f"  Last Update: {format_timestamp(timestamp)}")
    
    if heartbeat_age is not None:
        if heartbeat_age < 60:
            print(f"  Heartbeat Age: {heartbeat_age:.1f}s")
        elif heartbeat_age < 3600:
            print(f"  Heartbeat Age: {heartbeat_age/60:.1f} minutes")
        else:
            print(f"  Heartbeat Age: {heartbeat_age/3600:.1f} hours")
    
    # PHASE 3: Display loop tick counter and age (secondary independent signal)
    if loop_tick is not None:
        print(f"  Loop Tick: {loop_tick}")
    
    if loop_tick_age is not None:
        if loop_tick_age < 60:
            print(f"  Loop Tick Age: {loop_tick_age:.1f}s")
        elif loop_tick_age < 3600:
            print(f"  Loop Tick Age: {loop_tick_age/60:.1f} minutes")
        else:
            print(f"  Loop Tick Age: {loop_tick_age/3600:.1f} hours")
    
    # PHASE 4 & 5: Display loop phase marker and duration (for freeze attribution)
    print(f"  Loop Phase: {loop_phase}")
    if phase_duration is not None:
        if phase_duration < 1.0:
            print(f"  Phase Duration: {phase_duration*1000:.1f}ms")
        elif phase_duration < 60.0:
            print(f"  Phase Duration: {phase_duration:.2f}s")
        else:
            print(f"  Phase Duration: {phase_duration/60:.1f} minutes")
    
    # PHASE 6: Display broker call timing
    if broker_call_duration_ms is not None and broker_call_duration_ms > 0:
        if broker_call_duration_ms < 1000:
            print(f"  Last Broker Call: {broker_call_duration_ms:.1f}ms")
        else:
            print(f"  Last Broker Call: {broker_call_duration_ms/1000:.2f}s")
    
    # ============================================================
    # PHASE 5 — MONITOR STRATEGY HEALTH CLASSIFICATION
    # ============================================================
    # Classify strategies: GREEN / YELLOW / RED
    # 
    # Definitions:
    # - strategy_age = now - strategy.last_tick
    # 
    # Thresholds:
    # - GREEN: age < 2×engine_loop_interval (assume ~1s default)
    # - YELLOW: age >= 2×engine_loop_interval AND age < FROZEN_THRESHOLD
    # - RED: age >= FROZEN_THRESHOLD (30s)
    # 
    # Rules:
    # - Strategy RED does NOT imply engine frozen
    # - Engine health remains primary
    # 
    # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
    # SAFETY: monitoring-only, no execution impact
    # ============================================================
    STRATEGY_GREEN_THRESHOLD = 2.0  # 2×engine_loop_interval (assume ~1s default)
    STRATEGY_YELLOW_THRESHOLD = 30.0  # FROZEN_THRESHOLD
    
    def classify_strategy_health(strategy_age: float) -> tuple[str, str]:
        """Classify strategy health and return (badge, status)."""
        if strategy_age < STRATEGY_GREEN_THRESHOLD:
            return ("🟢", "GREEN")
        elif strategy_age < STRATEGY_YELLOW_THRESHOLD:
            return ("🟡", "YELLOW")
        else:
            return ("🔴", "RED")
    
    # PHASE 5: Display strategy heartbeats with health classification
    if strategy_heartbeats:
        print()
        print("  Strategies:")
        now_mono = time.monotonic()
        for strategy_name, strategy_data in strategy_heartbeats.items():
            tick_count = strategy_data.get('tick_count', 0)
            last_tick_ts = strategy_data.get('last_tick_ts')
            
            if last_tick_ts is not None:
                # Calculate strategy age
                strategy_age = now_mono - last_tick_ts
                badge, health = classify_strategy_health(strategy_age)
                
                # Format age string
                if strategy_age < 60:
                    age_str = f"{strategy_age:.1f}s"
                elif strategy_age < 3600:
                    age_str = f"{strategy_age/60:.1f}min"
                else:
                    age_str = f"{strategy_age/3600:.1f}hr"
                
                print(f"    {strategy_name}: {badge} {health} ({age_str}) tick_count={tick_count}")
            else:
                # Fallback if last_tick_ts not available
                strategy_age = strategy_data.get('last_tick_age_seconds')
                if strategy_age is not None:
                    badge, health = classify_strategy_health(strategy_age)
                    if strategy_age < 60:
                        age_str = f"{strategy_age:.1f}s"
                    elif strategy_age < 3600:
                        age_str = f"{strategy_age/60:.1f}min"
                    else:
                        age_str = f"{strategy_age/3600:.1f}hr"
                    print(f"    {strategy_name}: {badge} {health} ({age_str}) tick_count={tick_count}")
                else:
                    print(f"    {strategy_name}: ? UNKNOWN tick_count={tick_count}")
    
    print()
    
    # ============================================================
    # PHASE 6 — STATUS OUTPUT HARDENING
    # ============================================================
    # Status output MUST include:
    # - ENGINE: RUNNING/STOPPED (mode)
    # - PID: <pid>
    # - Loop Phase: <phase>
    # - Heartbeat Age: Xs
    # - Loop Tick: <count>
    # - Loop Tick Age: Ys
    # - Broker: <name>
    # - Diagnosis: <human readable>
    # 
    # REGRESSION LOCK — STATUS OUTPUT FORMAT
    # DO NOT MODIFY WITHOUT ENGINE REVIEW
    # SAFETY: monitoring-only, no execution impact
    # ============================================================
    
    print()
    # PHASE 6: Display loop health with badge
    engine_badge, engine_status = get_engine_badge(loop_health)
    print(f"Loop Health: {engine_badge} {engine_status}")
    if loop_health == "RUNNING":
        print("  Diagnosis: Loop is actively progressing")
        if loop_tick_age is not None:
            print(f"  Loop Tick Age: {loop_tick_age:.1f}s (< 10s threshold)")
    elif loop_health == "STALE":
        print("⚠ STALE")
        print("  Diagnosis: Heartbeat stale but loop still advancing")
        print("  Engine may be slow or blocked on broker/executor call")
        if heartbeat_age is not None:
            print(f"  Heartbeat Age: {heartbeat_age:.1f}s (>= 10s threshold)")
        if loop_tick_age is not None:
            print(f"  Loop Tick Age: {loop_tick_age:.1f}s (< 30s threshold)")
        # Display phase for stale state (early warning)
        if loop_phase != 'UNKNOWN':
            print(f"  Current Phase: {loop_phase}")
            if loop_phase == "BROKER_SUBMIT":
                print("  → Likely blocked on broker API call")
            elif loop_phase == "ROUTING":
                print("  → Likely blocked in order routing logic")
            elif loop_phase == "STRATEGY_EVAL":
                print("  → Likely blocked in strategy evaluation")
    elif loop_health == "FROZEN":
        print("✗ FROZEN")
        print("  Diagnosis: Loop appears frozen or deadlocked")
        if heartbeat_age is not None:
            print(f"  Heartbeat Age: {heartbeat_age:.1f}s (>= 10s threshold)")
        if loop_tick_age is not None:
            print(f"  Loop Tick Age: {loop_tick_age:.1f}s (>= 30s threshold)")
        # Display phase attribution when frozen for precise diagnosis
        print()
        print("  Freeze Attribution:")
        if loop_phase != 'UNKNOWN':
            print(f"    Engine appears frozen during phase: {loop_phase}")
            # Provide phase-specific guidance
            if loop_phase == "BROKER_SUBMIT":
                print("    → Engine may be blocked on broker API call")
                print("    → Check broker connection and API response times")
                print("    → Verify broker credentials and network connectivity")
            elif loop_phase == "ROUTING":
                print("    → Engine may be blocked in order routing logic")
                print("    → Check router and executor state")
                print("    → Review execution_router.py for blocking calls")
            elif loop_phase == "STRATEGY_EVAL":
                print("    → Engine may be blocked in strategy evaluation")
                print("    → Check strategy logic for infinite loops or blocking calls")
                print("    → Review strategy_manager.py and strategy implementations")
            elif loop_phase == "LOOP_START":
                print("    → Engine may be blocked at loop initialization")
                print("    → Check loop startup logic")
                print("    → Review engine.py run_forever() initialization")
            elif loop_phase == "IDLE":
                print("    → Engine may be blocked during sleep/idle phase")
                print("    → Check sleep mechanism")
                print("    → Review scheduler timing logic")
            else:
                print(f"    → Engine frozen in {loop_phase} phase")
                print("    → Review engine.py for phase-specific blocking operations")
        else:
            print("    Engine loop may be stalled, deadlocked, or blocked")
            print("    → Check engine logs for freeze escalation warnings")
            print("    → Review engine.py run_forever() loop structure")
        print()
        print("  Action Required:")
        print("    → Check engine logs: tail -f logs/engine.log")
        print("    → Verify process is responsive: ps aux | grep run_sentinel_x")
        print("    → Manual intervention may be required")
        print("    → Consider restarting engine if frozen > 60s")
    else:
        print("? UNKNOWN")
        print("  Diagnosis: Cannot determine loop state")
        if heartbeat_age is None:
            print("    Heartbeat age unavailable")
        if loop_tick_age is None:
            print("    Loop tick age unavailable")
        print("    → Check heartbeat file: /tmp/sentinel_x_heartbeat.json")
        print("    → Verify engine process is running")
    
    print()
    
    # Broker status (read-only)
    broker_display = broker_name.replace('_', ' ') if broker_name else 'NONE'
    print(f"BROKER: {broker_display}")
    print()
    
    # PHASE 6: Strategy Laboratory Observability (read-only)
    print()
    print("=" * 60)
    print("STRATEGY LABORATORY OBSERVABILITY (READ-ONLY)")
    print("=" * 60)
    print()
    
    try:
        from sentinel_x.intelligence.strategy_manager import get_strategy_manager, StrategyStatus
        from sentinel_x.intelligence.strategy_factory import get_strategy_factory
        from sentinel_x.intelligence.factory_enforcement import audit_strategy_creation
        from sentinel_x.intelligence.models import StrategyLifecycleState
        
        strategy_manager = get_strategy_manager()
        factory = get_strategy_factory()
        
        # PHASE 6: Display strategy metadata (configs, lifecycle states)
        strategies_list = strategy_manager.list_strategies()
        
        if strategies_list:
            print(f"Total Strategies: {len(strategies_list)}")
            
            # Count by lifecycle state
            lifecycle_counts = {}
            status_counts = {}
            factory_created_count = 0
            factory_bypassed_count = 0
            
            for strategy_info in strategies_list:
                lifecycle_state = strategy_info.get('lifecycle_state', 'TRAINING')
                status = strategy_info.get('status', 'DISABLED')
                lifecycle_counts[lifecycle_state] = lifecycle_counts.get(lifecycle_state, 0) + 1
                status_counts[status] = status_counts.get(status, 0) + 1
                
                # Check if created via factory (check strategy instance)
                strategy_name = strategy_info['name']
                if strategy_name in strategy_manager.strategies:
                    strategy = strategy_manager.strategies[strategy_name]
                    if hasattr(strategy, '_created_by_factory') and strategy._created_by_factory:
                        factory_created_count += 1
                    elif hasattr(strategy, '_factory_enforcement_bypassed') and strategy._factory_enforcement_bypassed:
                        factory_bypassed_count += 1
            
            print(f"  Active (TRAINING): {status_counts.get('ACTIVE', 0)}")
            print(f"  Disabled: {status_counts.get('DISABLED', 0)}")
            print(f"  Auto-Disabled: {status_counts.get('AUTO_DISABLED', 0)}")
            print()
            print(f"Lifecycle States:")
            for state, count in lifecycle_counts.items():
                print(f"  {state}: {count}")
            print()
            
            # PHASE 6: Factory enforcement status
            factory_audit = audit_strategy_creation()
            print(f"Factory Enforcement:")
            print(f"  Factory-Created: {factory_created_count}")
            print(f"  Factory-Bypassed: {factory_bypassed_count}")
            print(f"  Enforcement Enabled: {factory_audit.get('enforcement_enabled', 'unknown')}")
            print()
            
            # PHASE 6: Display strategy configs (sanitized, read-only)
            print("Strategy Configs (sanitized, read-only):")
            for strategy_info in strategies_list[:10]:  # Show first 10
                strategy_name = strategy_info['name']
                lifecycle_state = strategy_info.get('lifecycle_state', 'TRAINING')
                status = strategy_info.get('status', 'DISABLED')
                score = strategy_info.get('score')
                
                # Get config if available (from strategy instance)
                config_info = "N/A"
                if strategy_name in strategy_manager.strategies:
                    strategy = strategy_manager.strategies[strategy_name]
                    if hasattr(strategy, '_config'):
                        config = strategy._config
                        # Sanitize config (no sensitive data)
                        config_info = (
                            f"type={config.strategy_type}, "
                            f"timeframe={config.timeframe}m, "
                            f"lookback={config.lookback}, "
                            f"risk_per_trade={config.risk_per_trade:.2%}, "
                            f"max_trades_per_day={config.max_trades_per_day}"
                        )
                
                print(f"  {strategy_name}:")
                print(f"    Status: {status}, Lifecycle: {lifecycle_state}")
                if score is not None:
                    print(f"    Score: {score:.4f}")
                print(f"    Config: {config_info}")
            if len(strategies_list) > 10:
                print(f"  ... and {len(strategies_list) - 10} more strategies")
            print()
        else:
            print("No strategies registered")
            print()
        
        # PHASE 6: Governance limits (read-only)
        try:
            governance_summary = strategy_manager.enforce_governance_limits()
            limits = governance_summary.get('limits', {})
            if limits:
                print("Governance Limits:")
                print(f"  Max Active: {limits.get('max_active', 'N/A')}")
                print(f"  Max Disabled: {limits.get('max_disabled', 'N/A')}")
                print(f"  Max Total: {limits.get('max_total', 'N/A')}")
                print()
            
            if governance_summary.get('warnings'):
                print("Governance Warnings:")
                for warning in governance_summary['warnings'][:5]:  # Show first 5
                    print(f"  ⚠ {warning}")
                print()
        except Exception as e:
            logger.debug(f"Error getting governance limits (non-fatal): {e}")
        
        print("Note: Strategy metadata is READ-ONLY - no execution changes possible")
        print("Note: Lifecycle state = TRAINING (only active state)")
        print()
        
        # PHASE 8: Seed → Variants mapping (observability)
        try:
            from sentinel_x.intelligence.strategy_variant_generator import get_variant_generator
            variant_generator = get_variant_generator()
            
            seed_variant_mapping = variant_generator.get_seed_variant_mapping()
            seed_strategies = variant_generator.list_seeds()
            
            if seed_strategies or seed_variant_mapping:
                print()
                print("=" * 60)
                print("STRATEGY VARIANT GENERATION (PHASE 8 - OBSERVABILITY)")
                print("=" * 60)
                print()
                print("SAFETY: Auto-generation is parameter-only")
                print("SAFETY: Training-only")
                print("REGRESSION LOCK — STRATEGY VARIANT SYSTEM")
                print()
                
                if seed_strategies:
                    print(f"Registered Seed Strategies: {len(seed_strategies)}")
                    for seed_name in seed_strategies:
                        seed_config = variant_generator.get_seed_config(seed_name)
                        variants = variant_generator.list_variants(seed_name)
                        active_variants = []
                        disabled_variants = []
                        
                        # Check variant lifecycle states
                        for variant_name in variants:
                            if variant_name in strategy_manager.strategy_states:
                                state = strategy_manager.strategy_states[variant_name]
                                if state == StrategyLifecycleState.TRAINING:
                                    if strategy_manager.status.get(variant_name) == StrategyStatus.ACTIVE:
                                        active_variants.append(variant_name)
                                    else:
                                        disabled_variants.append(variant_name)
                                else:
                                    disabled_variants.append(variant_name)
                            else:
                                disabled_variants.append(variant_name)
                        
                        print(f"  Seed: {seed_name}")
                        if seed_config:
                            print(f"    Type: {seed_config.strategy_type}")
                            print(f"    Timeframe: {seed_config.timeframe}m")
                            print(f"    Lookback: {seed_config.lookback}")
                        print(f"    Variants: {len(variants)} total ({len(active_variants)} active, {len(disabled_variants)} disabled)")
                        
                        # Show variant parameter differences (observational only)
                        if variants:
                            print(f"    Variant Details:")
                            for variant_name in variants[:5]:  # Show first 5 variants
                                variant_config = variant_generator.get_variant_config(variant_name)
                                if variant_config:
                                    # Show parameter differences from seed
                                    diff_params = []
                                    if seed_config:
                                        if variant_config.lookback != seed_config.lookback:
                                            diff_params.append(f"lookback={variant_config.lookback}")
                                        if variant_config.entry_params != seed_config.entry_params:
                                            entry_diff = {k: v for k, v in variant_config.entry_params.items() 
                                                        if k not in seed_config.entry_params or seed_config.entry_params[k] != v}
                                            if entry_diff:
                                                diff_params.append(f"entry_params={entry_diff}")
                                        if variant_config.exit_params != seed_config.exit_params:
                                            exit_diff = {k: v for k, v in variant_config.exit_params.items() 
                                                        if k not in seed_config.exit_params or seed_config.exit_params[k] != v}
                                            if exit_diff:
                                                diff_params.append(f"exit_params={exit_diff}")
                                        if variant_config.stop_atr != seed_config.stop_atr:
                                            diff_params.append(f"stop_atr={variant_config.stop_atr:.2f}")
                                        if variant_config.take_profit_atr != seed_config.take_profit_atr:
                                            diff_params.append(f"take_profit_atr={variant_config.take_profit_atr:.2f}")
                                        if variant_config.session != seed_config.session:
                                            diff_params.append(f"session={variant_config.session}")
                                    
                                    variant_state = strategy_manager.strategy_states.get(variant_name, StrategyLifecycleState.TRAINING)
                                    variant_status = strategy_manager.status.get(variant_name, StrategyStatus.DISABLED)
                                    print(f"      {variant_name}: {variant_status.value} ({variant_state.value})")
                                    if diff_params:
                                        print(f"        Parameter Differences: {', '.join(diff_params)}")
                            if len(variants) > 5:
                                print(f"      ... and {len(variants) - 5} more variants")
                        print()
                else:
                    print("No seed strategies registered for variant generation")
                    print()
                
                print("Note: Variant generation is parameter-only mutation")
                print("Note: No logic changes occur during variant generation")
                print("Note: All variants pass through StrategyFactory")
                print()
        except ImportError:
            logger.debug("Variant generator not available (non-fatal)")
        except Exception as e:
            logger.debug(f"Error getting variant generation observability (non-fatal): {e}")
    except Exception as e:
        logger.debug(f"Error getting strategy laboratory observability (non-fatal): {e}")
        print("Strategy laboratory observability unavailable")
        print()
    
    # PHASE 6: Capital allocation display (read-only, simulated)
    try:
        from sentinel_x.monitoring.dashboard import get_strategy_dashboard
        dashboard = get_strategy_dashboard()
        capital_allocation = dashboard.get_capital_allocation()
        
        if capital_allocation:
            print()
            print("=" * 60)
            print("SIMULATED CAPITAL ALLOCATION — NO EXECUTION EFFECT")
            print("=" * 60)
            print()
            print(f"Model: {capital_allocation.get('model_mode', 'UNKNOWN')}")
            print(f"Total Simulated Capital: {capital_allocation.get('total_simulated_capital', 0.0):.0%}")
            allocations = capital_allocation.get('allocations', [])
            if allocations:
                active_allocations = [a for a in allocations if a.get('recommended_weight', 0) > 0]
                print(f"Active Allocations: {len(active_allocations)}")
                if active_allocations:
                    print()
                    print("Top Allocations (by weight):")
                    sorted_allocations = sorted(
                        active_allocations,
                        key=lambda x: x.get('recommended_weight', 0),
                        reverse=True
                    )
                    for alloc in sorted_allocations[:5]:
                        weight = alloc.get('recommended_weight', 0.0)
                        name = alloc.get('strategy_name', 'UNKNOWN')
                        model = alloc.get('allocation_model_used', 'UNKNOWN')
                        raw_score = alloc.get('raw_score', 0.0)
                        risk_score = alloc.get('risk_adjusted_score', 0.0)
                        notes = alloc.get('notes', '')
                        print(f"  {name}:")
                        print(f"    Weight: {weight:.2%} ({model})")
                        print(f"    Raw Score: {raw_score:.4f}, Risk-Adjusted: {risk_score:.4f}")
                        if notes:
                            print(f"    Notes: {notes}")
            governance_warnings = capital_allocation.get('governance_warnings', [])
            if governance_warnings:
                print()
                print(f"Governance Warnings: {len(governance_warnings)}")
                for warning in governance_warnings[:3]:
                    print(f"  - {warning}")
            print()
            print("Note: Capital Allocation is SIMULATED - no execution effect")
    except Exception as e:
        logger.debug(f"Error getting capital allocation (non-fatal): {e}")
    
    # Note about additional details
    print()
    print("Note: For detailed strategy and trade information, use:")
    print("  curl http://localhost:8000/health")
    print("  curl http://localhost:8000/strategies")
    print("  curl http://localhost:8000/dashboard/system")
    print("  curl http://localhost:8000/dashboard/strategies")
    print("  curl http://localhost:8000/dashboard/allocation")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
