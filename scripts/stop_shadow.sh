#!/bin/bash
# PHASE 6 — STOP SHADOW TRAINING
#
# Stop shadow training by sending kill signal.
#
# Usage:
#   ./scripts/stop_shadow.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCK_FILE="/tmp/sentinel_x.lock"

echo "Stopping Sentinel X..."

# Check if daemon is running
if launchctl list | grep -q "com.aegisalpha.sentinelx"; then
    echo "Stopping daemon..."
    launchctl unload "$HOME/Library/LaunchAgents/com.aegisalpha.sentinelx.plist" 2>/dev/null || true
    echo "Daemon stopped"
fi

# Check if process is running (by lock file)
if [[ -f "$LOCK_FILE" ]]; then
    PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        echo "Stopping process (PID: $PID)..."
        kill "$PID" 2>/dev/null || true
        sleep 2
        if kill -0 "$PID" 2>/dev/null; then
            echo "Force killing process..."
            kill -9 "$PID" 2>/dev/null || true
        fi
    fi
    rm -f "$LOCK_FILE"
fi

echo "Sentinel X stopped"
