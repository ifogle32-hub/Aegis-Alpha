"""
PHASE 1 — DATA LOADER FOR SHADOW BACKTESTING

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Loads historical price data for shadow backtesting.
"""

from typing import List, Optional, Dict
from datetime import datetime, timedelta
from pathlib import Path

from sentinel_x.backtest.types import PriceBar
from sentinel_x.monitoring.logger import logger

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None
    HAS_PANDAS = False
    logger.warning("pandas not available, CSV loading will be disabled")

try:
    from sentinel_x.data.storage import get_storage
    from sentinel_x.data.market_data import MarketData
except ImportError:
    logger.warning("Could not import storage or market_data modules")
    get_storage = None
    MarketData = None


def load_price_history(
    asset: str,
    start: datetime,
    end: datetime,
    source: Optional[str] = None
) -> List[PriceBar]:
    """
    Load price bars for backtesting.
    
    SAFETY: SHADOW mode only - never triggers live execution
    
    Args:
        asset: Trading symbol (e.g., "NVDA", "BTC")
        start: Start datetime (inclusive)
        end: End datetime (inclusive)
        source: Data source ("storage", "market_data", "csv", or None for auto)
        
    Returns:
        List of PriceBar objects sorted by timestamp
    """
    if source is None:
        # Try storage first, then market_data, then CSV
        source = "auto"
    
    price_bars = []
    
    # Try loading from storage
    if source in ("auto", "storage") and get_storage:
        try:
            price_bars = _load_from_storage(asset, start, end)
            if price_bars:
                logger.debug(f"Loaded {len(price_bars)} bars for {asset} from storage")
                return price_bars
        except Exception as e:
            logger.debug(f"Could not load from storage: {e}")
    
    # Try loading from market_data
    if source in ("auto", "market_data") and MarketData:
        try:
            price_bars = _load_from_market_data(asset, start, end)
            if price_bars:
                logger.debug(f"Loaded {len(price_bars)} bars for {asset} from market_data")
                return price_bars
        except Exception as e:
            logger.debug(f"Could not load from market_data: {e}")
    
    # Try loading from CSV
    if source in ("auto", "csv"):
        try:
            price_bars = _load_from_csv(asset, start, end)
            if price_bars:
                logger.debug(f"Loaded {len(price_bars)} bars for {asset} from CSV")
                return price_bars
        except Exception as e:
            logger.debug(f"Could not load from CSV: {e}")
    
    # Generate synthetic data if no source available
    if not price_bars:
        logger.warning(f"No data source available for {asset}, generating synthetic data")
        price_bars = _generate_synthetic_data(asset, start, end)
    
    return price_bars


def _load_from_storage(asset: str, start: datetime, end: datetime) -> List[PriceBar]:
    """
    Load price bars from storage (SQLite).
    
    Note: This is a placeholder that would need to be implemented
    based on your storage schema.
    """
    # Placeholder implementation
    # In production, this would query the storage database
    storage = get_storage()
    if not storage:
        return []
    
    # TODO: Implement actual storage query based on your schema
    # For now, return empty list
    return []


def _load_from_market_data(asset: str, start: datetime, end: datetime) -> List[PriceBar]:
    """
    Load price bars from market data provider.
    
    SAFETY: SHADOW mode only - never triggers live execution
    """
    if not MarketData:
        return []
    
    try:
        # Get market data instance (would need to be passed or created)
        # For now, this is a placeholder
        # In production, this would use the MarketData.fetch_history method
        return []
    except Exception as e:
        logger.error(f"Error loading from market_data: {e}")
        return []


def _load_from_csv(asset: str, start: datetime, end: datetime) -> List[PriceBar]:
    """
    Load price bars from CSV file.
    
    Expected CSV format:
    timestamp,open,high,low,close,volume
    
    SAFETY: SHADOW mode only - read-only file access
    """
    if not HAS_PANDAS:
        return []
    
    # Try common CSV file locations
    csv_paths = [
        Path(f"data/{asset}.csv"),
        Path(f"data/{asset.lower()}.csv"),
        Path(f"historical_data/{asset}.csv"),
        Path(f"backtest_data/{asset}.csv"),
    ]
    
    for csv_path in csv_paths:
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                
                # Validate columns
                required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                if not all(col in df.columns for col in required_cols):
                    logger.warning(f"CSV {csv_path} missing required columns")
                    continue
                
                # Convert timestamp to datetime
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                
                # Filter by date range
                mask = (df['timestamp'] >= start) & (df['timestamp'] <= end)
                df_filtered = df[mask].sort_values('timestamp')
                
                # Convert to PriceBar objects
                price_bars = []
                for _, row in df_filtered.iterrows():
                    try:
                        price_bar = PriceBar(
                            timestamp=row['timestamp'],
                            open=float(row['open']),
                            high=float(row['high']),
                            low=float(row['low']),
                            close=float(row['close']),
                            volume=float(row['volume'])
                        )
                        price_bars.append(price_bar)
                    except Exception as e:
                        logger.warning(f"Error parsing row in CSV: {e}")
                        continue
                
                return price_bars
                
            except Exception as e:
                logger.warning(f"Error reading CSV {csv_path}: {e}")
                continue
    
    return []


def _generate_synthetic_data(asset: str, start: datetime, end: datetime) -> List[PriceBar]:
    """
    Generate synthetic price data for testing.
    
    SAFETY: SHADOW mode only - synthetic data generation
    """
    import random
    try:
        import numpy as np
        has_numpy = True
    except ImportError:
        logger.warning("numpy not available, using basic random for synthetic data")
        has_numpy = False
        np = None
    
    # Base price (different for different assets)
    base_prices = {
        "NVDA": 500.0,
        "AAPL": 180.0,
        "MSFT": 350.0,
        "AMZN": 150.0,
        "TSLA": 250.0,
        "BTC": 45000.0,
        "ETH": 3000.0,
        "BNB": 300.0,
        "SOL": 100.0,
        "ADA": 0.5,
    }
    
    base_price = base_prices.get(asset, 100.0)
    
    # Generate 1-minute bars (or adjust interval as needed)
    current_time = start
    price_bars = []
    current_price = base_price
    
    # Use deterministic seed for reproducibility
    seed = hash(asset) % 2**32
    if has_numpy:
        np.random.seed(seed)
    else:
        random.seed(seed)
    
    while current_time <= end:
        # Random walk with slight upward drift
        if has_numpy:
            change_pct = np.random.normal(0.0001, 0.01)  # 0.01% volatility
        else:
            change_pct = random.normalvariate(0.0001, 0.01)
        current_price = max(0.01, current_price * (1 + change_pct))
        
        # Generate OHLC from base price
        intraday_vol = 0.005  # 0.5% intraday volatility
        if has_numpy:
            high = current_price * (1 + abs(np.random.normal(0, intraday_vol)))
            low = current_price * (1 - abs(np.random.normal(0, intraday_vol)))
            open_price = current_price * (1 + np.random.normal(0, intraday_vol * 0.5))
            volume = np.random.uniform(1000, 10000)
        else:
            high = current_price * (1 + abs(random.normalvariate(0, intraday_vol)))
            low = current_price * (1 - abs(random.normalvariate(0, intraday_vol)))
            open_price = current_price * (1 + random.normalvariate(0, intraday_vol * 0.5))
            volume = random.uniform(1000, 10000)
        
        close_price = current_price
        
        # Ensure high >= close >= low and high >= open >= low
        high = max(high, open_price, close_price)
        low = min(low, open_price, close_price)
        
        price_bar = PriceBar(
            timestamp=current_time,
            open=open_price,
            high=high,
            low=low,
            close=close_price,
            volume=volume
        )
        price_bars.append(price_bar)
        
        # Move to next bar (1 minute intervals)
        current_time += timedelta(minutes=1)
    
    logger.info(f"Generated {len(price_bars)} synthetic bars for {asset}")
    return price_bars


def load_price_history_dict(
    assets: List[str],
    start: datetime,
    end: datetime,
    source: Optional[str] = None
) -> Dict[str, List[PriceBar]]:
    """
    Load price history for multiple assets.
    
    Args:
        assets: List of trading symbols
        start: Start datetime
        end: End datetime
        source: Data source (optional)
        
    Returns:
        Dict mapping asset -> List of PriceBar objects
    """
    result = {}
    for asset in assets:
        result[asset] = load_price_history(asset, start, end, source)
    return result


def load_price_history_csv(asset: str, start: datetime, end: datetime) -> List[PriceBar]:
    """
    Load price history from CSV file.
    
    SAFETY: SHADOW MODE ONLY - read-only file access
    
    Args:
        asset: Trading symbol (e.g., "NVDA", "BTC")
        start: Start datetime (inclusive)
        end: End datetime (inclusive)
        
    Returns:
        List of PriceBar objects sorted by timestamp
    """
    return _load_from_csv(asset, start, end)


def fetch_live_bars(symbol: str, timeframe: str = "1Day", limit: int = 200) -> List[PriceBar]:
    """
    Fetch live bars from Alpaca paper feed.
    
    SAFETY: SHADOW MODE ONLY - read-only data fetching, no order execution
    
    Args:
        symbol: Trading symbol (e.g., "NVDA", "BTC")
        timeframe: Bar timeframe (e.g., "1Day", "1Hour", "1Min")
        limit: Maximum number of bars to fetch
        
    Returns:
        List of PriceBar objects sorted by timestamp
    """
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame
        import os
    except ImportError:
        logger.warning("alpaca-py not available, cannot fetch live bars")
        return []
    
    try:
        # Get Alpaca credentials from environment
        api_key = os.getenv("ALPACA_API_KEY_ID")
        api_secret = os.getenv("ALPACA_API_SECRET_KEY")
        
        if not api_key or not api_secret:
            logger.warning("Alpaca credentials not found, cannot fetch live bars")
            return []
        
        # Determine if crypto or stock
        is_crypto = symbol in ["BTC", "ETH", "BNB", "SOL", "ADA"] or symbol.endswith("USD")
        
        # Map timeframe string to TimeFrame object
        timeframe_map = {
            "1Min": TimeFrame.Minute,
            "5Min": TimeFrame(5, TimeFrame.Unit.Minute),
            "15Min": TimeFrame(15, TimeFrame.Unit.Minute),
            "1Hour": TimeFrame.Hour,
            "1Day": TimeFrame.Day,
        }
        
        tf = timeframe_map.get(timeframe, TimeFrame.Day)
        
        price_bars = []
        
        if is_crypto:
            # Use CryptoHistoricalDataClient for crypto
            client = CryptoHistoricalDataClient(api_key, api_secret)
            request_params = CryptoBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=tf,
                limit=limit
            )
            bars = client.get_crypto_bars(request_params)
        else:
            # Use StockHistoricalDataClient for stocks
            client = StockHistoricalDataClient(api_key, api_secret)
            request_params = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=tf,
                limit=limit
            )
            bars = client.get_stock_bars(request_params)
        
        # Convert to PriceBar objects
        # Alpaca returns bars in different formats depending on client type
        try:
            if hasattr(bars, 'data') and isinstance(bars.data, dict):
                # Historical data client format
                if symbol in bars.data:
                    for bar in bars.data[symbol]:
                        price_bar = PriceBar(
                            timestamp=bar.timestamp,
                            open=float(bar.open),
                            high=float(bar.high),
                            low=float(bar.low),
                            close=float(bar.close),
                            volume=float(bar.volume)
                        )
                        price_bars.append(price_bar)
            elif hasattr(bars, 'bars') and isinstance(bars.bars, dict):
                # Alternative format
                if symbol in bars.bars:
                    for bar in bars.bars[symbol]:
                        price_bar = PriceBar(
                            timestamp=bar.timestamp,
                            open=float(bar.open),
                            high=float(bar.high),
                            low=float(bar.low),
                            close=float(bar.close),
                            volume=float(bar.volume)
                        )
                        price_bars.append(price_bar)
            elif isinstance(bars, list):
                # List format
                for bar in bars:
                    price_bar = PriceBar(
                        timestamp=bar.timestamp,
                        open=float(bar.open),
                        high=float(bar.high),
                        low=float(bar.low),
                        close=float(bar.close),
                        volume=float(bar.volume)
                    )
                    price_bars.append(price_bar)
        except Exception as e:
            logger.warning(f"Error parsing Alpaca bars for {symbol}: {e}")
            return []
        
        # Sort by timestamp
        price_bars.sort(key=lambda b: b.timestamp)
        
        logger.info(f"Fetched {len(price_bars)} bars for {symbol} from Alpaca")
        return price_bars
        
    except Exception as e:
        logger.error(f"Error fetching live bars from Alpaca for {symbol}: {e}", exc_info=True)
        return []
