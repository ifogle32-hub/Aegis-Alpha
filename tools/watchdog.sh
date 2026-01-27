#!/usr/bin/env bash
#
# Sentinel X Engine Watchdog Supervisor
#
# ============================================================================
# CRITICAL SAFETY NOTICE
# ============================================================================
# This script implements auto-restart behavior, which CONFLICTS with
# previous system constraints that explicitly forbid auto-restarts.
#
# USE WITH CAUTION:
# - Auto-restart may interrupt live trading
# - Restarts during broker operations may cause order state issues
# - Only use in TRAINING/PAPER mode for testing
# - NEVER use in LIVE trading mode
#
# REGRESSION LOCK:
# This watchdog is an OPTIONAL supervisor layer.
# It does NOT modify engine code or trading logic.
# Auto-restart behavior is DISABLED by default.
# ============================================================================

set -euo pipefail

# Configuration
PROJECT_DIR="${SENTINEL_PROJECT_DIR:-$HOME/Aegis Alpha}"
VENV="${SENTINEL_VENV:-$PROJECT_DIR/.venv/bin/activate}"
ENGINE_CMD="${SENTINEL_ENGINE_CMD:-python run_sentinel_x.py}"
CHECK_CMD="${SENTINEL_CHECK_CMD:-python tools/status.py}"
CHECK_INTERVAL="${SENTINEL_CHECK_INTERVAL:-30}"
FREEZE_THRESHOLD="${SENTINEL_FREEZE_THRESHOLD:-2}"  # consecutive frozen checks

# ============================================================================
# AUTO-RESTART CONTROL (DISABLED BY DEFAULT)
# ============================================================================
# Set SENTINEL_ENABLE_AUTO_RESTART=1 to enable auto-restart behavior
# WARNING: Auto-restart is dangerous and may cause data loss or order issues
# ============================================================================
ENABLE_AUTO_RESTART="${SENTINEL_ENABLE_AUTO_RESTART:-0}"

# State tracking
frozen_count=0
restart_count=0
last_restart_ts=0

# Logging
LOG_DIR="$PROJECT_DIR/logs"
WATCHDOG_LOG="$LOG_DIR/watchdog.log"
ENGINE_LOG="$LOG_DIR/engine.log"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Logging function
log_watchdog() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$WATCHDOG_LOG"
}

# Check if engine process is running
is_engine_running() {
    pgrep -f "run_sentinel_x.py" > /dev/null 2>&1
}

# Start engine
start_engine() {
    if is_engine_running; then
        log_watchdog "WARN" "Engine process already running, skipping start"
        return 1
    fi

    log_watchdog "INFO" "Starting engine: $ENGINE_CMD"
    cd "$PROJECT_DIR"
    
    if [ -f "$VENV" ]; then
        source "$VENV"
    else
        log_watchdog "WARN" "Virtual environment not found at $VENV, continuing without it"
    fi
    
    nohup $ENGINE_CMD >> "$ENGINE_LOG" 2>&1 &
    local pid=$!
    log_watchdog "INFO" "Engine started with PID: $pid"
    
    restart_count=$((restart_count + 1))
    last_restart_ts=$(date +%s)
    
    # Wait a moment to see if engine starts successfully
    sleep 5
    if ! is_engine_running; then
        log_watchdog "ERROR" "Engine failed to start or crashed immediately"
        return 1
    fi
    
    return 0
}

# Stop engine gracefully
stop_engine() {
    if ! is_engine_running; then
        log_watchdog "WARN" "Engine process not running, skipping stop"
        return 0
    fi

    log_watchdog "INFO" "Stopping engine gracefully (SIGTERM)"
    pkill -TERM -f "run_sentinel_x.py" || true
    
    # Wait for graceful shutdown
    local wait_count=0
    while is_engine_running && [ $wait_count -lt 10 ]; do
        sleep 1
        wait_count=$((wait_count + 1))
    done
    
    if is_engine_running; then
        log_watchdog "WARN" "Engine did not stop gracefully, forcing termination (SIGKILL)"
        pkill -KILL -f "run_sentinel_x.py" || true
        sleep 2
    fi
    
    log_watchdog "INFO" "Engine stopped"
}

# Restart engine (only if auto-restart enabled)
restart_engine() {
    if [ "$ENABLE_AUTO_RESTART" != "1" ]; then
        log_watchdog "WARN" "Auto-restart DISABLED. Engine is FROZEN but will NOT be restarted."
        log_watchdog "WARN" "To enable auto-restart, set: export SENTINEL_ENABLE_AUTO_RESTART=1"
        log_watchdog "WARN" "Manual intervention required."
        return 1
    fi

    # Rate limiting: Don't restart more than once per 5 minutes
    local current_ts=$(date +%s)
    if [ $((current_ts - last_restart_ts)) -lt 300 ]; then
        log_watchdog "WARN" "Restart rate limit: Last restart was less than 5 minutes ago"
        log_watchdog "WARN" "Skipping restart to prevent restart loop"
        return 1
    fi

    log_watchdog "CRITICAL" "========================================"
    log_watchdog "CRITICAL" "AUTO-RESTART TRIGGERED"
    log_watchdog "CRITICAL" "Frozen count: $frozen_count/$FREEZE_THRESHOLD"
    log_watchdog "CRITICAL" "Total restarts today: $restart_count"
    log_watchdog "CRITICAL" "========================================"

    stop_engine
    sleep 3
    start_engine
    
    if [ $? -eq 0 ]; then
        log_watchdog "INFO" "Engine restarted successfully"
        frozen_count=0
        return 0
    else
        log_watchdog "ERROR" "Engine restart failed"
        return 1
    fi
}

# Check engine status
check_engine_status() {
    cd "$PROJECT_DIR"
    
    if [ -f "$VENV" ]; then
        source "$VENV" 2>/dev/null || true
    fi
    
    local status_output
    status_output=$($CHECK_CMD 2>&1) || {
        log_watchdog "ERROR" "Status check command failed"
        return 2
    }
    
    echo "$status_output"
    
    # Check for FROZEN status
    if echo "$status_output" | grep -q "Loop: FROZEN"; then
        return 1  # FROZEN detected
    elif echo "$status_output" | grep -q "ENGINE: STOPPED"; then
        return 2  # STOPPED detected
    else
        return 0  # RUNNING or STALE
    fi
}

# Main watchdog loop
main() {
    log_watchdog "INFO" "========================================"
    log_watchdog "INFO" "Sentinel X Watchdog Supervisor Starting"
    log_watchdog "INFO" "========================================"
    log_watchdog "INFO" "Project Directory: $PROJECT_DIR"
    log_watchdog "INFO" "Check Interval: ${CHECK_INTERVAL}s"
    log_watchdog "INFO" "Freeze Threshold: $FREEZE_THRESHOLD consecutive checks"
    log_watchdog "INFO" "Auto-Restart: $([ "$ENABLE_AUTO_RESTART" = "1" ] && echo "ENABLED ⚠️" || echo "DISABLED (safe)")"
    log_watchdog "INFO" "========================================"

    # Initial engine check
    if ! is_engine_running; then
        log_watchdog "WARN" "Engine process not running, attempting to start..."
        start_engine || {
            log_watchdog "ERROR" "Failed to start engine initially"
            exit 1
        }
    else
        log_watchdog "INFO" "Engine process already running"
    fi

    # Main monitoring loop
    while true; do
        local status_result
        local status_output
        
        status_output=$(check_engine_status)
        status_result=$?

        case $status_result in
            0)
                # RUNNING or STALE - reset frozen count
                if [ $frozen_count -gt 0 ]; then
                    log_watchdog "INFO" "Engine recovered from frozen state (frozen_count reset)"
                    frozen_count=0
                fi
                ;;
            1)
                # FROZEN detected
                frozen_count=$((frozen_count + 1))
                log_watchdog "WARN" "FROZEN detected ($frozen_count/$FREEZE_THRESHOLD consecutive checks)"
                
                if [ "$frozen_count" -ge "$FREEZE_THRESHOLD" ]; then
                    log_watchdog "CRITICAL" "Freeze threshold exceeded, considering restart..."
                    restart_engine
                    # Note: frozen_count is reset inside restart_engine on success
                fi
                ;;
            2)
                # STOPPED detected
                log_watchdog "WARN" "Engine STOPPED detected"
                if [ "$ENABLE_AUTO_RESTART" = "1" ]; then
                    log_watchdog "INFO" "Auto-restart enabled, attempting to start engine..."
                    start_engine || log_watchdog "ERROR" "Failed to restart stopped engine"
                else
                    log_watchdog "WARN" "Auto-restart disabled, engine remains stopped"
                fi
                frozen_count=0
                ;;
        esac

        # Check if engine process is still alive (even if status says otherwise)
        if ! is_engine_running; then
            log_watchdog "WARN" "Engine process not found (may have crashed)"
            if [ "$ENABLE_AUTO_RESTART" = "1" ]; then
                log_watchdog "INFO" "Auto-restart enabled, attempting to start engine..."
                start_engine || log_watchdog "ERROR" "Failed to restart crashed engine"
            else
                log_watchdog "WARN" "Auto-restart disabled, engine remains down"
            fi
        fi

        sleep "$CHECK_INTERVAL"
    done
}

# Signal handlers for graceful shutdown
trap 'log_watchdog "INFO" "Watchdog received SIGTERM, shutting down gracefully..."; exit 0' TERM
trap 'log_watchdog "INFO" "Watchdog received SIGINT, shutting down gracefully..."; exit 0' INT

# Run main function
main
