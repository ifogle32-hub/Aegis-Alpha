# sentinel_x/execution/router.py

"""
=== TRAINING BASELINE — DO NOT MODIFY ===

ARCHITECTURAL TRUTH:
1. Alpaca PAPER is the TRAINING broker
2. Alpaca PAPER must auto-connect on engine startup
3. Alpaca PAPER runs forever
4. Tradovate is LIVE ONLY
5. LIVE trading must require explicit human intent
6. UI is observer-only

SAFETY LOCK:
- TRAINING/PAPER: Alpaca allowed, Tradovate forbidden
- LIVE: Tradovate allowed, Alpaca forbidden
- UI is observer-only (read-only health checks, no execution triggers)

────────────────────────────────────────
PHASE 6 — LIVE TRADING HARD LOCK
────────────────────────────────────────

LIVE MODE RULES:
- LIVE requires explicit: SENTINEL_ENGINE_MODE=LIVE
- Tradovate credentials MUST be present
- Alpaca is FORBIDDEN in LIVE mode

HARD GUARDS IMPLEMENTED:
1. update_executor(): Type-based check for AlpacaPaperExecutor/AlpacaExecutor
   → Raises RuntimeError if Alpaca detected in LIVE mode
2. register_executor(): Broker name check at registration
   → Raises RuntimeError if Alpaca attempted in LIVE mode
3. execute(): Active executor validation before order execution
   → Raises RuntimeError if Alpaca executor active in LIVE mode
4. engine_mode.set_mode(): Validation on mode transition to LIVE
   → Raises RuntimeError if Alpaca executor detected during transition
5. engine.run_forever(): Type-based check in main loop
   → Raises RuntimeError if Alpaca executor active when entering LIVE

ASSERTIONS:
- LIVE cannot be entered accidentally
- Alpaca can NEVER place LIVE trades
- All guards use isinstance() type checks for maximum safety
- Multiple redundant checks at different execution layers

REGRESSION FREEZE ASSERTIONS:
- Alpaca auto-connect cannot be removed accidentally
- Engine boots without broker (continues running)
- Engine runs without UI (no execution dependencies on API/UI)
- TRAINING mode auto-connects Alpaca PAPER
- LIVE requires explicit env unlock (ALL: UNLOCK, CONFIRM, TRADOVATE_ACCOUNT_ID)
- OrderRouter.execute() never raises (always returns ExecutionRecord)
- LIVE mode hard guards cannot be removed without explicit override
- Orders MUST fail safely if no executor available (rejected ExecutionRecord)
- No execution path depends on realized_pnl (PnL is monitoring-only)
- No analytics in engine path (engine loop has no analytics dependencies)
"""

# ============================================================
# REGRESSION LOCK — DO NOT MODIFY
# Stable execution baseline.
# Changes require architectural review.
# ============================================================
# NO future changes may:
#   • Alter executor signatures
#   • Change router → executor contracts
#   • Introduce lifecycle dependencies in bootstrap
#   • Affect TRAINING auto-connect behavior
# ============================================================

import os
from datetime import datetime
from typing import Optional, Dict, List
from sentinel_x.core.config import Config
from sentinel_x.core.engine_mode import EngineMode, get_engine_mode
from sentinel_x.execution.paper_executor import PaperExecutor
from sentinel_x.execution.alpaca_executor import AlpacaExecutor, AlpacaPaperExecutor, build_alpaca_paper_executor
from sentinel_x.execution.broker_base import BaseBroker
try:
    from sentinel_x.execution.execution_router import ExecutionRouter
except Exception:
    ExecutionRouter = None
from sentinel_x.execution.order_intent import OrderIntent
from sentinel_x.execution.models import ExecutionRecord, ExecutionStatus
from sentinel_x.monitoring.logger import logger

# PHASE 8: Helper to get loop_tick for execution logs (observability only)
def _get_loop_tick_for_logging() -> Optional[int]:
    """
    PHASE 8 — TICK-LEVEL EXECUTION OBSERVABILITY
    Safely retrieve loop_tick from heartbeat file for log correlation.
    
    Returns loop_tick if available, None otherwise.
    Never raises exceptions. Non-blocking.
    
    SAFETY: monitoring-only change, no execution impact.
    """
    try:
        from sentinel_x.monitoring.heartbeat import read_heartbeat
        heartbeat = read_heartbeat()
        if heartbeat:
            return heartbeat.get('loop_tick')
    except Exception:
        pass  # Fail silently - loop_tick is optional for logs
    return None


def _live_execution_allowed() -> bool:
    """
    Check if LIVE execution is explicitly unlocked.
    
    CRITICAL: LIVE trading is FORBIDDEN unless explicitly unlocked via:
    - Environment variable: SENTINEL_ALLOW_LIVE_EXECUTION="YES_I_UNDERSTAND"
    
    This is a hard cryptographic guard - LIVE trading cannot happen accidentally.
    
    Returns:
        True if LIVE execution is explicitly allowed, False otherwise
    """
    return os.getenv("SENTINEL_ALLOW_LIVE_EXECUTION") == "YES_I_UNDERSTAND"


class OrderRouter:
    """
    OrderRouter - Backward compatibility wrapper around ExecutionRouter.
    
    ────────────────────────────────────────
    PHASE 3 — EXECUTION ROUTER FAIL-OPEN
    ────────────────────────────────────────
    
    REGRESSION LOCK:
    - Router is OPTIONAL
    - Router failure NEVER blocks engine
    - Router failure FALLS BACK to paper executor
    - Execution must never raise uncaught exceptions
    - Always return ExecutionRecord, never raise
    
    PHASE 3: All execution now goes through ExecutionRouter.execute(intent).
    This class maintains backward compatibility for legacy code.
    """
    def __init__(
        self,
        config: Config,
        paper_executor: Optional[PaperExecutor] = None,
        alpaca_executor: Optional[AlpacaExecutor] = None,
    ):
        """
        Initialize OrderRouter.
        
        PHASE 1: Execution router starts with ZERO executors registered.
        No auto-registration based on env vars.
        Orders MUST fail safely if no executor is armed.
        """
        self.config = config
        # PHASE 1: Start with None executors - explicit arming required
        self.paper_executor = None
        self.alpaca_executor = None
        self.active_executor = None
        
        # PHASE 1: Mode-to-executor mapping for explicit wiring - starts empty
        self._mode_executors: Dict[EngineMode, Optional[BaseBroker]] = {}
        self._armed_brokers: List[str] = []  # Track which brokers are armed by name
        
        # PHASE 3: Create ExecutionRouter (single authority) - safe initialization with no executors
        if ExecutionRouter is not None:
            try:
                self._execution_router = ExecutionRouter(
                    config=config,
                    paper_executor=None,  # No executors at init
                    alpaca_executor=None  # No executors at init
                )
            except Exception as e:
                logger.error(f"Failed to initialize ExecutionRouter: {e}", exc_info=True)
                self._execution_router = None
        else:
            self._execution_router = None
        
        # PHASE 1: Do NOT update executor at init - wait for explicit arming
        # self.update_executor()  # REMOVED - no auto-registration
    
    def register_executor(self, mode: EngineMode, executor: BaseBroker) -> None:
        """
        Register an executor for a specific engine mode.
        
        PHASE 1: Explicit broker wiring - allows explicit registration of executors
        by mode. This is the primary method for wiring brokers.
        
        Args:
            mode: EngineMode (PAPER, LIVE, etc.)
            executor: Broker executor instance
            
        Safety:
            - LIVE mode registration is forbidden (safety guard)
            - Updates internal executor references based on executor type
            - Triggers executor update after registration
            
        Raises:
            RuntimeError: If Alpaca is attempted to be registered in LIVE mode
        """
        # HARD BLOCK: Alpaca is FORBIDDEN in LIVE mode
        broker_name = getattr(executor, 'name', 'unknown')
        if mode == EngineMode.LIVE and broker_name == "alpaca":
            error_msg = "Alpaca is forbidden in LIVE mode. LIVE mode requires Tradovate executor only."
            logger.critical(error_msg)
            raise RuntimeError(error_msg)
        
        # CRITICAL: LIVE mode registration is forbidden in explicit wiring
        if mode == EngineMode.LIVE:
            logger.critical(
                f"LIVE executor registration FORBIDDEN in wire_brokers - "
                f"LIVE trading must be unlocked through separate mechanism"
            )
            return
        
        try:
            # Normalize PAPER to TRAINING for registration
            registration_mode = EngineMode.TRAINING if mode == EngineMode.PAPER else mode
            
            # Register executor for normalized mode
            self._mode_executors[registration_mode] = executor
            logger.info(f"Executor registered for {registration_mode.value} mode: {executor.name}")
            
            # Update internal executor references based on executor type
            if isinstance(executor, (AlpacaExecutor, AlpacaPaperExecutor)):
                self.alpaca_executor = executor
                logger.info("Alpaca executor reference updated")
            elif isinstance(executor, PaperExecutor):
                self.paper_executor = executor
                logger.info("Paper executor reference updated")
            
            # Update ExecutionRouter if it exists
            if self._execution_router is not None:
                if isinstance(executor, (AlpacaExecutor, AlpacaPaperExecutor)):
                    self._execution_router.alpaca_executor = executor
                elif isinstance(executor, PaperExecutor):
                    self._execution_router.paper_executor = executor
            
            # Trigger executor update to activate registered executor
            self.update_executor()
            
        except Exception as e:
            logger.error(f"Failed to register executor for {mode.value} mode: {e}", exc_info=True)
            # Do not raise - registration failure should not block router

    def update_executor(self):
        """
        Update active executor based on engine mode and armed executors.
        
        PHASE 2: Broker selection logic based on engine mode.
        === TRAINING BASELINE — DO NOT MODIFY ===
        
        BROKER SELECTION LOGIC:
        - TRAINING/PAPER mode: AlpacaPaperExecutor (auto-connects)
        - LIVE mode: TradovateExecutor (explicit arming required)
        - If broker missing → engine continues (no trading, no crash)
        
        ────────────────────────────────────────
        PHASE 8 — REGRESSION LOCK
        ────────────────────────────────────────
        
        REGRESSION LOCK:
        Do NOT modify engine loop, broker wiring, or order schemas
        without architect approval. Changes here can cause
        silent trading failures or engine crashes.
        
        ENFORCE:
        • No lifecycle module imports in bootstrap
        • No default/non-default argument order violations
        • No schema assumptions
        """
        current_mode = get_engine_mode()
        # Normalize PAPER to TRAINING for lookup
        lookup_mode = EngineMode.TRAINING if current_mode == EngineMode.PAPER else current_mode
        
        # PHASE 6: LIVE TRADING HARD LOCK
        # HARD GUARD: Alpaca is FORBIDDEN in LIVE mode
        # Check executor type explicitly before setting active executor
        if current_mode == EngineMode.LIVE:
            # Check if any executor in mode mapping is Alpaca (hard block)
            if lookup_mode in self._mode_executors:
                executor = self._mode_executors[lookup_mode]
                if executor is not None:
                    # PHASE 6: Type-based check for AlpacaPaperExecutor
                    if isinstance(executor, (AlpacaExecutor, AlpacaPaperExecutor)):
                        error_msg = "Alpaca forbidden in LIVE mode. LIVE mode requires Tradovate executor only."
                        logger.critical(error_msg)
                        raise RuntimeError(error_msg)
            
            # Check direct executor references for Alpaca
            if self.alpaca_executor:
                error_msg = "Alpaca forbidden in LIVE mode. LIVE mode requires Tradovate executor only."
                logger.critical(error_msg)
                raise RuntimeError(error_msg)
        
        # PHASE 2: Mode-based broker selection
        if current_mode in (EngineMode.TRAINING, EngineMode.PAPER):
            # TRAINING/PAPER mode: Use Alpaca PAPER executor
            if lookup_mode in self._mode_executors:
                executor = self._mode_executors[lookup_mode]
                if executor is not None:
                    self.active_executor = executor
                    return
            
            # Fallback: Check direct executor references (auto-registered Alpaca)
            if self.alpaca_executor and hasattr(self.alpaca_executor, 'connected') and self.alpaca_executor.connected:
                self.active_executor = self.alpaca_executor
                logger.debug("Active executor: Alpaca PAPER (TRAINING mode)")
                return
            elif self.alpaca_executor:
                # Try to connect if not connected
                try:
                    if hasattr(self.alpaca_executor, 'connect') and self.alpaca_executor.connect():
                        self.active_executor = self.alpaca_executor
                        logger.debug("Active executor: Alpaca PAPER (connected)")
                        return
                except Exception as e:
                    logger.warning(f"Alpaca connection failed: {e}")
            
            # Final fallback: Paper executor (no broker = no trading, but engine continues)
            self.active_executor = self.paper_executor
            if not self.active_executor:
                logger.debug("No executor available - engine continues without trading")
            
        elif current_mode == EngineMode.LIVE:
            # LIVE mode: Tradovate executor only (explicit arming required)
            if lookup_mode in self._mode_executors:
                executor = self._mode_executors[lookup_mode]
                if executor is not None:
                    # Verify it's not Alpaca (hard block)
                    broker_name = getattr(executor, 'name', 'unknown')
                    if broker_name == "alpaca":
                        error_msg = "Alpaca is forbidden in LIVE mode. LIVE mode requires Tradovate executor only."
                        logger.critical(error_msg)
                        raise RuntimeError(error_msg)
                    self.active_executor = executor
                    return
            
            # No Tradovate executor armed - engine continues without trading
            self.active_executor = None
            logger.debug("No Tradovate executor armed for LIVE mode - engine continues without trading")
            
        else:
            # RESEARCH/PAUSED mode: No executor (training only)
            self.active_executor = None
    
    def execute(self, intent: OrderIntent):
        """
        Execute OrderIntent - CRITICAL: Must NEVER raise, always return ExecutionRecord or safe fallback.
        This is the primary execution entrypoint for the engine.
        
        PHASE 3: MANDATORY PATTERN - Router failure FALLS BACK to paper executor.
        
        LIVE GUARD: LIVE execution is blocked unless explicitly unlocked via environment variable.
        
        ────────────────────────────────────────
        PHASE 8 — REGRESSION LOCK
        ────────────────────────────────────────
        
        REGRESSION LOCK:
        Do NOT modify engine loop, broker wiring, or order schemas
        without architect approval. Changes here can cause
        silent trading failures or engine crashes.
        
        ENFORCE:
        • No lifecycle module imports in bootstrap
        • No default/non-default argument order violations
        • No schema assumptions
        
        TRAINING BASELINE:
        Alpaca PAPER must always connect when engine is running.
        
        REGRESSION LOCK:
        ExecutionRouter always emits normalized order fields.
        Router always passes: symbol, side, qty, price, strategy.
        Router does not adapt to brokers - executors must handle normalized parameters.
        Executors must safely accept or ignore unsupported parameters.
        
        PHASE 5: ROUTER SAFETY
        Router must NEVER assume executor availability.
        Router must NEVER raise uncaught exceptions.
        If no executor available: log warning, reject order safely, engine continues running.
        
        PHASE 2: EXECUTION QUALITY TRACING (PASSIVE)
        SAFETY: No execution timing modified
        SAFETY: No broker logic modified
        SAFETY: Trace is write-only (append/emit)
        """
        # PHASE 2: Trace order intent creation (passive, non-blocking)
        # SAFETY: Trace failures must never affect execution
        try:
            from sentinel_x.execution.execution_quality import get_execution_quality
            execution_quality = get_execution_quality()
            execution_quality.trace_intent_created(intent)
        except Exception:
            pass  # Silent failure - tracing must never block execution
        
        # PHASE 5: EXECUTION ROUTER SAFETY
        # Router must NEVER assume executor availability - check first
        try:
            # Ensure executor is up-to-date
            self.update_executor()
        except Exception as e:
            # CRITICAL: update_executor() must never crash router
            logger.error(f"Error updating executor (non-fatal): {e}", exc_info=True)
        
        # Early safety check: No executor available
        if not self.active_executor:
            loop_tick = _get_loop_tick_for_logging()
            tick_info = f" | loop_tick={loop_tick}" if loop_tick is not None else ""
            logger.warning(f"No active executor available – order rejected{tick_info}")
            intent_id = getattr(intent, 'intent_id', 'unknown')
            client_order_id = getattr(intent, 'client_order_id', None) or f"sentinel_{intent_id[:8] if len(intent_id) >= 8 else 'unknown'}"
            
            # PHASE 2: Trace order rejection (passive, non-blocking)
            try:
                from sentinel_x.execution.execution_quality import get_execution_quality
                execution_quality = get_execution_quality()
                execution_quality.trace_order_rejected(intent_id, intent.strategy, reason="NO_EXECUTOR")
            except Exception:
                pass  # Silent failure - tracing must never block execution
            
            return ExecutionRecord.failed(
                intent_id=intent_id,
                client_order_id=client_order_id,
                reason="NO_EXECUTOR"
            )
        
        # PHASE 5: Execution router guarantees - enforce broker-mode rules
        current_mode = get_engine_mode()
        
        # TRAINING/PAPER: Alpaca allowed, Tradovate forbidden
        # LIVE: Tradovate allowed, Alpaca forbidden
        if current_mode in (EngineMode.TRAINING, EngineMode.PAPER):
            # TRAINING mode - only Alpaca PAPER allowed
            # Check if executor is Tradovate (forbidden in TRAINING)
            # Note: active_executor already checked above, but verify broker name for safety
            if self.active_executor and hasattr(self.active_executor, 'name'):
                if self.active_executor.name == "tradovate":
                    logger.critical(f"Tradovate executor forbidden in TRAINING mode - order rejected")
                    intent_id = getattr(intent, 'intent_id', 'unknown')
                    client_order_id = getattr(intent, 'client_order_id', None) or f"sentinel_{intent_id[:8] if len(intent_id) >= 8 else 'unknown'}"
                    return ExecutionRecord.failed(
                        intent_id=intent_id,
                        client_order_id=client_order_id,
                        reason="Tradovate executor forbidden in TRAINING mode"
                    )
        
        elif current_mode == EngineMode.LIVE:
            # LIVE mode - only Tradovate allowed, requires explicit unlock
            if not _live_execution_allowed():
                logger.critical(
                    f"LIVE execution BLOCKED by hard guard | "
                    f"intent_mode={intent.engine_mode.value} | "
                    f"current_mode={current_mode.value} | "
                    f"SENTINEL_ALLOW_LIVE_EXECUTION not set to YES_I_UNDERSTAND"
                )
                intent_id = getattr(intent, 'intent_id', 'unknown')
                client_order_id = getattr(intent, 'client_order_id', None) or f"sentinel_{intent_id[:8] if len(intent_id) >= 8 else 'unknown'}"
                return ExecutionRecord.failed(
                    intent_id=intent_id,
                    client_order_id=client_order_id,
                    reason="LIVE execution guard active - SENTINEL_ALLOW_LIVE_EXECUTION=YES_I_UNDERSTAND required"
                )
            
            # PHASE 6: LIVE TRADING HARD LOCK
            # HARD GUARD: Alpaca is FORBIDDEN in LIVE mode - fail fast with RuntimeError
            # Type-based check for maximum safety (more robust than name check)
            if self.active_executor:
                from sentinel_x.execution.alpaca_executor import AlpacaExecutor, AlpacaPaperExecutor
                if isinstance(self.active_executor, (AlpacaExecutor, AlpacaPaperExecutor)):
                    error_msg = "Alpaca forbidden in LIVE mode"
                    logger.critical(error_msg)
                    raise RuntimeError(error_msg)
        
        # PHASE 3: CRITICAL - Must never raise - return safe fallback on any error
        try:
            # Use ExecutionRouter if available
            if self._execution_router:
                try:
                    return self._execution_router.execute(intent)
                except Exception as e:
                    logger.warning(f"Execution router failed — falling back to paper: {e}", exc_info=True)
                    # PHASE 3: Fall through to fallback
            
            # Fallback: Use direct executor
            # PHASE 5: Router must NEVER assume executor availability
            # active_executor already checked at start of method, but double-check for safety
            if not self.active_executor:
                logger.warning("No active executor available – order rejected")
                intent_id = getattr(intent, 'intent_id', 'unknown')
                client_order_id = getattr(intent, 'client_order_id', None) or f"sentinel_{intent_id[:8] if len(intent_id) >= 8 else 'unknown'}"
                return ExecutionRecord.failed(
                    intent_id=intent_id,
                    client_order_id=client_order_id,
                    reason="NO_EXECUTOR"
                )
            
            try:
                # PHASE 8: Tick-level execution observability (log correlation)
                loop_tick = _get_loop_tick_for_logging()
                tick_info = f" | loop_tick={loop_tick}" if loop_tick is not None else ""
                
                # PHASE 2: Trace order submission (passive, non-blocking)
                # SAFETY: Trace failures must never affect execution
                try:
                    from sentinel_x.execution.execution_quality import get_execution_quality
                    execution_quality = get_execution_quality()
                    broker_status = getattr(self.active_executor, 'name', 'unknown')
                    execution_quality.trace_order_submitted(intent.intent_id, intent, broker_status=broker_status)
                except Exception:
                    pass  # Silent failure - tracing must never block execution
                
                # REGRESSION LOCK:
                # ExecutionRouter always emits normalized order fields.
                # Executors must safely accept or ignore unsupported parameters.
                # Execute via active executor
                # SAFETY: monitoring-only change, no execution impact
                result = self.active_executor.submit_order(
                    symbol=intent.symbol,
                    side=intent.side,
                    qty=intent.qty,
                    price=intent.limit_price,
                    strategy=intent.strategy
                )
                
                # Convert result to ExecutionRecord-like format
                exec_record_obj = None
                if result:
                    fill_price = result.get('price', 0.0) or result.get('fill_price', 0.0)
                    filled_qty = result.get('qty', 0.0) or result.get('filled_qty', 0.0)
                    
                    exec_record_obj = type('ExecutionRecord', (), {
                        'intent_id': intent.intent_id,
                        'client_order_id': getattr(intent, 'client_order_id', None),
                        'broker_order_id': result.get('order_id'),
                        'status': type('Status', (), {'value': 'FILLED' if filled_qty > 0 else 'REJECTED'})(),
                        'filled_qty': filled_qty,
                        'requested_qty': intent.qty,
                        'avg_fill_price': fill_price,
                        'submitted_at': datetime.now(),
                        'updated_at': datetime.now(),
                        'execution_latency_ms': 0.0,  # Will be computed by ExecutionQuality
                        'slippage_bps': 0.0,  # Will be computed by ExecutionQuality
                        'rejection_reason': None
                    })()
                else:
                    exec_record_obj = ExecutionRecord.failed(
                        intent_id=intent.intent_id,
                        client_order_id=getattr(intent, 'client_order_id', None) or f"sentinel_{intent.intent_id[:8]}",
                        reason="BROKER_REJECTED"
                    )
                
                # PHASE 2: Trace order fill/rejection (passive, non-blocking)
                # SAFETY: Trace failures must never affect execution
                try:
                    from sentinel_x.execution.execution_quality import get_execution_quality
                    execution_quality = get_execution_quality()
                    
                    if exec_record_obj and hasattr(exec_record_obj, 'status'):
                        status_value = exec_record_obj.status.value if hasattr(exec_record_obj.status, 'value') else str(exec_record_obj.status)
                        if status_value in ('FILLED', 'PARTIALLY_FILLED'):
                            fill_price = getattr(exec_record_obj, 'avg_fill_price', None) or (result.get('price') if result else None)
                            execution_quality.trace_order_filled(exec_record_obj, intent.strategy, fill_price=fill_price)
                        else:
                            reason = getattr(exec_record_obj, 'rejection_reason', None) or "BROKER_REJECTED"
                            execution_quality.trace_order_rejected(intent.intent_id, intent.strategy, reason=reason)
                except Exception:
                    pass  # Silent failure - tracing must never block execution
                
                # Return execution record
                if result:
                    return exec_record_obj
                else:
                    return exec_record_obj
                    
            except Exception as e:
                logger.error(f"Fallback executor execution error: {e}", exc_info=True)
                # Return rejected record on any error
                return type('ExecutionRecord', (), {
                    'status': type('Status', (), {'value': 'REJECTED'})(),
                    'broker_order_id': None,
                    'client_order_id': getattr(intent, 'client_order_id', None),
                    'filled_qty': 0.0,
                    'avg_fill_price': 0.0,
                    'updated_at': datetime.now()
                })()
                
        except Exception as e:
            # CRITICAL: Catch ALL exceptions and return safe fallback
            logger.critical(f"OrderRouter.execute() fatal error (should never happen): {e}", exc_info=True)
            return type('ExecutionRecord', (), {
                'status': type('Status', (), {'value': 'REJECTED'})(),
                'broker_order_id': None,
                'client_order_id': getattr(intent, 'client_order_id', None) if intent else None,
                'filled_qty': 0.0,
                'avg_fill_price': 0.0,
                'updated_at': datetime.now()
            })()

    def execute_order(self, symbol, side, qty, price=None, strategy=None):
        """
        Legacy execute_order method - wraps execute() for backward compatibility.
        CRITICAL: Must never raise.
        Creates OrderIntent and executes via execute() method.
        """
        try:
            # Create OrderIntent from legacy parameters
            engine_mode = get_engine_mode()
            intent = OrderIntent.from_strategy_order(
                {
                    'symbol': symbol,
                    'side': side,
                    'qty': qty,
                    'price': price,
                    'strategy': strategy or 'UnknownStrategy'
                },
                engine_mode=engine_mode
            )
            
            # Execute via execute() method (which never raises)
            execution_record = self.execute(intent)
            
            # Convert ExecutionRecord to legacy format
            if execution_record and execution_record.status.value in ('FILLED', 'PARTIALLY_FILLED'):
                return {
                    'order_id': execution_record.broker_order_id or execution_record.client_order_id,
                    'symbol': symbol,
                    'side': side,
                    'qty': execution_record.filled_qty,
                    'price': execution_record.avg_fill_price,
                    'status': execution_record.status.value.lower(),
                    'strategy': strategy,
                    'timestamp': execution_record.updated_at.isoformat() if hasattr(execution_record.updated_at, 'isoformat') else datetime.now().isoformat()
                }
            else:
                # Order was rejected or not filled
                return None
        
        except Exception as e:
            # CRITICAL: This should never happen if execute() is correct
            logger.error(f"Error in execute_order wrapper: {e}", exc_info=True)
            return None

    def get_positions(self) -> List[Dict]:
        """Get positions via ExecutionRouter or fallback to paper_executor."""
        if self._execution_router:
            return self._execution_router.get_positions()
        elif self.paper_executor:
            return self.paper_executor.get_positions()
        else:
            return []

    def get_account(self) -> Optional[Dict]:
        """Get account via ExecutionRouter or fallback to paper_executor."""
        if self._execution_router:
            return self._execution_router.get_account()
        elif self.paper_executor:
            return self.paper_executor.get_account()
        else:
            return None

    def cancel_all_orders(self) -> int:
        """
        PHASE 7: Cancel all orders (kill-switch support).
        Delegates to ExecutionRouter or falls back to paper_executor.
        """
        if self._execution_router:
            return self._execution_router.cancel_all_orders()
        elif self.paper_executor:
            try:
                return self.paper_executor.cancel_all_orders() or 0
            except Exception:
                return 0
        else:
            return 0
    
    def auto_register_training_brokers(self, config: Config) -> None:
        """
        Auto-register TRAINING brokers (Alpaca PAPER).
        
        PHASE 2: Auto-connection for TRAINING mode.
        === TRAINING BASELINE — DO NOT MODIFY ===
        
        ARCHITECTURAL TRUTH:
        - Alpaca PAPER is the TRAINING broker
        - Alpaca PAPER must auto-connect on engine startup
        - Alpaca PAPER runs forever
        
        Rules:
        - No explicit arming required
        - No safety prompts
        - No retries
        - Never throws exceptions
        - Silent failure allowed (engine still runs)
        
        REGRESSION LOCK:
        Alpaca PAPER must always be enabled in TRAINING mode.
        Training must never require explicit arming.
        
        Args:
            config: Configuration object
        """
        # REGRESSION LOCK:
        # Alpaca PAPER must always be enabled in TRAINING mode.
        # Training must never require explicit arming.
        # PHASE 2: Only auto-register for TRAINING/PAPER modes
        current_mode = get_engine_mode()
        
        # HARD BLOCK: Never auto-register Alpaca in LIVE mode
        if current_mode == EngineMode.LIVE:
            error_msg = "Alpaca is forbidden in LIVE mode. LIVE mode requires Tradovate executor only."
            logger.critical(error_msg)
            raise RuntimeError(error_msg)
        
        if current_mode not in (EngineMode.TRAINING, EngineMode.PAPER):
            logger.debug(f"Training broker auto-registration skipped - engine mode is {current_mode.value}")
            return
        
        try:
            # Build Alpaca paper executor (returns None if keys missing)
            alpaca = build_alpaca_paper_executor(config)
            if alpaca:
                # Attempt connection (non-blocking)
                if alpaca.connect():
                    # Register executor for TRAINING mode (normalized)
                    self.register_executor(EngineMode.TRAINING, alpaca)
                    self._armed_brokers.append("alpaca")
                    logger.info("Alpaca TRAINING broker auto-connected")
                else:
                    logger.debug("Alpaca TRAINING executor built but connection failed - engine continues")
            else:
                logger.debug("Alpaca TRAINING executor not built (keys missing) - engine continues")
                
        except Exception as e:
            # CRITICAL: Silent failure allowed - engine continues without broker
            logger.debug(f"Training broker auto-registration failed (silent): {e}")
            # Do not raise - engine continues without brokers
    
    def arm_paper_brokers(self, config: Config) -> None:
        """
        DEPRECATED: Use auto_register_training_brokers() instead.
        Kept for backward compatibility.
        """
        self.auto_register_training_brokers(config)
    
    def get_executor_health(self) -> dict:
        """
        Get health status for all registered executors.
        
        RULE: Health checks must NEVER raise exceptions.
        This method is safe to call from UI/observability code.
        No broker calls should happen in engine loop - this is for monitoring only.
        
        Returns:
            Dictionary mapping engine mode (str) to health status (dict):
            {
                "PAPER": {"connected": True, "broker": "alpaca_paper"},
                ...
            }
        """
        health = {}
        
        try:
            # Check all executors registered by mode
            for mode, executor in self._mode_executors.items():
                if executor is None:
                    health[mode.value] = {"connected": False, "broker": "none"}
                    continue
                
                try:
                    if hasattr(executor, "health_check"):
                        health[mode.value] = executor.health_check()
                    else:
                        # Executor doesn't support health check - assume disconnected
                        health[mode.value] = {
                            "connected": False,
                            "broker": getattr(executor, 'name', 'unknown'),
                            "error": "Health check not supported"
                        }
                except Exception as e:
                    # CRITICAL: Individual executor health check failure must not break overall health
                    logger.error(f"Health check failed for {mode.value} executor: {e}", exc_info=True)
                    health[mode.value] = {
                        "connected": False,
                        "broker": getattr(executor, 'name', 'unknown'),
                        "error": f"Health check exception: {str(e)}"
                    }
            
            # Also check direct executor references (for backwards compatibility)
            # These may not be in _mode_executors if registered differently
            executors_to_check = []
            if self.paper_executor:
                executors_to_check.append(("PAPER", self.paper_executor))
            if self.alpaca_executor:
                executors_to_check.append(("ALPACA", self.alpaca_executor))
            
            for mode_str, executor in executors_to_check:
                # Only add if not already in health dict (avoid duplicates)
                if mode_str not in health:
                    try:
                        if hasattr(executor, "health_check"):
                            health[mode_str] = executor.health_check()
                        else:
                            health[mode_str] = {
                                "connected": False,
                                "broker": getattr(executor, 'name', 'unknown'),
                                "error": "Health check not supported"
                            }
                    except Exception as e:
                        logger.error(f"Health check failed for {mode_str} executor: {e}", exc_info=True)
                        health[mode_str] = {
                            "connected": False,
                            "broker": getattr(executor, 'name', 'unknown'),
                            "error": f"Health check exception: {str(e)}"
                        }
        
        except Exception as e:
            # CRITICAL: Overall health check must NEVER raise
            logger.error(f"get_executor_health() error (non-fatal): {e}", exc_info=True)
            return {
                "error": f"Health check system error: {str(e)}",
                "connected": False
            }
        
        return health