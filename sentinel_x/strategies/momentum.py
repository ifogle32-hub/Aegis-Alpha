"""Momentum strategy using EMA crossover.

Safe v1 implementation:
- Implements BaseStrategy.on_tick
- Returns None unless a valid crossover signal is detected
- Does NOT place orders if market data is insufficient
"""

from typing import Optional, Dict, Any
import pandas as pd

from sentinel_x.strategies.base import BaseStrategy
from sentinel_x.monitoring.logger import logger


class MomentumStrategy(BaseStrategy):
    name = "MomentumStrategy"

    def __init__(self, fast_ema: int = 12, slow_ema: int = 26):
        super().__init__()
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema

    def on_tick(self, market_data) -> Optional[Dict[str, Any]]:
        """
        Called by the engine on every trading tick.
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
            df = None
            if hasattr(market_data, "data") and isinstance(market_data.data, dict):
                df = market_data.data.get(symbol)
            elif hasattr(market_data, "fetch_history"):
                df = market_data.fetch_history(symbol, lookback=self.slow_ema + 10)

            if df is None or not isinstance(df, pd.DataFrame) or len(df) < self.slow_ema + 2:
                return None

            signal = self._generate_signal(df)

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
            logger.error(f"MomentumStrategy.on_tick failed: {e}", exc_info=True)
            return None

    def _generate_signal(self, df: pd.DataFrame) -> int:
        """
        EMA crossover signal:
        +1 = bullish crossover
        -1 = bearish crossover
         0 = no signal
        """
        close = df["close"]

        fast = close.ewm(span=self.fast_ema, adjust=False).mean()
        slow = close.ewm(span=self.slow_ema, adjust=False).mean()

        if fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]:
            logger.debug("Momentum bullish crossover")
            return 1

        if fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]:
            logger.debug("Momentum bearish crossover")
            return -1

        return 0
