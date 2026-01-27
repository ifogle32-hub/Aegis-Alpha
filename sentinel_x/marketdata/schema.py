"""
PHASE 1 — CANONICAL DATA MODEL

Unified OHLCV schema for ALL assets.

Required columns:
- timestamp (UTC, tz-aware)
- open
- high
- low
- close
- volume

All assets must be converted into this schema before replay.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd
import pytz

from sentinel_x.monitoring.logger import logger


class OHLCVSchema:
    """
    Canonical OHLCV schema for all asset types.
    
    All historical data must conform to this schema before replay.
    """
    
    REQUIRED_COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    TIMESTAMP_COLUMN = 'timestamp'
    
    @staticmethod
    def validate(df: pd.DataFrame) -> bool:
        """
        Validate DataFrame conforms to OHLCV schema.
        
        Args:
            df: DataFrame to validate
            
        Returns:
            True if valid, False otherwise
        """
        if df is None or df.empty:
            return False
        
        # Check required columns
        missing = set(OHLCVSchema.REQUIRED_COLUMNS) - set(df.columns)
        if missing:
            logger.error(f"Missing required columns: {missing}")
            return False
        
        # Check timestamp column
        if OHLCVSchema.TIMESTAMP_COLUMN not in df.columns:
            logger.error(f"Missing timestamp column: {OHLCVSchema.TIMESTAMP_COLUMN}")
            return False
        
        # Validate timestamp is datetime
        if not pd.api.types.is_datetime64_any_dtype(df[OHLCVSchema.TIMESTAMP_COLUMN]):
            logger.error("Timestamp column must be datetime type")
            return False
        
        # Ensure timestamp is timezone-aware (UTC)
        if df[OHLCVSchema.TIMESTAMP_COLUMN].dt.tz is None:
            logger.warning("Timestamp column is not timezone-aware, assuming UTC")
            df[OHLCVSchema.TIMESTAMP_COLUMN] = pd.to_datetime(
                df[OHLCVSchema.TIMESTAMP_COLUMN]
            ).dt.tz_localize('UTC')
        elif df[OHLCVSchema.TIMESTAMP_COLUMN].dt.tz != pytz.UTC:
            logger.warning("Converting timestamp to UTC")
            df[OHLCVSchema.TIMESTAMP_COLUMN] = df[OHLCVSchema.TIMESTAMP_COLUMN].dt.tz_convert('UTC')
        
        # Validate numeric columns
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            if not pd.api.types.is_numeric_dtype(df[col]):
                logger.error(f"Column {col} must be numeric")
                return False
        
        # Validate OHLC relationships
        invalid_ohlc = (
            (df['high'] < df['low']) |
            (df['high'] < df['open']) |
            (df['high'] < df['close']) |
            (df['low'] > df['open']) |
            (df['low'] > df['close'])
        )
        
        if invalid_ohlc.any():
            logger.warning(f"Found {invalid_ohlc.sum()} rows with invalid OHLC relationships")
        
        # Validate volume is non-negative
        if (df['volume'] < 0).any():
            logger.warning("Found negative volume values")
        
        return True
    
    @staticmethod
    def normalize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Normalize DataFrame to canonical OHLCV schema.
        
        Args:
            df: Input DataFrame
            symbol: Symbol name (for logging)
            
        Returns:
            Normalized DataFrame
        """
        if df is None or df.empty:
            logger.warning(f"Empty DataFrame for {symbol}")
            return pd.DataFrame(columns=OHLCVSchema.REQUIRED_COLUMNS)
        
        # Create normalized DataFrame
        normalized = pd.DataFrame()
        
        # Handle timestamp
        if 'timestamp' in df.columns:
            normalized['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        elif df.index.name == 'timestamp' or isinstance(df.index, pd.DatetimeIndex):
            normalized['timestamp'] = pd.to_datetime(df.index, utc=True)
        else:
            raise ValueError(f"Cannot find timestamp column or index for {symbol}")
        
        # Ensure UTC timezone
        if normalized['timestamp'].dt.tz is None:
            normalized['timestamp'] = normalized['timestamp'].dt.tz_localize('UTC')
        else:
            normalized['timestamp'] = normalized['timestamp'].dt.tz_convert('UTC')
        
        # Copy OHLCV columns
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                normalized[col] = pd.to_numeric(df[col], errors='coerce')
            else:
                # Use close as fallback for missing OHLC
                if col in ['open', 'high', 'low']:
                    normalized[col] = normalized.get('close', df.get('close', df.get('price', 0)))
                elif col == 'volume':
                    normalized[col] = 0.0
        
        # Sort by timestamp
        normalized = normalized.sort_values('timestamp').reset_index(drop=True)
        
        # Remove duplicates
        normalized = normalized.drop_duplicates(subset=['timestamp'], keep='last')
        
        # Validate
        if not OHLCVSchema.validate(normalized):
            logger.error(f"Normalized DataFrame for {symbol} failed validation")
            return pd.DataFrame(columns=OHLCVSchema.REQUIRED_COLUMNS)
        
        return normalized
    
    @staticmethod
    def get_schema_dict() -> Dict[str, Any]:
        """
        Get schema definition as dictionary.
        
        Returns:
            Schema dictionary
        """
        return {
            "required_columns": OHLCVSchema.REQUIRED_COLUMNS,
            "timestamp_column": OHLCVSchema.TIMESTAMP_COLUMN,
            "description": "Canonical OHLCV schema for all asset types",
        }


def validate_ohlcv_data(df: pd.DataFrame) -> bool:
    """
    Validate OHLCV data conforms to schema.
    
    Args:
        df: DataFrame to validate
        
    Returns:
        True if valid, False otherwise
    """
    return OHLCVSchema.validate(df)
