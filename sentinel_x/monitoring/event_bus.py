"""Async event bus for real-time event streaming."""
import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Optional, Set
from collections import deque
from sentinel_x.monitoring.logger import logger
from sentinel_x.utils import safe_emit


class EventBus:
    """Lightweight async event bus using asyncio.Queue."""
    
    def __init__(self, max_queue_size: int = 1000):
        """
        Initialize event bus.
        
        Args:
            max_queue_size: Maximum queue size (drops oldest if full)
        """
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._subscribers: Set[asyncio.Queue] = set()
        self._subscribers_lock = asyncio.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def publish_safe(self, event: Dict[str, Any]) -> None:
        """
        PHASE 1: Safe event publishing - checks for running loop.
        
        If no loop is running, no-ops safely. Never creates tasks without a loop.
        
        Args:
            event: Event dict (must be JSON-serializable)
        """
        try:
            loop = asyncio.get_running_loop()
            # Loop exists - schedule publish
            asyncio.create_task(self.publish(event))
        except RuntimeError:
            # No running loop - no-op safely
            pass
        except Exception as e:
            logger.error(f"Error in publish_safe: {e}", exc_info=True)
    
    async def publish(self, event: Dict[str, Any]) -> None:
        """
        Publish an event (non-blocking).
        
        Args:
            event: Event dict (must be JSON-serializable)
        """
        try:
            # Add timestamp if not present
            if "timestamp" not in event:
                event["timestamp"] = datetime.utcnow().isoformat() + "Z"
            
            # Try to put event (non-blocking)
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event if queue is full
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(event)
                    logger.warning("Event bus queue full, dropped oldest event")
                except asyncio.QueueEmpty:
                    pass
        except Exception as e:
            logger.error(f"Error publishing event: {e}", exc_info=True)
    
    async def subscribe(self) -> asyncio.Queue:
        """
        Subscribe to events.
        
        Returns:
            Queue that will receive events
        """
        subscriber_queue = asyncio.Queue()
        async with self._subscribers_lock:
            self._subscribers.add(subscriber_queue)
        logger.debug(f"New event subscriber (total: {len(self._subscribers)})")
        return subscriber_queue
    
    async def unsubscribe(self, subscriber_queue: asyncio.Queue) -> None:
        """Unsubscribe from events."""
        async with self._subscribers_lock:
            self._subscribers.discard(subscriber_queue)
        logger.debug(f"Event subscriber removed (total: {len(self._subscribers)})")
    
    async def _broadcast_loop(self) -> None:
        """Internal loop that broadcasts events to all subscribers."""
        while self._running:
            try:
                # Get event from queue (with timeout to allow shutdown)
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Broadcast to all subscribers
                async with self._subscribers_lock:
                    dead_subscribers = []
                    for subscriber in self._subscribers:
                        try:
                            subscriber.put_nowait(event)
                        except asyncio.QueueFull:
                            # Subscriber is slow, skip
                            logger.warning("Subscriber queue full, skipping event")
                        except Exception as e:
                            logger.error(f"Error broadcasting to subscriber: {e}")
                            dead_subscribers.append(subscriber)
                    
                    # Remove dead subscribers
                    for dead in dead_subscribers:
                        self._subscribers.discard(dead)
                
            except Exception as e:
                logger.error(f"Error in event bus broadcast loop: {e}", exc_info=True)
    
    async def start(self) -> None:
        """Start the event bus broadcast loop."""
        if self._running:
            return
        self._running = True
        self._task = safe_emit(self._broadcast_loop())
        logger.info("Event bus started")
    
    async def stop(self) -> None:
        """Stop the event bus broadcast loop."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Event bus stopped")


# Global singleton event bus
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
