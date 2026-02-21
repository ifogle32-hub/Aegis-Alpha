"""
Sentinel X v0.1 — Engine loop.
Process all timeframes sequentially; update heartbeat; log events; sleep 60s; never crash silently.
"""
import json
import time
from pathlib import Path

from sentinel_x_v01.config import get_config
from sentinel_x_v01.data import get_latest_bars
from sentinel_x_v01.strategy import compute_signal
from sentinel_x_v01.executor import get_executor
from sentinel_x_v01.learner import get_learner
from sentinel_x_v01.logger import log_event, log_error, log_info


def write_heartbeat(heartbeat_path: str) -> None:
    payload = {
        "ts": time.time(),
        "status": "running",
    }
    try:
        p = Path(heartbeat_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as e:
        log_error("heartbeat_write_failed", error=str(e))


def write_state_file(state_path: str, executor, learner, cfg) -> None:
    """Write engine state for monitor API (separate process)."""
    try:
        p = Path(state_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "capital": executor.capital,
            "position": executor.position,
            "entry_price": executor.entry_price,
            "realized_pnl": executor.realized_pnl,
            "unrealized_pnl": executor.unrealized_pnl,
            "symbol": cfg.symbol,
            "signal_threshold": learner.signal_threshold,
            "position_multiplier": learner.position_multiplier,
        }
        p.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as e:
        log_error("state_write_failed", error=str(e))


def run_loop() -> None:
    cfg = get_config()
    executor = get_executor()
    learner = get_learner()
    symbol = cfg.symbol
    timeframes = cfg.timeframes
    heartbeat_path = cfg.heartbeat_path
    sleep_s = cfg.loop_sleep_seconds

    state_path = cfg.state_path
    log_info("engine_start", symbol=symbol, timeframes=timeframes)

    while True:
        try:
            last_close = None
            for tf in timeframes:
                bars = get_latest_bars(symbol, tf, count=cfg.momentum_window + cfg.vol_lookback + 5)
                if not bars:
                    continue
                closes = [b["close"] for b in bars]
                last_close = closes[-1] if closes else last_close
                threshold = learner.signal_threshold
                multiplier = learner.position_multiplier
                signal, confidence = compute_signal(
                    closes,
                    cfg.momentum_window,
                    cfg.vol_lookback,
                    threshold,
                )
                executor.set_mark(last_close)
                realized = executor.execute_shadow(signal, last_close, multiplier)
                if realized is not None:
                    learner.update_after_trade(realized, signal, confidence)
                log_event(
                    "tick",
                    timeframe=tf,
                    signal=signal,
                    confidence=confidence,
                    pnl=executor.realized_pnl,
                    capital=executor.capital,
                    threshold=threshold,
                    multiplier=multiplier,
                )
            write_heartbeat(heartbeat_path)
            write_state_file(state_path, executor, learner, cfg)
        except KeyboardInterrupt:
            log_info("engine_stop", reason="keyboard")
            break
        except Exception as e:
            log_error("loop_error", error=str(e))
            write_heartbeat(heartbeat_path)
        time.sleep(sleep_s)


if __name__ == "__main__":
    run_loop()
