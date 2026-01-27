"""
Multi-Asset Historical Market Data System

Provides deterministic historical replay for shadow training.
"""

from sentinel_x.marketdata.historical_feed import HistoricalMarketFeed, get_historical_feed, ReplayMode, MultiAssetTick
from sentinel_x.marketdata.calendars import MarketCalendar, get_market_calendar
from sentinel_x.marketdata.rollover import FuturesRollover, get_futures_rollover, RolloverMethod
from sentinel_x.marketdata.fx import FXNormalizer, get_fx_normalizer
from sentinel_x.marketdata.schema import OHLCVSchema, validate_ohlcv_data
from sentinel_x.marketdata.metadata import MetadataLoader, get_metadata_loader, ContractMetadata, AssetType, FXMetadata

__all__ = [
    "HistoricalMarketFeed",
    "get_historical_feed",
    "ReplayMode",
    "MultiAssetTick",
    "MarketCalendar",
    "get_market_calendar",
    "FuturesRollover",
    "get_futures_rollover",
    "RolloverMethod",
    "FXNormalizer",
    "get_fx_normalizer",
    "OHLCVSchema",
    "validate_ohlcv_data",
    "MetadataLoader",
    "get_metadata_loader",
    "ContractMetadata",
    "AssetType",
    "FXMetadata",
]
