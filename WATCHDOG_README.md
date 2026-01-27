# Sentinel X Watchdog Supervisor

## Overview

The `tools/watchdog.sh` script is an **optional** supervisor layer that monitors the Sentinel X engine and can automatically restart it if it becomes frozen or stops.

## ⚠️ CRITICAL WARNINGS

**AUTO-RESTART BEHAVIOR IS DANGEROUS:**
- Auto-restart may interrupt live trading operations
- Restarts during broker operations may cause order state issues
- May cause data loss or inconsistent state
- **NEVER use in LIVE trading mode**
- Only use in TRAINING/PAPER mode for testing and development

**AUTO-RESTART IS DISABLED BY DEFAULT** for safety reasons.

## Usage

### Basic Monitoring (No Auto-Restart)

```bash
# Monitor engine but do NOT auto-restart (safe mode)
./tools/watchdog.sh
```

This will:
- Monitor engine status every 30 seconds
- Log warnings when FROZEN is detected
- **NOT** restart the engine automatically

### Enable Auto-Restart (Use with Extreme Caution)

```bash
# Enable auto-restart (DANGEROUS - only for testing)
export SENTINEL_ENABLE_AUTO_RESTART=1
./tools/watchdog.sh
```

## Configuration

The watchdog can be configured via environment variables:

```bash
# Project directory (default: $HOME/Aegis Alpha)
export SENTINEL_PROJECT_DIR="$HOME/Aegis Alpha"

# Virtual environment path (default: $PROJECT_DIR/.venv/bin/activate)
export SENTINEL_VENV="$PROJECT_DIR/.venv/bin/activate"

# Engine command (default: python run_sentinel_x.py)
export SENTINEL_ENGINE_CMD="python run_sentinel_x.py"

# Status check command (default: python tools/status.py)
export SENTINEL_CHECK_CMD="python tools/status.py"

# Check interval in seconds (default: 30)
export SENTINEL_CHECK_INTERVAL=30

# Freeze threshold - consecutive frozen checks before restart (default: 2)
export SENTINEL_FREEZE_THRESHOLD=2

# Enable auto-restart (default: 0 = disabled)
export SENTINEL_ENABLE_AUTO_RESTART=0  # Set to 1 to enable
```

## Behavior

### Monitoring Mode (Default)

When `SENTINEL_ENABLE_AUTO_RESTART=0` (default):
- Monitors engine status every `CHECK_INTERVAL` seconds
- Logs FROZEN detections to `logs/watchdog.log`
- Logs warnings when threshold is exceeded
- **Does NOT restart the engine**
- Requires manual intervention

### Auto-Restart Mode

When `SENTINEL_ENABLE_AUTO_RESTART=1`:
- Monitors engine status every `CHECK_INTERVAL` seconds
- If engine is FROZEN for `FREEZE_THRESHOLD` consecutive checks:
  - Sends SIGTERM to engine (graceful shutdown)
  - Waits 10 seconds for graceful shutdown
  - Sends SIGKILL if still running (force termination)
  - Waits 3 seconds
  - Starts engine in background
  - Logs restart to `logs/watchdog.log`

**Rate Limiting:**
- Restart is rate-limited to once per 5 minutes
- Prevents restart loops

## Logs

- **Watchdog Log**: `logs/watchdog.log`
- **Engine Log**: `logs/engine.log`

Watchdog logs include:
- Status check results
- FROZEN detections
- Restart attempts and results
- Errors and warnings

## Status Detection

The watchdog uses `tools/status.py` to check engine status:

- **RUNNING/STALE**: Engine is active, reset frozen counter
- **FROZEN**: Increment frozen counter, restart if threshold exceeded
- **STOPPED**: Engine process not running, restart if enabled

## Safety Features

1. **Auto-restart disabled by default**
2. **Rate limiting** prevents restart loops
3. **Graceful shutdown** attempts SIGTERM before SIGKILL
4. **Process existence checks** verify engine actually started
5. **Comprehensive logging** for audit trail
6. **Signal handlers** for clean shutdown

## Integration with System Services

### systemd Service (Example)

Create `/etc/systemd/system/sentinel-watchdog.service`:

```ini
[Unit]
Description=Sentinel X Engine Watchdog
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/home/your-user/Aegis Alpha
Environment="SENTINEL_ENABLE_AUTO_RESTART=0"
Environment="SENTINEL_CHECK_INTERVAL=30"
Environment="SENTINEL_FREEZE_THRESHOLD=2"
ExecStart=/home/your-user/Aegis Alpha/tools/watchdog.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Remember**: Set `SENTINEL_ENABLE_AUTO_RESTART=0` in the service file for safety.

## Regression Lock

This watchdog is an **OPTIONAL** supervisor layer that:
- Does NOT modify engine code
- Does NOT change trading logic
- Does NOT affect broker behavior
- Is completely external to the engine

The watchdog can be removed or disabled without affecting engine functionality.

## Best Practices

1. **Never enable auto-restart in production**
2. Use monitoring mode to detect issues early
3. Investigate FROZEN states manually before restarting
4. Review watchdog logs regularly
5. Test restart behavior in development environment first
6. Keep freeze threshold high (≥3) to avoid false positives

## Troubleshooting

### Watchdog not detecting engine

Check that:
- Engine is actually running: `pgrep -f run_sentinel_x.py`
- Heartbeat file exists: `ls -la /tmp/sentinel_x_heartbeat.json`
- Status command works: `python tools/status.py`

### False FROZEN detections

- Increase `FREEZE_THRESHOLD` (default: 2, try 3-5)
- Increase `CHECK_INTERVAL` (default: 30s, try 60s)
- Verify engine heartbeat is updating correctly

### Restart loops

- Check rate limiting is working (5 minute minimum)
- Review `logs/watchdog.log` for restart frequency
- Disable auto-restart and investigate root cause manually

## Compliance with System Constraints

This watchdog script:
- ✅ Does NOT modify trading logic
- ✅ Does NOT change execution behavior
- ✅ Does NOT touch broker code
- ✅ Is completely external (supervisor layer)
- ✅ Can be disabled without affecting engine
- ⚠️ **DOES implement auto-restart** (conflicts with previous "no auto-restart" constraint)
  - **Mitigation**: Auto-restart is **DISABLED BY DEFAULT**
  - Requires explicit opt-in via `SENTINEL_ENABLE_AUTO_RESTART=1`
  - Includes strong warnings and rate limiting
