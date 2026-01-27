"""
Execution Adapter Layer

PHASE 1-6 — EXECUTION ADAPTER WITH SAFETY GUARDS

Provides broker-agnostic execution interface with centralized safety guards.
Execution is impossible unless engine is ARMED and all conditions pass.
"""

from api.execution.base import ExecutionRequest, ExecutionResult, ExecutionAdapter
from api.execution.guard import ExecutionGuard, get_execution_guard
from api.execution.router import ExecutionRouter, get_execution_router
from api.execution.alpaca_paper import AlpacaPaperExecutor

__all__ = [
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionAdapter",
    "ExecutionGuard",
    "get_execution_guard",
    "ExecutionRouter",
    "get_execution_router",
    "AlpacaPaperExecutor",
]
