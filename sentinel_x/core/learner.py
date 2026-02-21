"""
Adaptive learner for Shadow v0.1.
Adjusts signal_threshold and position_multiplier; bounded; update after each trade close.
SHADOW MODE ONLY.
"""
import os
from typing import Optional

from sentinel_x.monitoring.logger import logger

# Bounds and learning rate (env overrides)
LEARNING_RATE = float(os.getenv("SENTINEL_ADAPTIVE_LEARNING_RATE", "0.01"))
THRESHOLD_MIN = float(os.getenv("SENTINEL_ADAPTIVE_THRESHOLD_MIN", "0.0"))
THRESHOLD_MAX = float(os.getenv("SENTINEL_ADAPTIVE_THRESHOLD_MAX", "1.0"))
MULTIPLIER_MIN = float(os.getenv("SENTINEL_ADAPTIVE_MULTIPLIER_MIN", "0.5"))
MULTIPLIER_MAX = float(os.getenv("SENTINEL_ADAPTIVE_MULTIPLIER_MAX", "1.5"))

_learner: Optional["AdaptiveLearner"] = None


class AdaptiveLearner:
    def __init__(self):
        self._threshold = 0.5
        self._multiplier = 1.0

    @property
    def signal_threshold(self) -> float:
        return self._threshold

    @property
    def position_multiplier(self) -> float:
        return self._multiplier

    def update_after_trade(self, realized_pnl: float, signal: int, confidence: float) -> None:
        if realized_pnl > 0:
            self._threshold = max(THRESHOLD_MIN, min(THRESHOLD_MAX, self._threshold - LEARNING_RATE * 0.1))
            self._multiplier = max(MULTIPLIER_MIN, min(MULTIPLIER_MAX, self._multiplier + LEARNING_RATE * 0.05))
        else:
            self._threshold = max(THRESHOLD_MIN, min(THRESHOLD_MAX, self._threshold + LEARNING_RATE * 0.2))
            self._multiplier = max(MULTIPLIER_MIN, min(MULTIPLIER_MAX, self._multiplier - LEARNING_RATE * 0.1))

    def state(self) -> dict:
        return {
            "signal_threshold": round(self._threshold, 6),
            "position_multiplier": round(self._multiplier, 6),
            "learning_rate": LEARNING_RATE,
        }


def get_adaptive_learner() -> AdaptiveLearner:
    global _learner
    if _learner is None:
        _learner = AdaptiveLearner()
    return _learner
