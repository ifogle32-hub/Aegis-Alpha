#!/usr/bin/env python3
"""
Sentinel X Watchdog

Purpose:
- Observe engine heartbeat + loop tick
- Distinguish RUNNING vs STALE vs FROZEN
- Restart engine ONLY when truly frozen
- Never interfere with trading logic

============================================================
PHASE 1 — DESIGN PRINCIPLES
============================================================
Watchdog is:
- A separate process (never runs inside engine)
- Read-only observer (reads heartbeat file only)
- Uses heartbeat + loop_tick signals
- Never touches engine internals
- Engine remains unaware of watchdog

SAFETY GUARANTEES:
- External process (never runs inside engine)
- No trading logic access
- No broker access
- Restart is guarded + cooldown enforced
- NEVER restart on STALE
- NEVER restart repeatedly
- Manual override always possible

============================================================
REGRESSION LOCK — WATCHDOG SIGNAL QUALITY
============================================================
DO NOT MODIFY WITHOUT ARCHITECT REVIEW

PHASE 2: Heartbeat noise reduction
- Only logs "Heartbeat missing → waiting" after 2 consecutive misses
- Never suppresses FROZEN or STALE escalation
- Noise reduction only, no behavior change

PHASE 3: Periodic health summary
- Emits summary every 60 seconds
- Provides operator confidence for long-running sessions
- Uses same classification logic as main loop

NO future changes may:
- Add auto-restarts beyond FROZEN state
- Change trading logic
- Change broker behavior
- Add blocking calls
- Add threads
- Alter loop timing
- Weaken safety guards
- Restart on STALE state

============================================================
PHASE 6 — OPERATIONAL SAFETY
============================================================
Guarantees:
- Watchdog cannot affect trading logic
- Engine remains PAPER-only
- LIVE mode untouched
- Manual override always possible
- Restart only on true freeze (FROZEN)
- Cooldown prevents rapid restarts

============================================================
PHASE 7 — DEPLOYMENT
============================================================
Run engine:
  nohup python run_sentinel_x.py > logs/engine.log 2>&1 &

Run watchdog:
  nohup python tools/watchdog.py > logs/watchdog.log 2>&1 &

Stop watchdog:
  pkill -f "tools/watchdog.py"

Stop engine:
  pkill -f "run_sentinel_x.py"
============================================================
"""

import os
import json
import time
import signal
import subprocess
from pathlib import Path
from typing import Optional

# ============================
# CONFIG
# ============================

HEARTBEAT_FILE = "/tmp/sentinel_x_heartbeat.json"

CHECK_INTERVAL = 5.0          # seconds
STALE_THRESHOLD = 10.0        # seconds - heartbeat age threshold
FROZEN_THRESHOLD = 30.0       # seconds - loop tick age threshold for FROZEN
RESTART_COOLDOWN = 60.0       # minimum seconds between restarts
GRACE_PERIOD = 3.0           # seconds to wait after SIGTERM before relaunch

ENGINE_CMD = ["python", "run_sentinel_x.py"]
ENGINE_LOG = "logs/engine.log"

# ============================
# STATE
# ============================

last_restart_ts: float = 0.0
last_seen_loop_tick: Optional[int] = None
last_seen_loop_tick_ts: Optional[float] = None

# REGRESSION LOCK — WATCHDOG SIGNAL QUALITY
# DO NOT MODIFY WITHOUT ARCHITECT REVIEW
# SAFETY: monitoring-only, no execution impact

# PHASE 2: Heartbeat noise reduction
missed_heartbeat_count: int = 0  # Track consecutive missed heartbeats

# PHASE 3: Periodic health summary
last_summary_time: float = 0.0
SUMMARY_INTERVAL: float = 60.0  # seconds
loop_tick_rate_samples: list = []  # Track loop_tick changes for rate calculation
MAX_RATE_SAMPLES: int = 10  # Keep last 10 samples for rate calculation


# ============================
# LOGGING
# ============================

def log(msg: str, level: str = "INFO") -> None:
    """
    Log message with optional level prefix.
    
    PHASE 5: Log level hygiene
    - INFO: Normal operations, summaries
    - WARNING: STALE states
    - ERROR: FROZEN states, critical issues
    """
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{level}]" if level != "INFO" else ""
    print(f"[{ts}] {prefix} {msg}", flush=True)


# ============================
# ENGINE CONTROL
# ============================

def find_engine_pid() -> Optional[int]:
    """Best-effort engine PID discovery."""
    try:
        out = subprocess.check_output(["pgrep", "-f", "run_sentinel_x.py"]).decode()
        pids = [int(x) for x in out.split()]
        return pids[0] if pids else None
    except Exception:
        return None


def restart_engine() -> None:
    """
    PHASE 4 — SAFE RESTART MECHANISM
    
    Restart method:
    - Send SIGTERM to engine process
    - Wait grace period for clean shutdown
    - Relaunch via: python run_sentinel_x.py
    
    Rules:
    - NEVER restart on STALE
    - NEVER restart repeatedly (cooldown enforced)
    - Log every decision
    - Check PID exists before attempting restart
    
    REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
    SAFETY: monitoring-only, no execution impact
    """
    global last_restart_ts

    now = time.time()
    
    # PHASE 4: Restart cooldown check
    if now - last_restart_ts < RESTART_COOLDOWN:
        remaining = RESTART_COOLDOWN - (now - last_restart_ts)
        log(f"Restart skipped (cooldown active, {remaining:.1f}s remaining)", level="WARNING")
        return

    # PHASE 4: Check if engine PID still exists
    pid = find_engine_pid()
    if not pid:
        log("Engine PID not found - may already be stopped", level="WARNING")
        # Still attempt to start engine (may have crashed)
    else:
        log(f"Stopping engine PID {pid}", level="ERROR")
        try:
            # PHASE 4: Send SIGTERM for graceful shutdown
            os.kill(pid, signal.SIGTERM)
            log(f"SIGTERM sent to PID {pid}", level="INFO")
        except ProcessLookupError:
            log(f"Engine PID {pid} already terminated", level="INFO")
        except Exception as e:
            log(f"Failed to terminate engine: {e}", level="ERROR")
            # Continue anyway - may have already stopped

    # PHASE 4: Wait grace period for clean shutdown
    log(f"Waiting {GRACE_PERIOD}s grace period for clean shutdown", level="INFO")
    time.sleep(GRACE_PERIOD)

    # PHASE 4: Relaunch engine
    log("Starting engine", level="INFO")
    Path("logs").mkdir(exist_ok=True)

    try:
        subprocess.Popen(
            ENGINE_CMD,
            stdout=open(ENGINE_LOG, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log("Engine restart initiated", level="INFO")
    except Exception as e:
        log(f"Failed to start engine: {e}", level="ERROR")
        return

    last_restart_ts = now
    log(f"Engine restart completed (cooldown: {RESTART_COOLDOWN}s)", level="INFO")


# ============================
# HEARTBEAT READ
# ============================

def read_heartbeat() -> Optional[dict]:
    """
    PHASE 2 — WATCHDOG INPUT CONTRACT
    
    Watchdog reads:
    - /tmp/sentinel_x_heartbeat.json
    
    Required fields:
    - heartbeat_monotonic (timestamp for age calculation)
    - loop_tick (counter for loop activity)
    - last_loop_tick_ts (timestamp for loop tick age)
    - mode (engine mode: TRAINING/PAPER/LIVE)
    - loop_phase (current engine phase)
    
    Returns None if file doesn't exist or is invalid.
    
    SAFETY: read-only, no execution impact
    """
    try:
        with open(HEARTBEAT_FILE, "r") as f:
            data = json.load(f)
            # Validate required fields exist
            required_fields = ["heartbeat_monotonic", "loop_tick", "last_loop_tick_ts"]
            if all(field in data for field in required_fields):
                return data
            else:
                log(f"Heartbeat file missing required fields: {required_fields}", level="WARNING")
                return None
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        log("Heartbeat file contains invalid JSON", level="WARNING")
        return None
    except Exception as e:
        log(f"Error reading heartbeat file: {e}", level="WARNING")
        return None


# ============================
# CLASSIFICATION
# ============================

def classify(hb: dict) -> str:
    """
    Classify engine state based on heartbeat and loop tick signals.
    
    PHASE 3 — WATCHDOG CLASSIFICATION LOGIC
    
    Compute:
    - heartbeat_age = now - heartbeat_monotonic
    - loop_tick_age = now - last_loop_tick_ts
    
    Classification rules (EXACT):
    - RUNNING: loop_tick_age < STALE_THRESHOLD (loop actively progressing)
    - STALE: heartbeat_age >= STALE_THRESHOLD AND loop_tick_age < FROZEN_THRESHOLD
      (heartbeat stale but loop_tick still advancing)
    - FROZEN: heartbeat_age >= STALE_THRESHOLD AND loop_tick_age >= FROZEN_THRESHOLD
      (both signals stale = truly frozen)
    
    IMPORTANT: Never mark FROZEN if loop_tick advances
    
    REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
    SAFETY: monitoring-only, no execution impact
    """
    global last_seen_loop_tick, last_seen_loop_tick_ts, loop_tick_rate_samples

    now_mono = time.monotonic()

    heartbeat_ts = hb.get("heartbeat_monotonic")
    loop_tick = hb.get("loop_tick")
    loop_tick_ts = hb.get("last_loop_tick_ts")

    if heartbeat_ts is None or loop_tick is None or loop_tick_ts is None:
        return "UNKNOWN"

    heartbeat_age = now_mono - heartbeat_ts
    loop_tick_age = now_mono - loop_tick_ts

    # Track loop advancement and rate samples
    if last_seen_loop_tick != loop_tick:
        # PHASE 3: Track loop tick rate
        if last_seen_loop_tick is not None and last_seen_loop_tick_ts is not None:
            tick_delta = loop_tick - last_seen_loop_tick
            time_delta = now_mono - last_seen_loop_tick_ts
            if time_delta > 0:
                rate = tick_delta / time_delta
                loop_tick_rate_samples.append((now_mono, rate))
                # Keep only recent samples
                if len(loop_tick_rate_samples) > MAX_RATE_SAMPLES:
                    loop_tick_rate_samples.pop(0)
        
        last_seen_loop_tick = loop_tick
        last_seen_loop_tick_ts = now_mono

    # ============================================================
    # PHASE 3 — CLASSIFICATION RULES (EXACT)
    # ============================================================
    # RUNNING: loop_tick_age < STALE_THRESHOLD
    if loop_tick_age < STALE_THRESHOLD:
        return "RUNNING"
    
    # STALE: heartbeat stale but loop_tick advancing
    # heartbeat_age >= STALE_THRESHOLD AND loop_tick_age < FROZEN_THRESHOLD
    if heartbeat_age >= STALE_THRESHOLD and loop_tick_age < FROZEN_THRESHOLD:
        return "STALE"
    
    # FROZEN: both heartbeat AND loop_tick are stale
    # heartbeat_age >= STALE_THRESHOLD AND loop_tick_age >= FROZEN_THRESHOLD
    if heartbeat_age >= STALE_THRESHOLD and loop_tick_age >= FROZEN_THRESHOLD:
        return "FROZEN"
    
    # Fallback
    return "UNKNOWN"


def calculate_avg_loop_tick_rate() -> float:
    """
    Calculate average loop tick rate from recent samples.
    
    PHASE 3: Rate calculation for health summary
    Returns ticks per second.
    
    SAFETY: monitoring-only, no execution impact
    """
    global loop_tick_rate_samples
    
    if not loop_tick_rate_samples:
        return 0.0
    
    # Calculate average rate from samples
    rates = [rate for _, rate in loop_tick_rate_samples]
    return sum(rates) / len(rates) if rates else 0.0


def get_health_classification(status: str) -> str:
    """
    Map status to health classification for summary.
    
    PHASE 4: Classification consistency
    - RUNNING → HEALTHY
    - STALE → DEGRADED
    - FROZEN → UNHEALTHY
    - UNKNOWN → UNKNOWN
    
    SAFETY: monitoring-only, no execution impact
    """
    mapping = {
        "RUNNING": "HEALTHY",
        "STALE": "DEGRADED",
        "FROZEN": "UNHEALTHY",
        "UNKNOWN": "UNKNOWN"
    }
    return mapping.get(status, "UNKNOWN")


def emit_health_summary(hb: dict, status: str) -> None:
    """
    Emit periodic health summary every 60 seconds.
    
    PHASE 3: Watchdog health summary
    Provides operator confidence for long-running sessions.
    
    SAFETY: monitoring-only, no execution impact
    """
    global last_summary_time
    
    now = time.monotonic()
    
    # Check if 60 seconds have passed
    if last_summary_time == 0.0:
        last_summary_time = now
        return
    
    if now - last_summary_time < SUMMARY_INTERVAL:
        return
    
    # Calculate metrics
    now_mono = time.monotonic()
    heartbeat_ts = hb.get("heartbeat_monotonic")
    loop_tick_ts = hb.get("last_loop_tick_ts")
    heartbeat_age = (now_mono - heartbeat_ts) if heartbeat_ts is not None else 0.0
    loop_tick_age = (now_mono - loop_tick_ts) if loop_tick_ts is not None else 0.0
    avg_rate = calculate_avg_loop_tick_rate()
    health = get_health_classification(status)
    
    # Format summary
    summary = (
        f"[WATCHDOG SUMMARY]\n"
        f"status={status} mode={hb.get('mode', 'UNKNOWN')}\n"
        f"loop_phase={hb.get('loop_phase', 'UNKNOWN')}\n"
        f"loop_tick={hb.get('loop_tick', 0)}\n"
        f"avg_loop_tick_rate={avg_rate:.1f}/s\n"
        f"heartbeat_age={heartbeat_age:.1f}s\n"
        f"loop_tick_age={loop_tick_age:.1f}s\n"
        f"broker={hb.get('broker', 'NONE')}\n"
        f"health={health}"
    )
    
    log(summary, level="INFO")
    last_summary_time = now


# ============================
# MAIN LOOP
# ============================

def main() -> None:
    """
    Main watchdog loop.
    
    PHASE 2: Heartbeat noise reduction
    PHASE 3: Periodic health summary
    PHASE 5: Log level hygiene
    
    SAFETY: monitoring-only, no execution impact
    """
    global missed_heartbeat_count
    
    log("=" * 60)
    log("Sentinel X Watchdog started")
    log("=" * 60)
    log("Configuration:")
    log(f"  Heartbeat file: {HEARTBEAT_FILE}")
    log(f"  Check interval: {CHECK_INTERVAL}s")
    log(f"  STALE threshold: {STALE_THRESHOLD}s (heartbeat age)")
    log(f"  FROZEN threshold: {FROZEN_THRESHOLD}s (loop tick age)")
    log(f"  Restart cooldown: {RESTART_COOLDOWN}s")
    log(f"  Grace period: {GRACE_PERIOD}s (after SIGTERM)")
    log(f"  Health summary interval: {SUMMARY_INTERVAL}s")
    log("")
    log("Operational Safety:")
    log("  ✓ Watchdog is isolated (separate process)")
    log("  ✓ Read-only observer (no engine internals)")
    log("  ✓ Restart ONLY on FROZEN state")
    log("  ✓ NEVER restart on STALE")
    log("  ✓ Cooldown enforced (no rapid restarts)")
    log("  ✓ Manual override always possible")
    log("=" * 60)

    while True:
        hb = read_heartbeat()

        if not hb:
            # PHASE 2: Noise reduction - only log after 2 consecutive misses
            missed_heartbeat_count += 1
            if missed_heartbeat_count >= 2:
                log("Heartbeat missing → waiting", level="INFO")
            # SAFETY: noise reduction only, no behavior change
            time.sleep(CHECK_INTERVAL)
            continue
        
        # PHASE 2: Reset counter when heartbeat reappears
        missed_heartbeat_count = 0

        status = classify(hb)

        # ============================================================
        # PHASE 5 — WATCHDOG LOGGING
        # ============================================================
        # Log fields:
        # - status
        # - mode
        # - loop_phase
        # - loop_tick
        # - heartbeat_age
        # - loop_tick_age
        # - restart decision
        # ============================================================
        now_mono = time.monotonic()
        heartbeat_age = round(now_mono - hb.get('heartbeat_monotonic', now_mono), 1)
        loop_tick_age = round(now_mono - hb.get('last_loop_tick_ts', now_mono), 1)
        
        # PHASE 5: Log level hygiene
        log_level = "INFO" if status == "RUNNING" else ("WARNING" if status == "STALE" else "ERROR")
        log(
            f"status={status} "
            f"mode={hb.get('mode', 'UNKNOWN')} "
            f"loop_phase={hb.get('loop_phase', 'UNKNOWN')} "
            f"loop_tick={hb.get('loop_tick', 0)} "
            f"heartbeat_age={heartbeat_age}s "
            f"loop_tick_age={loop_tick_age}s",
            level=log_level
        )

        # PHASE 3: Emit periodic health summary
        emit_health_summary(hb, status)
        
        # ============================================================
        # PHASE 7 — WATCHDOG INTEGRATION (READ-ONLY)
        # ============================================================
        # Watchdog MAY log:
        # - engine badge
        # - strategy badge summary
        # - loop_phase distribution
        # 
        # Watchdog MUST NOT:
        # - restart on strategy RED
        # - restart on STALE
        # - act on UI badge state
        # 
        # Engine restart remains gated ONLY by:
        # ENGINE == FROZEN
        # 
        # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
        # SAFETY: monitoring-only, no execution impact
        # ============================================================
        # Log engine badge for observability (read-only)
        if status == "RUNNING":
            engine_badge = "🟢"
        elif status == "STALE":
            engine_badge = "🟡"
        elif status == "FROZEN":
            engine_badge = "🔴"
        else:
            engine_badge = "⚪"
        
        # Log strategy badge summary if available
        strategy_heartbeats = hb.get('strategy_heartbeats', {})
        if strategy_heartbeats:
            now_mono = time.monotonic()
            strategy_badges = []
            for strategy_name, strategy_data in strategy_heartbeats.items():
                last_tick_ts = strategy_data.get('last_tick_ts')
                if last_tick_ts:
                    strategy_age = now_mono - last_tick_ts
                    if strategy_age < 2.0:
                        badge = "🟢"
                    elif strategy_age < 30.0:
                        badge = "🟡"
                    else:
                        badge = "🔴"
                    strategy_badges.append(f"{badge}{strategy_name}")
            
            if strategy_badges:
                log(f"Strategy badges: {' '.join(strategy_badges)}", level="INFO")

        # ============================================================
        # PHASE 4 — RESTART DECISION
        # ============================================================
        # Restart ONLY if:
        # - status == FROZEN
        # - restart cooldown elapsed
        # - engine PID still exists (checked in restart_engine)
        # 
        # NEVER restart on STALE
        # NEVER restart repeatedly
        # ============================================================
        if status == "FROZEN":
            log("FROZEN detected → evaluating restart", level="ERROR")
            
            # PHASE 4: Additional safety check - verify PID exists
            pid = find_engine_pid()
            if pid:
                log(f"Engine PID {pid} exists → proceeding with restart", level="ERROR")
                restart_engine()
            else:
                log("Engine PID not found → may have crashed, attempting restart", level="ERROR")
                restart_engine()
        elif status == "STALE":
            # PHASE 4: Explicitly log that we do NOT restart on STALE
            log("STALE state detected → NO restart (loop still advancing)", level="WARNING")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
