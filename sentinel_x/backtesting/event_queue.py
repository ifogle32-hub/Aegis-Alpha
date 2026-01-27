"""
PHASE 1 — EVENT QUEUE

SAFETY: OFFLINE BACKTEST ENGINE
REGRESSION LOCK — DO NOT CONNECT TO LIVE

Priority queue for event-driven backtesting.
Events are processed in strict timestamp order (deterministic).
"""

import heapq
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# SAFETY: OFFLINE BACKTEST ENGINE
# REGRESSION LOCK — DO NOT CONNECT TO LIVE

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


class EventType(Enum):
    """PHASE 3: Canonical event types for event-driven backtesting."""
    MARKET_TICK = "MARKET_TICK"  # Tick-level price update
    BAR_CLOSE = "BAR_CLOSE"  # Bar close event (1m, 5m, 15m, etc.)
    STRATEGY_SIGNAL = "STRATEGY_SIGNAL"  # Strategy generated signal
    ORDER = "ORDER"  # Order placed
    FILL = "FILL"  # Order filled
    PORTFOLIO_UPDATE = "PORTFOLIO_UPDATE"  # Portfolio state change


@dataclass
class BacktestEvent:
    """
    PHASE 3: Canonical event for event-driven backtesting.
    
    SAFETY: events are offline only
    SAFETY: no live execution path
    """
    event_type: EventType
    timestamp: datetime
    symbol: Optional[str] = None
    data: dict = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}
    
    def __lt__(self, other):
        """For priority queue ordering (earliest timestamp first)."""
        return self.timestamp < other.timestamp
    
    def __eq__(self, other):
        """Equality check."""
        if not isinstance(other, BacktestEvent):
            return False
        return (self.event_type == other.event_type and 
                self.timestamp == other.timestamp and
                self.symbol == other.symbol)


class EventQueue:
    """
    PHASE 1: Priority queue for event-driven backtesting.
    
    SAFETY: offline only
    SAFETY: no live execution path
    
    Events are processed in strict timestamp order (deterministic).
    """
    
    def __init__(self):
        """Initialize event queue."""
        self.queue: List[BacktestEvent] = []
        self.processed_count = 0
        self.max_timestamp: Optional[datetime] = None
    
    def push(self, event: BacktestEvent):
        """
        PHASE 1: Push event to queue.
        
        SAFETY: events must be in timestamp order (no future leakage)
        """
        # PHASE 10: Assert no future data leakage
        if self.max_timestamp is not None and event.timestamp < self.max_timestamp:
            raise ValueError(
                f"Event timestamp {event.timestamp} is before max processed timestamp "
                f"{self.max_timestamp} (lookahead bias)"
            )
        
        heapq.heappush(self.queue, event)
    
    def push_many(self, events: List[BacktestEvent]):
        """PHASE 1: Push multiple events to queue."""
        for event in events:
            self.push(event)
    
    def pop(self) -> Optional[BacktestEvent]:
        """PHASE 1: Pop earliest event from queue."""
        if not self.queue:
            return None
        
        event = heapq.heappop(self.queue)
        self.processed_count += 1
        
        # Update max timestamp (for lookahead bias detection)
        if self.max_timestamp is None or event.timestamp > self.max_timestamp:
            self.max_timestamp = event.timestamp
        
        return event
    
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self.queue) == 0
    
    def size(self) -> int:
        """Get queue size."""
        return len(self.queue)
