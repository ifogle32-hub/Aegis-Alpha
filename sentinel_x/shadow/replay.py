"""
PHASE 2 — HISTORICAL REPLAY ENGINE

HistoricalReplayFeed with:
- Tick-accurate timestamps
- Deterministic ordering
- Clock control (play, pause, step, rewind)
- Windowed replay (date ranges)
- Multi-symbol synchronized replay

Replay modes:
- STRICT (exact timestamps)
- ACCELERATED (fast-forward)
- STEP (manual tick stepping)

Guarantees:
- Same input → same outputs
- Replay results reproducible byte-for-byte
- Replay cannot leak into live execution
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import threading
import time
import pandas as pd
import numpy as np

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.feed import MarketFeed, MarketTick, ShadowMode


class ReplayMode(str, Enum):
    """Replay modes."""
    STRICT = "STRICT"  # Exact timestamps
    ACCELERATED = "ACCELERATED"  # Fast-forward
    STEP = "STEP"  # Manual tick stepping


@dataclass
class ReplayState:
    """
    Replay state.
    """
    mode: ReplayMode
    playing: bool
    current_timestamp: datetime
    start_timestamp: datetime
    end_timestamp: datetime
    speed_multiplier: float
    current_tick_index: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mode": self.mode.value,
            "playing": self.playing,
            "current_timestamp": self.current_timestamp.isoformat() + "Z",
            "start_timestamp": self.start_timestamp.isoformat() + "Z",
            "end_timestamp": self.end_timestamp.isoformat() + "Z",
            "speed_multiplier": self.speed_multiplier,
            "current_tick_index": self.current_tick_index,
        }


class HistoricalReplayFeed(MarketFeed):
    """
    Historical replay feed with tick-accurate timestamps and deterministic ordering.
    
    Features:
    - Tick-accurate timestamps
    - Deterministic ordering
    - Clock control (play, pause, step, rewind)
    - Windowed replay (date ranges)
    - Multi-symbol synchronized replay
    - Reproducible byte-for-byte
    """
    
    def __init__(
        self,
        symbols: List[str],
        historical_data: Dict[str, pd.DataFrame],
        start_date: datetime,
        end_date: datetime,
        replay_mode: ReplayMode = ReplayMode.STRICT,
        speed_multiplier: float = 1.0,
        seed: Optional[int] = None,
    ):
        """
        Initialize historical replay feed.
        
        Args:
            symbols: List of symbols to replay
            historical_data: Dict mapping symbol to DataFrame with OHLCV data
            start_date: Replay start date
            end_date: Replay end date
            replay_mode: Replay mode (STRICT, ACCELERATED, STEP)
            speed_multiplier: Speed multiplier for ACCELERATED mode
            seed: Random seed for determinism
        """
        super().__init__(symbols, ShadowMode.HISTORICAL)
        
        self.historical_data = historical_data
        self.start_date = start_date
        self.end_date = end_date
        self.replay_mode = replay_mode
        self.speed_multiplier = speed_multiplier
        self.seed = seed
        
        # Set random seed for determinism
        if seed is not None:
            np.random.seed(seed)
        
        # Prepare synchronized tick stream
        self.tick_stream: List[Tuple[datetime, str, Dict[str, Any]]] = []
        self._prepare_tick_stream()
        
        # Replay state
        self.state = ReplayState(
            mode=replay_mode,
            playing=False,
            current_timestamp=start_date,
            start_timestamp=start_date,
            end_timestamp=end_date,
            speed_multiplier=speed_multiplier,
        )
        
        self.current_stream_index = 0
        self.replay_start_time: Optional[float] = None
        
        self._lock = threading.RLock()
        
        logger.info(
            f"HistoricalReplayFeed initialized | "
            f"symbols={len(symbols)} | "
            f"mode={replay_mode.value} | "
            f"start={start_date} | end={end_date}"
        )
    
    def _prepare_tick_stream(self) -> None:
        """
        Prepare synchronized tick stream from historical data.
        
        Creates a deterministic, time-ordered stream of ticks across all symbols.
        """
        all_ticks = []
        
        for symbol in self.symbols:
            if symbol not in self.historical_data:
                continue
            
            df = self.historical_data[symbol]
            
            # Ensure timestamp column exists
            if 'timestamp' not in df.columns:
                if df.index.name == 'timestamp' or isinstance(df.index, pd.DatetimeIndex):
                    df = df.reset_index()
                    if 'timestamp' not in df.columns:
                        # Create timestamp from index
                        df['timestamp'] = df.index
            
            # Convert timestamp to datetime if needed
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Filter by date range
            df_filtered = df[
                (df['timestamp'] >= self.start_date) &
                (df['timestamp'] <= self.end_date)
            ]
            
            # Create ticks
            for _, row in df_filtered.iterrows():
                tick_time = pd.to_datetime(row['timestamp'])
                tick_data = {
                    'symbol': symbol,
                    'price': float(row.get('close', row.get('price', 0))),
                    'volume': float(row.get('volume', 0)),
                    'bid': float(row.get('bid', row.get('close', 0))),
                    'ask': float(row.get('ask', row.get('close', 0))),
                    'high': float(row.get('high', row.get('close', 0))),
                    'low': float(row.get('low', row.get('close', 0))),
                    'open': float(row.get('open', row.get('close', 0))),
                    'close': float(row.get('close', row.get('price', 0))),
                }
                all_ticks.append((tick_time, symbol, tick_data))
        
        # Sort by timestamp (deterministic ordering)
        all_ticks.sort(key=lambda x: (x[0], x[1]))  # Sort by timestamp, then symbol
        
        self.tick_stream = all_ticks
        
        logger.info(f"Prepared {len(self.tick_stream)} ticks for replay")
    
    def start(self) -> None:
        """Start replay."""
        with self._lock:
            self.running = True
            self.state.playing = True
            self.replay_start_time = time.monotonic()
            self.current_stream_index = 0
            logger.info("Historical replay started")
    
    def stop(self) -> None:
        """Stop replay."""
        with self._lock:
            self.running = False
            self.state.playing = False
            logger.info("Historical replay stopped")
    
    def pause(self) -> None:
        """Pause replay."""
        with self._lock:
            self.state.playing = False
            logger.info("Historical replay paused")
    
    def resume(self) -> None:
        """Resume replay."""
        with self._lock:
            self.state.playing = True
            if self.replay_start_time is None:
                self.replay_start_time = time.monotonic()
            logger.info("Historical replay resumed")
    
    def rewind(self) -> None:
        """Rewind to beginning."""
        with self._lock:
            self.current_stream_index = 0
            self.state.current_timestamp = self.start_date
            self.replay_start_time = time.monotonic()
            logger.info("Historical replay rewound")
    
    def step(self) -> Optional[MarketTick]:
        """
        Step to next tick (STEP mode only).
        
        Returns:
            Next MarketTick or None if at end
        """
        with self._lock:
            if self.current_stream_index >= len(self.tick_stream):
                return None
            
            tick_time, symbol, tick_data = self.tick_stream[self.current_stream_index]
            self.current_stream_index += 1
            self.state.current_timestamp = tick_time
            
            tick = MarketTick(
                symbol=symbol,
                timestamp=tick_time,
                price=tick_data['price'],
                volume=tick_data['volume'],
                bid=tick_data.get('bid'),
                ask=tick_data.get('ask'),
                high=tick_data.get('high'),
                low=tick_data.get('low'),
                open=tick_data.get('open'),
                close=tick_data.get('close'),
            )
            
            self._notify_callbacks(tick)
            return tick
    
    def get_next_tick(self) -> Optional[MarketTick]:
        """
        Get next tick based on replay mode.
        
        Returns:
            MarketTick or None if no tick available
        """
        if not self.running or not self.state.playing:
            return None
        
        with self._lock:
            if self.current_stream_index >= len(self.tick_stream):
                return None
            
            if self.replay_mode == ReplayMode.STEP:
                # STEP mode: manual stepping only
                return None
            
            # Calculate elapsed replay time
            if self.replay_start_time is None:
                self.replay_start_time = time.monotonic()
            
            elapsed = (time.monotonic() - self.replay_start_time) * self.speed_multiplier
            
            # Find next tick based on timestamp
            next_tick = None
            next_timestamp = None
            
            for i in range(self.current_stream_index, len(self.tick_stream)):
                tick_time, symbol, tick_data = self.tick_stream[i]
                
                # Calculate time delta from start
                time_delta = (tick_time - self.start_date).total_seconds()
                
                # Check if this tick should be emitted
                if time_delta <= elapsed:
                    if next_timestamp is None or tick_time < next_timestamp:
                        next_timestamp = tick_time
                        next_tick = (i, tick_time, symbol, tick_data)
                else:
                    break
            
            if next_tick is None:
                return None
            
            i, tick_time, symbol, tick_data = next_tick
            self.current_stream_index = i + 1
            self.state.current_timestamp = tick_time
            
            tick = MarketTick(
                symbol=symbol,
                timestamp=tick_time,
                price=tick_data['price'],
                volume=tick_data['volume'],
                bid=tick_data.get('bid'),
                ask=tick_data.get('ask'),
                high=tick_data.get('high'),
                low=tick_data.get('low'),
                open=tick_data.get('open'),
                close=tick_data.get('close'),
            )
            
            self._notify_callbacks(tick)
            return tick
    
    def get_progress(self) -> Dict[str, Any]:
        """
        Get replay progress.
        
        Returns:
            Progress dictionary
        """
        with self._lock:
            total_ticks = len(self.tick_stream)
            current_index = self.current_stream_index
            
            if total_ticks > 0:
                progress_pct = (current_index / total_ticks) * 100.0
            else:
                progress_pct = 0.0
            
            time_elapsed = (self.state.current_timestamp - self.start_date).total_seconds()
            time_total = (self.end_date - self.start_date).total_seconds()
            
            if time_total > 0:
                time_progress_pct = (time_elapsed / time_total) * 100.0
            else:
                time_progress_pct = 0.0
            
            return {
                "current_tick": current_index,
                "total_ticks": total_ticks,
                "progress_pct": progress_pct,
                "current_timestamp": self.state.current_timestamp.isoformat() + "Z",
                "start_timestamp": self.start_date.isoformat() + "Z",
                "end_timestamp": self.end_date.isoformat() + "Z",
                "time_progress_pct": time_progress_pct,
                "mode": self.replay_mode.value,
                "playing": self.state.playing,
            }
    
    def set_window(self, start_date: datetime, end_date: datetime) -> None:
        """
        Set replay window (date range).
        
        Args:
            start_date: New start date
            end_date: New end date
        """
        with self._lock:
            self.start_date = start_date
            self.end_date = end_date
            self.state.start_timestamp = start_date
            self.state.end_timestamp = end_date
            self._prepare_tick_stream()
            self.current_stream_index = 0
            logger.info(f"Replay window set: {start_date} to {end_date}")


def create_historical_replay_feed(
    symbols: List[str],
    historical_data: Dict[str, pd.DataFrame],
    start_date: datetime,
    end_date: datetime,
    **kwargs
) -> HistoricalReplayFeed:
    """
    Factory function to create historical replay feed.
    
    Args:
        symbols: List of symbols
        historical_data: Historical data dictionary
        start_date: Start date
        end_date: End date
        **kwargs: Additional arguments for HistoricalReplayFeed
        
    Returns:
        HistoricalReplayFeed instance
    """
    return HistoricalReplayFeed(
        symbols=symbols,
        historical_data=historical_data,
        start_date=start_date,
        end_date=end_date,
        **kwargs
    )
