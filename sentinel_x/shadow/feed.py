"""
PHASE 2 — MARKET DATA FEED LAYER

Unified MarketFeed abstraction supporting:
- Live feed (websocket / polling ready)
- Historical replay (timestamp-accurate)
- Synthetic generator (Monte Carlo / regime simulation)
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, List, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
import time
import numpy as np
import pandas as pd

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.definitions import ShadowMode


@dataclass
class MarketTick:
    """
    Standardized market tick payload.
    
    Strategy-agnostic format that works with all strategy types.
    """
    symbol: str
    timestamp: datetime
    price: float
    volume: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    close: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert tick to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat() + "Z",
            "price": self.price,
            "volume": self.volume,
            "bid": self.bid,
            "ask": self.ask,
            "high": self.high,
            "low": self.low,
            "open": self.open,
            "close": self.close,
        }


class MarketFeed(ABC):
    """
    Abstract base class for market data feeds.
    
    Provides unified interface for:
    - Live feeds (websocket/polling)
    - Historical replay
    - Synthetic generation
    """
    
    def __init__(self, symbols: List[str], mode: ShadowMode):
        """
        Initialize market feed.
        
        Args:
            symbols: List of symbols to track
            mode: Feed mode (LIVE, HISTORICAL, SYNTHETIC)
        """
        self.symbols = symbols
        self.mode = mode
        self.running = False
        self.callbacks: List[Callable[[MarketTick], None]] = []
        
    @abstractmethod
    def start(self) -> None:
        """Start the feed."""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the feed."""
        pass
    
    @abstractmethod
    def get_next_tick(self) -> Optional[MarketTick]:
        """
        Get next market tick.
        
        Returns:
            MarketTick or None if no tick available
        """
        pass
    
    def register_callback(self, callback: Callable[[MarketTick], None]) -> None:
        """
        Register callback for tick events.
        
        Args:
            callback: Function to call on each tick
        """
        self.callbacks.append(callback)
    
    def _notify_callbacks(self, tick: MarketTick) -> None:
        """Notify all registered callbacks."""
        for callback in self.callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error(f"Error in feed callback: {e}", exc_info=True)


class LiveMarketFeed(MarketFeed):
    """
    Live market data feed (websocket/polling ready).
    
    Currently uses mock data generation, but structured for
    real websocket/polling integration.
    """
    
    def __init__(self, symbols: List[str], poll_interval: float = 1.0):
        """
        Initialize live feed.
        
        Args:
            symbols: List of symbols to track
            poll_interval: Polling interval in seconds
        """
        super().__init__(symbols, ShadowMode.LIVE)
        self.poll_interval = poll_interval
        self.last_prices: Dict[str, float] = {}
        
        # Initialize prices
        for symbol in symbols:
            self.last_prices[symbol] = np.random.uniform(50, 500)
    
    def start(self) -> None:
        """Start live feed."""
        self.running = True
        logger.info(f"Live market feed started for {len(self.symbols)} symbols")
    
    def stop(self) -> None:
        """Stop live feed."""
        self.running = False
        logger.info("Live market feed stopped")
    
    def get_next_tick(self) -> Optional[MarketTick]:
        """
        Get next live tick (mock implementation).
        
        In production, this would poll websocket or API.
        """
        if not self.running:
            return None
        
        # Generate tick for random symbol
        symbol = np.random.choice(self.symbols)
        current_price = self.last_prices[symbol]
        
        # Random walk price movement
        change = np.random.normal(0, current_price * 0.01)
        new_price = max(1.0, current_price + change)
        self.last_prices[symbol] = new_price
        
        # Generate bid/ask spread
        spread = new_price * 0.001  # 0.1% spread
        bid = new_price - spread / 2
        ask = new_price + spread / 2
        
        tick = MarketTick(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            price=new_price,
            volume=np.random.uniform(1000, 10000),
            bid=bid,
            ask=ask,
            high=new_price * 1.01,
            low=new_price * 0.99,
            open=current_price,
            close=new_price,
        )
        
        self._notify_callbacks(tick)
        return tick


class HistoricalMarketFeed(MarketFeed):
    """
    Historical replay feed with timestamp-accurate stepping.
    
    Supports deterministic replay, rewind, and window replay.
    """
    
    def __init__(
        self,
        symbols: List[str],
        historical_data: Dict[str, pd.DataFrame],
        speed_multiplier: float = 1.0,
    ):
        """
        Initialize historical feed.
        
        Args:
            symbols: List of symbols to track
            historical_data: Dict mapping symbol to DataFrame with OHLCV data
            speed_multiplier: Replay speed (1.0 = real-time, 2.0 = 2x speed)
        """
        super().__init__(symbols, ShadowMode.HISTORICAL)
        self.historical_data = historical_data
        self.speed_multiplier = speed_multiplier
        self.current_indices: Dict[str, int] = {symbol: 0 for symbol in symbols}
        self.start_time: Optional[datetime] = None
        self.replay_start_time: Optional[float] = None
        
    def start(self) -> None:
        """Start historical replay."""
        self.running = True
        self.start_time = datetime.utcnow()
        self.replay_start_time = time.monotonic()
        logger.info(f"Historical replay started for {len(self.symbols)} symbols")
    
    def stop(self) -> None:
        """Stop historical replay."""
        self.running = False
        logger.info("Historical replay stopped")
    
    def rewind(self, symbol: Optional[str] = None) -> None:
        """
        Rewind to beginning of historical data.
        
        Args:
            symbol: Optional symbol to rewind (all if None)
        """
        if symbol:
            self.current_indices[symbol] = 0
        else:
            self.current_indices = {s: 0 for s in self.symbols}
        logger.info(f"Rewound historical feed for {symbol or 'all symbols'}")
    
    def get_next_tick(self) -> Optional[MarketTick]:
        """
        Get next historical tick based on timestamp accuracy.
        
        Returns tick at appropriate time based on speed multiplier.
        """
        if not self.running:
            return None
        
        # Calculate elapsed replay time
        elapsed = (time.monotonic() - self.replay_start_time) * self.speed_multiplier
        
        # Find next tick based on timestamp
        next_tick = None
        next_timestamp = None
        
        for symbol in self.symbols:
            if symbol not in self.historical_data:
                continue
            
            df = self.historical_data[symbol]
            idx = self.current_indices[symbol]
            
            if idx >= len(df):
                continue
            
            row = df.iloc[idx]
            tick_time = pd.to_datetime(row.get('timestamp', row.name))
            
            # Calculate time delta from start
            if self.start_time:
                time_delta = (tick_time - self.start_time).total_seconds()
            else:
                time_delta = 0
            
            # Check if this tick should be emitted
            if time_delta <= elapsed:
                if next_timestamp is None or tick_time < next_timestamp:
                    next_timestamp = tick_time
                    next_tick = (symbol, row, idx)
        
        if next_tick is None:
            return None
        
        symbol, row, idx = next_tick
        
        # Create tick
        tick = MarketTick(
            symbol=symbol,
            timestamp=next_timestamp if isinstance(next_timestamp, datetime) else pd.to_datetime(next_timestamp),
            price=float(row.get('close', row.get('price', 0))),
            volume=float(row.get('volume', 0)),
            bid=float(row.get('bid', row.get('close', 0))),
            ask=float(row.get('ask', row.get('close', 0))),
            high=float(row.get('high', row.get('close', 0))),
            low=float(row.get('low', row.get('close', 0))),
            open=float(row.get('open', row.get('close', 0))),
            close=float(row.get('close', row.get('price', 0))),
        )
        
        # Advance index
        self.current_indices[symbol] = idx + 1
        
        self._notify_callbacks(tick)
        return tick


class SyntheticMarketFeed(MarketFeed):
    """
    Synthetic market data generator (Monte Carlo / regime simulation).
    
    Generates realistic market data for stress testing and regime analysis.
    """
    
    def __init__(
        self,
        symbols: List[str],
        regime: str = "normal",
        volatility: float = 0.02,
        trend: float = 0.0,
    ):
        """
        Initialize synthetic feed.
        
        Args:
            symbols: List of symbols to track
            regime: Market regime ("normal", "bull", "bear", "sideways", "volatile")
            volatility: Base volatility (0.02 = 2%)
            trend: Trend component (0.0 = no trend, positive = up, negative = down)
        """
        super().__init__(symbols, ShadowMode.SYNTHETIC)
        self.regime = regime
        self.volatility = volatility
        self.trend = trend
        self.prices: Dict[str, float] = {}
        self.tick_count = 0
        
        # Initialize prices
        np.random.seed(42)  # Deterministic for testing
        for symbol in symbols:
            self.prices[symbol] = np.random.uniform(50, 500)
    
    def start(self) -> None:
        """Start synthetic feed."""
        self.running = True
        logger.info(f"Synthetic feed started: regime={self.regime}, volatility={self.volatility}")
    
    def stop(self) -> None:
        """Stop synthetic feed."""
        self.running = False
        logger.info("Synthetic feed stopped")
    
    def get_next_tick(self) -> Optional[MarketTick]:
        """Generate next synthetic tick."""
        if not self.running:
            return None
        
        # Select symbol (round-robin)
        symbol = self.symbols[self.tick_count % len(self.symbols)]
        self.tick_count += 1
        
        current_price = self.prices[symbol]
        
        # Regime-specific price movement
        if self.regime == "bull":
            drift = self.trend + 0.001  # Upward bias
            vol = self.volatility * 0.8  # Lower vol in bull
        elif self.regime == "bear":
            drift = self.trend - 0.001  # Downward bias
            vol = self.volatility * 1.2  # Higher vol in bear
        elif self.regime == "volatile":
            drift = 0.0
            vol = self.volatility * 2.0  # High volatility
        elif self.regime == "sideways":
            drift = 0.0
            vol = self.volatility * 0.5  # Low volatility
        else:  # normal
            drift = self.trend
            vol = self.volatility
        
        # Generate price change
        change = np.random.normal(drift * current_price, vol * current_price)
        new_price = max(1.0, current_price + change)
        self.prices[symbol] = new_price
        
        # Generate spread
        spread = new_price * 0.001
        bid = new_price - spread / 2
        ask = new_price + spread / 2
        
        tick = MarketTick(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            price=new_price,
            volume=np.random.uniform(1000, 10000),
            bid=bid,
            ask=ask,
            high=new_price * (1 + abs(change / current_price)),
            low=new_price * (1 - abs(change / current_price)),
            open=current_price,
            close=new_price,
        )
        
        self._notify_callbacks(tick)
        return tick


def create_market_feed(
    mode: ShadowMode,
    symbols: List[str],
    **kwargs
) -> MarketFeed:
    """
    Factory function to create appropriate market feed.
    
    Args:
        mode: Feed mode (LIVE, HISTORICAL, SYNTHETIC)
        symbols: List of symbols to track
        **kwargs: Additional arguments for specific feed types
        
    Returns:
        MarketFeed instance
    """
    if mode == ShadowMode.LIVE:
        poll_interval = kwargs.get("poll_interval", 1.0)
        return LiveMarketFeed(symbols, poll_interval)
    elif mode == ShadowMode.HISTORICAL:
        historical_data = kwargs.get("historical_data", {})
        speed_multiplier = kwargs.get("speed_multiplier", 1.0)
        return HistoricalMarketFeed(symbols, historical_data, speed_multiplier)
    elif mode == ShadowMode.SYNTHETIC:
        regime = kwargs.get("regime", "normal")
        volatility = kwargs.get("volatility", 0.02)
        trend = kwargs.get("trend", 0.0)
        return SyntheticMarketFeed(symbols, regime, volatility, trend)
    else:
        raise ValueError(f"Unknown feed mode: {mode}")
