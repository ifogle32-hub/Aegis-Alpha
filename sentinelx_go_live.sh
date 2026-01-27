#!/usr/bin/env bash
set -e

echo "======================================"
echo "🚀 SENTINEL X — GO LIVE SEQUENCE"
echo "======================================"

echo "1) Verifying environment..."
if [ -z "$SENTINEL_MODE" ]; then
  export SENTINEL_MODE=live
fi
echo "   MODE=$SENTINEL_MODE"

echo "2) Running preflight checks..."
python -m sentinelx.preflight || { echo "❌ Preflight failed"; exit 1; }

echo "3) Verifying shadow determinism..."
python -m sentinelx.shadow.verify || { echo "❌ Shadow verification failed"; exit 1; }

echo "4) Starting LIVE engine..."
python -m sentinelx.engine &

sleep 3

echo "5) Checking engine health..."
curl -sf http://localhost:8000/health >/dev/null   && echo "✅ Engine is LIVE"   || { echo "❌ Engine health check failed"; exit 1; }

echo "======================================"
echo "✅ SENTINEL X IS NOW LIVE"
echo "======================================"
