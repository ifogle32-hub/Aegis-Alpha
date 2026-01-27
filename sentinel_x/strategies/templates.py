"""
PHASE 1 — STRATEGY TEMPLATES

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Strategy template functions for shadow backtesting.
Each function generates trading signals from historical price data.
"""

from typing import List, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime
import math

from sentinel_x.backtest.types import PriceBar, Signal
from sentinel_x.monitoring.logger import logger


@dataclass
class StrategyDefinition:
    """
    Strategy definition for shadow backtesting.
    
    SAFETY: SHADOW mode only - never triggers live execution
    
    Attributes:
        id: Unique strategy identifier
        name: Human-readable strategy name
        asset: Trading symbol (e.g., "NVDA", "BTC")
        type: Strategy type (e.g., "momentum", "mean_reversion")
        parameters: Strategy parameters dict
        signal_function: Function that generates signals from price data
        mode: Strategy mode (always "SHADOW" for templates)
    """
    id: str
    name: str
    asset: str
    type: str
    parameters: Dict[str, Any]
    signal_function: Callable[[List[PriceBar], Dict[str, Any]], List[Signal]]
    mode: str = "SHADOW"
    
    def __post_init__(self):
        """Validate strategy definition."""
        if self.mode != "SHADOW":
            logger.warning(f"Strategy {self.id} mode set to {self.mode}, enforcing SHADOW mode")
            self.mode = "SHADOW"


# ============================================================================
# STRATEGY TEMPLATE FUNCTIONS
# ============================================================================

def generate_nvda_momentum_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute momentum signals for NVDA in SHADOW mode.
    
    Uses EMA crossover with configurable lookback periods.
    
    Args:
        price_data: List of PriceBar objects (historical OHLCV)
        params: Strategy parameters (lookback, fast_ema, slow_ema, threshold)
        
    Returns:
        List of Signal objects (empty if no signal)
    """
    if len(price_data) < params.get("lookback", 20):
        return []
    
    fast_ema = params.get("fast_ema", 12)
    slow_ema = params.get("slow_ema", 26)
    threshold = params.get("threshold", 1.5)
    
    if len(price_data) < slow_ema:
        return []
    
    # Calculate EMAs
    closes = [bar.close for bar in price_data]
    
    # Simple EMA calculation
    fast_ema_value = _calculate_ema(closes, fast_ema)
    slow_ema_value = _calculate_ema(closes, slow_ema)
    
    if fast_ema_value is None or slow_ema_value is None:
        return []
    
    # Check for crossover
    if len(closes) < 2:
        return []
    
    current_close = closes[-1]
    prev_fast = _calculate_ema(closes[:-1], fast_ema) if len(closes) > 1 else None
    prev_slow = _calculate_ema(closes[:-1], slow_ema) if len(closes) > 1 else None
    
    signals = []
    timestamp = price_data[-1].timestamp
    
    # Bullish crossover
    if prev_fast is not None and prev_slow is not None:
        if prev_fast <= prev_slow and fast_ema_value > slow_ema_value:
            momentum_strength = (fast_ema_value - slow_ema_value) / slow_ema_value
            if momentum_strength >= threshold / 100.0:  # Convert threshold to decimal
                confidence = min(0.9, 0.5 + momentum_strength * 2.0)
                signals.append(Signal(
                    strategy_id="nvda_momentum",
                    timestamp=timestamp,
                    symbol="NVDA",
                    side="BUY",
                    confidence=confidence,
                    price=current_close
                ))
    
    # Bearish crossover
    if prev_fast is not None and prev_slow is not None:
        if prev_fast >= prev_slow and fast_ema_value < slow_ema_value:
            momentum_strength = abs(fast_ema_value - slow_ema_value) / slow_ema_value
            if momentum_strength >= threshold / 100.0:
                confidence = min(0.9, 0.5 + momentum_strength * 2.0)
                signals.append(Signal(
                    strategy_id="nvda_momentum",
                    timestamp=timestamp,
                    symbol="NVDA",
                    side="SELL",
                    confidence=confidence,
                    price=current_close
                ))
    
    return signals


def generate_aapl_swing_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute swing trading signals for AAPL in SHADOW mode.
    
    Uses RSI and price action patterns.
    
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
    
    # Oversold -> Buy signal
    if rsi < oversold:
        confidence = (oversold - rsi) / oversold * 0.8
        signals.append(Signal(
            strategy_id="aapl_swing",
            timestamp=timestamp,
            symbol="AAPL",
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Overbought -> Sell signal
    if rsi > overbought:
        confidence = (rsi - overbought) / (100 - overbought) * 0.8
        signals.append(Signal(
            strategy_id="aapl_swing",
            timestamp=timestamp,
            symbol="AAPL",
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_msft_mean_reversion_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute mean reversion signals for MSFT in SHADOW mode.
    
    Uses Bollinger Bands and Z-score.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (lookback, entry_z, exit_z, band_period, std_dev)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    entry_z = params.get("entry_z", 2.0)
    band_period = params.get("band_period", 20)
    std_dev = params.get("std_dev", 2.0)
    
    if len(price_data) < band_period:
        return []
    
    closes = [bar.close for bar in price_data[-band_period:]]
    mean = sum(closes) / len(closes)
    variance = sum((c - mean) ** 2 for c in closes) / len(closes)
    std = math.sqrt(variance) if variance > 0 else 0.001
    
    current_close = closes[-1]
    z_score = (current_close - mean) / std if std > 0 else 0.0
    
    signals = []
    timestamp = price_data[-1].timestamp
    
    # Price below mean -> Buy signal
    if z_score < -entry_z:
        confidence = min(0.9, abs(z_score) / entry_z * 0.7)
        signals.append(Signal(
            strategy_id="msft_mean_reversion",
            timestamp=timestamp,
            symbol="MSFT",
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Price above mean -> Sell signal
    if z_score > entry_z:
        confidence = min(0.9, z_score / entry_z * 0.7)
        signals.append(Signal(
            strategy_id="msft_mean_reversion",
            timestamp=timestamp,
            symbol="MSFT",
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_amzn_breakout_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute breakout signals for AMZN in SHADOW mode.
    
    Uses support/resistance levels and volume confirmation.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (lookback, breakout_threshold, volume_multiplier)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    breakout_threshold = params.get("breakout_threshold", 0.02)  # 2%
    volume_multiplier = params.get("volume_multiplier", 1.5)
    
    if len(price_data) < lookback + 1:
        return []
    
    recent_bars = price_data[-lookback:]
    highs = [bar.high for bar in recent_bars]
    lows = [bar.low for bar in recent_bars]
    volumes = [bar.volume for bar in recent_bars]
    
    resistance = max(highs[:-1])  # Exclude current bar
    support = min(lows[:-1])
    
    current_bar = price_data[-1]
    current_close = current_bar.close
    current_volume = current_bar.volume
    avg_volume = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else current_volume
    
    signals = []
    timestamp = current_bar.timestamp
    
    # Breakout above resistance with volume
    if current_close > resistance * (1 + breakout_threshold):
        if current_volume >= avg_volume * volume_multiplier:
            confidence = min(0.9, 0.6 + (current_close / resistance - 1) * 10)
            signals.append(Signal(
                strategy_id="amzn_breakout",
                timestamp=timestamp,
                symbol="AMZN",
                side="BUY",
                confidence=confidence,
                price=current_close
            ))
    
    # Breakdown below support with volume
    if current_close < support * (1 - breakout_threshold):
        if current_volume >= avg_volume * volume_multiplier:
            confidence = min(0.9, 0.6 + (1 - current_close / support) * 10)
            signals.append(Signal(
                strategy_id="amzn_breakout",
                timestamp=timestamp,
                symbol="AMZN",
                side="SELL",
                confidence=confidence,
                price=current_close
            ))
    
    return signals


def generate_tsla_scalping_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute scalping signals for TSLA in SHADOW mode.
    
    Uses short-term moving averages and price momentum.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (fast_period, slow_period, momentum_threshold)
        
    Returns:
        List of Signal objects
    """
    fast_period = params.get("fast_period", 5)
    slow_period = params.get("slow_period", 10)
    momentum_threshold = params.get("momentum_threshold", 0.005)  # 0.5%
    
    if len(price_data) < slow_period + 1:
        return []
    
    closes = [bar.close for bar in price_data]
    
    fast_ma = _calculate_sma(closes, fast_period)
    slow_ma = _calculate_sma(closes, slow_period)
    
    if fast_ma is None or slow_ma is None:
        return []
    
    # Calculate momentum
    if len(closes) < 2:
        return []
    
    momentum = (closes[-1] - closes[-2]) / closes[-2]
    
    signals = []
    timestamp = price_data[-1].timestamp
    current_close = price_data[-1].close
    
    # Fast MA above slow MA + positive momentum -> Buy
    if fast_ma > slow_ma and momentum > momentum_threshold:
        confidence = min(0.85, 0.5 + abs(momentum) / momentum_threshold * 0.35)
        signals.append(Signal(
            strategy_id="tsla_scalping",
            timestamp=timestamp,
            symbol="TSLA",
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Fast MA below slow MA + negative momentum -> Sell
    if fast_ma < slow_ma and momentum < -momentum_threshold:
        confidence = min(0.85, 0.5 + abs(momentum) / momentum_threshold * 0.35)
        signals.append(Signal(
            strategy_id="tsla_scalping",
            timestamp=timestamp,
            symbol="TSLA",
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_btc_trend_following_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute trend following signals for BTC in SHADOW mode.
    
    Uses ADX and directional movement indicators.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (adx_period, adx_threshold, lookback)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 14)
    adx_period = params.get("adx_period", 14)
    adx_threshold = params.get("adx_threshold", 25)
    
    if len(price_data) < adx_period + 1:
        return []
    
    # Simplified trend following using price and moving average
    closes = [bar.close for bar in price_data]
    ma = _calculate_sma(closes, adx_period)
    
    if ma is None:
        return []
    
    current_close = closes[-1]
    price_change = (current_close - closes[-adx_period]) / closes[-adx_period] if len(closes) >= adx_period else 0.0
    
    signals = []
    timestamp = price_data[-1].timestamp
    
    # Strong uptrend -> Buy
    if current_close > ma and abs(price_change) > 0.02:  # 2% move
        if price_change > 0:
            confidence = min(0.9, 0.6 + abs(price_change) * 5)
            signals.append(Signal(
                strategy_id="btc_trend_following",
                timestamp=timestamp,
                symbol="BTC",
                side="BUY",
                confidence=confidence,
                price=current_close
            ))
    
    # Strong downtrend -> Sell
    if current_close < ma and abs(price_change) > 0.02:
        if price_change < 0:
            confidence = min(0.9, 0.6 + abs(price_change) * 5)
            signals.append(Signal(
                strategy_id="btc_trend_following",
                timestamp=timestamp,
                symbol="BTC",
                side="SELL",
                confidence=confidence,
                price=current_close
            ))
    
    return signals


def generate_eth_range_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute range trading signals for ETH in SHADOW mode.
    
    Uses support/resistance levels in a trading range.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (lookback, range_percent)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    range_percent = params.get("range_percent", 0.05)  # 5%
    
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
    
    # Near support -> Buy
    if range_position < range_percent:
        confidence = (1 - range_position / range_percent) * 0.8
        signals.append(Signal(
            strategy_id="eth_range",
            timestamp=timestamp,
            symbol="ETH",
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Near resistance -> Sell
    if range_position > (1 - range_percent):
        confidence = ((range_position - (1 - range_percent)) / range_percent) * 0.8
        signals.append(Signal(
            strategy_id="eth_range",
            timestamp=timestamp,
            symbol="ETH",
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_bnb_news_event_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute news event-driven signals for BNB in SHADOW mode.
    
    Uses volume spikes and price volatility as proxy for news events.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (volume_spike_multiplier, volatility_threshold)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    volume_spike_multiplier = params.get("volume_spike_multiplier", 2.0)
    volatility_threshold = params.get("volatility_threshold", 0.03)  # 3%
    
    if len(price_data) < lookback + 1:
        return []
    
    recent_bars = price_data[-lookback:]
    volumes = [bar.volume for bar in recent_bars[:-1]]
    avg_volume = sum(volumes) / len(volumes) if volumes else recent_bars[-1].volume
    
    current_bar = price_data[-1]
    current_volume = current_bar.volume
    current_close = current_bar.close
    
    # Calculate volatility (price change)
    prev_close = price_data[-2].close if len(price_data) > 1 else current_close
    price_change = abs(current_close - prev_close) / prev_close if prev_close > 0 else 0.0
    
    signals = []
    timestamp = current_bar.timestamp
    
    # Volume spike + upward price movement -> Buy
    if current_volume >= avg_volume * volume_spike_multiplier:
        if price_change >= volatility_threshold and current_close > prev_close:
            confidence = min(0.85, 0.5 + price_change / volatility_threshold * 0.35)
            signals.append(Signal(
                strategy_id="bnb_news_event",
                timestamp=timestamp,
                symbol="BNB",
                side="BUY",
                confidence=confidence,
                price=current_close
            ))
    
    # Volume spike + downward price movement -> Sell
    if current_volume >= avg_volume * volume_spike_multiplier:
        if price_change >= volatility_threshold and current_close < prev_close:
            confidence = min(0.85, 0.5 + price_change / volatility_threshold * 0.35)
            signals.append(Signal(
                strategy_id="bnb_news_event",
                timestamp=timestamp,
                symbol="BNB",
                side="SELL",
                confidence=confidence,
                price=current_close
            ))
    
    return signals


def generate_sol_pairs_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute pairs trading signals for SOL (paired with BTC) in SHADOW mode.
    
    Uses correlation and spread analysis. Note: This is a simplified version
    that would typically require paired asset data.
    
    Args:
        price_data: List of PriceBar objects (SOL prices)
        params: Strategy parameters (lookback, spread_threshold, btc_prices)
        
    Returns:
        List of Signal objects
    """
    lookback = params.get("lookback", 20)
    spread_threshold = params.get("spread_threshold", 0.02)  # 2%
    
    # Note: In real implementation, would need BTC prices here
    # For now, use SOL momentum as proxy
    if len(price_data) < lookback:
        return []
    
    closes = [bar.close for bar in price_data]
    current_close = closes[-1]
    
    # Calculate moving average
    ma = _calculate_sma(closes, lookback)
    if ma is None:
        return []
    
    # Calculate spread from mean
    spread = (current_close - ma) / ma
    
    signals = []
    timestamp = price_data[-1].timestamp
    
    # Price below mean (spread is negative) -> Buy (expect reversion)
    if spread < -spread_threshold:
        confidence = min(0.8, abs(spread) / spread_threshold * 0.7)
        signals.append(Signal(
            strategy_id="sol_pairs",
            timestamp=timestamp,
            symbol="SOL",
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    # Price above mean (spread is positive) -> Sell (expect reversion)
    if spread > spread_threshold:
        confidence = min(0.8, spread / spread_threshold * 0.7)
        signals.append(Signal(
            strategy_id="sol_pairs",
            timestamp=timestamp,
            symbol="SOL",
            side="SELL",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


def generate_ada_dca_signal(price_data: List[PriceBar], params: Dict[str, Any]) -> List[Signal]:
    """
    Compute Dollar-Cost Averaging (DCA) signals for ADA in SHADOW mode.
    
    Uses time-based intervals and price averaging.
    
    Args:
        price_data: List of PriceBar objects
        params: Strategy parameters (interval_bars, buy_threshold)
        
    Returns:
        List of Signal objects (typically BUY signals at intervals)
    """
    interval_bars = params.get("interval_bars", 10)
    buy_threshold = params.get("buy_threshold", 0.95)  # Buy when price < 95% of average
    
    if len(price_data) < interval_bars:
        return []
    
    # Check if we're at an interval (simplified: every Nth bar)
    bar_count = len(price_data)
    if bar_count % interval_bars != 0:
        return []
    
    closes = [bar.close for bar in price_data[-interval_bars:]]
    avg_price = sum(closes) / len(closes)
    current_close = price_data[-1].close
    
    signals = []
    timestamp = price_data[-1].timestamp
    
    # DCA buy signal if price is below average
    if current_close < avg_price * buy_threshold:
        confidence = min(0.7, (avg_price - current_close) / avg_price * 2.0)
        signals.append(Signal(
            strategy_id="ada_dca",
            timestamp=timestamp,
            symbol="ADA",
            side="BUY",
            confidence=confidence,
            price=current_close
        ))
    
    return signals


# ============================================================================
# HELPER FUNCTIONS
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


# ============================================================================
# STRATEGY DEFINITIONS
# ============================================================================

STRATEGY_TEMPLATES = [
    StrategyDefinition(
        id="nvda_momentum",
        name="NVDA Momentum",
        asset="NVDA",
        type="momentum",
        parameters={"lookback": 20, "fast_ema": 12, "slow_ema": 26, "threshold": 1.5},
        signal_function=generate_nvda_momentum_signal,
        mode="SHADOW"
    ),
    StrategyDefinition(
        id="aapl_swing",
        name="AAPL Swing Trading",
        asset="AAPL",
        type="swing",
        parameters={"lookback": 14, "rsi_period": 14, "oversold": 30, "overbought": 70},
        signal_function=generate_aapl_swing_signal,
        mode="SHADOW"
    ),
    StrategyDefinition(
        id="msft_mean_reversion",
        name="MSFT Mean Reversion",
        asset="MSFT",
        type="mean_reversion",
        parameters={"lookback": 20, "entry_z": 2.0, "exit_z": 0.5, "band_period": 20, "std_dev": 2.0},
        signal_function=generate_msft_mean_reversion_signal,
        mode="SHADOW"
    ),
    StrategyDefinition(
        id="amzn_breakout",
        name="AMZN Breakout",
        asset="AMZN",
        type="breakout",
        parameters={"lookback": 20, "breakout_threshold": 0.02, "volume_multiplier": 1.5},
        signal_function=generate_amzn_breakout_signal,
        mode="SHADOW"
    ),
    StrategyDefinition(
        id="tsla_scalping",
        name="TSLA Scalping",
        asset="TSLA",
        type="scalping",
        parameters={"fast_period": 5, "slow_period": 10, "momentum_threshold": 0.005},
        signal_function=generate_tsla_scalping_signal,
        mode="SHADOW"
    ),
    StrategyDefinition(
        id="btc_trend_following",
        name="BTC Trend Following",
        asset="BTC",
        type="trend_following",
        parameters={"lookback": 14, "adx_period": 14, "adx_threshold": 25},
        signal_function=generate_btc_trend_following_signal,
        mode="SHADOW"
    ),
    StrategyDefinition(
        id="eth_range",
        name="ETH Range Trading",
        asset="ETH",
        type="range",
        parameters={"lookback": 20, "range_percent": 0.05},
        signal_function=generate_eth_range_signal,
        mode="SHADOW"
    ),
    StrategyDefinition(
        id="bnb_news_event",
        name="BNB News Event",
        asset="BNB",
        type="event_driven",
        parameters={"lookback": 20, "volume_spike_multiplier": 2.0, "volatility_threshold": 0.03},
        signal_function=generate_bnb_news_event_signal,
        mode="SHADOW"
    ),
    StrategyDefinition(
        id="sol_pairs",
        name="SOL Pairs Trading",
        asset="SOL",
        type="pairs",
        parameters={"lookback": 20, "spread_threshold": 0.02},
        signal_function=generate_sol_pairs_signal,
        mode="SHADOW"
    ),
    StrategyDefinition(
        id="ada_dca",
        name="ADA Dollar-Cost Averaging",
        asset="ADA",
        type="dca",
        parameters={"interval_bars": 10, "buy_threshold": 0.95},
        signal_function=generate_ada_dca_signal,
        mode="SHADOW"
    ),
]


def get_strategy_template(strategy_id: str) -> StrategyDefinition:
    """
    Get strategy template by ID.
    
    Args:
        strategy_id: Strategy identifier
        
    Returns:
        StrategyDefinition or None if not found
    """
    for template in STRATEGY_TEMPLATES:
        if template.id == strategy_id:
            return template
    return None


def get_all_strategy_templates() -> List[StrategyDefinition]:
    """Get all strategy templates."""
    return STRATEGY_TEMPLATES.copy()
