"""
Sentinel X v0.1 — Online learning.
Adjust signal threshold and position multiplier; configurable learning rate; bounded; update after each trade close.
"""
from typing import Optional

from sentinel_x_v01.config import get_config


class Learner:
    def __init__(self):
        cfg = get_config()
        self._lr = cfg.learning_rate
        self._threshold = 0.5
        self._multiplier = 1.0
        self._t_min = cfg.signal_threshold_min
        self._t_max = cfg.signal_threshold_max
        self._m_min = cfg.position_multiplier_min
        self._m_max = cfg.position_multiplier_max

    @property
    def signal_threshold(self) -> float:
        return self._threshold

    @property
    def position_multiplier(self) -> float:
        return self._multiplier

    def update_after_trade(self, realized_pnl: float, signal: int, confidence: float) -> None:
        """
        Update threshold and multiplier after a trade close.
        Positive PnL -> slightly relax threshold / keep multiplier; negative -> tighten threshold, reduce multiplier.
        """
        if realized_pnl > 0:
            self._threshold = max(self._t_min, min(self._t_max, self._threshold - self._lr * 0.1))
            self._multiplier = max(self._m_min, min(self._m_max, self._multiplier + self._lr * 0.05))
        else:
            self._threshold = max(self._t_min, min(self._t_max, self._threshold + self._lr * 0.2))
            self._multiplier = max(self._m_min, min(self._m_max, self._multiplier - self._lr * 0.1))

    def state(self) -> dict:
        return {
            "signal_threshold": round(self._threshold, 6),
            "position_multiplier": round(self._multiplier, 6),
            "learning_rate": self._lr,
        }


_learner: Optional["Learner"] = None


def get_learner() -> "Learner":
    global _learner
    if _learner is None:
        _learner = Learner()
    return _learner
