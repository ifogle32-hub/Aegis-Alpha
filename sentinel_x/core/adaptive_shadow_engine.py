"""
Adaptive Shadow Engine v0.1 — internal loop.
Runs when shadow mode is enabled; updates shared shadow registry; NVDA, 10% capital, adaptive.
SHADOW MODE ONLY. No execution. No new FastAPI instance.
"""
import os
import threading
import time
from typing import List

from sentinel_x.monitoring.logger import logger
from sentinel_x.core.shadow_registry import get_shadow_controller
from sentinel_x.core.strategy import compute_signal
from sentinel_x.core.learner import get_adaptive_learner
from sentinel_x.core.executor import get_shadow_capital_executor

SYMBOL = os.getenv("SENTINEL_ADAPTIVE_SYMBOL", "NVDA")
MOMENTUM_WINDOW = int(os.getenv("SENTINEL_ADAPTIVE_MOMENTUM_WINDOW", "20"))
VOL_LOOKBACK = int(os.getenv("SENTINEL_ADAPTIVE_VOL_LOOKBACK", "20"))
LOOP_SLEEP = float(os.getenv("SENTINEL_ADAPTIVE_LOOP_SLEEP", "60.0"))

_engine_thread: threading.Thread | None = None
_engine_stop = threading.Event()
_adaptive_market_data = None


def _get_closes(symbol: str, lookback: int) -> List[float]:
    """Fetch close prices for symbol. Uses dedicated market data for NVDA (no global dependency)."""
    global _adaptive_market_data
    try:
        from sentinel_x.data.market_data import MarketData
        if _adaptive_market_data is None:
            _adaptive_market_data = MarketData([symbol], seed=42)
        df = _adaptive_market_data.fetch_history(symbol, lookback=lookback)
        if df is not None and "close" in df.columns:
            return df["close"].astype(float).tolist()
        _adaptive_market_data.fetch_latest(symbol)
    except Exception as e:
        logger.debug("Adaptive engine get_closes: %s", e)
    return []


def _run_loop_once() -> None:
    """Single iteration: get bars, strategy, executor, learner, update registry."""
    controller = get_shadow_controller()
    if not controller.is_enabled():
        return
    executor = get_shadow_capital_executor()
    learner = get_adaptive_learner()
    lookback = MOMENTUM_WINDOW + VOL_LOOKBACK + 5
    closes = _get_closes(SYMBOL, lookback)
    if not closes:
        return
    last_close = closes[-1]
    threshold = learner.signal_threshold
    multiplier = learner.position_multiplier
    signal, confidence = compute_signal(closes, MOMENTUM_WINDOW, VOL_LOOKBACK, threshold)
    executor.set_mark(last_close)
    realized = executor.execute_shadow(signal, last_close, multiplier)
    if realized is not None:
        learner.update_after_trade(realized, signal, confidence)
    # Update shared state for /shadow/status
    controller.update_adaptive_metrics({
        "symbol": SYMBOL,
        "capital": executor.capital,
        "position": executor.position,
        "entry_price": executor.entry_price,
        "realized_pnl": executor.realized_pnl,
        "unrealized_pnl": executor.unrealized_pnl,
        "signal_threshold": learner.signal_threshold,
        "position_multiplier": learner.position_multiplier,
        "last_signal": signal,
        "last_confidence": confidence,
    })
    controller.update_trading_window("OPEN")
    logger.info(
        "ADAPTIVE_SHADOW_TICK | symbol=%s | signal=%s | confidence=%.4f | capital=%.2f | pnl=%.2f | threshold=%.4f | multiplier=%.4f",
        SYMBOL, signal, confidence, executor.capital, executor.realized_pnl, threshold, multiplier,
    )


def _engine_loop() -> None:
    """Daemon loop: only run when shadow enabled, never crash silently."""
    logger.info("Adaptive shadow engine thread started")
    while not _engine_stop.is_set():
        try:
            _run_loop_once()
        except Exception as e:
            logger.exception("Adaptive shadow loop error: %s", e)
        _engine_stop.wait(timeout=LOOP_SLEEP)


def start_adaptive_shadow_engine() -> None:
    """Start the adaptive shadow engine in a daemon thread. Idempotent."""
    global _engine_thread
    if _engine_thread is not None and _engine_thread.is_alive():
        return
    _engine_stop.clear()
    _engine_thread = threading.Thread(target=_engine_loop, daemon=True, name="adaptive_shadow_engine")
    _engine_thread.start()
    logger.info("Adaptive shadow engine started (daemon thread)")


def stop_adaptive_shadow_engine() -> None:
    """Signal the engine thread to stop."""
    _engine_stop.set()
