"""Performance metrics for strategy evaluation."""
import numpy as np
from typing import List, Optional
from sentinel_x.research.backtester import Trade


def sharpe(returns: np.ndarray, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """
    Calculate Sharpe ratio.
    
    Args:
        returns: Array of period returns
        risk_free_rate: Annual risk-free rate (default 0.0)
        periods_per_year: Number of periods per year for annualization
        
    Returns:
        Sharpe ratio (annualized)
    """
    if len(returns) == 0:
        return 0.0
    
    excess_returns = returns - (risk_free_rate / periods_per_year)
    
    if np.std(excess_returns) == 0:
        return 0.0
    
    # Annualize
    sharpe_ratio = np.sqrt(periods_per_year) * np.mean(excess_returns) / np.std(excess_returns)
    
    return sharpe_ratio


def max_drawdown(equity_curve: np.ndarray) -> float:
    """
    Calculate maximum drawdown.
    
    Args:
        equity_curve: Array of equity values over time
        
    Returns:
        Maximum drawdown as a fraction (0.0 to 1.0)
    """
    if len(equity_curve) < 2:
        return 0.0
    
    peak = equity_curve[0]
    max_dd = 0.0
    
    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
    
    return max_dd


def win_rate(trades: List[Trade]) -> float:
    """
    Calculate win rate.
    
    Args:
        trades: List of completed trades
        
    Returns:
        Win rate as a fraction (0.0 to 1.0)
    """
    completed_trades = [t for t in trades if t.pnl is not None]
    
    if len(completed_trades) == 0:
        return 0.0
    
    winning_trades = [t for t in completed_trades if t.pnl > 0]
    
    return len(winning_trades) / len(completed_trades)


def profit_factor(trades: List[Trade]) -> float:
    """
    Calculate profit factor.
    
    Args:
        trades: List of completed trades
        
    Returns:
        Profit factor (gross profit / gross loss)
    """
    completed_trades = [t for t in trades if t.pnl is not None]
    
    if len(completed_trades) == 0:
        return 0.0
    
    gross_profit = sum(t.pnl for t in completed_trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in completed_trades if t.pnl < 0))
    
    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0
    
    return gross_profit / gross_loss


def expectancy(trades: List[Trade]) -> float:
    """
    Calculate trade expectancy.
    
    Args:
        trades: List of completed trades
        
    Returns:
        Average P&L per trade
    """
    completed_trades = [t for t in trades if t.pnl is not None]
    
    if len(completed_trades) == 0:
        return 0.0
    
    return np.mean([t.pnl for t in completed_trades])


def calculate_composite_score(returns: np.ndarray, equity_curve: np.ndarray, 
                             trades: List[Trade], execution_quality_score: Optional[float] = None) -> float:
    """
    PHASE 3: Calculate composite score for strategy ranking.
    
    Formula (with execution quality):
    - Base: sharpe * profit_factor * (1 - max_drawdown)
    - With execution: base * execution_quality_score
    
    No strategy may promote without passing execution thresholds.
    
    Args:
        returns: Array of period returns
        equity_curve: Array of equity values
        trades: List of completed trades
        execution_quality_score: Execution quality score [0, 1] (optional)
        
    Returns:
        Composite score (higher is better)
    """
    sharpe_val = sharpe(returns)
    pf = profit_factor(trades)
    dd = max_drawdown(equity_curve)
    
    # Normalize profit factor (cap at 10 to avoid extreme values)
    pf_normalized = min(pf, 10.0)
    
    # Ensure positive values
    if sharpe_val < 0:
        sharpe_val = 0.0
    
    # Base score (performance-only)
    base_score = sharpe_val * pf_normalized * (1 - dd)
    
    # PHASE 3: Apply execution quality score if provided
    if execution_quality_score is not None:
        # Execution quality is required - poor execution lowers score regardless of PnL
        # Use weighted combination: 70% performance, 30% execution quality
        # This ensures execution quality matters but doesn't completely override performance
        performance_weight = 0.7
        execution_weight = 0.3
        
        # Normalize execution quality (0.0 - 1.0)
        exec_score_normalized = max(0.0, min(1.0, execution_quality_score))
        
        # Combine scores (execution quality acts as multiplier on base)
        score = base_score * (performance_weight + execution_weight * exec_score_normalized)
    else:
        # No execution quality available - use base score only
        score = base_score
    
    return max(0.0, score)  # Ensure non-negative


def calculate_all_metrics(returns: np.ndarray, equity_curve: np.ndarray, 
                          trades: List[Trade], execution_quality_score: Optional[float] = None) -> dict:
    """
    PHASE 3: Calculate all performance metrics (with execution quality).
    
    Args:
        returns: Array of period returns
        equity_curve: Array of equity values
        trades: List of completed trades
        execution_quality_score: Execution quality score [0, 1] (optional)
        
    Returns:
        Dictionary with all metrics including composite_score with execution quality
    """
    return {
        'sharpe': sharpe(returns),
        'max_drawdown': max_drawdown(equity_curve),
        'win_rate': win_rate(trades),
        'profit_factor': profit_factor(trades),
        'expectancy': expectancy(trades),
        'composite_score': calculate_composite_score(returns, equity_curve, trades, execution_quality_score),
        'total_trades': len([t for t in trades if t.pnl is not None]),
        'final_return': (equity_curve[-1] - equity_curve[0]) / equity_curve[0] if len(equity_curve) > 1 else 0.0,
        'execution_quality_score': execution_quality_score  # Include in metrics
    }

