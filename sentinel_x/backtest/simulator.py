"""
PHASE 1 — SHADOW BACKTESTING SIMULATOR

SAFETY: SHADOW MODE ONLY
NO live execution paths
NO paper order submission

Shadow backtesting simulator that runs strategies on historical OHLCV data
and computes performance metrics.
"""

from typing import List, Dict, Any, Optional, TYPE_CHECKING
from dataclasses import dataclass
from datetime import datetime
import math
import statistics

from sentinel_x.backtest.types import PriceBar, Signal
from sentinel_x.backtest.data_loader import load_price_history
from sentinel_x.monitoring.logger import logger

if TYPE_CHECKING:
    from sentinel_x.strategies.templates import StrategyDefinition


@dataclass
class BacktestResult:
    """
    Backtest results for a strategy.
    
    SAFETY: SHADOW mode only - read-only results
    """
    strategy_id: str
    strategy_name: str
    asset: str
    start_date: datetime
    end_date: datetime
    pnl: float  # Cumulative PnL
    sharpe: float  # Rolling Sharpe Ratio
    max_drawdown: float  # Maximum drawdown (as percentage)
    trades: int  # Trade count
    win_rate: float  # Win rate (0.0 to 1.0)
    total_return: float  # Total return percentage
    equity_curve: List[float]  # Equity curve over time
    signals: List[Signal]  # All signals generated
    
    def __post_init__(self):
        """Validate backtest results."""
        if self.max_drawdown < 0 or self.max_drawdown > 1:
            raise ValueError(f"Max drawdown must be between 0 and 1, got {self.max_drawdown}")
        if not 0.0 <= self.win_rate <= 1.0:
            raise ValueError(f"Win rate must be between 0.0 and 1.0, got {self.win_rate}")


@dataclass
class Trade:
    """
    Represents a backtest trade.
    
    SAFETY: SHADOW mode only - read-only trade record
    """
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    side: str  # "BUY" or "SELL"
    quantity: float
    pnl: Optional[float] = None
    
    @property
    def is_open(self) -> bool:
        """Check if trade is still open."""
        return self.exit_time is None
    
    def close(self, exit_price: float, exit_time: datetime) -> None:
        """Close the trade and calculate PnL."""
        self.exit_time = exit_time
        self.exit_price = exit_price
        
        # Calculate PnL
        if self.side.upper() == "BUY":
            # Long position: profit if exit > entry
            self.pnl = (exit_price - self.entry_price) * self.quantity
        else:
            # Short position: profit if exit < entry
            self.pnl = (self.entry_price - exit_price) * self.quantity


class ShadowBacktestSimulator:
    """
    Shadow backtesting simulator.
    
    SAFETY: SHADOW MODE ONLY
    - Never triggers live execution
    - Never submits paper orders
    - Read-only simulation of strategy performance
    
    Runs strategies on historical data and computes:
    - Cumulative PnL
    - Rolling Sharpe Ratio
    - Maximum Drawdown
    - Trade Count
    """
    
    def __init__(
        self,
        initial_capital: float = 100000.0,
        slippage_pct: float = 0.001,  # 0.1%
        fee_pct: float = 0.001,  # 0.1%
        position_size_pct: float = 0.1  # 10% of capital per trade
    ):
        """
        Initialize shadow backtest simulator.
        
        Args:
            initial_capital: Starting capital
            slippage_pct: Slippage as percentage (0.001 = 0.1%)
            fee_pct: Trading fee as percentage (0.001 = 0.1%)
            position_size_pct: Position size as percentage of capital
        """
        self.initial_capital = initial_capital
        self.slippage_pct = slippage_pct
        self.fee_pct = fee_pct
        self.position_size_pct = position_size_pct
        
        logger.info(
            f"ShadowBacktestSimulator initialized: "
            f"capital=${initial_capital:,.2f}, "
            f"slippage={slippage_pct*100:.2f}%, "
            f"fee={fee_pct*100:.2f}%"
        )
    
    def run_backtest(
        self,
        strategy: "StrategyDefinition",
        history: Dict[str, List[PriceBar]],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> BacktestResult:
        """
        Runs strategy in SHADOW mode on provided history.
        
        SAFETY: SHADOW MODE ONLY - never triggers live execution
        
        Args:
            strategy: Strategy definition
            history: Dict mapping asset -> List of PriceBar objects
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            BacktestResult with performance metrics
        """
        # Get price data for strategy asset
        price_data = history.get(strategy.asset, [])
        
        if not price_data:
            logger.warning(f"No price data found for {strategy.asset}")
            return self._empty_result(strategy)
        
        # Filter by date range if provided
        if start_date or end_date:
            filtered_data = []
            for bar in price_data:
                if start_date and bar.timestamp < start_date:
                    continue
                if end_date and bar.timestamp > end_date:
                    continue
                filtered_data.append(bar)
            price_data = filtered_data
        
        if not price_data:
            logger.warning(f"No price data in date range for {strategy.asset}")
            return self._empty_result(strategy)
        
        # Sort by timestamp
        price_data = sorted(price_data, key=lambda b: b.timestamp)
        
        # Determine actual date range
        actual_start = price_data[0].timestamp
        actual_end = price_data[-1].timestamp
        
        # Initialize simulation state
        capital = self.initial_capital
        position: Optional[Trade] = None
        trades: List[Trade] = []
        signals: List[Signal] = []
        equity_curve = [capital]
        
        # Iterate through price bars
        for i, current_bar in enumerate(price_data):
            # Get historical data up to current bar (no lookahead bias)
            historical_data = price_data[:i+1]
            
            # Generate signals from strategy
            try:
                new_signals = strategy.signal_function(historical_data, strategy.parameters)
                signals.extend(new_signals)
            except Exception as e:
                logger.warning(f"Strategy {strategy.id} error at bar {i}: {e}")
                new_signals = []
            
            # Process signals (simple: one signal at a time)
            for signal in new_signals:
                if signal.side.upper() not in ("BUY", "SELL"):
                    continue
                
                # Close existing position if reversing
                if position:
                    if (position.side.upper() == "BUY" and signal.side.upper() == "SELL") or \
                       (position.side.upper() == "SELL" and signal.side.upper() == "BUY"):
                        # Close position
                        exec_price = self._apply_slippage(
                            current_bar.close,
                            position.side.upper() == "SELL"  # Selling = negative slippage
                        )
                        position.close(exec_price, current_bar.timestamp)
                        capital += position.pnl - self._calculate_fee(position.entry_price, position.quantity)
                        trades.append(position)
                        position = None
                
                # Open new position if no position exists
                if not position:
                    exec_price = self._apply_slippage(
                        current_bar.close,
                        signal.side.upper() == "BUY"  # Buying = positive slippage
                    )
                    
                    # Calculate position size
                    position_value = capital * self.position_size_pct
                    quantity = position_value / exec_price if exec_price > 0 else 0.0
                    
                    if quantity > 0:
                        position = Trade(
                            entry_time=current_bar.timestamp,
                            exit_time=None,
                            entry_price=exec_price,
                            exit_price=None,
                            side=signal.side.upper(),
                            quantity=quantity
                        )
                        
                        # Deduct capital (for long positions)
                        if signal.side.upper() == "BUY":
                            capital -= (exec_price * quantity + self._calculate_fee(exec_price, quantity))
            
            # Update equity (capital + position value)
            if position:
                current_price = current_bar.close
                unrealized_pnl = self._calculate_unrealized_pnl(position, current_price)
                equity = capital + (position.entry_price * position.quantity) + unrealized_pnl
            else:
                equity = capital
            
            equity_curve.append(equity)
        
        # Close any remaining open position
        if position and price_data:
            final_bar = price_data[-1]
            exec_price = self._apply_slippage(
                final_bar.close,
                position.side.upper() == "SELL"
            )
            position.close(exec_price, final_bar.timestamp)
            capital += position.pnl - self._calculate_fee(position.entry_price, position.quantity)
            trades.append(position)
        
        # Calculate metrics
        final_pnl = capital - self.initial_capital
        total_return = (final_pnl / self.initial_capital) if self.initial_capital > 0 else 0.0
        
        # Calculate Sharpe ratio
        sharpe = self._calculate_sharpe_ratio(equity_curve)
        
        # Calculate max drawdown
        max_drawdown = self._calculate_max_drawdown(equity_curve)
        
        # Calculate win rate
        closed_trades = [t for t in trades if t.pnl is not None]
        wins = sum(1 for t in closed_trades if t.pnl > 0)
        win_rate = wins / len(closed_trades) if closed_trades else 0.0
        
        logger.info(
            f"Backtest completed: {strategy.id} on {strategy.asset} - "
            f"Trades: {len(trades)}, PnL: ${final_pnl:,.2f}, "
            f"Sharpe: {sharpe:.2f}, Max DD: {max_drawdown*100:.2f}%"
        )
        
        return BacktestResult(
            strategy_id=strategy.id,
            strategy_name=strategy.name,
            asset=strategy.asset,
            start_date=actual_start,
            end_date=actual_end,
            pnl=final_pnl,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            trades=len(trades),
            win_rate=win_rate,
            total_return=total_return,
            equity_curve=equity_curve,
            signals=signals
        )
    
    def _apply_slippage(self, price: float, is_buy: bool) -> float:
        """Apply slippage to execution price."""
        if is_buy:
            return price * (1 + self.slippage_pct)
        else:
            return price * (1 - self.slippage_pct)
    
    def _calculate_fee(self, price: float, quantity: float) -> float:
        """Calculate trading fee."""
        return price * quantity * self.fee_pct
    
    def _calculate_unrealized_pnl(self, trade: Trade, current_price: float) -> float:
        """Calculate unrealized PnL for open trade."""
        if trade.side.upper() == "BUY":
            return (current_price - trade.entry_price) * trade.quantity
        else:
            return (trade.entry_price - current_price) * trade.quantity
    
    def _calculate_sharpe_ratio(self, equity_curve: List[float]) -> float:
        """
        Calculate rolling Sharpe ratio.
        
        Uses returns from equity curve and assumes risk-free rate of 0.
        """
        if len(equity_curve) < 2:
            return 0.0
        
        # Calculate returns
        returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i-1] > 0:
                ret = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
                returns.append(ret)
        
        if not returns:
            return 0.0
        
        # Calculate Sharpe (annualized, assuming daily returns)
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0.0
        
        if std_return == 0:
            return 0.0
        
        # Annualize (252 trading days)
        sharpe = (mean_return / std_return) * math.sqrt(252)
        
        return sharpe
    
    def _calculate_max_drawdown(self, equity_curve: List[float]) -> float:
        """
        Calculate maximum drawdown as percentage.
        
        Returns value between 0.0 and 1.0 (e.g., 0.15 = 15% drawdown)
        """
        if len(equity_curve) < 2:
            return 0.0
        
        max_dd = 0.0
        peak = equity_curve[0]
        
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            
            if peak > 0:
                dd = (peak - equity) / peak
                max_dd = max(max_dd, dd)
        
        return max_dd
    
    def _empty_result(self, strategy: "StrategyDefinition") -> BacktestResult:
        """Return empty result structure."""
        return BacktestResult(
            strategy_id=strategy.id,
            strategy_name=strategy.name,
            asset=strategy.asset,
            start_date=datetime.now(),
            end_date=datetime.now(),
            pnl=0.0,
            sharpe=0.0,
            max_drawdown=0.0,
            trades=0,
            win_rate=0.0,
            total_return=0.0,
            equity_curve=[self.initial_capital],
            signals=[]
        )


def run_backtest(
    strategy: "StrategyDefinition",
    history: Dict[str, List[PriceBar]],
    initial_capital: float = 100000.0,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> BacktestResult:
    """
    Convenience function to run a backtest.
    
    SAFETY: SHADOW MODE ONLY - never triggers live execution
    
    Args:
        strategy: Strategy definition
        history: Dict mapping asset -> List of PriceBar objects
        initial_capital: Starting capital
        start_date: Optional start date filter
        end_date: Optional end date filter
        
    Returns:
        BacktestResult with performance metrics
    """
    simulator = ShadowBacktestSimulator(initial_capital=initial_capital)
    return simulator.run_backtest(strategy, history, start_date, end_date)
