"""
PHASE 7 — FX NORMALIZATION

FX normalization:
- Convert all FX prices to a normalized base
- Ensure PnL consistency across quote/base
- Allow cross-asset PnL aggregation

No strategy should need FX-specific math.
"""

from typing import Dict, Optional
from dataclasses import dataclass
import pandas as pd
import numpy as np
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.marketdata.metadata import FXMetadata, get_metadata_loader


@dataclass
class FXRate:
    """FX rate definition."""
    base_currency: str
    quote_currency: str
    rate: float  # 1 base = rate quote
    
    def invert(self) -> 'FXRate':
        """Invert rate."""
        return FXRate(
            base_currency=self.quote_currency,
            quote_currency=self.base_currency,
            rate=1.0 / self.rate if self.rate > 0 else 0.0,
        )


class FXNormalizer:
    """
    FX normalizer for cross-asset PnL aggregation.
    
    Converts all FX prices to normalized base (default: USD).
    Ensures PnL consistency across quote/base.
    """
    
    def __init__(self, normalization_base: str = "USD"):
        """
        Initialize FX normalizer.
        
        Args:
            normalization_base: Base currency for normalization (default: USD)
        """
        self.normalization_base = normalization_base
        self.fx_rates: Dict[str, float] = {}  # symbol -> rate to base
        self.metadata_loader = get_metadata_loader()
        self._lock = threading.RLock()
        
        logger.info(f"FXNormalizer initialized with base: {normalization_base}")
    
    def normalize_price(
        self,
        price: float,
        symbol: str,
    ) -> float:
        """
        Normalize FX price to base currency.
        
        Args:
            price: Original price
            symbol: FX pair symbol (e.g., "EURUSD")
            
        Returns:
            Normalized price in base currency
        """
        with self._lock:
            fx_meta = self.metadata_loader.get_fx_metadata(symbol)
            if not fx_meta:
                # Not an FX pair or metadata not found
                return price
            
            # Get rate to base currency
            rate = self._get_rate_to_base(symbol, fx_meta)
            
            # Normalize price
            if fx_meta.quote_currency == self.normalization_base:
                # Quote is base - price is already in base
                return price
            elif fx_meta.base_currency == self.normalization_base:
                # Base is normalization base - invert price
                return 1.0 / price if price > 0 else 0.0
            else:
                # Need to convert via base currency
                # price is in quote_currency per base_currency
                # Convert to normalization_base
                return price * rate
    
    def normalize_dataframe(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> pd.DataFrame:
        """
        Normalize FX DataFrame to base currency.
        
        Args:
            df: DataFrame with OHLCV data
            symbol: FX pair symbol
            
        Returns:
            Normalized DataFrame
        """
        with self._lock:
            fx_meta = self.metadata_loader.get_fx_metadata(symbol)
            if not fx_meta:
                # Not an FX pair
                return df
            
            normalized = df.copy()
            rate = self._get_rate_to_base(symbol, fx_meta)
            
            # Normalize OHLC columns
            if fx_meta.quote_currency == self.normalization_base:
                # Already in base currency
                pass
            elif fx_meta.base_currency == self.normalization_base:
                # Invert prices
                for col in ['open', 'high', 'low', 'close']:
                    if col in normalized.columns:
                        normalized[col] = 1.0 / normalized[col].replace(0, np.nan)
            else:
                # Convert via rate
                for col in ['open', 'high', 'low', 'close']:
                    if col in normalized.columns:
                        normalized[col] = normalized[col] * rate
            
            logger.debug(f"Normalized {symbol} DataFrame to {self.normalization_base}")
            
            return normalized
    
    def _get_rate_to_base(
        self,
        symbol: str,
        fx_meta: FXMetadata,
    ) -> float:
        """
        Get FX rate to normalization base.
        
        Args:
            symbol: FX pair symbol
            fx_meta: FX metadata
            
        Returns:
            Rate to base currency
        """
        # Check cache
        if symbol in self.fx_rates:
            return self.fx_rates[symbol]
        
        # Calculate rate
        if fx_meta.quote_currency == self.normalization_base:
            # Quote is base - rate is 1.0 (price is already in base)
            rate = 1.0
        elif fx_meta.base_currency == self.normalization_base:
            # Base is normalization base - rate is inverse of price
            # This is handled in normalize_price
            rate = 1.0
        else:
            # Need cross-rate
            # For now, assume 1.0 (would need actual FX rates in production)
            rate = 1.0
            logger.warning(
                f"Cross-rate not available for {symbol}, using 1.0. "
                f"Production should use actual FX rates."
            )
        
        # Cache rate
        self.fx_rates[symbol] = rate
        
        return rate
    
    def set_fx_rate(
        self,
        base_currency: str,
        quote_currency: str,
        rate: float,
    ) -> None:
        """
        Set FX rate manually.
        
        Args:
            base_currency: Base currency
            quote_currency: Quote currency
            rate: Exchange rate (1 base = rate quote)
        """
        with self._lock:
            symbol = f"{base_currency}{quote_currency}"
            self.fx_rates[symbol] = rate
            logger.debug(f"Set FX rate: {symbol} = {rate}")


# Global FX normalizer instance
_fx_normalizer: Optional[FXNormalizer] = None
_fx_normalizer_lock = threading.Lock()


def get_fx_normalizer(normalization_base: str = "USD") -> FXNormalizer:
    """
    Get global FX normalizer instance (singleton).
    
    Args:
        normalization_base: Base currency for normalization
        
    Returns:
        FXNormalizer instance
    """
    global _fx_normalizer
    
    if _fx_normalizer is None:
        with _fx_normalizer_lock:
            if _fx_normalizer is None:
                _fx_normalizer = FXNormalizer(normalization_base)
    
    return _fx_normalizer
