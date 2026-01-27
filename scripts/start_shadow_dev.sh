#!/bin/bash
# PHASE 6 — START SHADOW TRAINING (DEVELOPMENT)
#
# Start shadow training in development mode (not as daemon).
#
# Usage:
#   ./scripts/start_shadow_dev.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Starting Sentinel X in shadow training mode (development)..."

cd "$PROJECT_ROOT"

# Activate virtualenv if it exists
if [[ -d "venv" ]]; then
    source venv/bin/activate
elif [[ -d ".venv" ]]; then
    source .venv/bin/activate
fi

# Set environment variables for shadow mode
export SENTINEL_ENGINE_MODE=SHADOW
export SHADOW_TRAINING_ENABLED=true

# Start API server (which starts engine loop)
python api/main.py
