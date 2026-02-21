"""
Shadow-only executor for Adaptive Shadow v0.1.
10% capital per trade; tracks capital, position, entry_price, realized/unrealized PnL.
NVDA only. No real orders.
"""
import os
from typing import Optional

from sentinel_x.monitoring.logger import logger

try:
    from sentinel_x.core.config import get_config
    _config = get_config()
    INITIAL_CAPITAL = _config.initial_capital
    CAPITAL_PCT = getattr(_config, "max_position_size", 0.1)
except Exception:
    INITIAL_CAPITAL = float(os.getenv("SENTINEL_ADAPTIVE_INITIAL_CAPITAL", "100000"))
    CAPITAL_PCT = float(os.getenv("SENTINEL_ADAPTIVE_CAPITAL_PCT", "0.10"))

SYMBOL = os.getenv("SENTINEL_ADAPTIVE_SYMBOL", "NVDA")

_executor: Optional["ShadowCapitalExecutor"] = None


class ShadowCapitalExecutor:
    """Shadow-only: 10% capital per trade, no real orders."""

    def __init__(self):
        self._capital = INITIAL_CAPITAL
        self._position = 0.0
        self._entry_price: Optional[float] = None
        self._realized_pnl = 0.0
        self._mark: Optional[float] = None
        logger.info(
            "ShadowCapitalExecutor initialized | symbol=%s | capital=%.2f | capital_pct=%.2f",
            SYMBOL, self._capital, CAPITAL_PCT,
        )

    @property
    def capital(self) -> float:
        return self._capital

    @property
    def position(self) -> float:
        return self._position

    @property
    def entry_price(self) -> Optional[float]:
        return self._entry_price

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    def set_mark(self, price: float) -> None:
        self._mark = price

    def unrealized_pnl_at(self, mark_price: float) -> float:
        if self._position == 0 or self._entry_price is None:
            return 0.0
        return (mark_price - self._entry_price) * self._position

    @property
    def unrealized_pnl(self) -> float:
        if self._mark is not None:
            return self.unrealized_pnl_at(self._mark)
        return 0.0

    def execute_shadow(self, signal: int, price: float, multiplier: float = 1.0) -> Optional[float]:
        """Apply shadow trade. Returns realized PnL if position closed, else None."""
        if signal == 0 or price <= 0:
            return None
        trade_capital = self._capital * CAPITAL_PCT * multiplier
        size = trade_capital / price
        if size <= 0:
            return None
        realized = None
        if signal == 1:
            if self._position <= 0:
                self._position = size
                self._entry_price = price
            else:
                self._position += size
                self._entry_price = (
                    self._entry_price * (self._position - size) + price * size
                ) / self._position
        else:
            if self._position > 0:
                close_size = min(size, self._position)
                if self._entry_price is not None:
                    realized = (price - self._entry_price) * close_size
                    self._realized_pnl += realized
                    self._capital += realized
                self._position -= close_size
                if self._position <= 0:
                    self._entry_price = None
        return realized

    def state(self) -> dict:
        return {
            "capital": round(self._capital, 2),
            "position": round(self._position, 6),
            "entry_price": self._entry_price,
            "realized_pnl": round(self._realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "symbol": SYMBOL,
        }


def get_shadow_capital_executor() -> ShadowCapitalExecutor:
    global _executor
    if _executor is None:
        _executor = ShadowCapitalExecutor()
    return _executor
