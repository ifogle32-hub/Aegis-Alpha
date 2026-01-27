"""
PHASE 2 — STRATEGY PERFORMANCE SNAPSHOT

Read-only strategy metrics collector.

REGRESSION LOCK:
Observability only.
No execution logic.
No trading logic.
No broker mutations.

DO NOT IMPORT INTO ENGINE CORE
"""

from typing import List, Dict, Optional
from datetime import datetime

from sentinel_x.monitoring.logger import logger


def get_strategy_status() -> List[Dict]:
    """
    Get read-only strategy status snapshot.
    
    Returns:
        List of dictionaries, one per strategy, with fields:
        - name: Strategy name
        - status: ACTIVE / PAUSED / DISABLED / AUTO_DISABLED
        - trades_taken: Total number of trades
        - wins: Number of winning trades
        - losses: Number of losing trades
        - realized_pnl: Total realized P&L
        - max_drawdown: Maximum drawdown
        - avg_hold_seconds: Average hold time in seconds
        - last_trade_ts: Timestamp of last trade (or None)
        
    Rules:
        - Source data ONLY from existing strategy_manager fields
        - NO new calculations inside strategies
        - Returns empty list if strategy_manager not available
    """
    try:
        # Get strategy manager from API server (safe access)
        from sentinel_x.api.rork_server import _strategy_manager
        
        if not _strategy_manager:
            return []
        
        strategies_status = []
        
        # Iterate through all registered strategies
        for strategy_name, strategy in _strategy_manager.strategies.items():
            try:
                # Get status
                status = _strategy_manager.status.get(strategy_name, None)
                status_str = status.value if status else "UNKNOWN"
                
                # Get rolling PnL data
                rolling_pnl = _strategy_manager.rolling_pnl.get(strategy_name, [])
                realized_pnl = sum(rolling_pnl) if rolling_pnl else 0.0
                
                # Get rolling trades data
                rolling_trades = _strategy_manager.rolling_trades.get(strategy_name, [])
                trades_taken = len(rolling_trades)
                
                # Calculate wins and losses from rolling trades
                wins = 0
                losses = 0
                last_trade_ts = None
                total_hold_seconds = 0.0
                trade_count = 0
                
                for trade in rolling_trades:
                    # Trade can be dict or object - handle both
                    if isinstance(trade, dict):
                        pnl = trade.get('pnl', 0.0)
                        if pnl > 0:
                            wins += 1
                        elif pnl < 0:
                            losses += 1
                        
                        # Try to get timestamp
                        if 'timestamp' in trade:
                            ts = trade['timestamp']
                            if isinstance(ts, datetime):
                                last_trade_ts = ts
                            elif isinstance(ts, str):
                                try:
                                    last_trade_ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                                except:
                                    pass
                        
                        # Try to get hold time
                        if 'hold_seconds' in trade:
                            total_hold_seconds += float(trade['hold_seconds'])
                            trade_count += 1
                    else:
                        # Try object attributes
                        if hasattr(trade, 'pnl'):
                            pnl = float(getattr(trade, 'pnl', 0.0))
                            if pnl > 0:
                                wins += 1
                            elif pnl < 0:
                                losses += 1
                        
                        if hasattr(trade, 'timestamp'):
                            ts = getattr(trade, 'timestamp', None)
                            if isinstance(ts, datetime):
                                last_trade_ts = ts
                        
                        if hasattr(trade, 'hold_seconds'):
                            total_hold_seconds += float(getattr(trade, 'hold_seconds', 0.0))
                            trade_count += 1
                
                # Calculate average hold time
                avg_hold_seconds = total_hold_seconds / trade_count if trade_count > 0 else 0.0
                
                # Get max drawdown from evaluations if available
                max_drawdown = 0.0
                for eval_key, evaluation in _strategy_manager.evaluations.items():
                    if eval_key.startswith(strategy_name):
                        if hasattr(evaluation, 'max_drawdown'):
                            max_drawdown = max(max_drawdown, abs(float(evaluation.max_drawdown)))
                        elif isinstance(evaluation, dict):
                            max_drawdown = max(max_drawdown, abs(float(evaluation.get('max_drawdown', 0.0))))
                
                # Convert last_trade_ts to ISO string if datetime
                last_trade_ts_str = None
                if last_trade_ts:
                    if isinstance(last_trade_ts, datetime):
                        last_trade_ts_str = last_trade_ts.isoformat()
                    else:
                        last_trade_ts_str = str(last_trade_ts)
                
                strategies_status.append({
                    'name': strategy_name,
                    'status': status_str,
                    'trades_taken': trades_taken,
                    'wins': wins,
                    'losses': losses,
                    'realized_pnl': float(realized_pnl),
                    'max_drawdown': float(max_drawdown),
                    'avg_hold_seconds': float(avg_hold_seconds),
                    'last_trade_ts': last_trade_ts_str
                })
                
            except Exception as e:
                logger.error(f"Error getting status for strategy {strategy_name} (non-fatal): {e}", exc_info=True)
                # Continue with other strategies
                continue
        
        return strategies_status
        
    except Exception as e:
        logger.error(f"Error getting strategy status (non-fatal): {e}", exc_info=True)
        # Return empty list on error
        return []
