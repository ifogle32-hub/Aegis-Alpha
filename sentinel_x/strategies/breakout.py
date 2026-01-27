"""Breakout strategy using Donchian channels."""
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from sentinel_x.strategies.base import BaseStrategy
from sentinel_x.monitoring.logger import logger


class BreakoutStrategy(BaseStrategy):
    """Breakout strategy using Donchian channel breakout."""
    
    name = "BreakoutStrategy"
    
    def __init__(self, parameters: dict = None):
        """Initialize breakout strategy."""
        super().__init__()
        params = parameters or {}
        self.parameters = {
            "channel_period": 20,
            "breakout_threshold": 0.01,  # 1% above/below channel
            "max_position_pct": 0.1
        }
        self.parameters.update(params)
    
    def on_tick(self, market_data) -> Optional[Dict[str, Any]]:
        """
        Called by engine on every trading tick.
        Returns order dict or None.
        Never throws.
        """
        try:
            if not market_data:
                return None
            
            # Safe symbol extraction
            symbol = None
            if hasattr(market_data, "symbols") and market_data.symbols and len(market_data.symbols) > 0:
                symbol = market_data.symbols[0]
            elif hasattr(market_data, "symbol") and market_data.symbol:
                symbol = market_data.symbol
            
            if not symbol:
                return None
            
            # Safe data extraction
            data = None
            if hasattr(market_data, "data") and isinstance(market_data.data, dict):
                data = market_data.data.get(symbol)
            elif hasattr(market_data, "fetch_history"):
                period = self.parameters["channel_period"]
                data = market_data.fetch_history(symbol, lookback=period + 10)
            
            if data is None or not isinstance(data, pd.DataFrame) or len(data) < self.parameters["channel_period"]:
                return None
            
            signal = self._generate_signal(data)
            
            if signal == 0:
                return None
            
            side = "buy" if signal > 0 else "sell"
            
            return {
                "symbol": symbol,
                "side": side,
                "qty": 1,
                "price": None,  # market order
                "strategy": self.name,
            }
        
        except Exception as e:
            logger.error(f"BreakoutStrategy.on_tick failed: {e}", exc_info=True)
            return None
    
    def _generate_signal(self, data: pd.DataFrame) -> int:
        """
        Generate signal based on Donchian channel breakout.
        
        Signal logic:
        - Long (+1): Price breaks above upper channel
        - Short (-1): Price breaks below lower channel
        - Flat (0): Price within channel
        """
        try:
            period = self.parameters["channel_period"]
            threshold = self.parameters["breakout_threshold"]
            
            if len(data) < period:
                return 0
            
            close_prices = data['close'].values
            high_prices = data['high'].values
            low_prices = data['low'].values
            
            # Calculate Donchian channels
            recent_highs = high_prices[-period:]
            recent_lows = low_prices[-period:]
            
            upper_channel = np.max(recent_highs)
            lower_channel = np.min(recent_lows)
            
            current_price = close_prices[-1]
            
            # Check for breakout
            upper_threshold = upper_channel * (1 + threshold)
            lower_threshold = lower_channel * (1 - threshold)
            
            if current_price >= upper_threshold:
                # Breakout above upper channel
                logger.debug(f"Breakout: Price {current_price:.2f} broke above upper channel {upper_threshold:.2f}")
                return 1
            elif current_price <= lower_threshold:
                # Breakdown below lower channel
                logger.debug(f"Breakout: Price {current_price:.2f} broke below lower channel {lower_threshold:.2f}")
                return -1
            
            return 0
        except Exception as e:
            logger.error(f"BreakoutStrategy._generate_signal failed: {e}", exc_info=True)
            return 0

