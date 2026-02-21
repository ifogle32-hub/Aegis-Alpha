"""
Sentinel X v0.1 — JSON line logging.
Fields: timeframe, signal, confidence, pnl, capital, threshold, multiplier.
"""
import json
import sys
from datetime import datetime
from typing import Any, Optional


def _serialize(obj: Any) -> Any:
    if hasattr(obj, "__float__") and not isinstance(obj, bool):
        return float(obj)
    raise TypeError(type(obj).__name__)


def log_event(
    event: str,
    timeframe: Optional[str] = None,
    signal: Optional[int] = None,
    confidence: Optional[float] = None,
    pnl: Optional[float] = None,
    capital: Optional[float] = None,
    threshold: Optional[float] = None,
    multiplier: Optional[float] = None,
    **extra: Any,
) -> None:
    """Emit one JSON line to stdout."""
    payload = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "event": event,
    }
    if timeframe is not None:
        payload["timeframe"] = timeframe
    if signal is not None:
        payload["signal"] = signal
    if confidence is not None:
        payload["confidence"] = round(float(confidence), 6)
    if pnl is not None:
        payload["pnl"] = round(float(pnl), 4)
    if capital is not None:
        payload["capital"] = round(float(capital), 2)
    if threshold is not None:
        payload["threshold"] = round(float(threshold), 6)
    if multiplier is not None:
        payload["multiplier"] = round(float(multiplier), 6)
    payload.update(extra)
    try:
        line = json.dumps(payload, default=_serialize)
    except TypeError:
        line = json.dumps({k: str(v) for k, v in payload.items()})
    print(line, flush=True)


def log_info(msg: str, **kwargs: Any) -> None:
    """Info-level JSON log."""
    log_event("info", message=msg, **kwargs)


def log_error(msg: str, **kwargs: Any) -> None:
    """Error-level JSON log."""
    log_event("error", message=msg, **kwargs)
