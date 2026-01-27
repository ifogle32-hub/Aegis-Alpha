"""
PHASE 1: Strategy Config & Genome Model

Strategy configuration dataclass with validation.
Allows config-driven strategy representation without executable logic.

SAFETY: StrategyConfig contains NO executable logic
SAFETY: No callables, no lambdas, no executable code
SAFETY: All values validated
SAFETY: Hard max risk enforced
SAFETY: Invalid configs rejected

# ============================================================
# REGRESSION LOCK — STRATEGY CONFIG
# ============================================================
# StrategyConfig is the ONLY config representation
# 
# NO future changes may:
#   • Add executable code to config
#   • Allow callables in config
#   • Allow lambdas in config
#   • Remove validation
#   • Bypass risk limits
# 
# SAFETY: training-only
# SAFETY: no execution behavior modified
# REGRESSION LOCK — GOVERNANCE LAYER
# ============================================================
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime


class StrategyLifecycleState(Enum):
    """
    PHASE 4: Strategy lifecycle states.
    
    TRAINING: Active training mode (only active state)
    SHADOW: Future-locked placeholder (informational only)
    APPROVED: Future-locked placeholder (informational only)
    DISABLED: Strategy disabled (visible but inactive)
    """
    TRAINING = "TRAINING"
    SHADOW = "SHADOW"  # Future-locked - placeholder only
    APPROVED = "APPROVED"  # Future-locked - placeholder only
    DISABLED = "DISABLED"


# SAFETY: Allowed strategy types (no eval/exec)
ALLOWED_STRATEGY_TYPES = {
    "momentum",
    "mean_reversion",
    "breakout",
    "test"
}

# SAFETY: Allowed timeframes (minutes)
ALLOWED_TIMEFRAMES = {
    1, 5, 15, 30, 60, 240, 1440  # 1m, 5m, 15m, 30m, 1h, 4h, 1d
}

# SAFETY: Hard risk limits
MAX_POSITION_SIZE = 0.1  # 10% max position
MAX_DAILY_LOSS = 0.05  # 5% max daily loss
MAX_STOP_ATR = 5.0  # Max stop loss ATR multiple
MAX_TAKE_PROFIT_ATR = 10.0  # Max take profit ATR multiple


@dataclass
class RiskLimits:
    """Risk limits for a strategy."""
    max_position_size: float = 0.1  # Max position as fraction of capital (0.1 = 10%)
    max_daily_loss: float = 0.05  # Max daily loss as fraction (0.05 = 5%)
    max_trades_per_day: int = 10  # Max trades per day
    
    def validate(self) -> None:
        """Validate risk limits."""
        if self.max_position_size <= 0 or self.max_position_size > MAX_POSITION_SIZE:
            raise ValueError(
                f"max_position_size must be in (0, {MAX_POSITION_SIZE}], got {self.max_position_size}"
            )
        if self.max_daily_loss <= 0 or self.max_daily_loss > MAX_DAILY_LOSS:
            raise ValueError(
                f"max_daily_loss must be in (0, {MAX_DAILY_LOSS}], got {self.max_daily_loss}"
            )
        if self.max_trades_per_day <= 0:
            raise ValueError(f"max_trades_per_day must be > 0, got {self.max_trades_per_day}")


@dataclass
class StrategyConfig:
    """
    PHASE 1: Strategy configuration dataclass.
    
    Config-driven strategy representation with validation.
    No executable logic in config - all values validated.
    Hard max risk enforced - invalid configs rejected.
    
    SAFETY: StrategyConfig contains NO executable logic
    SAFETY: No callables, no lambdas, no executable code
    
    Fields (minimum required):
    - strategy_type: Allowed strategy type (momentum, mean_reversion, breakout, test)
    - timeframe: Timeframe as string or int in minutes (must be in ALLOWED_TIMEFRAMES)
    - lookback: Lookback period (must be > 0)
    - entry_params: Entry parameters dict (validated per strategy type)
    - exit_params: Exit parameters dict (validated per strategy type)
    - stop_atr: Stop loss ATR multiple (must be in (0, MAX_STOP_ATR])
    - take_profit_atr: Take profit ATR multiple (must be in (0, MAX_TAKE_PROFIT_ATR])
    - session: Trading session (e.g., "RTH", "ETH", "ALL")
    - max_trades_per_day: Maximum trades per day (must be > 0)
    - risk_per_trade: Risk per trade as fraction of capital (must be in (0, MAX_POSITION_SIZE])
    """
    strategy_type: str
    timeframe: Any  # Can be int or str, validated as int
    lookback: int
    entry_params: Dict[str, Any] = field(default_factory=dict)
    exit_params: Dict[str, Any] = field(default_factory=dict)
    stop_atr: float = 2.0
    take_profit_atr: float = 4.0
    session: str = "RTH"  # Regular trading hours
    max_trades_per_day: int = 10
    risk_per_trade: float = 0.01  # 1% risk per trade
    # Keep risk_limits for backward compatibility
    risk_limits: Optional[RiskLimits] = None
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        # Convert timeframe to int if string
        if isinstance(self.timeframe, str):
            try:
                self.timeframe = int(self.timeframe)
            except ValueError:
                raise ValueError(f"timeframe must be integer or numeric string, got {self.timeframe}")
        elif not isinstance(self.timeframe, int):
            raise ValueError(f"timeframe must be int, got {type(self.timeframe)}")
        
        # Backward compatibility: create risk_limits if not provided
        if self.risk_limits is None:
            self.risk_limits = RiskLimits(
                max_position_size=self.risk_per_trade,
                max_daily_loss=0.05,
                max_trades_per_day=self.max_trades_per_day
            )
        
        self.validate()
    
    def validate(self) -> None:
        """
        Validate strategy configuration.
        
        Rules:
        - strategy_type must be in ALLOWED_STRATEGY_TYPES
        - timeframe must be in ALLOWED_TIMEFRAMES
        - lookback must be > 0
        - stop_atr must be in (0, MAX_STOP_ATR]
        - take_profit_atr must be in (0, MAX_TAKE_PROFIT_ATR]
        - risk_limits must be valid
        - entry_params and exit_params validated per strategy type
        
        Raises:
            ValueError: If validation fails
        """
        # Validate strategy_type
        if self.strategy_type not in ALLOWED_STRATEGY_TYPES:
            raise ValueError(
                f"strategy_type must be in {ALLOWED_STRATEGY_TYPES}, got {self.strategy_type}"
            )
        
        # Validate timeframe (ensure it's int)
        if not isinstance(self.timeframe, int):
            raise ValueError(f"timeframe must be int after conversion, got {type(self.timeframe)}")
        
        if self.timeframe not in ALLOWED_TIMEFRAMES:
            raise ValueError(
                f"timeframe must be in {ALLOWED_TIMEFRAMES}, got {self.timeframe}"
            )
        
        # Validate lookback
        if self.lookback <= 0:
            raise ValueError(f"lookback must be > 0, got {self.lookback}")
        
        # Validate stop_atr
        if self.stop_atr <= 0 or self.stop_atr > MAX_STOP_ATR:
            raise ValueError(
                f"stop_atr must be in (0, {MAX_STOP_ATR}], got {self.stop_atr}"
            )
        
        # Validate take_profit_atr
        if self.take_profit_atr <= 0 or self.take_profit_atr > MAX_TAKE_PROFIT_ATR:
            raise ValueError(
                f"take_profit_atr must be in (0, {MAX_TAKE_PROFIT_ATR}], got {self.take_profit_atr}"
            )
        
        # Validate session
        if self.session not in ["RTH", "ETH", "ALL"]:
            raise ValueError(f"session must be in ['RTH', 'ETH', 'ALL'], got {self.session}")
        
        # Validate max_trades_per_day
        if self.max_trades_per_day <= 0:
            raise ValueError(f"max_trades_per_day must be > 0, got {self.max_trades_per_day}")
        if self.max_trades_per_day > 100:
            raise ValueError(f"max_trades_per_day must be <= 100, got {self.max_trades_per_day}")
        
        # Validate risk_per_trade
        if self.risk_per_trade <= 0 or self.risk_per_trade > MAX_POSITION_SIZE:
            raise ValueError(
                f"risk_per_trade must be in (0, {MAX_POSITION_SIZE}], got {self.risk_per_trade}"
            )
        
        # Validate risk_limits (if provided)
        if self.risk_limits:
            self.risk_limits.validate()
        
        # Validate strategy-specific parameters
        self._validate_strategy_params()
        
        # SAFETY: Validate no callables or lambdas in entry_params/exit_params
        self._validate_no_executables()
    
    def _validate_no_executables(self) -> None:
        """
        SAFETY: Validate no executable code in config.
        
        Rules:
        - No callables
        - No lambdas
        - No functions
        - No classes
        """
        import inspect
        import types
        
        for param_dict in [self.entry_params, self.exit_params]:
            for key, value in param_dict.items():
                if callable(value):
                    raise ValueError(
                        f"Config contains callable in {param_dict}: {key}={value}. "
                        f"SAFETY: No executable logic allowed in config."
                    )
                if inspect.isclass(value):
                    raise ValueError(
                        f"Config contains class in {param_dict}: {key}={value}. "
                        f"SAFETY: No classes allowed in config."
                    )
                if isinstance(value, types.LambdaType):
                    raise ValueError(
                        f"Config contains lambda in {param_dict}: {key}={value}. "
                        f"SAFETY: No lambdas allowed in config."
                    )
    
    def _validate_strategy_params(self) -> None:
        """
        Validate strategy-specific parameters.
        
        Rules per strategy type:
        - momentum: entry_params must have 'fast_ema' and 'slow_ema' (both > 0, fast < slow)
        - mean_reversion: entry_params must have 'entry_z' (must be > 0), exit_params must have 'exit_z' (must be >= 0)
        - breakout: entry_params must have 'channel_period' (must be > 0) and 'breakout_threshold' (must be in (0, 0.1])
        - test: no specific validation
        """
        if self.strategy_type == "momentum":
            if "fast_ema" not in self.entry_params or "slow_ema" not in self.entry_params:
                raise ValueError("momentum strategy requires 'fast_ema' and 'slow_ema' in entry_params")
            fast_ema = self.entry_params["fast_ema"]
            slow_ema = self.entry_params["slow_ema"]
            if not isinstance(fast_ema, (int, float)) or fast_ema <= 0:
                raise ValueError(f"fast_ema must be > 0, got {fast_ema}")
            if not isinstance(slow_ema, (int, float)) or slow_ema <= 0:
                raise ValueError(f"slow_ema must be > 0, got {slow_ema}")
            if fast_ema >= slow_ema:
                raise ValueError(f"fast_ema ({fast_ema}) must be < slow_ema ({slow_ema})")
        
        elif self.strategy_type == "mean_reversion":
            if "entry_z" not in self.entry_params:
                raise ValueError("mean_reversion strategy requires 'entry_z' in entry_params")
            entry_z = self.entry_params["entry_z"]
            if not isinstance(entry_z, (int, float)) or entry_z <= 0:
                raise ValueError(f"entry_z must be > 0, got {entry_z}")
            if "exit_z" in self.exit_params:
                exit_z = self.exit_params["exit_z"]
                if not isinstance(exit_z, (int, float)) or exit_z < 0:
                    raise ValueError(f"exit_z must be >= 0, got {exit_z}")
        
        elif self.strategy_type == "breakout":
            if "channel_period" not in self.entry_params:
                raise ValueError("breakout strategy requires 'channel_period' in entry_params")
            channel_period = self.entry_params["channel_period"]
            if not isinstance(channel_period, int) or channel_period <= 0:
                raise ValueError(f"channel_period must be > 0, got {channel_period}")
            if "breakout_threshold" not in self.entry_params:
                raise ValueError("breakout strategy requires 'breakout_threshold' in entry_params")
            breakout_threshold = self.entry_params["breakout_threshold"]
            if not isinstance(breakout_threshold, (int, float)) or breakout_threshold <= 0 or breakout_threshold > 0.1:
                raise ValueError(f"breakout_threshold must be in (0, 0.1], got {breakout_threshold}")
        
        # test strategy has no specific validation
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "strategy_type": self.strategy_type,
            "timeframe": self.timeframe,
            "lookback": self.lookback,
            "entry_params": self.entry_params,
            "exit_params": self.exit_params,
            "stop_atr": self.stop_atr,
            "take_profit_atr": self.take_profit_atr,
            "session": self.session,
            "max_trades_per_day": self.max_trades_per_day,
            "risk_per_trade": self.risk_per_trade,
            "risk_limits": {
                "max_position_size": self.risk_limits.max_position_size if self.risk_limits else self.risk_per_trade,
                "max_daily_loss": self.risk_limits.max_daily_loss if self.risk_limits else 0.05,
                "max_trades_per_day": self.risk_limits.max_trades_per_day if self.risk_limits else self.max_trades_per_day,
            } if self.risk_limits else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyConfig":
        """Create config from dictionary."""
        # Extract risk_limits if present (backward compatibility)
        risk_limits_data = data.pop("risk_limits", None)
        risk_limits = RiskLimits(**risk_limits_data) if risk_limits_data else None
        
        config = cls(
            strategy_type=data["strategy_type"],
            timeframe=data["timeframe"],
            lookback=data["lookback"],
            entry_params=data.get("entry_params", {}),
            exit_params=data.get("exit_params", {}),
            stop_atr=data.get("stop_atr", 2.0),
            take_profit_atr=data.get("take_profit_atr", 4.0),
            session=data.get("session", "RTH"),
            max_trades_per_day=data.get("max_trades_per_day", 10),
            risk_per_trade=data.get("risk_per_trade", 0.01),
            risk_limits=risk_limits
        )
        return config


@dataclass
class StrategyGenome:
    """
    PHASE 1: Strategy genome model.
    
    Encapsulates a strategy configuration with metadata.
    Used for strategy generation and variation.
    """
    config: StrategyConfig
    name: str  # Unique strategy name
    created_at: datetime = field(default_factory=datetime.utcnow)
    seed_name: Optional[str] = None  # Name of seed strategy if variant
    variant_id: Optional[str] = None  # Variant identifier
    lifecycle_state: StrategyLifecycleState = StrategyLifecycleState.TRAINING
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert genome to dictionary."""
        return {
            "config": self.config.to_dict(),
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "seed_name": self.seed_name,
            "variant_id": self.variant_id,
            "lifecycle_state": self.lifecycle_state.value
        }
