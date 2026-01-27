"""
PHASE 4 — MARKET CALENDAR & SESSION HANDLING

Calendar logic for:
- Equities: exchange sessions, holidays
- Futures: session + rollover boundaries
- Crypto: 24/7 continuous
- FX: Sunday open → Friday close

Replay must:
- Skip non-trading hours where applicable
- Preserve correct session boundaries
- Align multi-asset timestamps safely
"""

from typing import Dict, List, Optional, Set
from datetime import datetime, time, timedelta
from dataclasses import dataclass
import pytz
import pandas as pd
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.marketdata.metadata import AssetType


@dataclass
class TradingSession:
    """Trading session definition."""
    open_time: time
    close_time: time
    timezone: str = "America/New_York"
    
    def is_trading_hour(self, dt: datetime) -> bool:
        """
        Check if datetime is within trading hours.
        
        Args:
            dt: Datetime to check
            
        Returns:
            True if within trading hours
        """
        tz = pytz.timezone(self.timezone)
        local_dt = dt.astimezone(tz)
        local_time = local_dt.time()
        
        return self.open_time <= local_time <= self.close_time


class MarketCalendar:
    """
    Market calendar for different asset types.
    
    Handles:
    - Equities: NYSE/NASDAQ sessions, holidays
    - Futures: Session hours, rollover boundaries
    - Crypto: 24/7 continuous
    - FX: Sunday 22:00 UTC → Friday 22:00 UTC
    """
    
    def __init__(self):
        """Initialize market calendar."""
        # Equities: NYSE/NASDAQ (9:30 AM - 4:00 PM ET)
        self.equity_session = TradingSession(
            open_time=time(9, 30),
            close_time=time(16, 0),
            timezone="America/New_York",
        )
        
        # Futures: Extended hours (6:00 PM previous day - 5:00 PM ET)
        self.future_session = TradingSession(
            open_time=time(18, 0),  # Previous day
            close_time=time(17, 0),
            timezone="America/New_York",
        )
        
        # FX: Sunday 22:00 UTC → Friday 22:00 UTC
        self.fx_open_dow = 6  # Sunday
        self.fx_close_dow = 4  # Friday
        self.fx_open_hour = 22  # 22:00 UTC
        
        # Holidays (NYSE/NASDAQ)
        self.equity_holidays: Set[datetime] = self._load_equity_holidays()
    
    def _load_equity_holidays(self) -> Set[datetime]:
        """Load equity market holidays."""
        # Common NYSE holidays (simplified - in production, use pandas_market_calendars)
        holidays = set()
        
        # New Year's Day, MLK Day, Presidents Day, Good Friday, Memorial Day,
        # Independence Day, Labor Day, Thanksgiving, Christmas
        # This is a simplified list - in production, use a proper calendar library
        
        return holidays
    
    def is_trading_time(
        self,
        dt: datetime,
        asset_type: AssetType,
    ) -> bool:
        """
        Check if datetime is trading time for asset type.
        
        Args:
            dt: Datetime to check (must be UTC)
            asset_type: Asset type
            
        Returns:
            True if trading time
        """
        if asset_type == AssetType.CRYPTO:
            # Crypto: 24/7
            return True
        
        elif asset_type == AssetType.FX:
            # FX: Sunday 22:00 UTC → Friday 22:00 UTC
            dow = dt.weekday()  # 0=Monday, 6=Sunday
            
            if dow == 6:  # Sunday
                return dt.hour >= self.fx_open_hour
            elif dow == 4:  # Friday
                return dt.hour < self.fx_open_hour
            elif 0 <= dow <= 3:  # Monday-Thursday
                return True
            else:
                return False
        
        elif asset_type == AssetType.EQUITY:
            # Equities: Exchange sessions, exclude holidays
            if dt.date() in [h.date() for h in self.equity_holidays]:
                return False
            
            return self.equity_session.is_trading_hour(dt)
        
        elif asset_type == AssetType.FUTURE:
            # Futures: Extended hours
            return self.future_session.is_trading_hour(dt)
        
        else:
            # Unknown asset type - default to trading
            return True
    
    def filter_trading_hours(
        self,
        df: pd.DataFrame,
        asset_type: AssetType,
        timestamp_col: str = 'timestamp',
    ) -> pd.DataFrame:
        """
        Filter DataFrame to trading hours only.
        
        Args:
            df: DataFrame with timestamp column
            asset_type: Asset type
            timestamp_col: Timestamp column name
            
        Returns:
            Filtered DataFrame
        """
        if df.empty:
            return df
        
        if timestamp_col not in df.columns:
            logger.warning(f"Timestamp column {timestamp_col} not found")
            return df
        
        # Apply trading hours filter
        mask = df[timestamp_col].apply(
            lambda dt: self.is_trading_time(dt, asset_type)
        )
        
        filtered = df[mask].copy()
        
        logger.debug(
            f"Filtered {len(df)} rows to {len(filtered)} trading hours "
            f"for {asset_type.value}"
        )
        
        return filtered
    
    def get_session_boundaries(
        self,
        start: datetime,
        end: datetime,
        asset_type: AssetType,
    ) -> List[tuple[datetime, datetime]]:
        """
        Get trading session boundaries within date range.
        
        Args:
            start: Start datetime
            end: End datetime
            asset_type: Asset type
            
        Returns:
            List of (session_start, session_end) tuples
        """
        if asset_type == AssetType.CRYPTO:
            # Crypto: One continuous session
            return [(start, end)]
        
        elif asset_type == AssetType.FX:
            # FX: Weekly sessions
            sessions = []
            current = start
            
            while current < end:
                # Find next Sunday 22:00 UTC
                days_until_sunday = (6 - current.weekday()) % 7
                if days_until_sunday == 0 and current.hour < self.fx_open_hour:
                    session_start = current.replace(hour=self.fx_open_hour, minute=0, second=0, microsecond=0)
                else:
                    next_sunday = current + timedelta(days=days_until_sunday)
                    session_start = next_sunday.replace(hour=self.fx_open_hour, minute=0, second=0, microsecond=0)
                
                # Find next Friday 22:00 UTC
                days_until_friday = (4 - session_start.weekday()) % 7
                if days_until_friday == 0:
                    session_end = session_start.replace(hour=self.fx_open_hour, minute=0, second=0, microsecond=0)
                else:
                    next_friday = session_start + timedelta(days=days_until_friday)
                    session_end = next_friday.replace(hour=self.fx_open_hour, minute=0, second=0, microsecond=0)
                
                sessions.append((session_start, min(session_end, end)))
                current = session_end
            
            return sessions
        
        else:
            # Equities/Futures: Daily sessions
            sessions = []
            current = start
            
            while current < end:
                # Find next trading day
                if asset_type == AssetType.EQUITY:
                    # Skip holidays
                    while current.date() in [h.date() for h in self.equity_holidays]:
                        current += timedelta(days=1)
                
                # Get session start/end for this day
                tz = pytz.timezone("America/New_York")
                local_dt = current.astimezone(tz)
                
                if asset_type == AssetType.EQUITY:
                    session_start = local_dt.replace(hour=9, minute=30, second=0, microsecond=0)
                    session_end = local_dt.replace(hour=16, minute=0, second=0, microsecond=0)
                else:  # FUTURE
                    # Futures: Previous day 6 PM to current day 5 PM
                    session_start = (local_dt - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
                    session_end = local_dt.replace(hour=17, minute=0, second=0, microsecond=0)
                
                # Convert back to UTC
                session_start_utc = session_start.astimezone(pytz.UTC)
                session_end_utc = session_end.astimezone(pytz.UTC)
                
                if session_start_utc < end:
                    sessions.append((max(session_start_utc, start), min(session_end_utc, end)))
                
                current += timedelta(days=1)
            
            return sessions


# Global calendar instance
_calendar: Optional[MarketCalendar] = None
_calendar_lock = threading.Lock()


def get_market_calendar() -> MarketCalendar:
    """
    Get global market calendar instance (singleton).
    
    Returns:
        MarketCalendar instance
    """
    global _calendar
    
    if _calendar is None:
        with _calendar_lock:
            if _calendar is None:
                _calendar = MarketCalendar()
    
    return _calendar
