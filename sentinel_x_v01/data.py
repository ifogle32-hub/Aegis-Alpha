"""
Sentinel X v0.1 — Data layer.
alpaca-py: NVDA historical + latest bars; timeframes 1Min, 5Min, 15Min, 1Hour, 1Day.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from sentinel_x_v01.config import TIMEFRAMES, TIMEFRAME_MINUTES, get_config


# Map our labels to alpaca TimeFrame
def _alpaca_timeframe(tf: str):
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    m = TIMEFRAME_MINUTES.get(tf)
    if m is None:
        return TimeFrame.Day
    if m < 60:
        return TimeFrame(amount=m, unit=TimeFrameUnit.Minute)
    if m == 60:
        return TimeFrame.Hour
    if m == 1440:
        return TimeFrame.Day
    return TimeFrame(amount=m // 60, unit=TimeFrameUnit.Hour)


def get_bars(
    symbol: str,
    timeframe: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 100,
) -> List[dict]:
    """
    Fetch bar data for symbol and timeframe.
    Returns list of dicts: open, high, low, close, volume, timestamp (iso).
    """
    cfg = get_config()
    if not cfg.alpaca_api_key or not cfg.alpaca_secret_key:
        return []
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
    except ImportError:
        return []
    if end is None:
        end = datetime.utcnow()
    if start is None:
        start = end - timedelta(days=5)
    try:
        client = StockHistoricalDataClient(
            api_key=cfg.alpaca_api_key,
            secret_key=cfg.alpaca_secret_key,
        )
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=_alpaca_timeframe(timeframe),
            start=start,
            end=end,
            limit=limit,
        )
        bars = client.get_stock_bars(req)
        out = []
        if symbol in bars.data:
            for b in bars.data[symbol]:
                out.append({
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": int(b.volume),
                    "timestamp": b.timestamp.isoformat() if hasattr(b.timestamp, "isoformat") else str(b.timestamp),
                })
        return out
    except Exception:
        return []


def get_latest_bars(symbol: str, timeframe: str, count: int = 50) -> List[dict]:
    """Latest N bars for symbol and timeframe."""
    end = datetime.utcnow()
    return get_bars(symbol, timeframe, start=end - timedelta(days=14), end=end, limit=count)
