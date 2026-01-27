"""
PHASE 1 — STRATEGY LOGIC IMPLEMENTATIONS

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Strategy logic functions for generating trading signals.
Each function implements a technical analysis approach using numpy/pandas.
"""

from typing import List, Dict, Any, Callable
from datetime import datetime
import math

from sentinel_x.backtest.types import PriceBar, Signal
from sentinel_x.strategies.templates import (
    generate_nvda_momentum_signal,
    generate_aapl_swing_signal,
    generate_msft_mean_reversion_signal,
    generate_amzn_breakout_signal,
    generate_tsla_scalping_signal,
    generate_btc_trend_following_signal,
    generate_eth_range_signal,
    generate_bnb_news_event_signal,
    generate_sol_pairs_signal,
    generate_ada_dca_signal
)
from sentinel_x.monitoring.logger import logger

try:
    import numpy as np
    import pandas as pd
    HAS_NUMPY = True
    HAS_PANDAS = True
except ImportError:
    HAS_NUMPY = False
    HAS_PANDAS = False
    logger.warning("numpy/pandas not available, using basic implementations")


# ============================================================================
# GENERIC STRATEGY LOGIC FUNCTIONS
# ============================================================================

def generate_momentum(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate momentum signals using EMA crossover.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (lookback, fast_ema, slow_ema, threshold)
        
    Returns:
        List of Signal objects
    """
    if len(price_data) < params.get("lookback", 20):
        return []
    
    fast_ema = params.get("fast_ema", 12)
    slow_ema = params.get("slow_ema", 26)
    threshold = params.get("threshold", 1.5)
    
    if len(price_data) < slow_ema:
        return []
    
    closes = [bar.close for bar in price_data]
    
    fast_ema_value = _calculate_ema(closes, fast_ema)
    slow_ema_value = _calculate_ema(closes, slow_ema)
    
    if fast_ema_value is None or slow_ema_value is None:
        return []
    
    signals = []
    timestamp = price_data[-1].timestamp
    current_close = closes[-1]
    symbol = params.get('symbol', params.get('asset', 'UNKNOWN'))
    
    # Bullish crossover
    if len(closes) >= 2:
        prev_fast = _calculate_ema(closes[:-1], fast_ema) if len(closes) > 1 else None
        prev_slow = _calculate_ema(closes[:-1], slow_ema) if len(closes) > 1 else None
        
        if prev_fast is not None and prev_slow is not None:
            if prev_fast <= prev_slow and fast_ema_value > slow_ema_value:
                momentum_strength = (fast_ema_value - slow_ema_value) / slow_ema_value
                if momentum_strength >= threshold / 100.0:
                    confidence = min(0.9, 0.5 + momentum_strength * 2.0)
                    signals.append(Signal(
                        strategy_id=params.get('strategy_id', 'momentum'),
                        timestamp=timestamp,
                        symbol=symbol,
                        side="BUY",
                        confidence=confidence,
                        price=current_close
                    ))
    
    return signals


def generate_mean_reversion(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate mean reversion signals using Bollinger Bands and Z-score.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (lookback, entry_z, exit_z, band_period, std_dev)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    entry_z = params.get("entry_z", 2.0)
    band_period = params.get("band_period", 20)
    
    if len(price_data) < band_period:
        return []
    
    closes = [bar.close for bar in price_data[-band_period:]]
    mean = _calculate_sma(closes, band_period)
    
    if mean is None:
        return []
    
    # Calculate standard deviation
    variance = sum((c - mean) ** 2 for c in closes) / len(closes)
    std = math.sqrt(variance) if variance > 0 else 0.001
    
    current_close = closes[-1]
    z_score = (current_close - mean) / std if std > 0 else 0.0
    
    signals = []
    timestamp = price_data[-1].timestamp
    symbol = price_data[-1].symbol if hasattr(price_data[-1], 'symbol') else params.get('symbol', 'UNKNOWN')
    
    # Price below mean -> Buy signal
    if z_score < -entry_z:
        confidence = min(0.9, abs(z_score) / entry_z * 0.7)
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'mean_reversion'),
            timestamp=timestamp,
            symbol=symbol,
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Price above mean -> Sell signal
    if z_score > entry_z:
        confidence = min(0.9, z_score / entry_z * 0.7)
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'mean_reversion'),
            timestamp=timestamp,
            symbol=symbol,
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_range(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate range trading signals using support/resistance levels.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (lookback, range_percent)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    range_percent = params.get("range_percent", 0.05)
    
    if len(price_data) < lookback:
        return []
    
    recent_bars = price_data[-lookback:]
    highs = [bar.high for bar in recent_bars]
    lows = [bar.low for bar in recent_bars]
    
    resistance = max(highs)
    support = min(lows)
    range_size = resistance - support
    
    if range_size == 0:
        return []
    
    current_close = price_data[-1].close
    range_position = (current_close - support) / range_size
    
    signals = []
    timestamp = price_data[-1].timestamp
    symbol = price_data[-1].symbol if hasattr(price_data[-1], 'symbol') else params.get('symbol', 'UNKNOWN')
    
    # Near support -> Buy
    if range_position < range_percent:
        confidence = (1 - range_position / range_percent) * 0.8
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'range'),
            timestamp=timestamp,
            symbol=symbol,
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Near resistance -> Sell
    if range_position > (1 - range_percent):
        confidence = ((range_position - (1 - range_percent)) / range_percent) * 0.8
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'range'),
            timestamp=timestamp,
            symbol=symbol,
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_breakout(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate breakout signals using support/resistance and volume.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (lookback, breakout_threshold, volume_multiplier)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    breakout_threshold = params.get("breakout_threshold", 0.02)
    volume_multiplier = params.get("volume_multiplier", 1.5)
    
    if len(price_data) < lookback + 1:
        return []
    
    recent_bars = price_data[-lookback:]
    highs = [bar.high for bar in recent_bars[:-1]]
    lows = [bar.low for bar in recent_bars[:-1]]
    volumes = [bar.volume for bar in recent_bars[:-1]]
    
    resistance = max(highs) if highs else price_data[-1].close
    support = min(lows) if lows else price_data[-1].close
    avg_volume = sum(volumes) / len(volumes) if volumes else price_data[-1].volume
    
    current_bar = price_data[-1]
    current_close = current_bar.close
    current_volume = current_bar.volume
    
    signals = []
    timestamp = current_bar.timestamp
    symbol = price_data[-1].symbol if hasattr(price_data[-1], 'symbol') else params.get('symbol', 'UNKNOWN')
    
    # Breakout above resistance with volume
    if current_close > resistance * (1 + breakout_threshold):
        if current_volume >= avg_volume * volume_multiplier:
            confidence = min(0.9, 0.6 + (current_close / resistance - 1) * 10)
            signals.append(Signal(
                strategy_id=params.get('strategy_id', 'breakout'),
                timestamp=timestamp,
                symbol=symbol,
                side="BUY",
                confidence=confidence,
                price=current_close
            ))
    
    # Breakdown below support with volume
    if current_close < support * (1 - breakout_threshold):
        if current_volume >= avg_volume * volume_multiplier:
            confidence = min(0.9, 0.6 + (1 - current_close / support) * 10)
            signals.append(Signal(
                strategy_id=params.get('strategy_id', 'breakout'),
                timestamp=timestamp,
                symbol=symbol,
                side="SELL",
                confidence=confidence,
                price=current_close
            ))
    
    return signals


def generate_swing(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate swing trading signals using RSI.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (lookback, rsi_period, oversold, overbought)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 14)
    rsi_period = params.get("rsi_period", 14)
    oversold = params.get("oversold", 30)
    overbought = params.get("overbought", 70)
    
    if len(price_data) < rsi_period + 1:
        return []
    
    closes = [bar.close for bar in price_data[-rsi_period-1:]]
    rsi = _calculate_rsi(closes, rsi_period)
    
    if rsi is None:
        return []
    
    signals = []
    timestamp = price_data[-1].timestamp
    current_close = price_data[-1].close
    symbol = price_data[-1].symbol if hasattr(price_data[-1], 'symbol') else params.get('symbol', 'UNKNOWN')
    
    # Oversold -> Buy
    if rsi < oversold:
        confidence = (oversold - rsi) / oversold * 0.8
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'swing'),
            timestamp=timestamp,
            symbol=symbol,
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Overbought -> Sell
    if rsi > overbought:
        confidence = (rsi - overbought) / (100 - overbought) * 0.8
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'swing'),
            timestamp=timestamp,
            symbol=symbol,
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_scalping(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate scalping signals using short-term moving averages.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (fast_period, slow_period, momentum_threshold)
        
    Returns:
        List of Signal objects
    """
    fast_period = params.get("fast_period", 5)
    slow_period = params.get("slow_period", 10)
    momentum_threshold = params.get("momentum_threshold", 0.005)
    
    if len(price_data) < slow_period + 1:
        return []
    
    closes = [bar.close for bar in price_data]
    
    fast_ma = _calculate_sma(closes, fast_period)
    slow_ma = _calculate_sma(closes, slow_period)
    
    if fast_ma is None or slow_ma is None:
        return []
    
    if len(closes) < 2:
        return []
    
    momentum = (closes[-1] - closes[-2]) / closes[-2]
    
    signals = []
    timestamp = price_data[-1].timestamp
    current_close = price_data[-1].close
    symbol = price_data[-1].symbol if hasattr(price_data[-1], 'symbol') else params.get('symbol', 'UNKNOWN')
    
    # Fast MA above slow MA + positive momentum -> Buy
    if fast_ma > slow_ma and momentum > momentum_threshold:
        confidence = min(0.85, 0.5 + abs(momentum) / momentum_threshold * 0.35)
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'scalping'),
            timestamp=timestamp,
            symbol=symbol,
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Fast MA below slow MA + negative momentum -> Sell
    if fast_ma < slow_ma and momentum < -momentum_threshold:
        confidence = min(0.85, 0.5 + abs(momentum) / momentum_threshold * 0.35)
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'scalping'),
            timestamp=timestamp,
            symbol=symbol,
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_trend(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate trend following signals using moving average and price momentum.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (adx_period, adx_threshold, lookback)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 14)
    adx_period = params.get("adx_period", 14)
    
    if len(price_data) < adx_period + 1:
        return []
    
    closes = [bar.close for bar in price_data]
    ma = _calculate_sma(closes, adx_period)
    
    if ma is None:
        return []
    
    current_close = closes[-1]
    price_change = (current_close - closes[-adx_period]) / closes[-adx_period] if len(closes) >= adx_period else 0.0
    
    signals = []
    timestamp = price_data[-1].timestamp
    symbol = price_data[-1].symbol if hasattr(price_data[-1], 'symbol') else params.get('symbol', 'UNKNOWN')
    
    # Strong uptrend -> Buy
    if current_close > ma and abs(price_change) > 0.02:
        if price_change > 0:
            confidence = min(0.9, 0.6 + abs(price_change) * 5)
            signals.append(Signal(
                strategy_id=params.get('strategy_id', 'trend'),
                timestamp=timestamp,
                symbol=symbol,
                side="BUY",
                confidence=confidence,
                price=current_close
            ))
    
    # Strong downtrend -> Sell
    if current_close < ma and abs(price_change) > 0.02:
        if price_change < 0:
            confidence = min(0.9, 0.6 + abs(price_change) * 5)
            signals.append(Signal(
                strategy_id=params.get('strategy_id', 'trend'),
                timestamp=timestamp,
                symbol=symbol,
                side="SELL",
                confidence=confidence,
                price=current_close
            ))
    
    return signals


def generate_pairs(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate pairs trading signals using spread analysis.
    
    Note: Simplified version - real implementation would require paired asset data.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (lookback, spread_threshold, btc_prices)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    spread_threshold = params.get("spread_threshold", 0.02)
    
    if len(price_data) < lookback:
        return []
    
    closes = [bar.close for bar in price_data]
    current_close = closes[-1]
    
    ma = _calculate_sma(closes, lookback)
    if ma is None:
        return []
    
    spread = (current_close - ma) / ma
    
    signals = []
    timestamp = price_data[-1].timestamp
    symbol = price_data[-1].symbol if hasattr(price_data[-1], 'symbol') else params.get('symbol', 'UNKNOWN')
    
    # Price below mean (negative spread) -> Buy (expect reversion)
    if spread < -spread_threshold:
        confidence = min(0.8, abs(spread) / spread_threshold * 0.7)
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'pairs'),
            timestamp=timestamp,
            symbol=symbol,
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Price above mean (positive spread) -> Sell (expect reversion)
    if spread > spread_threshold:
        confidence = min(0.8, spread / spread_threshold * 0.7)
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'pairs'),
            timestamp=timestamp,
            symbol=symbol,
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_news_reaction(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate news event-driven signals using volume spikes and volatility.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (volume_spike_multiplier, volatility_threshold)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    volume_spike_multiplier = params.get("volume_spike_multiplier", 2.0)
    volatility_threshold = params.get("volatility_threshold", 0.03)
    
    if len(price_data) < lookback + 1:
        return []
    
    recent_bars = price_data[-lookback:]
    volumes = [bar.volume for bar in recent_bars[:-1]]
    avg_volume = sum(volumes) / len(volumes) if volumes else recent_bars[-1].volume
    
    current_bar = price_data[-1]
    current_volume = current_bar.volume
    current_close = current_bar.close
    
    prev_close = price_data[-2].close if len(price_data) > 1 else current_close
    price_change = abs(current_close - prev_close) / prev_close if prev_close > 0 else 0.0
    
    signals = []
    timestamp = current_bar.timestamp
    symbol = price_data[-1].symbol if hasattr(price_data[-1], 'symbol') else params.get('symbol', 'UNKNOWN')
    
    # Volume spike + upward price movement -> Buy
    if current_volume >= avg_volume * volume_spike_multiplier:
        if price_change >= volatility_threshold and current_close > prev_close:
            confidence = min(0.85, 0.5 + price_change / volatility_threshold * 0.35)
            signals.append(Signal(
                strategy_id=params.get('strategy_id', 'news_reaction'),
                timestamp=timestamp,
                symbol=symbol,
                side="BUY",
                confidence=confidence,
                price=current_close
            ))
    
    # Volume spike + downward price movement -> Sell
    if current_volume >= avg_volume * volume_spike_multiplier:
        if price_change >= volatility_threshold and current_close < prev_close:
            confidence = min(0.85, 0.5 + price_change / volatility_threshold * 0.35)
            signals.append(Signal(
                strategy_id=params.get('strategy_id', 'news_reaction'),
                timestamp=timestamp,
                symbol=symbol,
                side="SELL",
                confidence=confidence,
                price=current_close
            ))
    
    return signals


def generate_dca(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Generate Dollar-Cost Averaging (DCA) signals.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (interval_bars, buy_threshold)
        
    Returns:
        List of Signal objects (typically BUY signals at intervals)
    """
    interval_bars = params.get("interval_bars", 10)
    buy_threshold = params.get("buy_threshold", 0.95)
    
    if len(price_data) < interval_bars:
        return []
    
    # Check if we're at an interval
    bar_count = len(price_data)
    if bar_count % interval_bars != 0:
        return []
    
    closes = [bar.close for bar in price_data[-interval_bars:]]
    avg_price = sum(closes) / len(closes)
    current_close = price_data[-1].close
    
    signals = []
    timestamp = price_data[-1].timestamp
    symbol = price_data[-1].symbol if hasattr(price_data[-1], 'symbol') else params.get('symbol', 'UNKNOWN')
    
    # DCA buy signal if price is below average
    if current_close < avg_price * buy_threshold:
        confidence = min(0.7, (avg_price - current_close) / avg_price * 2.0)
        signals.append(Signal(
            strategy_id=params.get('strategy_id', 'dca'),
            timestamp=timestamp,
            symbol=symbol,
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


# ============================================================================
# HELPER FUNCTIONS (Technical Indicators)
# ============================================================================

def _calculate_ema(prices: List[float], period: int) -> float:
    """Calculate Exponential Moving Average."""
    if len(prices) < period:
        return None
    
    prices_window = prices[-period:]
    multiplier = 2.0 / (period + 1)
    ema = prices_window[0]
    
    for price in prices_window[1:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))
    
    return ema


def _calculate_sma(prices: List[float], period: int) -> float:
    """Calculate Simple Moving Average."""
    if len(prices) < period:
        return None
    
    return sum(prices[-period:]) / period


def _calculate_rsi(prices: List[float], period: int) -> float:
    """Calculate Relative Strength Index."""
    if len(prices) < period + 1:
        return None
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    
    return rsi


def _calculate_bollinger_bands(prices: List[float], period: int, std_dev: float = 2.0) -> tuple:
    """Calculate Bollinger Bands (upper, middle, lower)."""
    if len(prices) < period:
        return None, None, None
    
    sma = _calculate_sma(prices, period)
    if sma is None:
        return None, None, None
    
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = math.sqrt(variance) if variance > 0 else 0.001
    
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    
    return upper, sma, lower


def _calculate_macd(prices: List[float], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> tuple:
    """Calculate MACD (macd_line, signal_line, histogram)."""
    if len(prices) < slow_period:
        return None, None, None
    
    fast_ema = _calculate_ema(prices, fast_period)
    slow_ema = _calculate_ema(prices, slow_period)
    
    if fast_ema is None or slow_ema is None:
        return None, None, None
    
    macd_line = fast_ema - slow_ema
    
    # For signal line, we'd need historical MACD values
    # Simplified: return macd_line as signal_line for now
    signal_line = macd_line  # Simplified
    
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


# ============================================================================
# STRATEGY LOGIC MAP
# ============================================================================

strategy_logic_map: Dict[str, Callable[[List[PriceBar], Dict[str, Any]], List[Signal]]] = {
    "nvda_momentum": generate_nvda_momentum_signal,
    "aapl_swing": generate_aapl_swing_signal,
    "msft_mean_reversion": generate_msft_mean_reversion_signal,
    "amzn_breakout": generate_amzn_breakout_signal,
    "tsla_scalping": generate_tsla_scalping_signal,
    "btc_trend_following": generate_btc_trend_following_signal,
    "eth_range": generate_eth_range_signal,
    "bnb_news_event": generate_bnb_news_event_signal,
    "sol_pairs": generate_sol_pairs_signal,
    "ada_dca": generate_ada_dca_signal,
    
    # Generic mappings (for use with custom strategies)
    "momentum": generate_momentum,
    "swing": generate_swing,
    "mean_reversion": generate_mean_reversion,
    "breakout": generate_breakout,
    "scalping": generate_scalping,
    "trend": generate_trend,
    "pairs": generate_pairs,
    "news_reaction": generate_news_reaction,
    "dca": generate_dca,
    "range": generate_range,
}
