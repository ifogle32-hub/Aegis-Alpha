"""
PHASE 6 — REGIME & STRESS TESTING

RegimeAnalyzer for market regime detection and stress testing.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import numpy as np
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.feed import MarketTick


class MarketRegime(str):
    """Market regime types."""
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    VOLATILE = "VOLATILE"
    NORMAL = "NORMAL"


@dataclass
class RegimeSnapshot:
    """
    Market regime snapshot.
    """
    timestamp: datetime
    regime: MarketRegime
    volatility: float
    trend: float
    volume: float
    correlation_shock: bool = False
    liquidity_drought: bool = False
    stress_flags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "regime": self.regime,
            "volatility": self.volatility,
            "trend": self.trend,
            "volume": self.volume,
            "correlation_shock": self.correlation_shock,
            "liquidity_drought": self.liquidity_drought,
            "stress_flags": self.stress_flags,
        }


class RegimeAnalyzer:
    """
    Market regime analyzer and stress tester.
    
    Features:
    - Bull/Bear/Sideways detection
    - Volatility expansion/contraction
    - Correlation shock detection
    - Liquidity drought simulation
    - Automatic regime tagging
    - Stress flag generation
    """
    
    def __init__(
        self,
        lookback_periods: int = 20,
        volatility_threshold: float = 0.02,
        trend_threshold: float = 0.001,
    ):
        """
        Initialize regime analyzer.
        
        Args:
            lookback_periods: Number of periods for regime detection
            volatility_threshold: Volatility threshold for regime classification
            trend_threshold: Trend threshold for regime classification
        """
        self.lookback_periods = lookback_periods
        self.volatility_threshold = volatility_threshold
        self.trend_threshold = trend_threshold
        
        self.price_history: Dict[str, List[Tuple[datetime, float]]] = {}  # symbol -> (timestamp, price)
        self.regime_history: List[RegimeSnapshot] = []
        
        self._lock = threading.RLock()
        
        logger.info("RegimeAnalyzer initialized")
    
    def analyze_tick(self, tick: MarketTick) -> RegimeSnapshot:
        """
        Analyze market tick and detect regime.
        
        Args:
            tick: Market tick
            
        Returns:
            RegimeSnapshot
        """
        with self._lock:
            # Store price history
            symbol = tick.symbol
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            
            self.price_history[symbol].append((tick.timestamp, tick.price))
            
            # Keep only lookback period
            if len(self.price_history[symbol]) > self.lookback_periods:
                self.price_history[symbol] = self.price_history[symbol][-self.lookback_periods:]
            
            # Detect regime
            regime = self._detect_regime(tick)
            volatility = self._calculate_volatility(symbol)
            trend = self._calculate_trend(symbol)
            volume = tick.volume
            
            # Check for stress conditions
            correlation_shock = self._detect_correlation_shock()
            liquidity_drought = self._detect_liquidity_drought(tick)
            stress_flags = self._generate_stress_flags(volatility, trend, volume)
            
            snapshot = RegimeSnapshot(
                timestamp=tick.timestamp,
                regime=regime,
                volatility=volatility,
                trend=trend,
                volume=volume,
                correlation_shock=correlation_shock,
                liquidity_drought=liquidity_drought,
                stress_flags=stress_flags,
            )
            
            self.regime_history.append(snapshot)
            
            # Keep only last 10000 snapshots
            if len(self.regime_history) > 10000:
                self.regime_history = self.regime_history[-10000:]
            
            return snapshot
    
    def _detect_regime(self, tick: MarketTick) -> MarketRegime:
        """
        Detect current market regime.
        
        Args:
            tick: Market tick
            
        Returns:
            MarketRegime
        """
        symbol = tick.symbol
        if symbol not in self.price_history or len(self.price_history[symbol]) < 10:
            return MarketRegime.NORMAL
        
        prices = [p[1] for p in self.price_history[symbol]]
        
        # Calculate volatility
        returns = np.diff(prices) / prices[:-1]
        volatility = np.std(returns) if len(returns) > 0 else 0.0
        
        # Calculate trend
        trend = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0.0
        
        # Classify regime
        if volatility > self.volatility_threshold * 2:
            return MarketRegime.VOLATILE
        elif trend > self.trend_threshold:
            return MarketRegime.BULL
        elif trend < -self.trend_threshold:
            return MarketRegime.BEAR
        elif abs(trend) < self.trend_threshold / 2:
            return MarketRegime.SIDEWAYS
        else:
            return MarketRegime.NORMAL
    
    def _calculate_volatility(self, symbol: str) -> float:
        """Calculate current volatility."""
        if symbol not in self.price_history or len(self.price_history[symbol]) < 2:
            return 0.0
        
        prices = [p[1] for p in self.price_history[symbol]]
        returns = np.diff(prices) / prices[:-1]
        return np.std(returns) if len(returns) > 0 else 0.0
    
    def _calculate_trend(self, symbol: str) -> float:
        """Calculate current trend."""
        if symbol not in self.price_history or len(self.price_history[symbol]) < 2:
            return 0.0
        
        prices = [p[1] for p in self.price_history[symbol]]
        if prices[0] > 0:
            return (prices[-1] - prices[0]) / prices[0]
        return 0.0
    
    def _detect_correlation_shock(self) -> bool:
        """
        Detect correlation shock across symbols.
        
        Returns:
            True if correlation shock detected
        """
        if len(self.price_history) < 2:
            return False
        
        # Simple correlation shock detection
        # In production, would compute actual correlation matrix
        # For now, check if multiple symbols have high volatility simultaneously
        high_vol_count = 0
        for symbol in self.price_history:
            vol = self._calculate_volatility(symbol)
            if vol > self.volatility_threshold * 1.5:
                high_vol_count += 1
        
        return high_vol_count >= 2
    
    def _detect_liquidity_drought(self, tick: MarketTick) -> bool:
        """
        Detect liquidity drought.
        
        Args:
            tick: Market tick
            
        Returns:
            True if liquidity drought detected
        """
        # Simple heuristic: low volume relative to price
        if tick.price > 0:
            volume_ratio = tick.volume / tick.price
            # Threshold: very low volume
            return volume_ratio < 10.0  # Arbitrary threshold
        
        return False
    
    def _generate_stress_flags(
        self,
        volatility: float,
        trend: float,
        volume: float,
    ) -> List[str]:
        """
        Generate stress flags.
        
        Args:
            volatility: Current volatility
            trend: Current trend
            volume: Current volume
            
        Returns:
            List of stress flag strings
        """
        flags = []
        
        if volatility > self.volatility_threshold * 2:
            flags.append("HIGH_VOLATILITY")
        
        if abs(trend) > self.trend_threshold * 3:
            flags.append("EXTREME_TREND")
        
        if volume < 100:  # Very low volume
            flags.append("LOW_VOLUME")
        
        return flags
    
    def get_current_regime(self) -> Optional[RegimeSnapshot]:
        """
        Get current regime snapshot.
        
        Returns:
            Latest RegimeSnapshot or None
        """
        with self._lock:
            if not self.regime_history:
                return None
            return self.regime_history[-1]
    
    def get_regime_history(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[RegimeSnapshot]:
        """
        Get regime history in time window.
        
        Args:
            start_time: Optional start time
            end_time: Optional end time
            
        Returns:
            List of RegimeSnapshots
        """
        with self._lock:
            if not start_time and not end_time:
                return self.regime_history.copy()
            
            filtered = []
            for snapshot in self.regime_history:
                if start_time and snapshot.timestamp < start_time:
                    continue
                if end_time and snapshot.timestamp > end_time:
                    continue
                filtered.append(snapshot)
            
            return filtered


# Global analyzer instance
_analyzer: Optional[RegimeAnalyzer] = None
_analyzer_lock = threading.Lock()


def get_regime_analyzer(**kwargs) -> RegimeAnalyzer:
    """
    Get global regime analyzer instance (singleton).
    
    Args:
        **kwargs: Arguments for RegimeAnalyzer
        
    Returns:
        RegimeAnalyzer instance
    """
    global _analyzer
    
    if _analyzer is None:
        with _analyzer_lock:
            if _analyzer is None:
                _analyzer = RegimeAnalyzer(**kwargs)
    
    return _analyzer
