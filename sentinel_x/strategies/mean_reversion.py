"""Mean reversion strategy using Z-score."""
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from sentinel_x.strategies.base import BaseStrategy
from sentinel_x.monitoring.logger import logger


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion strategy using Z-score."""
    
    name = "MeanReversionStrategy"
    
    def __init__(self, parameters: dict = None):
        """Initialize mean reversion strategy."""
        super().__init__()
        params = parameters or {}
        self.parameters = {
            "lookback": 20,
            "entry_z": 2.0,  # Enter when Z-score exceeds this
            "exit_z": 0.5,   # Exit when Z-score returns to this
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
                data = market_data.fetch_history(symbol, lookback=self.parameters["lookback"] + 10)
            
            if data is None or not isinstance(data, pd.DataFrame) or len(data) < self.parameters["lookback"]:
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
            logger.error(f"MeanReversionStrategy.on_tick failed: {e}", exc_info=True)
            return None
    
    def _generate_signal(self, data: pd.DataFrame) -> int:
        """
        Generate signal based on Z-score mean reversion.
        
        Signal logic:
        - Long (+1): Price significantly below mean (negative Z-score)
        - Short (-1): Price significantly above mean (positive Z-score)
        - Flat (0): Price near mean
        """
        try:
            lookback = self.parameters["lookback"]
            entry_z = self.parameters["entry_z"]
            
            if len(data) < lookback:
                return 0
            
            close_prices = data['close'].values[-lookback:]
            current_price = close_prices[-1]
            
            # Calculate mean and standard deviation
            mean = np.mean(close_prices)
            std = np.std(close_prices)
            
            if std == 0:
                return 0
            
            # Calculate Z-score
            z_score = (current_price - mean) / std
            
            # Generate signal
            if z_score <= -entry_z:
                # Price significantly below mean - buy (revert to mean)
                logger.debug(f"MeanReversion: Z-score {z_score:.2f}, entering long")
                return 1
            elif z_score >= entry_z:
                # Price significantly above mean - sell (revert to mean)
                logger.debug(f"MeanReversion: Z-score {z_score:.2f}, entering short")
                return -1
            
            return 0
        except Exception as e:
            logger.error(f"MeanReversionStrategy._generate_signal failed: {e}", exc_info=True)
            return 0

