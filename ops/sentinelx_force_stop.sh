#!/usr/bin/env bash
echo "🛑 SENTINEL X — FORCE STOP"

sudo pkill -9 -f gunicorn || true
sudo pkill -9 -f uvicorn || true
sudo pkill -9 -f sentinelx || true
sudo pkill -9 -f api.main || true
sudo pkill -9 -f "python.*8000" || true

sleep 1

echo "🔍 Verifying port 8000..."
if lsof -i :8000 >/dev/null; then
  echo "❌ Port 8000 STILL IN USE"
  lsof -i :8000
  exit 1
else
  echo "✅ Sentinel X fully stopped"
fi
