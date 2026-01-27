"""
Configuration management for Sentinel X.

SAFETY LOCK — DO NOT AUTO-ARM BROKERS
LIVE TRADING MUST REQUIRE HUMAN INTENT

PHASE 4: Hard LIVE trading guard requires ALL conditions:
- engine_mode == LIVE
- ENV: SENTINEL_LIVE_UNLOCK=true
- ENV: SENTINEL_LIVE_CONFIRM=YES_I_UNDERSTAND
- ENV: SENTINEL_LIVE_ACCOUNT_ID present

If ANY missing: FORCE engine_mode = RESEARCH
"""
import os
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)
load_dotenv()



@dataclass
class Config:
    """Configuration for Sentinel X."""
    
    # Symbols
    symbols: List[str]
    
    # Timeframes (in minutes)
    timeframes: List[int]
    
    # Risk limits
    max_position_size: float = 0.1  # 10% of portfolio per position
    max_daily_loss: float = 0.05  # 5% daily loss limit
    
    # Trading mode
    trade_mode: str = "TRAINING"  # TRAINING (Alpaca PAPER) or LIVE (Tradovate)
    engine_mode: str = "TRAINING"  # Engine mode (RESEARCH, TRAINING, PAPER, LIVE)
    
    # Scheduler settings
    training_window_start: int = 0  # Hour of day (0-23)
    training_window_end: int = 6  # Hour of day (0-23)
    trading_window_start: int = 9  # Hour of day (0-23)
    trading_window_end: int = 16  # Hour of day (0-23)
    
    # Engine settings
    heartbeat_interval: float = 1.0  # seconds
    loop_sleep: float = 0.1  # seconds between checks
    
    # Paper trading settings
    initial_capital: float = 100000.0  # $100k paper capital
    
    # Alpaca settings
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    
    # Position limits
    max_position_per_symbol: float = 0.1  # 10% of portfolio per symbol
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables with defaults."""
        
        # Symbols: comma-separated list
        symbols_str = os.getenv("SYMBOLS", "AAPL,TSLA,BTC-USD,ETH-USD")
        symbols = [s.strip().upper() for s in symbols_str.split(",")]
        
        # Timeframes: comma-separated list of minutes
        timeframes_str = os.getenv("TIMEFRAMES", "15,60,240")
        timeframes = [int(t.strip()) for t in timeframes_str.split(",")]
        
        # Risk limits
        max_position_size = float(os.getenv("MAX_POSITION_SIZE", "0.1"))
        max_daily_loss = float(os.getenv("MAX_DAILY_LOSS", "0.05"))
        
        # PHASE 3: Default to TRAINING mode (PAPER is normalized to TRAINING)
        trade_mode_env = os.getenv("TRADE_MODE", "TRAINING").upper()
        # Normalize PAPER to TRAINING
        if trade_mode_env == "PAPER":
            trade_mode_env = "TRAINING"
        trade_mode = trade_mode_env
        
        # Scheduler windows (hours 0-23)
        training_window_start = int(os.getenv("TRAINING_WINDOW_START", "0"))
        training_window_end = int(os.getenv("TRAINING_WINDOW_END", "6"))
        trading_window_start = int(os.getenv("TRADING_WINDOW_START", "9"))
        trading_window_end = int(os.getenv("TRADING_WINDOW_END", "16"))
        
        # Engine settings
        heartbeat_interval = float(os.getenv("HEARTBEAT_INTERVAL", "1.0"))
        loop_sleep = float(os.getenv("LOOP_SLEEP", "0.1"))
        
        # Paper capital
        initial_capital = float(os.getenv("INITIAL_CAPITAL", "100000.0"))
        
        # Alpaca credentials
        alpaca_api_key = os.getenv("ALPACA_API_KEY", "")
        alpaca_secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        alpaca_base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        
        # Position limits
        max_position_per_symbol = float(os.getenv("MAX_POSITION_PER_SYMBOL", "0.1"))
        
        # Create config instance
        config_instance = cls(
            symbols=symbols,
            timeframes=timeframes,
            max_position_size=max_position_size,
            max_daily_loss=max_daily_loss,
            trade_mode=trade_mode,
            training_window_start=training_window_start,
            training_window_end=training_window_end,
            trading_window_start=trading_window_start,
            trading_window_end=trading_window_end,
            heartbeat_interval=heartbeat_interval,
            loop_sleep=loop_sleep,
            initial_capital=initial_capital,
            alpaca_api_key=alpaca_api_key,
            alpaca_secret_key=alpaca_secret_key,
            alpaca_base_url=alpaca_base_url,
            max_position_per_symbol=max_position_per_symbol,
        )
        
        # Set engine_mode (will be validated in validate())
        engine_mode_env = os.getenv("ENGINE_MODE", "TRAINING").upper()
        # Normalize PAPER to TRAINING
        if engine_mode_env == "PAPER":
            engine_mode_env = "TRAINING"
        config_instance.engine_mode = engine_mode_env
        
        return config_instance
    
    def validate(self) -> None:
        """
        Validate configuration.
        
        PHASE 2: HARDENED - Never raises exceptions that prevent boot.
        Invalid values are coerced to safe defaults with warnings.
        """
        from sentinel_x.monitoring.logger import logger
        
        # Safe validation - never raise, always coerce
        if not self.symbols:
            logger.warning("No symbols configured - defaulting to SPY")
            self.symbols = ["SPY"]
        
        if not self.timeframes:
            logger.warning("No timeframes configured - defaulting to [15, 60]")
            self.timeframes = [15, 60]
        
        if self.max_position_size <= 0 or self.max_position_size > 1:
            logger.warning(f"Invalid max_position_size {self.max_position_size} - defaulting to 0.1")
            self.max_position_size = 0.1
        
        if self.max_daily_loss <= 0 or self.max_daily_loss > 1:
            logger.warning(f"Invalid max_daily_loss {self.max_daily_loss} - defaulting to 0.05")
            self.max_daily_loss = 0.05
        
        # PHASE 4: Tradovate LIVE hard lock - requires ALL conditions
        # === TRAINING BASELINE — DO NOT MODIFY ===
        # LIVE mode requires ALL:
        # - engine_mode == LIVE
        # - ENV SENTINEL_LIVE_UNLOCK=true
        # - ENV SENTINEL_LIVE_CONFIRM=YES_I_UNDERSTAND
        # - ENV SENTINEL_TRADOVATE_ACCOUNT_ID present
        # If ANY missing: FORCE engine_mode = TRAINING
        
        # Get engine mode from env or default to TRAINING
        engine_mode_env = os.getenv("ENGINE_MODE", "TRAINING").upper()
        
        # Normalize PAPER to TRAINING
        if engine_mode_env == "PAPER":
            engine_mode_env = "TRAINING"
        
        # Check if LIVE is requested
        if engine_mode_env == "LIVE":
            live_unlock = os.getenv("SENTINEL_LIVE_UNLOCK", "").lower() == "true"
            live_confirm = os.getenv("SENTINEL_LIVE_CONFIRM", "") == "YES_I_UNDERSTAND"
            tradovate_account_id = os.getenv("SENTINEL_TRADOVATE_ACCOUNT_ID", "")
            
            # Check if ALL conditions are met
            if not (live_unlock and live_confirm and tradovate_account_id):
                logger.critical(
                    f"LIVE trading requested but Tradovate unlock conditions not met - "
                    f"UNLOCK={live_unlock}, CONFIRM={bool(live_confirm)}, TRADOVATE_ACCOUNT_ID={bool(tradovate_account_id)}. "
                    f"Forcing engine_mode to TRAINING for safety."
                )
                self.engine_mode = "TRAINING"
            else:
                logger.critical(
                    f"Tradovate LIVE trading UNLOCKED - All conditions met. "
                    f"Tradovate Account ID: {tradovate_account_id[:8]}..."
                )
                self.engine_mode = "LIVE"
        else:
            self.engine_mode = engine_mode_env
        
        # PHASE 2: Coerce invalid trade_mode to TRAINING (safe default)
        if self.trade_mode not in ["PAPER", "TRAINING", "LIVE", "RESEARCH"]:
            logger.warning(f"Invalid trade_mode '{self.trade_mode}' - defaulting to TRAINING")
            self.trade_mode = "TRAINING"
        
        # Normalize PAPER to TRAINING
        if self.trade_mode == "PAPER":
            self.trade_mode = "TRAINING"
        
        # Sync trade_mode with engine_mode if needed
        if self.engine_mode in ["TRAINING", "PAPER", "LIVE"]:
            self.trade_mode = self.engine_mode
        
        # Validate time windows - coerce to safe defaults
        for hour_name, hour_value in [
            ("training_window_start", self.training_window_start),
            ("training_window_end", self.training_window_end),
            ("trading_window_start", self.trading_window_start),
            ("trading_window_end", self.trading_window_end)
        ]:
            if not 0 <= hour_value <= 23:
                logger.warning(f"Invalid {hour_name} {hour_value} - defaulting to 9")
                setattr(self, hour_name, 9)


# Global config instance
_config = None


def get_config() -> Config:
    """
    Get global configuration instance.
    
    PHASE 2: HARDENED - Never fails, always returns valid config.
    """
    global _config
    if _config is None:
        try:
            _config = Config.from_env()
        except Exception as e:
            from sentinel_x.monitoring.logger import logger
            logger.error(f"Config.from_env() failed: {e}, using minimal defaults", exc_info=True)
            # Use minimal safe defaults
            _config = Config(
                symbols=["SPY"],
                timeframes=[15, 60],
                trade_mode="RESEARCH"
            )
        
        # PHASE 2: Validate never raises - only coerces
        try:
            _config.validate()
        except Exception as e:
            from sentinel_x.monitoring.logger import logger
            logger.error(f"Config validation failed: {e}, using minimal defaults", exc_info=True)
            # Fallback to minimal config if validation somehow fails
            if _config is None:
                _config = Config(
                    symbols=["SPY"],
                    timeframes=[15, 60],
                    trade_mode="RESEARCH"
                )
    
    return _config

