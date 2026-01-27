#!/bin/bash
# PHASE 6 — UNINSTALL LAUNCHD DAEMON
#
# Uninstall Sentinel X launchd daemon.
#
# Usage:
#   ./scripts/uninstall_daemon.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
INSTALLED_PLIST="$LAUNCHD_DIR/com.aegisalpha.sentinelx.plist"

echo "Uninstalling Sentinel X daemon..."

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This script is for macOS only"
    exit 1
fi

# Unload daemon if running
if [[ -f "$INSTALLED_PLIST" ]]; then
    if launchctl list | grep -q "com.aegisalpha.sentinelx"; then
        echo "Unloading daemon..."
        launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true
    fi
    
    echo "Removing plist file..."
    rm -f "$INSTALLED_PLIST"
    echo "Daemon uninstalled successfully!"
else
    echo "Daemon not installed (plist file not found)"
fi
