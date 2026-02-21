"""
Sentinel X v0.1 — Shadow execution only.
10% capital per trade; track capital, position, entry_price, realized PnL, unrealized PnL.
No real orders.
"""
from typing import Optional

from sentinel_x_v01.config import get_config


class ShadowExecutor:
    def __init__(self):
        cfg = get_config()
        self._capital = cfg.initial_capital
        self._position = 0.0
        self._entry_price: Optional[float] = None
        self._realized_pnl = 0.0
        self._capital_pct = cfg.capital_pct_per_trade
        self._mark: Optional[float] = None

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

    @property
    def unrealized_pnl(self) -> float:
        if self._mark is not None:
            return self.unrealized_pnl_at(self._mark)
        return 0.0

    def set_mark(self, price: float) -> None:
        """Set current mark for unrealized PnL (optional)."""
        self._mark = price

    def unrealized_pnl_at(self, mark_price: float) -> float:
        if self._position == 0 or self._entry_price is None:
            return 0.0
        return (mark_price - self._entry_price) * self._position

    def execute_shadow(self, signal: int, price: float, multiplier: float = 1.0) -> Optional[float]:
        """
        Apply shadow trade: 10% of capital per side.
        signal: -1 (sell), 0 (no trade), 1 (buy).
        Returns realized PnL if position was closed, else None.
        """
        if signal == 0:
            return None
        trade_capital = self._capital * self._capital_pct * multiplier
        size = trade_capital / price if price > 0 else 0.0
        if size <= 0:
            return None
        realized = None
        if signal == 1:
            if self._position <= 0:
                self._position = size
                self._entry_price = price
            else:
                self._position += size
                self._entry_price = (self._entry_price * (self._position - size) + price * size) / self._position
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
        }


# Singleton for monitor and main
_executor: Optional[ShadowExecutor] = None


def get_executor() -> ShadowExecutor:
    global _executor
    if _executor is None:
        _executor = ShadowExecutor()
    return _executor
