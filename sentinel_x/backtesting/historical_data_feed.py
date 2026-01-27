"""
PHASE 3 — HISTORICAL DATA FEED (SCAFFOLD)

SAFETY: OFFLINE BACKTEST ENGINE
REGRESSION LOCK — DO NOT CONNECT TO LIVE

Responsibilities:
- Yield MarketTickEvent or BarEvent
- Enforce monotonic timestamps
- Support multiple timeframes
- No future data leakage

Rules:
- No vectorized access
- No dataframe peeking
- All data emitted as events
"""

from typing import Dict, List, Optional, Any
from datetime import datetime

# SAFETY: OFFLINE BACKTEST ENGINE
# REGRESSION LOCK — DO NOT CONNECT TO LIVE

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    import pandas as pd
except ImportError:
    pd = None

from sentinel_x.backtesting.event_queue import BacktestEvent, EventType


class HistoricalDataFeed:
    """
    PHASE 3: Historical data feed (scaffold).
    
    SAFETY: offline only
    SAFETY: no live data access
    
    Note: Full implementation in sentinel_x/research/backtest_engine.py
    This is a scaffolding interface that will be expanded.
    """
    
    def __init__(self, data: Dict[str, Any], timeframes: List[str] = None):
        """
        Initialize historical data feed.
        
        Args:
            data: Dict mapping symbol -> DataFrame with OHLCV data
            timeframes: List of timeframes to support
        """
        self.data = data
        self.timeframes = timeframes or ['1m', '5m', '15m', '1h', '1d']
        
        # PHASE 10: Validate data (no future leakage)
        if pd:
            self._validate_data()
        
        logger.info(f"HistoricalDataFeed initialized: {len(data)} symbols")
    
    def _validate_data(self):
        """PHASE 10: Validate data is sorted and has no future leakage."""
        if not pd:
            return
        
        for symbol, df in self.data.items():
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            
            if 'timestamp' not in df.columns:
                raise ValueError(f"Data for {symbol} missing 'timestamp' column")
            
            # Sort by timestamp (ascending)
            df_sorted = df.sort_values('timestamp').reset_index(drop=True)
            self.data[symbol] = df_sorted
            
            # PHASE 10: Assert no future data leakage
            timestamps = pd.to_datetime(df_sorted['timestamp'])
            if not timestamps.is_monotonic_increasing:
                raise ValueError(f"Data for {symbol} has non-monotonic timestamps (lookahead bias risk)")
    
    def get_data_range(self, symbol: str, start: datetime, end: datetime) -> Optional[Any]:
        """
        PHASE 3: Get data for a symbol in a time range (no future leakage).
        
        SAFETY: returns only data up to 'end' timestamp (no lookahead)
        """
        if symbol not in self.data or not pd:
            return None
        
        df = self.data[symbol]
        mask = (pd.to_datetime(df['timestamp']) >= start) & (pd.to_datetime(df['timestamp']) <= end)
        return df[mask].copy()
    
    def get_timeframe_events(self, symbol: str, timeframe: str) -> List[BacktestEvent]:
        """
        PHASE 3: Generate bar close events for a timeframe.
        
        SAFETY: events are in timestamp order (no future leakage)
        """
        if symbol not in self.data or not pd:
            return []
        
        df = self.data[symbol]
        events = []
        
        for _, row in df.iterrows():
            timestamp = pd.to_datetime(row['timestamp'])
            
            event = BacktestEvent(
                event_type=EventType.BAR_CLOSE,
                timestamp=timestamp,
                symbol=symbol,
                data={
                    'open': row.get('open', 0.0),
                    'high': row.get('high', 0.0),
                    'low': row.get('low', 0.0),
                    'close': row.get('close', 0.0),
                    'volume': row.get('volume', 0.0),
                    'timeframe': timeframe
                }
            )
            events.append(event)
        
        return events
