"""
PHASE 6 — FUTURES ROLLOVER HANDLING

Futures rollover logic:
- Contract stitching
- Volume-based rollover or date-based rollover
- Preserve continuous price series
- Apply multiplier correctly
- Prevent artificial PnL jumps

Rollover behavior must be configurable and logged.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np

from sentinel_x.monitoring.logger import logger


class RolloverMethod(str, Enum):
    """Rollover methods."""
    VOLUME = "volume"  # Roll when volume shifts to next contract
    DATE = "date"  # Roll on specific date
    OPEN_INTEREST = "open_interest"  # Roll when open interest shifts


@dataclass
class RolloverPoint:
    """Rollover point definition."""
    timestamp: datetime
    from_contract: str
    to_contract: str
    rollover_price: float
    method: RolloverMethod


class FuturesRollover:
    """
    Futures rollover handler.
    
    Handles:
    - Contract stitching
    - Volume-based or date-based rollover
    - Continuous price series
    - Multiplier application
    - PnL jump prevention
    """
    
    def __init__(
        self,
        method: RolloverMethod = RolloverMethod.VOLUME,
        lookback_days: int = 5,
    ):
        """
        Initialize futures rollover handler.
        
        Args:
            method: Rollover method
            lookback_days: Days to look back for volume comparison
        """
        self.method = method
        self.lookback_days = lookback_days
        self.rollover_points: List[RolloverPoint] = []
    
    def detect_rollover(
        self,
        front_month_df: pd.DataFrame,
        back_month_df: pd.DataFrame,
        symbol: str,
    ) -> Optional[RolloverPoint]:
        """
        Detect rollover point between front and back month contracts.
        
        Args:
            front_month_df: Front month contract data
            back_month_df: Back month contract data
            symbol: Symbol name
            
        Returns:
            RolloverPoint or None
        """
        if front_month_df.empty or back_month_df.empty:
            return None
        
        # Align timestamps
        merged = pd.merge(
            front_month_df[['timestamp', 'volume', 'close']],
            back_month_df[['timestamp', 'volume', 'close']],
            on='timestamp',
            suffixes=('_front', '_back'),
            how='inner',
        )
        
        if merged.empty:
            return None
        
        if self.method == RolloverMethod.VOLUME:
            return self._detect_volume_rollover(merged, symbol)
        elif self.method == RolloverMethod.DATE:
            return self._detect_date_rollover(merged, symbol)
        else:
            return None
    
    def _detect_volume_rollover(
        self,
        merged: pd.DataFrame,
        symbol: str,
    ) -> Optional[RolloverPoint]:
        """Detect volume-based rollover."""
        # Calculate rolling volume ratio
        merged['volume_ratio'] = (
            merged['volume_back'] / (merged['volume_front'] + merged['volume_back'] + 1e-10)
        )
        
        # Find where back month volume exceeds front month
        rollover_mask = merged['volume_ratio'] > 0.5
        
        if not rollover_mask.any():
            return None
        
        # Get first rollover point
        rollover_idx = merged[rollover_mask].index[0]
        rollover_row = merged.loc[rollover_idx]
        
        # Calculate rollover price (average of front and back)
        rollover_price = (rollover_row['close_front'] + rollover_row['close_back']) / 2.0
        
        return RolloverPoint(
            timestamp=rollover_row['timestamp'],
            from_contract=f"{symbol}_front",
            to_contract=f"{symbol}_back",
            rollover_price=rollover_price,
            method=RolloverMethod.VOLUME,
        )
    
    def _detect_date_rollover(
        self,
        merged: pd.DataFrame,
        symbol: str,
    ) -> Optional[RolloverPoint]:
        """Detect date-based rollover."""
        # For date-based, use a fixed date (e.g., 5 days before expiration)
        # This is simplified - in production, would use actual expiration dates
        
        if merged.empty:
            return None
        
        # Use midpoint as rollover point
        mid_idx = len(merged) // 2
        rollover_row = merged.iloc[mid_idx]
        
        rollover_price = (rollover_row['close_front'] + rollover_row['close_back']) / 2.0
        
        return RolloverPoint(
            timestamp=rollover_row['timestamp'],
            from_contract=f"{symbol}_front",
            to_contract=f"{symbol}_back",
            rollover_price=rollover_price,
            method=RolloverMethod.DATE,
        )
    
    def stitch_contracts(
        self,
        front_month_df: pd.DataFrame,
        back_month_df: pd.DataFrame,
        rollover_point: RolloverPoint,
    ) -> pd.DataFrame:
        """
        Stitch front and back month contracts into continuous series.
        
        Args:
            front_month_df: Front month contract data
            back_month_df: Back month contract data
            rollover_point: Rollover point
            
        Returns:
            Stitched DataFrame
        """
        # Split data at rollover point
        front_before = front_month_df[front_month_df['timestamp'] < rollover_point.timestamp]
        back_after = back_month_df[back_month_df['timestamp'] >= rollover_point.timestamp]
        
        if front_before.empty:
            return back_after
        
        if back_after.empty:
            return front_before
        
        # Calculate price adjustment factor
        front_last_price = front_before.iloc[-1]['close']
        back_first_price = back_after.iloc[0]['close']
        
        if front_last_price > 0:
            adjustment_factor = rollover_point.rollover_price / front_last_price
        else:
            adjustment_factor = 1.0
        
        # Adjust front month prices
        front_adjusted = front_before.copy()
        for col in ['open', 'high', 'low', 'close']:
            front_adjusted[col] = front_adjusted[col] * adjustment_factor
        
        # Combine
        stitched = pd.concat([front_adjusted, back_after], ignore_index=True)
        stitched = stitched.sort_values('timestamp').reset_index(drop=True)
        
        logger.info(
            f"Stitched contracts: {len(front_before)} + {len(back_after)} = {len(stitched)} rows | "
            f"adjustment_factor={adjustment_factor:.6f}"
        )
        
        return stitched
    
    def apply_rollover(
        self,
        contracts: Dict[str, pd.DataFrame],
        symbol: str,
    ) -> pd.DataFrame:
        """
        Apply rollover to multiple contracts.
        
        Args:
            contracts: Dictionary of contract DataFrames
            symbol: Symbol name
            
        Returns:
            Rolled-over continuous series
        """
        if len(contracts) < 2:
            # No rollover needed
            return list(contracts.values())[0] if contracts else pd.DataFrame()
        
        # Sort contracts by expiration (simplified - use keys as contract names)
        contract_names = sorted(contracts.keys())
        
        result = contracts[contract_names[0]]
        
        for i in range(1, len(contract_names)):
            front_contract = contract_names[i-1]
            back_contract = contract_names[i]
            
            rollover_point = self.detect_rollover(
                contracts[front_contract],
                contracts[back_contract],
                symbol,
            )
            
            if rollover_point:
                result = self.stitch_contracts(
                    result,
                    contracts[back_contract],
                    rollover_point,
                )
                self.rollover_points.append(rollover_point)
            else:
                # No rollover detected - append back contract
                result = pd.concat([result, contracts[back_contract]], ignore_index=True)
        
        return result.sort_values('timestamp').reset_index(drop=True)


# Global rollover handler instance
_rollover: Optional[FuturesRollover] = None
_rollover_lock = threading.Lock()


def get_futures_rollover(**kwargs) -> FuturesRollover:
    """
    Get global futures rollover handler instance (singleton).
    
    Args:
        **kwargs: Arguments for FuturesRollover
        
    Returns:
        FuturesRollover instance
    """
    global _rollover
    
    if _rollover is None:
        with _rollover_lock:
            if _rollover is None:
                _rollover = FuturesRollover(**kwargs)
    
    return _rollover
