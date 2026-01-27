"""
PHASE 5 — MULTI-ASSET HISTORICAL REPLAY ENGINE

HistoricalMarketFeed:
- Load multiple assets simultaneously
- Align timestamps across assets
- Produce one deterministic engine tick per timestamp
- Support start/end windows
- Support strict, accelerated, and step replay modes

Replay output format:
{
  timestamp,
  assets: {
    "AAPL": {...},
    "NQ": {...},
    "BTC": {...},
    "EURUSD": {...}
  }
}

Replay must be fully deterministic and independent of wall-clock time.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import Enum
import pandas as pd
import numpy as np
import threading
import time

from sentinel_x.monitoring.logger import logger
from sentinel_x.marketdata.schema import OHLCVSchema, validate_ohlcv_data
from sentinel_x.marketdata.metadata import get_metadata_loader, AssetType
from sentinel_x.marketdata.calendars import get_market_calendar
from sentinel_x.marketdata.rollover import get_futures_rollover
from sentinel_x.marketdata.fx import get_fx_normalizer
from sentinel_x.shadow.feed import MarketFeed, MarketTick, ShadowMode


class ReplayMode(str, Enum):
    """Replay modes."""
    STRICT = "STRICT"  # Exact timestamps
    ACCELERATED = "ACCELERATED"  # Fast-forward
    STEP = "STEP"  # Manual tick stepping


@dataclass
class MultiAssetTick:
    """
    Multi-asset tick containing data for all assets at a timestamp.
    """
    timestamp: datetime
    assets: Dict[str, MarketTick]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "assets": {
                symbol: tick.to_dict()
                for symbol, tick in self.assets.items()
            },
        }


class HistoricalMarketFeed(MarketFeed):
    """
    Multi-asset historical replay feed.
    
    Features:
    - Load multiple assets simultaneously
    - Align timestamps across assets
    - Deterministic replay
    - Support for strict, accelerated, and step modes
    """
    
    def __init__(
        self,
        symbols: List[str],
        data_dir: Optional[Path] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        replay_mode: ReplayMode = ReplayMode.STRICT,
        speed_multiplier: float = 1.0,
        seed: Optional[int] = None,
    ):
        """
        Initialize historical market feed.
        
        Args:
            symbols: List of symbols to replay
            data_dir: Data directory path (default: data/historical)
            start_date: Replay start date
            end_date: Replay end date
            replay_mode: Replay mode
            speed_multiplier: Speed multiplier for accelerated mode
            seed: Random seed for determinism
        """
        super().__init__(symbols, ShadowMode.HISTORICAL)
        
        if data_dir is None:
            data_dir = Path("data/historical")
        
        self.data_dir = Path(data_dir)
        self.start_date = start_date
        self.end_date = end_date
        self.replay_mode = replay_mode
        self.speed_multiplier = speed_multiplier
        self.seed = seed
        
        # Set random seed for determinism
        if seed is not None:
            np.random.seed(seed)
        
        # Load components
        self.metadata_loader = get_metadata_loader(self.data_dir)
        self.calendar = get_market_calendar()
        self.rollover = get_futures_rollover()
        self.fx_normalizer = get_fx_normalizer()
        
        # Load and prepare data
        self.asset_data: Dict[str, pd.DataFrame] = {}
        self.tick_stream: List[MultiAssetTick] = []
        self._load_and_prepare_data()
        
        # Replay state
        self.current_tick_index = 0
        self.replay_start_time: Optional[float] = None
        
        self._lock = threading.RLock()
        
        logger.info(
            f"HistoricalMarketFeed initialized | "
            f"symbols={len(symbols)} | "
            f"mode={replay_mode.value} | "
            f"ticks={len(self.tick_stream)}"
        )
    
    def _load_and_prepare_data(self) -> None:
        """Load and prepare historical data for all assets."""
        for symbol in self.symbols:
            try:
                # Determine asset type and file path
                contract = self.metadata_loader.get_contract(symbol)
                if not contract:
                    logger.warning(f"No contract metadata for {symbol}, skipping")
                    continue
                
                asset_type = contract.asset_type
                
                # Load data file
                if asset_type == AssetType.EQUITY:
                    file_path = self.data_dir / "equities" / f"{symbol}.parquet"
                elif asset_type == AssetType.FUTURE:
                    file_path = self.data_dir / "futures" / f"{symbol}.parquet"
                elif asset_type == AssetType.CRYPTO:
                    file_path = self.data_dir / "crypto" / f"{symbol}.parquet"
                elif asset_type == AssetType.FX:
                    file_path = self.data_dir / "fx" / f"{symbol}.parquet"
                else:
                    logger.warning(f"Unknown asset type for {symbol}, skipping")
                    continue
                
                if not file_path.exists():
                    logger.warning(f"Data file not found: {file_path}, skipping")
                    continue
                
                # Load parquet file
                df = pd.read_parquet(file_path)
                
                # Normalize to OHLCV schema
                df = OHLCVSchema.normalize(df, symbol)
                
                # Filter by date range
                if self.start_date:
                    df = df[df['timestamp'] >= self.start_date]
                if self.end_date:
                    df = df[df['timestamp'] <= self.end_date]
                
                # Filter trading hours
                df = self.calendar.filter_trading_hours(df, asset_type)
                
                # Handle futures rollover if needed
                if asset_type == AssetType.FUTURE:
                    # Simplified - in production, would load multiple contracts
                    # For now, assume single contract
                    pass
                
                # Normalize FX if needed
                if asset_type == AssetType.FX:
                    df = self.fx_normalizer.normalize_dataframe(df, symbol)
                
                self.asset_data[symbol] = df
                
                logger.info(f"Loaded {len(df)} rows for {symbol}")
            
            except Exception as e:
                logger.error(f"Error loading data for {symbol}: {e}", exc_info=True)
        
        # Create synchronized tick stream
        self._create_tick_stream()
    
    def _create_tick_stream(self) -> None:
        """Create synchronized multi-asset tick stream."""
        if not self.asset_data:
            logger.warning("No asset data loaded, tick stream will be empty")
            return
        
        # Get all unique timestamps across all assets
        all_timestamps = set()
        for df in self.asset_data.values():
            all_timestamps.update(df['timestamp'].tolist())
        
        # Sort timestamps
        sorted_timestamps = sorted(all_timestamps)
        
        # Create multi-asset ticks
        for timestamp in sorted_timestamps:
            assets = {}
            
            for symbol, df in self.asset_data.items():
                # Get data for this timestamp
                row = df[df['timestamp'] == timestamp]
                
                if not row.empty:
                    r = row.iloc[0]
                    tick = MarketTick(
                        symbol=symbol,
                        timestamp=timestamp,
                        price=float(r['close']),
                        volume=float(r['volume']),
                        bid=float(r.get('close', r['close'])) * 0.9995,  # Small spread
                        ask=float(r.get('close', r['close'])) * 1.0005,
                        high=float(r.get('high', r['close'])),
                        low=float(r.get('low', r['close'])),
                        open=float(r.get('open', r['close'])),
                        close=float(r['close']),
                    )
                    assets[symbol] = tick
            
            if assets:
                multi_tick = MultiAssetTick(
                    timestamp=timestamp,
                    assets=assets,
                )
                self.tick_stream.append(multi_tick)
        
        logger.info(f"Created {len(self.tick_stream)} multi-asset ticks")
    
    def start(self) -> None:
        """Start replay."""
        with self._lock:
            self.running = True
            self.replay_start_time = time.monotonic()
            self.current_tick_index = 0
            logger.info("Historical replay started")
    
    def stop(self) -> None:
        """Stop replay."""
        with self._lock:
            self.running = False
            logger.info("Historical replay stopped")
    
    def get_next_tick(self) -> Optional[MultiAssetTick]:
        """
        Get next multi-asset tick.
        
        Returns:
            MultiAssetTick or None if at end
        """
        if not self.running:
            return None
        
        with self._lock:
            if self.current_tick_index >= len(self.tick_stream):
                return None
            
            if self.replay_mode == ReplayMode.STEP:
                # STEP mode: manual stepping only
                return None
            
            # Calculate elapsed replay time
            if self.replay_start_time is None:
                self.replay_start_time = time.monotonic()
            
            if self.replay_mode == ReplayMode.STRICT:
                # STRICT mode: real-time simulation
                tick = self.tick_stream[self.current_tick_index]
                tick_time_delta = (tick.timestamp - self.tick_stream[0].timestamp).total_seconds()
                elapsed = (time.monotonic() - self.replay_start_time) * self.speed_multiplier
                
                if tick_time_delta <= elapsed:
                    self.current_tick_index += 1
                    self._notify_callbacks_multi(tick)
                    return tick
                else:
                    return None
            
            elif self.replay_mode == ReplayMode.ACCELERATED:
                # ACCELERATED mode: fast-forward
                tick = self.tick_stream[self.current_tick_index]
                self.current_tick_index += 1
                self._notify_callbacks_multi(tick)
                return tick
            
            else:
                return None
    
    def step(self) -> Optional[MultiAssetTick]:
        """
        Step to next tick (STEP mode only).
        
        Returns:
            Next MultiAssetTick or None if at end
        """
        with self._lock:
            if self.current_tick_index >= len(self.tick_stream):
                return None
            
            tick = self.tick_stream[self.current_tick_index]
            self.current_tick_index += 1
            self._notify_callbacks_multi(tick)
            return tick
    
    def _notify_callbacks_multi(self, tick: MultiAssetTick) -> None:
        """Notify callbacks for each asset tick."""
        for symbol, asset_tick in tick.assets.items():
            self._notify_callbacks(asset_tick)
    
    def get_progress(self) -> Dict[str, Any]:
        """
        Get replay progress.
        
        Returns:
            Progress dictionary
        """
        with self._lock:
            total_ticks = len(self.tick_stream)
            current_index = self.current_tick_index
            
            if total_ticks > 0:
                progress_pct = (current_index / total_ticks) * 100.0
            else:
                progress_pct = 0.0
            
            if current_index < len(self.tick_stream):
                current_timestamp = self.tick_stream[current_index].timestamp
            else:
                current_timestamp = self.end_date if self.end_date else datetime.utcnow()
            
            return {
                "current_tick": current_index,
                "total_ticks": total_ticks,
                "progress_pct": progress_pct,
                "current_timestamp": current_timestamp.isoformat() + "Z",
                "start_timestamp": self.start_date.isoformat() + "Z" if self.start_date else None,
                "end_timestamp": self.end_date.isoformat() + "Z" if self.end_date else None,
                "mode": self.replay_mode.value,
                "playing": self.running,
            }


# Global feed instance
_historical_feed: Optional[HistoricalMarketFeed] = None
_historical_feed_lock = threading.Lock()


def get_historical_feed(**kwargs) -> HistoricalMarketFeed:
    """
    Get global historical feed instance (singleton).
    
    Args:
        **kwargs: Arguments for HistoricalMarketFeed
        
    Returns:
        HistoricalMarketFeed instance
    """
    global _historical_feed
    
    if _historical_feed is None:
        with _historical_feed_lock:
            if _historical_feed is None:
                _historical_feed = HistoricalMarketFeed(**kwargs)
    
    return _historical_feed
