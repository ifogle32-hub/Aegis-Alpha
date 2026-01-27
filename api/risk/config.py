"""
Risk Configuration

PHASE 5 — CONFIGURATION & GOVERNANCE

Risk configuration with all thresholds and rules.
Read-only in this phase.
"""

import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class TradingWindow(Enum):
    """Trading window definition"""
    MARKET_HOURS = "market_hours"  # 9:30 AM - 4:00 PM ET
    EXTENDED_HOURS = "extended_hours"  # 4:00 AM - 8:00 PM ET
    ALWAYS = "always"  # 24/7


@dataclass
class RiskConfig:
    """
    PHASE 5 — RISK CONFIGURATION
    
    Risk configuration with all thresholds and rules.
    """
    # PHASE 2: Core risk rules
    
    # Position size limits
    max_position_size_per_symbol: float = 1000.0  # Max shares per symbol
    max_position_value_per_symbol: float = 50000.0  # Max notional value per symbol
    
    # Notional value limits
    max_notional_per_order: float = 10000.0  # Max notional value per order
    
    # Daily loss limit
    daily_loss_limit: float = -5000.0  # Daily P&L threshold (negative = loss)
    
    # Position count limits
    max_open_positions: int = 10  # Max concurrent positions
    
    # Symbol allowlist
    allowed_symbols: List[str] = field(default_factory=lambda: ["SPY", "QQQ", "IWM", "DIA"])
    
    # Trading window
    trading_window: TradingWindow = TradingWindow.MARKET_HOURS
    
    # Configuration metadata
    config_version: str = "1.0.0"
    last_updated: float = field(default_factory=time.time)
    updated_by: str = "system"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dict for API responses"""
        return {
            "max_position_size_per_symbol": self.max_position_size_per_symbol,
            "max_position_value_per_symbol": self.max_position_value_per_symbol,
            "max_notional_per_order": self.max_notional_per_order,
            "daily_loss_limit": self.daily_loss_limit,
            "max_open_positions": self.max_open_positions,
            "allowed_symbols": self.allowed_symbols,
            "trading_window": self.trading_window.value,
            "config_version": self.config_version,
            "last_updated": self.last_updated,
            "updated_by": self.updated_by,
        }


# Global risk config instance
_risk_config: Optional[RiskConfig] = None


def get_risk_config() -> RiskConfig:
    """Get global risk config instance"""
    global _risk_config
    if _risk_config is None:
        _risk_config = RiskConfig()
    return _risk_config
