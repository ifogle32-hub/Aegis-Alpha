# sentinel_x/strategies/test_strategy.py

from typing import Optional, Dict, Any
from sentinel_x.strategies.base import BaseStrategy


class TestStrategy(BaseStrategy):
    name = "TestStrategy"

    def __init__(self):
        super().__init__()
        self._fired = False

    def on_tick(self, market_data) -> Optional[Dict[str, Any]]:
        """
        Fire exactly once, then self-disable.
        Returns order dict or None.
        Never throws.
        """
        try:
            if self._fired or not self.enabled:
                return None

            self._fired = True
            self.enabled = False

            # Safe symbol extraction
            symbol = "AAPL"  # Default
            if hasattr(market_data, "symbols"):
                if market_data.symbols and len(market_data.symbols) > 0:
                    symbol = market_data.symbols[0]
                elif isinstance(market_data.symbols, list) and len(market_data.symbols) == 0:
                    symbol = "AAPL"
            elif hasattr(market_data, "symbol") and market_data.symbol:
                symbol = market_data.symbol

            return {
                "symbol": symbol,
                "side": "buy",
                "qty": 1,
                "price": None,  # market order
                "strategy": self.name,
            }
        except Exception:
            # Never throw - return None on any error
            return None