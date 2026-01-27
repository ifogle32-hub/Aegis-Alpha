"""Event-driven backtester for strategy evaluation."""
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from sentinel_x.strategies.base import BaseStrategy
from sentinel_x.monitoring.logger import logger


@dataclass
class Trade:
    """Represents a backtest trade."""
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    size: float  # Positive for long, negative for short
    pnl: Optional[float] = None
    fees: float = 0.0
    slippage: float = 0.0
    
    @property
    def is_open(self) -> bool:
        """Check if trade is still open."""
        return self.exit_time is None
    
    def close(self, exit_price: float, exit_time: datetime, fees: float = 0.0, slippage: float = 0.0) -> None:
        """Close the trade."""
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.fees += fees
        self.slippage += slippage
        self.pnl = self.size * (exit_price - self.entry_price) - self.fees - abs(self.slippage)
    
    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L for open trades."""
        if not self.is_open:
            return 0.0
        return self.size * (current_price - self.entry_price)


class EventDrivenBacktester:
    """Event-driven backtester for strategy evaluation."""
    
    def __init__(self, initial_capital: float = 100000.0, 
                 slippage_pct: float = 0.001,  # 0.1%
                 fee_pct: float = 0.001):  # 0.1%
        """
        Initialize backtester.
        
        Args:
            initial_capital: Starting capital
            slippage_pct: Slippage as percentage (0.001 = 0.1%)
            fee_pct: Trading fee as percentage (0.001 = 0.1%)
        """
        self.initial_capital = initial_capital
        self.slippage_pct = slippage_pct
        self.fee_pct = fee_pct
        logger.debug(f"Backtester initialized: capital=${initial_capital:,.2f}, slippage={slippage_pct*100:.2f}%, fee={fee_pct*100:.2f}%")
    
    def backtest(self, strategy: BaseStrategy, symbol: str, candles: pd.DataFrame) -> Dict[str, Any]:
        """
        Run backtest on a strategy with historical data.
        
        Args:
            strategy: Strategy instance to test
            symbol: Trading symbol
            candles: DataFrame with OHLCV data (columns: timestamp, open, high, low, close, volume)
            
        Returns:
            Dictionary with:
            - returns: np.array of period returns
            - trades: List of Trade objects
            - equity_curve: np.array of cumulative equity
            - final_capital: float
        """
        if candles.empty or len(candles) < 10:
            logger.warning(f"Insufficient data for {symbol} backtest: {len(candles)} bars")
            return self._empty_result()
        
        # Sort by timestamp
        candles = candles.sort_values('timestamp').reset_index(drop=True)
        
        # Initialize tracking
        capital = self.initial_capital
        position = 0.0  # Current position size
        entry_price = 0.0
        trades: List[Trade] = []
        open_trade: Optional[Trade] = None
        equity_curve = [capital]
        returns = []
        
        # Required columns
        required_cols = ['timestamp', 'open', 'high', 'low', 'close']
        missing = [col for col in required_cols if col not in candles.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        # Iterate through bars
        for i in range(len(candles)):
            current_bar = candles.iloc[i]
            current_price = current_bar['close']
            current_time = current_bar['timestamp']
            
            # Get historical data up to current bar (exclusive)
            historical_data = candles.iloc[:i+1].copy()
            
            if len(historical_data) < 2:
                # Not enough data for strategy
                continue
            
            # Generate signal
            try:
                signal = strategy.generate_signal(historical_data)
            except Exception as e:
                logger.warning(f"Strategy {strategy.get_name()} error at bar {i}: {e}")
                signal = 0
            
            # Determine target position
            if signal != 0 and strategy.should_trade(signal):
                target_size = strategy.position_size(signal, capital, current_price)
            else:
                target_size = 0.0
            
            # Execute position changes
            size_change = target_size - position
            
            if abs(size_change) > 0.001:  # Significant change
                # Calculate execution price with slippage
                if size_change > 0:
                    # Buying
                    exec_price = current_price * (1 + self.slippage_pct)
                else:
                    # Selling
                    exec_price = current_price * (1 - self.slippage_pct)
                
                # Calculate fees
                trade_value = abs(size_change) * exec_price
                fees = trade_value * self.fee_pct
                slippage_cost = abs(size_change) * abs(current_price - exec_price)
                
                # Close existing position if reversing
                if open_trade and ((position > 0 and target_size < 0) or (position < 0 and target_size > 0)):
                    # Close and reverse
                    open_trade.close(exec_price, current_time, fees / 2, slippage_cost / 2)
                    trades.append(open_trade)
                    capital += open_trade.pnl
                    open_trade = None
                    position = 0.0
                
                # Open or adjust position
                if abs(target_size) > 0.001:
                    if open_trade:
                        # Adjust existing position (simple approach: close and reopen)
                        open_trade.close(exec_price, current_time, fees / 2, slippage_cost / 2)
                        trades.append(open_trade)
                        capital += open_trade.pnl
                    
                    # Open new position
                    open_trade = Trade(
                        entry_time=current_time,
                        exit_time=None,
                        entry_price=exec_price,
                        exit_price=None,
                        size=target_size,
                        fees=fees / 2 if open_trade else fees,
                        slippage=slippage_cost / 2 if open_trade else slippage_cost
                    )
                    position = target_size
                    
                    # Update capital (for long positions, reduce cash)
                    if target_size > 0:
                        capital -= (abs(target_size) * exec_price + fees)
                    else:
                        capital += (abs(target_size) * exec_price - fees)
                else:
                    # Closing position
                    if open_trade:
                        open_trade.close(exec_price, current_time, fees, slippage_cost)
                        trades.append(open_trade)
                        capital += open_trade.pnl
                        open_trade = None
                    position = 0.0
            
            # Calculate current equity (capital + position value)
            if open_trade:
                position_value = position * current_price
                unrealized_pnl = open_trade.unrealized_pnl(current_price)
                equity = capital + position_value + unrealized_pnl
            else:
                equity = capital
            
            equity_curve.append(equity)
            
            # Calculate period return
            if len(equity_curve) > 1:
                period_return = (equity - equity_curve[-2]) / equity_curve[-2]
                returns.append(period_return)
        
        # Close any remaining open position
        if open_trade and len(candles) > 0:
            final_bar = candles.iloc[-1]
            final_price = final_bar['close']
            final_time = final_bar['timestamp']
            open_trade.close(final_price, final_time, 0.0, 0.0)
            trades.append(open_trade)
            capital += open_trade.pnl
        
        final_capital = capital
        
        logger.info(f"Backtest completed: {strategy.get_name()} on {symbol} - "
                   f"Trades: {len(trades)}, Final Capital: ${final_capital:,.2f}")
        
        return {
            'returns': np.array(returns),
            'trades': trades,
            'equity_curve': np.array(equity_curve),
            'final_capital': final_capital,
            'strategy': strategy.get_name(),
            'symbol': symbol
        }
    
    def _empty_result(self) -> Dict[str, Any]:
        """Return empty result structure."""
        return {
            'returns': np.array([]),
            'trades': [],
            'equity_curve': np.array([self.initial_capital]),
            'final_capital': self.initial_capital,
            'strategy': '',
            'symbol': ''
        }

