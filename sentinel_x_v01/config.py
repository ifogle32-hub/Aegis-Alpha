"""
Sentinel X v0.1 — Configuration.
Single asset NVDA, shadow only, 10% capital per trade.
"""
import os
from dataclasses import dataclass
from typing import List

# Timeframe labels and minute equivalents for bars
TIMEFRAMES = ["1Min", "5Min", "15Min", "1Hour", "1Day"]
TIMEFRAME_MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60, "1Day": 1440}


@dataclass
class Config:
    """Lean config: NVDA, shadow only, adaptive."""
    symbol: str = "NVDA"
    timeframes: List[str] = None
    capital_pct_per_trade: float = 0.10
    initial_capital: float = 100_000.0
    # Strategy bounds
    momentum_window: int = 20
    vol_lookback: int = 20
    # Learning
    learning_rate: float = 0.01
    signal_threshold_min: float = 0.0
    signal_threshold_max: float = 1.0
    position_multiplier_min: float = 0.5
    position_multiplier_max: float = 1.5
    # Engine
    loop_sleep_seconds: float = 60.0
    heartbeat_path: str = "/tmp/sentinel_x_heartbeat.json"
    state_path: str = "/tmp/sentinel_x_state.json"
    # Alpaca (paper)
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    def __post_init__(self):
        if self.timeframes is None:
            self.timeframes = list(TIMEFRAMES)


def get_config() -> Config:
    """Load from env with defaults."""
    return Config(
        symbol=os.getenv("SENTINEL_SYMBOL", "NVDA"),
        initial_capital=float(os.getenv("SENTINEL_INITIAL_CAPITAL", "100000")),
        capital_pct_per_trade=float(os.getenv("SENTINEL_CAPITAL_PCT", "0.10")),
        learning_rate=float(os.getenv("SENTINEL_LEARNING_RATE", "0.01")),
        loop_sleep_seconds=float(os.getenv("SENTINEL_LOOP_SLEEP", "60")),
        alpaca_api_key=os.getenv("APCA_API_KEY_ID", ""),
        alpaca_secret_key=os.getenv("APCA_API_SECRET_KEY", ""),
        alpaca_base_url=os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets"),
    )
