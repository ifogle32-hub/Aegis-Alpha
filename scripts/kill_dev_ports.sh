#!/bin/bash
# PHASE 4 — Kill development ports safely
# Kills processes on ports 8000, 8001, and any uvicorn/gunicorn processes

set -e

echo "Killing processes on development ports..."

# Kill port 8000
if lsof -ti:8000 > /dev/null 2>&1; then
    echo "Killing process on port 8000..."
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# Kill port 8001
if lsof -ti:8001 > /dev/null 2>&1; then
    echo "Killing process on port 8001..."
    lsof -ti:8001 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# Kill uvicorn processes
if pgrep -f uvicorn > /dev/null 2>&1; then
    echo "Killing uvicorn processes..."
    pkill -9 -f uvicorn 2>/dev/null || true
    sleep 1
fi

# Kill gunicorn processes
if pgrep -f gunicorn > /dev/null 2>&1; then
    echo "Killing gunicorn processes..."
    pkill -9 -f gunicorn 2>/dev/null || true
    sleep 1
fi

# Kill python processes running api.main
if pgrep -f "python.*api.main" > /dev/null 2>&1; then
    echo "Killing python api.main processes..."
    pkill -9 -f "python.*api.main" 2>/dev/null || true
    sleep 1
fi

echo "Port cleanup complete."
