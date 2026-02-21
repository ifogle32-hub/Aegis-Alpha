"""
Sentinel X v0.1 — Adaptive momentum strategy.
Momentum window, volatility normalization, signal (-1, 0, 1), confidence score.
"""
from typing import List, Tuple

from sentinel_x_v01.config import get_config


def _volatility(closes: List[float], lookback: int) -> float:
    if len(closes) < 2 or lookback < 2:
        return 1.0
    use = closes[-lookback:]
    mean = sum(use) / len(use)
    var = sum((x - mean) ** 2 for x in use) / len(use)
    return max(var ** 0.5, 1e-8)


def _momentum(closes: List[float], window: int) -> float:
    if len(closes) < window or window < 1:
        return 0.0
    return closes[-1] - closes[-window - 1]


def compute_signal(
    closes: List[float],
    momentum_window: int,
    vol_lookback: int,
    threshold: float,
) -> Tuple[int, float]:
    """
    Returns (signal, confidence).
    signal: -1 (short), 0 (flat), 1 (long).
    confidence: 0..1 absolute strength.
    """
    if not closes or len(closes) < max(momentum_window, vol_lookback) + 1:
        return 0, 0.0
    mom = _momentum(closes, momentum_window)
    vol = _volatility(closes, vol_lookback)
    if vol <= 0:
        return 0, 0.0
    normalized = mom / vol
    # Clamp to roughly [-3, 3] then map to confidence
    raw = max(-3.0, min(3.0, normalized))
    confidence = abs(raw) / 3.0
    if raw >= threshold:
        return 1, confidence
    if raw <= -threshold:
        return -1, confidence
    return 0, confidence
