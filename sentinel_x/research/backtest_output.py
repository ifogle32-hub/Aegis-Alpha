"""
PHASE 11 — BACKTEST OUTPUT & INTEGRATION

SAFETY: backtester is isolated from live engine
SAFETY: no live execution path
REGRESSION LOCK — OFFLINE ONLY

Outputs:
- Structured results (JSON / Parquet)
- Trade logs
- Metrics snapshots

Integrates with:
- Strategy Performance Dashboard
- Promotion/Demotion logic (offline evaluation)
- Variant generator scoring
"""

import json
import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

# SAFETY: backtester is isolated from live engine
# SAFETY: no live execution path
# REGRESSION LOCK — OFFLINE ONLY

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


class BacktestOutput:
    """
    PHASE 11: Backtest output and integration.
    
    SAFETY: offline only
    SAFETY: no live execution path
    """
    
    def __init__(self, output_dir: str = "backtest_results"):
        """
        Initialize backtest output handler.
        
        Args:
            output_dir: Directory to save results
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def save_results(self, results: Dict[str, Any], filename: str = None) -> str:
        """
        PHASE 11: Save backtest results to JSON.
        
        SAFETY: offline only
        
        Args:
            results: Backtest results dictionary
            filename: Output filename (auto-generated if None)
        
        Returns:
            Path to saved file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backtest_results_{timestamp}.json"
        
        filepath = self.output_dir / filename
        
        # Convert numpy arrays to lists for JSON serialization
        json_results = self._prepare_for_json(results)
        
        with open(filepath, 'w') as f:
            json.dump(json_results, f, indent=2, default=str)
        
        logger.info(f"Backtest results saved to {filepath}")
        return str(filepath)
    
    def save_trades_parquet(self, trades: List[Dict[str, Any]], filename: str = None) -> str:
        """
        PHASE 11: Save trades to Parquet format.
        
        SAFETY: offline only
        
        Args:
            trades: List of trade dictionaries
            filename: Output filename (auto-generated if None)
        
        Returns:
            Path to saved file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backtest_trades_{timestamp}.parquet"
        
        filepath = self.output_dir / filename
        
        # Convert to DataFrame
        df = pd.DataFrame(trades)
        
        # Save to Parquet
        df.to_parquet(filepath, index=False)
        
        logger.info(f"Trades saved to {filepath}")
        return str(filepath)
    
    def save_equity_curve_parquet(self, equity_curve: List[Dict[str, Any]], filename: str = None) -> str:
        """
        PHASE 11: Save equity curve to Parquet format.
        
        SAFETY: offline only
        
        Args:
            equity_curve: List of equity curve snapshots
            filename: Output filename (auto-generated if None)
        
        Returns:
            Path to saved file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backtest_equity_curve_{timestamp}.parquet"
        
        filepath = self.output_dir / filename
        
        # Convert to DataFrame
        df = pd.DataFrame(equity_curve)
        
        # Save to Parquet
        df.to_parquet(filepath, index=False)
        
        logger.info(f"Equity curve saved to {filepath}")
        return str(filepath)
    
    def _prepare_for_json(self, obj: Any) -> Any:
        """PHASE 11: Prepare object for JSON serialization."""
        import numpy as np
        
        if isinstance(obj, dict):
            return {k: self._prepare_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._prepare_for_json(item) for item in obj]
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (np.integer, np.floating)):
            return float(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        else:
            return obj
    
    def integrate_with_dashboard(self, results: Dict[str, Any], strategy_name: str):
        """
        PHASE 11: Integrate backtest results with Strategy Performance Dashboard.
        
        SAFETY: offline only
        SAFETY: no live execution path
        
        Note: This is a placeholder - full integration would update
        the dashboard with backtest metrics for comparison.
        """
        try:
            # PHASE 11: Store backtest results for dashboard access
            # In production, this would update a metrics store or database
            from sentinel_x.monitoring.metrics_store import get_metrics_store
            
            metrics_store = get_metrics_store()
            if metrics_store:
                # Store backtest metrics (read-only, for dashboard display)
                metrics_store.record_backtest_metrics(
                    strategy_name=strategy_name,
                    metrics=results.get('metrics', {}),
                    timestamp=datetime.now()
                )
                
                logger.info(f"Backtest results integrated with dashboard for {strategy_name}")
        except Exception as e:
            logger.debug(f"Error integrating with dashboard (non-fatal): {e}")
    
    def integrate_with_promotion_logic(self, results: Dict[str, Any], strategy_name: str):
        """
        PHASE 11: Integrate backtest results with promotion/demotion logic.
        
        SAFETY: offline only
        SAFETY: no live execution path
        
        Note: This would feed backtest metrics into the strategy manager
        for offline evaluation (not live execution).
        """
        try:
            # PHASE 11: Feed backtest results to strategy manager (offline evaluation)
            from sentinel_x.intelligence.strategy_manager import get_strategy_manager
            
            strategy_manager = get_strategy_manager()
            if strategy_manager:
                # Store backtest metrics for offline evaluation
                # This does NOT affect live execution - only used for governance
                backtest_metrics = {
                    'backtest_sharpe': results.get('metrics', {}).get('sharpe', 0.0),
                    'backtest_max_drawdown': results.get('max_drawdown', 0.0),
                    'backtest_total_pnl': results.get('total_pnl', 0.0),
                    'backtest_trades_count': len(results.get('trades', [])),
                    'backtest_timestamp': datetime.now().isoformat()
                }
                
                # Store in strategy manager (offline only)
                if hasattr(strategy_manager, 'backtest_metrics'):
                    strategy_manager.backtest_metrics[strategy_name] = backtest_metrics
                
                logger.info(f"Backtest results integrated with promotion logic for {strategy_name} (offline only)")
        except Exception as e:
            logger.debug(f"Error integrating with promotion logic (non-fatal): {e}")
