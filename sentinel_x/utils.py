"""Utility functions for async operations."""
import asyncio
import threading


def safe_emit(coro):
    """
    Safely emit a coroutine as a task.
    
    If there's a running event loop, creates a task in it.
    If no loop is running, runs the coroutine in a background thread.
    
    Args:
        coro: Coroutine to execute
    
    Returns:
        Task if created in a running loop, None otherwise
    """
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(coro)
    except RuntimeError:
        # No loop → fire-and-forget in background thread
        threading.Thread(
            target=lambda: asyncio.run(coro),
            daemon=True
        ).start()
        return None
