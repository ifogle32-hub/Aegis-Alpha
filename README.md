# Sentinel X Trading System

Production-grade AI trading platform for paper trading with multiple symbols and strategies.

## Features

- **Continuous Operation**: Runs indefinitely until stopped
- **Instant Shutdown**: Kill switch via file flag or environment variable
- **Multiple Symbols**: Trade stocks and crypto simultaneously
- **Multiple Strategies**: Momentum, Mean Reversion, and Breakout strategies
- **Paper Trading**: Safe simulation mode with no real money
- **Time-based Scheduling**: Automatic training/trading window management
- **State Management**: Thread-safe global state tracking

## Installation

1. Install dependencies:
```bash
pip install -r sentinel_x/requirements.txt
```

2. (Optional) Copy and configure environment variables:
```bash
cp sentinel_x/.env.example sentinel_x/.env
# Edit .env as needed
```

## Usage

### Running Sentinel X

**Option 1: From sentinel_x directory**
```bash
cd sentinel_x
python main.py
```

**Option 2: From project root**
```bash
python run_sentinel_x.py
```

### Stopping Sentinel X

**Method 1: Keyboard interrupt**
- Press `Ctrl+C` to stop gracefully

**Method 2: Kill switch file**
```bash
touch KILL
# System will detect and stop immediately
```

**Method 3: Environment variable**
```bash
export KILL_SWITCH=true
# System will detect and stop immediately
```

## Configuration

Configuration is loaded from environment variables (see `.env.example`). Defaults are provided for all settings.

### Key Settings

- `SYMBOLS`: Comma-separated list of trading symbols
- `TRADE_MODE`: Set to `PAPER` for simulation (only mode currently supported)
- `TRAINING_WINDOW_START/END`: Hours (0-23) for training window
- `TRADING_WINDOW_START/END`: Hours (0-23) for trading window
- `INITIAL_CAPITAL`: Starting capital for paper trading

## Architecture

```
sentinel_x/
├── core/          # Core engine, state, scheduler, config
├── data/          # Market data provider (mock for now)
├── strategies/    # Trading strategies
├── execution/     # Order execution (paper trading)
├── monitoring/    # Logging system
└── main.py        # Entry point
```

## State Machine

- **STOPPED**: System is stopped
- **RUNNING**: System is running (initial state)
- **TRAINING**: In training window (no trading)
- **TRADING**: In trading window (active trading)

State transitions are logged and visible in the console output.

## Strategies

### Momentum Strategy
Uses Exponential Moving Average (EMA) crossover signals.

### Mean Reversion Strategy
Uses Z-score to identify overbought/oversold conditions.

### Breakout Strategy
Uses Donchian channels to detect breakouts.

## Development

All modules are fully implemented with no placeholders. The system is ready for:
- Integration with real market data feeds
- ML model integration (TODOs marked in code)
- Live trading execution (currently paper-only)

## License

Internal use only.

