"""Market data provider (mock implementation for now)."""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sentinel_x.monitoring.logger import logger


class MarketData:
    """Market data provider with mock data generation."""
    
    def __init__(self, symbols: List[str], seed: Optional[int] = None):
        """
        Initialize market data provider.
        
        Args:
            symbols: List of symbols to track
            seed: Random seed for reproducibility
        """
        self.symbols = symbols
        self.current_prices: Dict[str, float] = {}
        self.price_histories: Dict[str, List[float]] = {}
        
        # Initialize with random starting prices
        np.random.seed(seed)
        for symbol in symbols:
            base_price = np.random.uniform(50, 500)
            self.current_prices[symbol] = base_price
            self.price_histories[symbol] = [base_price]
        
        logger.info(f"MarketData initialized with {len(symbols)} symbols")
    
    def fetch_latest(self, symbol: str) -> Optional[float]:
        """
        Fetch latest price for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Latest price or None if symbol not found
        """
        if symbol not in self.symbols:
            logger.warning(f"Symbol {symbol} not found")
            return None
        
        # Generate new price with random walk
        current = self.current_prices[symbol]
        change = np.random.normal(0, current * 0.01)  # 1% volatility
        new_price = max(1.0, current + change)  # Ensure positive
        
        self.current_prices[symbol] = new_price
        self.price_histories[symbol].append(new_price)
        
        return new_price
    
    def fetch_history(self, symbol: str, lookback: int = 100) -> Optional[pd.DataFrame]:
        """
        Fetch price history for a symbol.
        
        Args:
            symbol: Trading symbol
            lookback: Number of periods to return
            
        Returns:
            DataFrame with OHLCV data or None if symbol not found
        """
        if symbol not in self.symbols:
            logger.warning(f"Symbol {symbol} not found")
            return None
        
        # Get historical prices
        prices = self.price_histories[symbol]
        if len(prices) < 2:
            # Generate synthetic history
            prices = self._generate_history(self.current_prices[symbol], lookback)
        else:
            # Use actual history, pad if needed
            if len(prices) < lookback:
                base_price = prices[0]
                synthetic = self._generate_history(base_price, lookback - len(prices))
                prices = list(synthetic) + prices
            else:
                prices = prices[-lookback:]
        
        # Create OHLCV DataFrame
        now = datetime.now()
        timestamps = [now - timedelta(minutes=(lookback - i) * 5) for i in range(lookback)]
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': prices,
            'high': [p * (1 + abs(np.random.normal(0, 0.005))) for p in prices],
            'low': [p * (1 - abs(np.random.normal(0, 0.005))) for p in prices],
            'close': prices,
            'volume': [np.random.uniform(1000, 10000) for _ in prices]
        })
        
        return df
    
    def _generate_history(self, base_price: float, length: int) -> List[float]:
        """Generate synthetic price history."""
        prices = [base_price]
        for _ in range(length - 1):
            change = np.random.normal(0, prices[-1] * 0.01)
            new_price = max(1.0, prices[-1] + change)
            prices.append(new_price)
        return prices
    
    def get_all_prices(self) -> Dict[str, float]:
        """Get current prices for all symbols."""
        return self.current_prices.copy()


# Global market data instance
_market_data = None


def get_market_data(symbols: List[str], seed: Optional[int] = None) -> MarketData:
    """Get global market data instance."""
    global _market_data
    if _market_data is None:
        _market_data = MarketData(symbols, seed)
    return _market_data

