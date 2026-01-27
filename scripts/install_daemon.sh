#!/bin/bash
# PHASE 6 — INSTALL LAUNCHD DAEMON
#
# Install Sentinel X as a macOS launchd daemon.
#
# Usage:
#   ./scripts/install_daemon.sh
#
# Requirements:
#   - macOS
#   - launchd
#   - Python 3 in virtualenv

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_FILE="$PROJECT_ROOT/launchd/com.aegisalpha.sentinelx.plist"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
INSTALLED_PLIST="$LAUNCHD_DIR/com.aegisalpha.sentinelx.plist"

echo "Installing Sentinel X daemon..."

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This script is for macOS only"
    exit 1
fi

# Check if plist file exists
if [[ ! -f "$PLIST_FILE" ]]; then
    echo "Error: Plist file not found: $PLIST_FILE"
    exit 1
fi

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCHD_DIR"

# Update plist file with actual paths
python3_path=$(which python3)
if [[ -z "$python3_path" ]]; then
    echo "Error: python3 not found in PATH"
    exit 1
fi

# Replace placeholders in plist
sed "s|/usr/bin/python3|$python3_path|g" "$PLIST_FILE" | \
sed "s|/Users/ins/Aegis Alpha|$PROJECT_ROOT|g" > "$INSTALLED_PLIST"

# Load daemon
if launchctl list | grep -q "com.aegisalpha.sentinelx"; then
    echo "Unloading existing daemon..."
    launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true
fi

echo "Loading daemon..."
launchctl load "$INSTALLED_PLIST"

echo "Daemon installed successfully!"
echo ""
echo "To check status:"
echo "  launchctl list | grep sentinelx"
echo ""
echo "To view logs:"
echo "  tail -f $PROJECT_ROOT/logs/sentinel.log"
echo ""
echo "To uninstall:"
echo "  ./scripts/uninstall_daemon.sh"
