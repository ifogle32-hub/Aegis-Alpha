"""
Broker wiring module for Sentinel X.

────────────────────────────────────────
PHASE 1 — BROKER EXECUTION WIRING (PAPER ONLY)
────────────────────────────────────────

SAFETY LOCK:
Broker execution is explicit, never implicit.
PAPER trading requires explicit wiring via wire_brokers().
LIVE trading requires deliberate human intent (environment + code unlock).
UI is observer-only - no execution capability exposed.

ABSOLUTE PRIORITIES (NON-NEGOTIABLE):
- PAPER trading is allowed ONLY when explicitly wired
- LIVE trading must be cryptographically and programmatically impossible unless explicitly unlocked
- No implicit broker connections
- All execution paths must be safe, explicit, and reversible

This module provides explicit broker wiring - DO NOT auto-connect based on 
environment variables alone.

REGRESSION LOCK:
- Engine boots without broker (wire_brokers() failure is non-fatal)
- PAPER requires explicit wiring (no auto-connection)
- LIVE requires explicit env unlock (hard guard in router.execute())
"""

from typing import Optional
from sentinel_x.execution.router import OrderRouter
from sentinel_x.execution.alpaca_executor import AlpacaExecutor
from sentinel_x.execution.paper_executor import PaperExecutor, get_executor
from sentinel_x.core.engine_mode import EngineMode
from sentinel_x.core.config import get_config
from sentinel_x.data.storage import get_storage
from sentinel_x.monitoring.logger import logger


def wire_brokers(router: OrderRouter, strategy_manager=None) -> None:
    """
    Explicit broker wiring.
    PAPER only. LIVE is forbidden here.
    
    This function explicitly wires brokers as execution backends.
    It does NOT auto-connect based on environment variables alone - the wiring
    must be called explicitly.
    
    Args:
        router: OrderRouter instance to wire executors to
        strategy_manager: Optional strategy manager for paper executor
        
    Safety:
        - Only wires PAPER mode executors
        - LIVE mode is explicitly forbidden
        - Connection failures are logged but do not raise
        - Router boot is never blocked by broker connection issues
        - Always ensures fallback paper executor is registered
    """
    try:
        config = get_config()
        
        # PHASE 1: Always register fallback paper executor first (safety)
        if router.paper_executor is None:
            logger.info("Registering fallback paper executor...")
            paper_executor = get_executor(config.initial_capital, strategy_manager)
            router.register_executor(EngineMode.PAPER, paper_executor)
            logger.info("Fallback paper executor registered")
        
        # CRITICAL: Only wire Alpaca if PAPER mode credentials exist
        # Do not auto-connect - wiring must be explicit
        if not config.alpaca_api_key or not config.alpaca_secret_key:
            logger.info("Alpaca credentials not configured - using simulated paper executor only")
            return
        
        # CRITICAL: Verify base URL is PAPER endpoint (safety guard)
        if "paper-api" not in config.alpaca_base_url.lower():
            logger.critical(
                f"LIVE broker URL detected: {config.alpaca_base_url} - "
                f"PAPER wiring is FORBIDDEN for LIVE endpoints"
            )
            return
        
        logger.info("Wiring Alpaca PAPER executor...")
        
        # Initialize Alpaca executor (enforces paper=True internally)
        storage = get_storage()
        alpaca_paper_executor = AlpacaExecutor(config, storage)
        
        # Attempt connection (non-blocking - failure doesn't prevent router boot)
        if alpaca_paper_executor.connect():
            logger.info("Alpaca PAPER executor connected successfully")
            
            # Register executor for PAPER mode (overrides fallback paper executor)
            router.register_executor(EngineMode.PAPER, alpaca_paper_executor)
            logger.info("Alpaca PAPER executor registered with router (primary)")
        else:
            logger.warning(
                "Alpaca PAPER connection failed - using fallback simulated paper executor."
            )
            # Do not register if connection failed - explicit wiring requires successful connection
            # Fallback paper executor remains active
            
    except Exception as e:
        logger.critical(
            f"Failed to wire brokers: {e}",
            exc_info=True
        )
        # Do not raise - router boot must never be blocked
        # Fallback paper executor should already be registered
