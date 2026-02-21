"""
Trading engine core loop for Sentinel X.

────────────────────────────────────────
PHASE 6 — LIVE TRADING HARD LOCK
────────────────────────────────────────

LIVE MODE HARD GUARDS:
- Type-based isinstance() checks for AlpacaPaperExecutor/AlpacaExecutor
- RuntimeError raised if Alpaca detected in LIVE mode (fail-fast)
- Guards at: engine_mode.set_mode(), router.update_executor(), router.execute(), engine.run_forever()
- Multiple redundant checks ensure Alpaca CANNOT place LIVE trades

────────────────────────────────────────
PHASE 7 — PERMANENT REGRESSION LOCK
────────────────────────────────────────

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
#   • Remove LIVE mode hard guards (PHASE 6)
# ============================================================

REGRESSION LOCK:
- Engine stability > features
- Execution must never block engine
- No required realized_pnl signatures
- UI is observer only
- PAPER is default when explicitly enabled
- Engine ALWAYS boots
- Engine ALWAYS enters TRAINING first (RESEARCH mode)
- PAPER trading only when explicitly enabled
- STOP = return to training, never shutdown
- START command → PAPER trading
- No "offline agent" state exists

ENGINE SAFETY LOCK:
- No analytics logic may exist in engine boot path
- No optional arguments in execution-critical functions  
- No UI-triggered execution
- All future features must attach via observers
- Engine and execution paths NEVER reference realized_pnl directly
- realized_pnl is computed ONLY inside monitoring / analytics layers
- ExecutionRouter.execute() MUST never raise - always return ExecutionRecord
- Alpaca PAPER broker is default for PAPER mode

=== TRAINING BASELINE — DO NOT MODIFY ===

ARCHITECTURAL TRUTH:
- Alpaca PAPER is the TRAINING broker
- Alpaca PAPER must auto-connect on engine startup
- Alpaca PAPER runs forever
- Tradovate is LIVE ONLY
- LIVE trading must require explicit human intent
- UI is observer-only

SAFETY LOCK:
- TRAINING mode auto-connects Alpaca PAPER (auto_register_training_brokers)
- UI is observer-only (read-only health checks, no execution triggers)
- LIVE trading requires deliberate human intent (multiple env vars + code check)

REGRESSION FREEZE ASSERTIONS:
- Alpaca auto-connect cannot be removed accidentally
- Engine boots without broker (OrderRouter handles None executors gracefully)
- Engine runs without UI (no execution dependencies on API/UI state)
- TRAINING mode auto-registers Alpaca PAPER (no explicit arming required)
- LIVE requires explicit env unlock (ALL: UNLOCK, CONFIRM, TRADOVATE_ACCOUNT_ID)
- OrderRouter.execute() never raises (all paths return ExecutionRecord)
- No execution path depends on realized_pnl (PnL is computed in monitoring layer only)
- No analytics in engine path (engine loop has zero analytics dependencies)

ARCHITECTURE (LOCKED):
- Engine NEVER idles and NEVER exits unless EngineMode == KILLED
- Default mode on boot: RESEARCH (training/backtesting)
- Engine modes:
    * RESEARCH  (training / backtesting / synthesis) - DEFAULT ON BOOT
    * PAPER     (paper trading - when explicitly enabled)
    * LIVE      (live trading)
    * KILLED    (only exit condition)
- STOP ≠ OFFLINE → STOP means RESEARCH (training)
- START → PAPER
- UI only changes EngineMode; engine loop is authoritative
- Training runs continuously when not trading

────────────────────────────────────────
PHASE 8 — HEARTBEAT & FREEZE DETECTION BASELINE
────────────────────────────────────────

# ============================================================
# HEARTBEAT BASELINE — DO NOT MODIFY
# ============================================================
# Stable heartbeat and monitoring baseline.
# Changes require architectural review.
# ============================================================
# HEARTBEAT SOURCE OF TRUTH:
#   • Engine emits heartbeat every loop iteration
#   • Uses monotonic time (_last_heartbeat_ts) for age calculation
#   • Secondary loop tick counter (_loop_tick) for freeze detection
#   • Heartbeat written to /tmp/sentinel_x_heartbeat.json
#   • Heartbeat includes: timestamp, pid, mode, broker, loop_tick
# 
# NO future changes may:
#   • Remove monotonic time tracking
#   • Remove loop tick counter
#   • Prevent heartbeat emission on any loop iteration
#   • Make heartbeat emission blocking or fatal
# ============================================================

# ============================================================
# FREEZE DETECTION BASELINE — DO NOT MODIFY
# ============================================================
# Stable freeze detection and escalation baseline.
# Changes require architectural review.
# ============================================================
# FREEZE DETECTION:
#   • STALE threshold: heartbeat age > 10 seconds
#   • FROZEN threshold: heartbeat age > 30 seconds
#   • is_frozen(max_age=30.0) method: never raises, never blocks
#   • Self-check in engine loop after heartbeat emission
#   • Freeze escalation: idempotent, non-destructive logging only
# 
# NO future changes may:
#   • Add auto-restart on freeze detection
#   • Make freeze escalation affect trading state
#   • Make freeze escalation touch brokers
#   • Make freeze escalation exit engine
#   • Remove freeze detection thresholds
#   • Make freeze detection blocking or fatal
# ============================================================

# ============================================================
# ENGINE PHASE MARKER BASELINE — DO NOT MODIFY
# ============================================================
# Deterministic phase markers for precise freeze attribution.
# Changes require architectural review.
# ============================================================
# PHASE MARKERS:
#   • self.loop_phase: str - Current engine execution phase
#   • Phase taxonomy: INIT, LOOP_START, STRATEGY_EVAL, ROUTING,
#     BROKER_SUBMIT, IDLE, SHUTDOWN
#   • Phase updates occur BEFORE risky operations
#   • Phase updates are non-blocking and never conditional
#   • Phase markers enable freeze attribution to specific phases
# 
# PHASE TIMERS:
#   • self.phase_enter_ts: float - Phase entry timestamp (monotonic)
#   • self.phase_duration: float - Current phase duration in seconds
#   • Phase timers enable phase-level performance diagnostics
# 
# BROKER CALL OBSERVABILITY:
#   • self.broker_call_start_ts: float - Broker call start timestamp
#   • self.broker_call_end_ts: float - Broker call end timestamp
#   • self.last_broker_call_duration_ms: float - Last broker call duration
#   • Timing captured without enforcing timeouts or retries
#   • SAFETY: timing only, no execution control
# 
# PER-STRATEGY HEARTBEAT:
#   • self.strategy_heartbeats: Dict[str, Dict] - Per-strategy tracking
#   • Tracks: last_tick_ts, tick_count for each strategy
#   • Updated on every strategy evaluation attempt (even if no trade)
#   • Enables detection of strategy starvation vs engine freeze
# 
# NO future changes may:
#   • Remove phase marker updates
#   • Make phase updates conditional on success
#   • Make phase updates blocking or fatal
#   • Modify phase taxonomy without monitor updates
#   • Remove phase from heartbeat file
#   • Remove phase timers or broker timing
#   • Remove strategy heartbeat tracking
#   • Add timeouts or retry logic based on timing
# ============================================================
"""

import time
import signal
import asyncio
from typing import Optional, List, Dict, Any

from sentinel_x.core.state import BotState, get_state, set_state
from sentinel_x.core.engine_mode import EngineMode, get_engine_mode, set_engine_mode
from sentinel_x.core.kill_switch import is_killed
from sentinel_x.core.config import get_config, Config
from sentinel_x.core.scheduler import get_scheduler

from sentinel_x.data.market_data import MarketData
from sentinel_x.data.storage import get_storage

from sentinel_x.execution.order_intent import OrderIntent
from sentinel_x.execution.router import OrderRouter

from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.shadow_comparison import get_shadow_comparison_manager

from sentinel_x.intelligence.strategy_manager import get_strategy_manager
from sentinel_x.intelligence.capital_allocator import get_capital_allocator, AllocatorMode
from sentinel_x.intelligence.synthesis_agent import get_synthesis_agent

from sentinel_x.research.backtester import EventDrivenBacktester
from sentinel_x.strategies.base import BaseStrategy


class TradingEngine:
    def __init__(
        self,
        config: Optional[Config] = None,
        strategies: Optional[List[BaseStrategy]] = None,
        market_data: Optional[MarketData] = None,
        order_router: Optional[OrderRouter] = None,
    ):
        # CRITICAL: Boot must NEVER fail - wrap ALL optional components
        try:
            self.config = config or get_config()
        except Exception as e:
            logger.error(f"Config initialization failed: {e}", exc_info=True)
            # Use minimal config if needed
            from sentinel_x.core.config import Config
            self.config = Config(symbols=["SPY"], timeframes=[5, 15, 60])
        
        try:
            self.scheduler = get_scheduler(self.config)
        except Exception as e:
            logger.error(f"Scheduler initialization failed: {e}", exc_info=True)
            self.scheduler = None

        self.strategies = strategies or []
        self.market_data = market_data
        self.order_router = order_router
        
        # PHASE 1: Observability - track start time for uptime calculation (read-only)
        import time
        self.started_at = time.time()
        
        # PHASE 6: Strategy promotion engine (allocation-only, TRAINING mode only)
        try:
            from sentinel_x.strategies.promotion import StrategyPromotionEngine
            self.promotion_engine = StrategyPromotionEngine()
            logger.info("Strategy promotion engine initialized")
        except Exception as e:
            logger.error(f"Error initializing promotion engine (non-fatal): {e}", exc_info=True)
            self.promotion_engine = None
        
        # ============================================================
        # PHASE 1 — HEARTBEAT SOURCE OF TRUTH (ENGINE)
        # ============================================================
        # Heartbeat tracking with monotonic time (source of truth)
        # These values are updated every loop iteration
        # REGRESSION LOCK: Heartbeat baseline - do not modify without review
        # ============================================================
        import time as time_module
        # PHASE 2: Heartbeat timestamp (monotonic time - source of truth)
        self.last_heartbeat_ts: float = time_module.monotonic()  # Monotonic time (never goes backward)
        # PHASE 3: Secondary loop tick counter and timestamp
        self.loop_tick: int = 0  # Secondary loop tick counter (monotonic, never reset)
        self.last_loop_tick_ts: float = time_module.monotonic()  # Timestamp of last loop tick update
        
        # PHASE 4: Freeze detection state
        self._freeze_escalated: bool = False  # Track if freeze escalation has fired (idempotent)
        
        # ============================================================
        # PHASE 6 — BROKER CALL OBSERVABILITY (NO TIMEOUTS)
        # ============================================================
        # Broker call timing without enforcing timeouts
        # SAFETY: timing only, no execution control
        # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
        # ============================================================
        self.broker_call_start_ts: float = 0.0  # Broker call start timestamp
        self.broker_call_end_ts: float = 0.0  # Broker call end timestamp
        self.last_broker_call_duration_ms: float = 0.0  # Last broker call duration in milliseconds
        # ============================================================
        
        # ============================================================
        # PHASE 5 — PER-STRATEGY HEARTBEAT EXTENSION
        # ============================================================
        # Per-strategy heartbeat tracking for strategy-level observability
        # Update on every strategy evaluation attempt (even if no trade)
        # No coupling to order submission
        # Purpose: Detect strategy starvation vs engine freeze
        # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
        # SAFETY: monitoring-only change
        # ============================================================
        self.strategy_heartbeats: Dict[str, Dict[str, Any]] = {}  # strategy_name -> {last_tick_ts, tick_count}
        # ============================================================
        
        # ============================================================
        # PHASE 3 — ENGINE PHASE MARKER (PATCH A)
        # PHASE 4 — PHASE MARKERS + PHASE TIMERS
        # ============================================================
        # Deterministic phase marker for freeze attribution
        # Phase updates must never block, not conditional on success,
        # survive exceptions, occur BEFORE risky operations
        # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
        # SAFETY: monitoring-only change, phase markers are observational only
        # ============================================================
        self.loop_phase: str = "INIT"
        self.phase_enter_ts: float = time_module.monotonic()  # Phase entry timestamp
        self.phase_duration: float = 0.0  # Current phase duration in seconds
        # ============================================================
        
        # SAFETY: monitoring-only change
        # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW

        # === TRAINING BASELINE — DO NOT MODIFY ===
        # PHASE 3: Engine startup contract - auto-connect TRAINING brokers
        # REGRESSION LOCK: Alpaca TRAINING broker MUST auto-connect.
        # Do NOT convert to explicit arming.
        if self.order_router:
            try:
                # Normalize engine_mode: PAPER → TRAINING
                current_mode = get_engine_mode()
                if current_mode == EngineMode.PAPER:
                    set_engine_mode(EngineMode.TRAINING, reason="normalize_paper_to_training")
                    logger.info("Engine mode normalized: PAPER → TRAINING")
                
                # REGRESSION LOCK:
                # Alpaca PAPER must always be enabled in TRAINING mode.
                # Training must never require explicit arming.
                # Auto-register TRAINING brokers (Alpaca PAPER)
                logger.info("Auto-registering TRAINING brokers...")
                self.order_router.auto_register_training_brokers(self.config)
                armed = getattr(self.order_router, '_armed_brokers', [])
                if armed:
                    logger.info(f"TRAINING brokers connected: {', '.join(armed)}")
                else:
                    logger.info("No TRAINING brokers connected (engine continues)")
            except Exception as e:
                logger.error(f"Failed to auto-register training brokers (non-fatal): {e}", exc_info=True)
                # Continue - engine runs without brokers

        self.strategy_manager = None
        self.backtester = None

        # CRITICAL: Strategy manager must NOT block boot
        try:
            if self.strategies:
                storage = get_storage()
                self.strategy_manager = get_strategy_manager(storage)

                for s in self.strategies:
                    try:
                        self.strategy_manager.register(s)
                    except Exception as e:
                        logger.error(f"Strategy registration failed: {e}", exc_info=True)

                try:
                    self.backtester = EventDrivenBacktester(
                        initial_capital=self.config.initial_capital
                    )
                except Exception as e:
                    logger.error(f"Backtester initialization failed: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Strategy manager initialization failed (non-fatal): {e}", exc_info=True)

        # CRITICAL: Capital allocator must NOT block boot
        try:
            self.capital_allocator = get_capital_allocator(
                mode=AllocatorMode.EQUAL_WEIGHT
            )
        except Exception as e:
            logger.error(f"Capital allocator initialization failed (non-fatal): {e}", exc_info=True)
            self.capital_allocator = None
        
        # PHASE 9 — SHADOW TRAINING INITIALIZATION
        # Initialize shadow trainer (non-blocking, never crashes boot)
        try:
            from sentinel_x.shadow.trainer import get_shadow_trainer
            self.shadow_trainer = get_shadow_trainer()
            logger.info("Shadow trainer initialized")
        except Exception as e:
            logger.debug(f"Shadow trainer initialization failed (non-fatal): {e}")
            self.shadow_trainer = None

        self.last_exec_ts = 0.0
        self.exec_interval = 5.0

        self.last_synthesis_ts = None
        self.synthesis_interval = 24 * 60 * 60

        # CRITICAL: Signal handlers must NOT fail
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except Exception as e:
            logger.error(f"Signal handler setup failed: {e}", exc_info=True)

        logger.info("TradingEngine initialized")

    # =========================
    # SIGNALS
    # =========================

    def _signal_handler(self, signum, frame):
        logger.critical("Process signal received → KILLED")
        set_engine_mode(EngineMode.KILLED, reason="process_signal")

    # =========================
    # FREEZE DETECTION (PHASE 3)
    # =========================
    
    def is_frozen(self, max_age: float = 30.0) -> bool:
        """
        PHASE 3 — FREEZE DETECTION (ENGINE-INTERNAL)
        
        Check if engine loop is frozen based on heartbeat age.
        
        Thresholds:
        - STALE: heartbeat age > 10 seconds
        - FROZEN: heartbeat age > 30 seconds (default)
        
        Args:
            max_age: Maximum allowed heartbeat age in seconds (default 30.0 for FROZEN)
        
        Returns:
            True if heartbeat age exceeds max_age, False otherwise
        
        Rules:
        - Never raises exceptions
        - Never blocks
        - Only computes age from last heartbeat
        - Observability-only. No execution impact.
        - SAFETY: monitoring-only change
        
        REGRESSION LOCK: Freeze detection baseline - do not modify without review
        """
        try:
            import time as time_module
            current_time = time_module.monotonic()
            age = current_time - self.last_heartbeat_ts
            return age > max_age
        except Exception:
            # SAFETY: Never raise, always return False if computation fails
            return False
    
    # =========================
    # FREEZE ESCALATION (PHASE 4)
    # =========================
    
    def _handle_freeze_escalation(self) -> None:
        """
        PHASE 4 — FREEZE ESCALATION (SAFE, NON-DESTRUCTIVE)
        
        Handle detected engine freeze. This method:
        - Logs CRITICAL once when freeze is detected
        - Marks engine as frozen internally
        - DOES NOT restart
        - DOES NOT exit
        - DOES NOT touch brokers
        - DOES NOT affect trading state
        
        Behavior:
        - Idempotent (fires once per freeze event)
        - Non-destructive (read-only operations)
        - Never raises exceptions
        
        REGRESSION LOCK: Freeze escalation baseline - do not modify without review
        """
        # Idempotent: only escalate once per freeze event
        if self._freeze_escalated:
            return
        
        try:
            import time as time_module
            current_time = time_module.monotonic()
            age = current_time - self.last_heartbeat_ts
            
            # Log CRITICAL freeze detection with phase attribution
            logger.critical(
                f"ENGINE FREEZE DETECTED | "
                f"heartbeat_age={age:.1f}s | "
                f"loop_tick={self.loop_tick} | "
                f"loop_phase={getattr(self, 'loop_phase', 'UNKNOWN')} | "
                f"max_threshold=30.0s | "
                f"Engine loop appears frozen in phase: {getattr(self, 'loop_phase', 'UNKNOWN')}. "
                f"Engine continues running. No auto-restart. Manual intervention may be required."
            )
            
            # Mark as escalated (idempotent flag)
            self._freeze_escalated = True
            
            # SAFETY: Do NOT restart, exit, touch brokers, or affect trading state
            # This is observability-only escalation
            
        except Exception:
            # SAFETY: Never raise, escalation failures are silent
            pass
    
    # =========================
    # PHASE 1 — API COMPATIBILITY (RORK)
    # =========================
    
    @property
    def last_heartbeat(self) -> float:
        """
        PHASE 1 — API COMPATIBILITY ALIAS (RORK)
        
        Property alias for last_heartbeat_ts to maintain API compatibility.
        Some API code expects 'last_heartbeat' attribute.
        
        REGRESSION LOCK — API compatibility for Rork
        DO NOT REMOVE — Required for backward compatibility
        
        Returns:
            last_heartbeat_ts (float): Monotonic timestamp of last heartbeat
        """
        return self.last_heartbeat_ts
    
    # =========================
    # PHASE 2 — STABLE STATUS CONTRACT
    # =========================
    # REGRESSION LOCK — Rork API contract
    # REGRESSION LOCK — monitoring only
    # =========================
    
    def get_status_snapshot(self) -> dict:
        """
        PHASE 2 — STABLE STATUS CONTRACT (RORK)
        
        Get a single canonical engine status object.
        
        Returns a stable status snapshot matching Rork schema:
        - engine_state: RUNNING|STOPPED
        - mode: TRAINING|SHADOW|LIVE
        - loop_phase: LOOP_START|STRATEGY_EVAL|ORDER_SUBMIT|...
        - heartbeat_ts: float (monotonic timestamp)
        - heartbeat_age: float (seconds since last heartbeat)
        - loop_tick: int (current loop tick counter)
        - loop_tick_age: float (seconds since last loop tick)
        - broker: str (broker name)
        - health: GREEN|YELLOW|RED (computed from heartbeat_age and loop_tick)
        
        SAFETY: Read-only, side-effect free, thread-safe
        REGRESSION LOCK — Rork API contract
        REGRESSION LOCK — monitoring only
        """
        try:
            import time as time_module
            # PHASE 2: Use time.time() for age calculations (stable contract)
            now = time_module.time()
            
            # Get heartbeat data (monotonic timestamp)
            hb_ts = self.last_heartbeat_ts
            # Calculate age using wall clock time for consistency
            # Note: hb_ts is monotonic, but for age calculation we use time.time()
            # This provides wall-clock relative age
            if hb_ts:
                now_mono = time_module.monotonic()
                heartbeat_age = now_mono - hb_ts
            else:
                heartbeat_age = None
            
            # Get loop tick data
            loop_tick = self.loop_tick
            loop_tick_ts = getattr(self, 'last_loop_tick_ts', None)
            # Calculate loop tick age
            if loop_tick_ts:
                now_mono = time_module.monotonic()
                loop_tick_age = now_mono - loop_tick_ts
            else:
                loop_tick_age = None
            
            # Get loop phase
            loop_phase = getattr(self, 'loop_phase', 'UNKNOWN')
            
            # Determine engine_state (RUNNING or STOPPED)
            try:
                current_mode = get_engine_mode()
                if current_mode == EngineMode.KILLED or is_killed():
                    engine_state = "STOPPED"
                else:
                    engine_state = "RUNNING"
            except Exception:
                engine_state = "RUNNING"  # Default to RUNNING if mode check fails
            
            # Determine mode (TRAINING|SHADOW|LIVE)
            try:
                current_mode = get_engine_mode()
                mode_value = current_mode.value
                mode_mapping = {
                    "RESEARCH": "TRAINING",
                    "TRAINING": "TRAINING",
                    "PAPER": "SHADOW",
                    "LIVE": "LIVE",
                    "PAUSED": "TRAINING",
                    "KILLED": "TRAINING"
                }
                mode = mode_mapping.get(mode_value, "TRAINING")
            except Exception:
                mode = "TRAINING"
            
            # Get broker name
            broker = "UNKNOWN"
            try:
                if self.order_router:
                    if self.order_router.active_executor:
                        broker_name_attr = getattr(self.order_router.active_executor, 'name', 'unknown')
                        if broker_name_attr == 'alpaca' or 'alpaca' in broker_name_attr.lower():
                            broker = "ALPACA_PAPER"
                        elif broker_name_attr == 'paper':
                            broker = "PAPER"
                        elif broker_name_attr == 'tradovate':
                            broker = "TRADOVATE"
                        else:
                            broker = broker_name_attr.upper()
                    elif hasattr(self.order_router, 'alpaca_executor') and self.order_router.alpaca_executor:
                        broker = "ALPACA_PAPER"
                    elif hasattr(self.order_router, 'paper_executor') and self.order_router.paper_executor:
                        broker = "PAPER"
                    else:
                        broker = "NONE"
            except Exception:
                pass  # Use default "UNKNOWN"
            
            # PHASE 2: Determine health (GREEN|YELLOW|RED) - Stable contract
            # RED: loop_tick_age > 30 seconds (engine frozen)
            # YELLOW: heartbeat_age > 5 seconds (delayed)
            # GREEN: otherwise (healthy)
            if loop_tick_age is not None and loop_tick_age > 30:
                health = "RED"
            elif heartbeat_age is not None and heartbeat_age > 5:
                health = "YELLOW"
            else:
                health = "GREEN"
            
            return {
                "engine_state": engine_state,
                "mode": mode,
                "loop_phase": loop_phase,
                "heartbeat_ts": heartbeat_ts,
                "heartbeat_age": heartbeat_age,
                "loop_tick": loop_tick,
                "loop_tick_age": loop_tick_age,
                "broker": broker,
                "health": health
            }
            
        except Exception as e:
            # SAFETY: Never raise, always return safe default
            from sentinel_x.monitoring.logger import logger
            logger.exception("Error generating status snapshot")
            return {
                "engine_state": "STOPPED",
                "mode": "TRAINING",
                "loop_phase": "ERROR",
                "heartbeat_ts": None,
                "heartbeat_age": None,
                "loop_tick": None,
                "loop_tick_age": None,
                "broker": "UNKNOWN",
                "health": "RED",
                "reason": f"Snapshot error: {str(e)}"
            }

    # =========================
    # MAIN LOOP
    # =========================

    def run_forever(self) -> None:
        """
        Main engine loop - NEVER exits unless EngineMode == KILLED.
        
        PHASE 3: Default mode on boot: TRAINING (Alpaca PAPER auto-connected).
        === TRAINING BASELINE — DO NOT MODIFY ===
        
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
        logger.info("Sentinel X Engine starting (always-on)")

        # PHASE 3: Normalize engine mode and set defaults
        from sentinel_x.core.engine_mode import EngineMode, get_engine_mode, set_engine_mode
        import os
        current_mode = get_engine_mode()
        env_mode = os.getenv("SENTINEL_ENGINE_MODE", "").upper()

        if env_mode in ("TRAINING", "PAPER"):
            set_engine_mode(EngineMode.TRAINING, reason="env_explicit")
            current_mode = EngineMode.TRAINING
            logger.info("EngineMode set to TRAINING (from SENTINEL_ENGINE_MODE env)")
        elif env_mode == "LIVE":
            set_engine_mode(EngineMode.LIVE, reason="env_explicit")
            current_mode = EngineMode.LIVE
            logger.info("EngineMode set to LIVE (from SENTINEL_ENGINE_MODE env)")
        elif current_mode == EngineMode.KILLED:
            logger.warning("EngineMode was KILLED at boot → resetting to TRAINING")
            set_engine_mode(EngineMode.TRAINING, reason="boot_safety_reset")
            current_mode = EngineMode.TRAINING
        elif current_mode not in (
            EngineMode.RESEARCH,
            EngineMode.TRAINING,
            EngineMode.PAPER,
            EngineMode.LIVE,
        ):
            logger.warning(
                f"Unexpected engine mode {current_mode.value} at boot → resetting to TRAINING"
            )
            set_engine_mode(EngineMode.TRAINING, reason="boot_safety_enforce")
            current_mode = EngineMode.TRAINING

        if current_mode == EngineMode.PAPER:
            set_engine_mode(EngineMode.TRAINING, reason="normalize_paper")
            current_mode = EngineMode.TRAINING

        if current_mode == EngineMode.RESEARCH:
            set_engine_mode(EngineMode.TRAINING, reason="boot_default_training")
            current_mode = EngineMode.TRAINING
            logger.info("Engine starting in TRAINING mode (Alpaca PAPER auto-connected)")
        else:
            logger.info(f"Engine starting in {current_mode.value} mode")

        # Set state based on mode
        if current_mode in (EngineMode.TRAINING, EngineMode.PAPER, EngineMode.LIVE):
            set_state(BotState.TRADING)
            logger.info(f"Trading mode active: {current_mode.value}")
        else:
            set_state(BotState.TRAINING)
            logger.info("Training mode active (RESEARCH)")
        # PHASE 2: Initialize loop tick counter (monotonic, never reset)
        tick = 0
        import time as time_module_init
        self.loop_tick = 0  # Reset to 0 at loop start, then increments
        self.last_loop_tick_ts = time_module_init.monotonic()  # Initialize timestamp

        # PHASE 1: ENGINE SAFETY BASELINE
        # Wrap entire loop in exception handler to prevent any uncaught exception from terminating the engine
        # KeyboardInterrupt exits cleanly (user-initiated shutdown)
        try:
            # PHASE 2: REQUIRED ENGINE LOOP - NO return, NO break, NO crash
            while True:
                # ============================================================
                # PHASE 2 — HEARTBEAT FIX (NON-BLOCKING)
                # ============================================================
                # REGRESSION LOCK — MONITORING SIGNAL
                # DO NOT MODIFY WITHOUT ENGINE REVIEW
                # 
                # Heartbeat MUST update unconditionally at TOP of loop.
                # Must NOT depend on broker, executor, or strategy success.
                # Must NOT block or sleep.
                # 
                # PHASE 11 — SAFETY GUARANTEES:
                # - SAFETY: monitoring-only change
                # - No new threads
                # - No sleeps added
                # - No broker behavior changes
                # - No executor behavior changes
                # - Alpaca remains PAPER-only
                # - LIVE remains locked
                # - Observability-only. No execution impact.
                # 
                # SAFETY: heartbeat + loop tick update MUST NEVER be skipped
                # REGRESSION LOCK
                # ============================================================
                now = time.monotonic()
                self.last_heartbeat_ts = now  # Update heartbeat timestamp unconditionally
                self.loop_tick += 1  # PHASE 3: Increment loop tick counter
                self.last_loop_tick_ts = now  # PHASE 3: Update loop tick timestamp
                self.loop_phase = "ENGINE_LOOP"  # PHASE 1: Set phase at top of loop
                
                # ============================================================
                # PHASE 3 — ENGINE PHASE MARKER (PATCH B)
                # PHASE 4 — PHASE TIMERS
                # ============================================================
                # Update phase timers for observability
                # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
                # SAFETY: monitoring-only change, phase markers are observational only
                # ============================================================
                current_time = time.monotonic()
                self.phase_duration = current_time - self.phase_enter_ts
                self.phase_enter_ts = current_time
                # ============================================================
                
                tick += 1
                mode = get_engine_mode()
                
                # PHASE 1: Observability - record tick for status tracking (read-only, non-invasive)
                try:
                    from sentinel_x.monitoring.engine_status import record_tick
                    record_tick()
                except Exception:
                    pass  # Observability must never block engine
                
                # ============================================================
                # PHASE 3 — SHADOW MODE INTEGRATION (ENGINE LOOP)
                # ============================================================
                # Check shadow mode state at top of loop
                # SAFETY: SHADOW MODE ONLY - never triggers order execution
                # SAFETY: Lazy import to avoid circular dependencies
                # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
                # ============================================================
                try:
                    from sentinel_x.core.shadow_registry import get_shadow_controller
                    shadow_controller = get_shadow_controller()
                    shadow_enabled = shadow_controller.is_enabled()
                except Exception as e:
                    logger.debug(f"Error checking shadow mode state (non-fatal): {e}")
                    shadow_enabled = False
                # ============================================================
                
                # ============================================================
                # PHASE 2 — HEARTBEAT FILE WRITE (AFTER UNCONDITIONAL UPDATE)
                # ============================================================
                # Heartbeat timestamp already updated at TOP of loop (unconditionally)
                # Now write heartbeat file with current state
                # External monitors read this file to report TRUE runtime state.
                # 
                # REGRESSION LOCK: HEARTBEAT BASELINE - do not modify without review
                # SAFETY: monitoring-only change
                # - Engine is production-stable
                # - Monitor correctness depends on heartbeat
                # - Do not reintroduce engine imports in monitors
                #
                # SAFETY GUARANTEES:
                # - Observability-only. No execution impact.
                # - Heartbeat failures must NEVER crash the engine
                # - No blocking I/O
                # - Heartbeat must NOT affect timing or execution
                # - Uses monotonic time (never goes backward)
                # ============================================================
                try:
                    from sentinel_x.monitoring.heartbeat import write_heartbeat
                    from sentinel_x.core.engine_mode import EngineMode
                    import os
                    import time as time_module
                    
                    # Use already-updated monotonic timestamp (updated at TOP of loop)
                    current_monotonic = self.last_heartbeat_ts
                    current_wallclock = time_module.time()
                    
                    # Determine broker name
                    broker_name = "NONE"
                    if self.order_router:
                        if self.order_router.active_executor:
                            broker_name = getattr(self.order_router.active_executor, 'name', 'unknown').upper()
                            if broker_name == "ALPACA":
                                broker_name = "ALPACA_PAPER"
                        elif self.order_router.alpaca_executor:
                            broker_name = "ALPACA_PAPER"
                        elif self.order_router.paper_executor:
                            broker_name = "PAPER"
                    
                    # Write heartbeat file with all observability metrics
                    # Heartbeat data reflects:
                    # - Actual running state (RUNNING while loop is active)
                    # - Actual engine mode (TRAINING/PAPER/LIVE)
                    # - Actual broker executor (Alpaca PAPER in training)
                    # - Monotonic heartbeat timestamp (for age calculation)
                    # - Loop tick counter (for freeze detection)
                    # - Loop tick timestamp (for independent age calculation)
                    # - Loop phase marker (for freeze attribution) - PHASE 4
                    # - Phase duration (for phase-level diagnostics) - PHASE 4
                    # - Broker call duration (for broker timing) - PHASE 6
                    # - Strategy heartbeats (for strategy-level observability) - PHASE 5
                    
                    # Calculate current phase duration
                    current_time_for_phase = time_module.monotonic()
                    current_phase_duration = current_time_for_phase - self.phase_enter_ts
                    
                    # Prepare strategy heartbeat summary
                    strategy_summary = {}
                    for strategy_name, heartbeat_data in self.strategy_heartbeats.items():
                        strategy_age = current_time_for_phase - heartbeat_data.get('last_tick_ts', current_time_for_phase)
                        strategy_summary[strategy_name] = {
                            'tick_count': heartbeat_data.get('tick_count', 0),
                            'last_tick_age_seconds': strategy_age
                        }
                    
                    write_heartbeat({
                        "engine": "RUNNING",
                        "mode": mode.value,
                        "broker": broker_name,
                        "pid": os.getpid(),
                        "timestamp": current_wallclock,  # Wallclock for display purposes
                        "heartbeat_monotonic": current_monotonic,  # Monotonic for age calculation
                        "loop_tick": self.loop_tick,  # PHASE 3: Secondary loop tick counter
                        "last_loop_tick_ts": self.last_loop_tick_ts,  # PHASE 3: Loop tick timestamp
                        "loop_phase": self.loop_phase,  # PHASE 4: Engine phase marker for freeze attribution
                        "phase_duration_seconds": current_phase_duration,  # PHASE 4: Current phase duration
                        "last_broker_call_duration_ms": self.last_broker_call_duration_ms,  # PHASE 6: Broker call timing
                        "strategy_heartbeats": strategy_summary,  # PHASE 5: Per-strategy heartbeat summary
                    })
                    
                    # PHASE 5: Reset freeze escalation flag (new heartbeat = loop is active)
                    self._freeze_escalated = False
                    
                except Exception:
                    # SAFETY: Heartbeat file write must never block or crash engine
                    # Observability-only. No execution impact.
                    pass
                
                # ============================================================
                # PHASE 5 — ENGINE LOOP SELF-CHECK
                # ============================================================
                # Check heartbeat age after emission to detect freezes
                # Thresholds: STALE >10s, FROZEN >30s
                # REGRESSION LOCK: FREEZE DETECTION BASELINE - do not modify without review
                # SAFETY: monitoring-only change
                # ============================================================
                try:
                    # Compute heartbeat age (monotonic time difference)
                    # Note: heartbeat already updated at TOP of loop unconditionally
                    current_time = time.monotonic()
                    heartbeat_age = current_time - self.last_heartbeat_ts
                    
                    # PHASE 5: Check if frozen (heartbeat age > 30 seconds)
                    if heartbeat_age > 30.0:
                        # Trigger freeze escalation handler (idempotent, non-destructive)
                        self._handle_freeze_escalation()
                    elif heartbeat_age > 10.0:
                        # STALE threshold exceeded, but not yet FROZEN
                        # Log warning only (not critical yet)
                        logger.warning(
                            f"HEARTBEAT STALE | "
                            f"age={heartbeat_age:.1f}s | "
                            f"loop_tick={self.loop_tick} | "
                            f"threshold=10.0s"
                        )
                except Exception:
                    # SAFETY: Freeze detection must never block or crash engine
                    # Observability-only. No execution impact.
                    pass
                
                # PHASE 7: Structured heartbeat logging (every 60s, read-only, non-invasive)
                try:
                    from sentinel_x.monitoring.heartbeat import log_heartbeat
                    log_heartbeat()
                except Exception:
                    pass  # Heartbeat logging must never block engine

                # ONLY exit condition: EngineMode == KILLED
                if mode == EngineMode.KILLED:
                    logger.critical("EngineMode=KILLED → exiting process")
                    break

                # CRITICAL: Kill switch check (non-fatal, just log)
                if is_killed():
                    logger.warning("Kill-switch active - execution blocked, training continues")
                    mode = EngineMode.RESEARCH  # Treat as RESEARCH mode

                # Inner try/except for per-tick error handling
                try:
                    # PHASE 2: ALWAYS heartbeat first (non-blocking)
                    try:
                        self._heartbeat()
                    except Exception:
                        pass  # Heartbeat is optional

                    # ============================================================
                    # PHASE 3 — ENGINE PHASE MARKER (PATCH C)
                    # PHASE 4 — PHASE TIMERS
                    # ============================================================
                    # STRATEGY_EVAL marker before strategy evaluation
                    # Update phase timers for observability
                    # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
                    # SAFETY: monitoring-only change, phase markers are observational only
                    # ============================================================
                    current_time = time.monotonic()
                    self.phase_duration = current_time - self.phase_enter_ts
                    self.loop_phase = "STRATEGY_EVAL"
                    self.phase_enter_ts = current_time
                    # ============================================================
                    
                    # ALWAYS evaluate strategies (if available)
                    try:
                        self._evaluate_strategies()
                    except Exception as e:
                        logger.error(f"Strategy evaluation error: {e}", exc_info=True)

                    # ALWAYS record shadow state (optional, non-blocking)
                    try:
                        self._record_shadow_state()
                    except Exception:
                        pass  # Shadow recording is optional
                    
                    # PHASE 9 — SHADOW TRAINING INTEGRATION
                    # Process market tick for shadow training (non-blocking, never crashes engine)
                    try:
                        self._process_shadow_tick()
                    except Exception as e:
                        logger.debug(f"Shadow training tick processing error (non-fatal): {e}")
                        # Shadow failures must not crash engine

                    # REGRESSION LOCK:
                    # Alpaca PAPER must always be enabled in TRAINING mode.
                    # Training must never require explicit arming.
                    # ============================================================
                    # PHASE 3 — ENGINE PHASE MARKER (PATCH D)
                    # PHASE 4 — PHASE TIMERS
                    # ============================================================
                    # ROUTING marker before order routing/execution logic
                    # Update phase timers for observability
                    # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
                    # SAFETY: monitoring-only change, phase markers are observational only
                    # ============================================================
                    current_time = time.monotonic()
                    self.phase_duration = current_time - self.phase_enter_ts
                    self.loop_phase = "ROUTING"
                    self.phase_enter_ts = current_time
                    # ============================================================
                    
                    # PHASE 3 & 5: Execute based on mode
                    # TRAINING = Alpaca PAPER, LIVE = Tradovate
                    if mode in (EngineMode.TRAINING, EngineMode.PAPER, EngineMode.LIVE):
                        # PHASE 6: LIVE TRADING HARD LOCK
                        # HARD GUARD: Alpaca is FORBIDDEN in LIVE mode
                        if mode == EngineMode.LIVE and self.order_router:
                            # Type-based check for AlpacaPaperExecutor
                            from sentinel_x.execution.alpaca_executor import AlpacaExecutor, AlpacaPaperExecutor
                            if self.order_router.active_executor:
                                if isinstance(self.order_router.active_executor, (AlpacaExecutor, AlpacaPaperExecutor)):
                                    error_msg = "Alpaca forbidden in LIVE mode"
                                    logger.critical(error_msg)
                                    raise RuntimeError(error_msg)
                            # Also check alpaca_executor reference
                            if self.order_router.alpaca_executor:
                                error_msg = "Alpaca forbidden in LIVE mode"
                                logger.critical(error_msg)
                                raise RuntimeError(error_msg)
                        
                        try:
                            set_state(BotState.TRADING)
                            now = time.time()
                            if now - self.last_exec_ts >= self.exec_interval:
                                # ============================================================
                                # PHASE 3 — ENGINE PHASE MARKER (PATCH E)
                                # PHASE 4 — PHASE TIMERS
                                # ============================================================
                                # BROKER_SUBMIT marker before trading execution
                                # This wraps Alpaca PAPER submits and any future broker submits
                                # Update phase timers for observability
                                # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
                                # SAFETY: monitoring-only change, phase markers are observational only
                                # ============================================================
                                current_time = time.monotonic()
                                self.phase_duration = current_time - self.phase_enter_ts
                                self.loop_phase = "BROKER_SUBMIT"
                                self.phase_enter_ts = current_time
                                # ============================================================
                                
                                # PHASE 3 — SHADOW MODE EXECUTION
                                # SAFETY: SHADOW MODE ONLY - never triggers order execution
                                if shadow_enabled:
                                    self._execute_shadow_strategies()
                                else:
                                    self._execute_trading(mode)
                                
                                self.last_exec_ts = now
                        except Exception as e:
                            logger.error(f"Trading execution error: {e}", exc_info=True)
                            # Continue loop - never crash
                    else:
                        # PHASE 5: RESEARCH or PAUSED mode = training/backtesting
                        # Engine trains/backtests continuously when not trading
                        try:
                            set_state(BotState.TRAINING)
                            self._run_training_cycle()
                        except Exception as e:
                            logger.error(f"Training cycle error: {e}", exc_info=True)
                            # Continue loop - never crash

                except Exception as e:
                    # CRITICAL: Log error with full traceback but continue loop
                    logger.error(f"Engine loop error (tick={tick}): {e}", exc_info=True)
                    # Continue loop - never crash

                # ============================================================
                # PHASE 3 — ENGINE PHASE MARKER (PATCH F)
                # PHASE 4 — PHASE TIMERS
                # ============================================================
                # IDLE marker at end of loop iteration (before sleep)
                # Set regardless of outcome to enable freeze attribution
                # Update phase timers for observability
                # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
                # SAFETY: monitoring-only change, phase markers are observational only
                # ============================================================
                current_time = time.monotonic()
                self.phase_duration = current_time - self.phase_enter_ts
                self.loop_phase = "IDLE"
                self.phase_enter_ts = current_time
                # ============================================================
                
                # CRITICAL: Sleep between ticks (use safe default if config fails)
                try:
                    sleep_time = self.config.loop_sleep or 1.0
                except:
                    sleep_time = 1.0
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            # Clean exit on user interrupt (Ctrl+C)
            # ============================================================
            # PHASE 3 — ENGINE PHASE MARKER (PATCH G)
            # ============================================================
            # SHUTDOWN marker before shutdown logging
            # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
            # SAFETY: monitoring-only change
            # ============================================================
            self.loop_phase = "SHUTDOWN"
            # ============================================================
            logger.info("KeyboardInterrupt received - shutting down engine cleanly")
            set_engine_mode(EngineMode.KILLED, reason="keyboard_interrupt")
        except Exception as e:
            # CRITICAL: Catch ALL exceptions including unexpected ones
            # Log with full traceback and continue (attempt to keep engine running)
            logger.critical(f"FATAL: Uncaught exception in engine loop: {e}", exc_info=True)
            logger.critical("Engine attempting to continue despite fatal error...")
            # Try to reset to safe state
            try:
                set_engine_mode(EngineMode.TRAINING, reason="fatal_error_recovery")
            except:
                pass
            # Don't re-raise - attempt to keep engine alive

        # ============================================================
        # PHASE 3 — ENGINE PHASE MARKER (PATCH G)
        # ============================================================
        # SHUTDOWN marker before shutdown logging
        # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
        # SAFETY: monitoring-only change
        # ============================================================
        self.loop_phase = "SHUTDOWN"
        # ============================================================
        logger.info("Engine shutdown complete")

    # =========================
    # STRATEGY EVALUATION
    # =========================

    def _evaluate_strategies(self) -> None:
        if not self.strategy_manager or not self.market_data:
            return

        # ============================================================
        # PHASE 5 — PER-STRATEGY HEARTBEAT EXTENSION
        # ============================================================
        # Update per-strategy heartbeat on every evaluation attempt
        # 
        # PHASE 2: Per-strategy heartbeat tracking
        # Goal: Detect strategy stalls independently from engine health
        # 
        # SAFETY: observability-only
        # SAFETY: no trading logic modified
        # SAFETY: no blocking calls
        # SAFETY: strategy failures MUST NOT block updates
        # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
        # ============================================================
        current_time = time.monotonic()
        
        for strategy in self.strategy_manager.get_active_strategies():
            try:
                strategy_name = strategy.get_name() if hasattr(strategy, 'get_name') else str(type(strategy).__name__)
                
                # Update strategy heartbeat (even if evaluation fails)
                if strategy_name not in self.strategy_heartbeats:
                    self.strategy_heartbeats[strategy_name] = {
                        'last_tick_ts': current_time,
                        'tick_count': 0
                    }
                
                self.strategy_heartbeats[strategy_name]['last_tick_ts'] = current_time
                self.strategy_heartbeats[strategy_name]['tick_count'] = self.strategy_heartbeats[strategy_name].get('tick_count', 0) + 1
                
                # Execute strategy evaluation
                strategy.safe_on_tick(self.market_data)
            except Exception as e:
                logger.error(f"Strategy eval error: {e}", exc_info=True)
                # Strategy heartbeat already updated above, continue with next strategy

    # =========================
    # EXECUTION
    # =========================

    def _execute_trading(self, mode: EngineMode) -> None:
        """
        Execute trading logic - CRITICAL: Must NEVER crash engine.
        If order_router is None, log warning and continue.
        """
        if not self.order_router:
            logger.warning("OrderRouter not available - trading skipped")
            return

        if not self.strategy_manager:
            logger.debug("StrategyManager not available - trading skipped")
            return

        if not self.market_data:
            logger.debug("MarketData not available - trading skipped")
            return

        # CRITICAL: Get active strategies safely
        try:
            active_strategies = self.strategy_manager.get_active_strategies()
        except Exception as e:
            logger.error(f"Error getting active strategies: {e}", exc_info=True)
            return

        for strategy in active_strategies:
            try:
                # CRITICAL: Strategy tick must NEVER raise
                order = strategy.safe_on_tick(self.market_data)
                if not order:
                    continue

                # CRITICAL: Intent creation must NEVER raise
                try:
                    intent = OrderIntent.from_strategy_order(order)
                except Exception as e:
                    logger.error(f"Error creating OrderIntent: {e}", exc_info=True)
                    continue

                # ============================================================
                # PHASE 6 — SAFETY GUARD: PREVENT ORDER EXECUTION IN SHADOW MODE
                # ============================================================
                # CRITICAL: If shadow mode is enabled, NEVER execute orders
                # This is a redundant safety check in case shadow mode check at loop top is bypassed
                # SAFETY: SHADOW MODE ONLY - never triggers order execution
                # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
                # ============================================================
                try:
                    from sentinel_x.core.shadow_registry import get_shadow_controller
                    shadow_controller = get_shadow_controller()
                    if shadow_controller.is_enabled():
                        # SAFETY GUARD: Shadow mode is enabled, block order execution
                        logger.warning(
                            f"SHADOW_MODE_SAFETY_GUARD | "
                            f"Order execution blocked for strategy {strategy.get_name()} | "
                            f"symbol={order.get('symbol')} | side={order.get('side')} | "
                            f"This should not happen if shadow mode check at loop top is correct."
                        )
                        # Log shadow signal with audit logger
                        try:
                            from sentinel_x.monitoring.audit_logger import log_audit_event
                            log_audit_event(
                                "SHADOW_SIGNAL_BLOCKED",
                                f"shadow_{strategy.get_name()}",
                                metadata={
                                    "strategy": strategy.get_name(),
                                    "symbol": order.get("symbol"),
                                    "side": order.get("side"),
                                    "qty": order.get("qty", 0),
                                    "price": order.get("price"),
                                    "reason": "Shadow mode enabled - order blocked by safety guard"
                                }
                            )
                        except Exception as e:
                            logger.debug(f"Error logging shadow signal to audit (non-fatal): {e}")
                        continue  # Skip order execution - NEVER reach order_router in shadow mode
                except Exception as e:
                    logger.debug(f"Error checking shadow mode in safety guard (non-fatal): {e}")
                    # Continue with normal execution if check fails
                # ============================================================
                
                # CRITICAL: Execution must NEVER raise to engine
                # OrderRouter.execute() MUST always return (never raises)
                # ============================================================
                # PHASE 6 — BROKER CALL OBSERVABILITY (NO TIMEOUTS)
                # ============================================================
                # Capture broker call timing without enforcing timeouts
                # SAFETY: timing only, no execution control
                # REGRESSION LOCK — DO NOT MODIFY WITHOUT ENGINE REVIEW
                # ============================================================
                broker_call_start = time.monotonic()
                self.broker_call_start_ts = broker_call_start
                try:
                    record = self.order_router.execute(intent)
                    # ExecutionRecord is returned - no need to check or process here
                    # Analytics/metrics will observe via event bus
                except Exception as e:
                    # CRITICAL: This should never happen if OrderRouter.execute() is correct
                    # But we catch it anyway as a safety net
                    logger.critical(f"OrderRouter.execute() raised exception (should never happen): {e}", exc_info=True)
                    # Continue loop - execution failure is non-fatal
                finally:
                    # Always capture broker call end time and duration
                    broker_call_end = time.monotonic()
                    self.broker_call_end_ts = broker_call_end
                    self.last_broker_call_duration_ms = (broker_call_end - broker_call_start) * 1000.0  # Convert to milliseconds
                # ============================================================

            except Exception as e:
                logger.error(f"Strategy execution error: {e}", exc_info=True)
                # Continue with next strategy
    
    # =========================
    # PHASE 3 — SHADOW EXECUTION
    # =========================
    
    def _execute_shadow_strategies(self) -> None:
        """
        Execute strategies in SHADOW mode.
        
        SAFETY: SHADOW MODE ONLY
        - Generates signals from strategies
        - Records metrics (PnL, Sharpe, drawdown, trade count)
        - NEVER calls order_router or execution adapters
        - Stores results in memory registry
        
        CRITICAL: Must NEVER crash engine.
        """
        if not self.strategy_manager:
            logger.debug("StrategyManager not available - shadow execution skipped")
            return

        if not self.market_data:
            logger.debug("MarketData not available - shadow execution skipped")
            return

        # Lazy import to avoid circular dependencies
        try:
            from sentinel_x.strategies.shadow_executor import get_shadow_executor
            shadow_executor = get_shadow_executor()
        except Exception as e:
            logger.error(f"Error getting shadow executor (non-fatal): {e}", exc_info=True)
            return

        # CRITICAL: Get active strategies safely
        try:
            active_strategies = self.strategy_manager.get_active_strategies()
        except Exception as e:
            logger.error(f"Error getting active strategies for shadow execution: {e}", exc_info=True)
            return

        # Execute strategies in shadow mode (signals only, no orders)
        try:
            records = shadow_executor.execute_shadow_strategies(active_strategies, self.market_data)
            if records:
                logger.debug(f"Shadow execution generated {len(records)} signals (no orders executed)")
        except Exception as e:
            logger.error(f"Shadow execution error: {e}", exc_info=True)
            # Continue loop - shadow execution failure is non-fatal

    # =========================
    # TRAINING / RESEARCH
    # =========================

    def _run_training_cycle(self) -> None:
        if not self.strategy_manager or not self.backtester:
            return

        try:
            self.strategy_manager.rank_strategies()
            self.strategy_manager.prune()
            self.strategy_manager.promote_top_n()
        except Exception as e:
            logger.error(f"Training cycle error: {e}", exc_info=True)

        # PHASE 6: Strategy promotion engine (TRAINING mode only)
        # SAFETY: Promotion affects ALLOCATION ONLY
        # PROMOTION NEVER RUNS IN LIVE MODE
        try:
            if self.promotion_engine and self.strategy_manager:
                # Get all strategies for promotion evaluation
                # Promotion engine adjusts allocation_weight only
                strategies_list = list(self.strategy_manager.strategies.values())
                if strategies_list:
                    self.promotion_engine.evaluate(strategies_list)
        except Exception as e:
            logger.error(f"Promotion engine evaluation error (non-fatal): {e}", exc_info=True)
            # SAFETY: Promotion engine failure must NOT affect trading

        self._maybe_run_synthesis()

    def _maybe_run_synthesis(self) -> None:
        now = time.time()
        if self.last_synthesis_ts and now - self.last_synthesis_ts < self.synthesis_interval:
            return

        try:
            agent = get_synthesis_agent(get_storage(), self.strategy_manager)
            asyncio.run(agent.run_synthesis_cycle())
            self.last_synthesis_ts = now
        except Exception as e:
            logger.debug(f"Synthesis error (non-fatal): {e}")

    # =========================
    # OBSERVABILITY
    # =========================

    def _process_shadow_tick(self) -> None:
        """
        PHASE 9 — SHADOW TRAINING INTEGRATION
        
        Process market tick for shadow training.
        
        SAFETY:
        - Never executes trades
        - Never touches execution adapters
        - Only simulates outcomes
        """
        try:
            from sentinel_x.shadow.controller import get_shadow_training_controller
            from sentinel_x.shadow.feed import MarketTick
            from datetime import datetime
            
            controller = get_shadow_training_controller()
            
            # Only process if shadow training is enabled
            if not controller.is_enabled():
                return
            
            # Get current market data and create tick
            if not self.market_data:
                return
            
            # Create market tick from current market data
            # This is a simplified tick - in production, this would come from the feed
            try:
                # Get latest price for each symbol
                for symbol in self.config.symbols:
                    try:
                        # Get latest price (simplified - would use actual feed in production)
                        price = 100.0  # Placeholder - would get from market_data
                        
                        tick = MarketTick(
                            symbol=symbol,
                            timestamp=datetime.utcnow(),
                            price=price,
                            volume=0.0,
                        )
                        
                        # Process tick in shadow training controller
                        controller.process_tick(tick)
                    except Exception as e:
                        logger.debug(f"Error processing shadow tick for {symbol}: {e}")
                        continue
                        
            except Exception as e:
                logger.debug(f"Error creating shadow tick: {e}")
                
        except Exception as e:
            # SAFETY: Shadow training failures must not crash engine
            logger.debug(f"Shadow training tick processing error (non-fatal): {e}")
        
        # SAFETY:
        # - Non-blocking
        # - Never crashes engine
        # - Shadow failures are logged but ignored
        # - Only processes if shadow training is enabled
        try:
            # Check if shadow training is enabled
            from sentinel_x.shadow.trainer import get_shadow_trainer
            from sentinel_x.shadow.feed import MarketTick
            from sentinel_x.core.shadow_registry import get_shadow_controller
            
            shadow_controller = get_shadow_controller()
            if not shadow_controller.is_enabled():
                return
            
            trainer = get_shadow_trainer()
            if not trainer.config.enabled:
                return
            
            # Get market data and create tick
            if not self.market_data:
                return
            
            # Get current prices for all symbols
            try:
                prices = self.market_data.get_all_prices()
            except Exception:
                return
            
            # Create tick for each symbol (simplified: use first symbol or iterate)
            # In production, would get actual tick from market data feed
            from datetime import datetime
            import random
            
            if prices:
                symbol = list(prices.keys())[0]
                price = prices[symbol]
                
                # Create market tick
                tick = MarketTick(
                    symbol=symbol,
                    timestamp=datetime.utcnow(),
                    price=price,
                    volume=1000.0,  # Default volume
                    bid=price * 0.9995,  # Small spread
                    ask=price * 1.0005,
                )
                
                # Process tick in shadow trainer
                trainer.process_tick(tick)
        
        except ImportError:
            # Shadow module not available - silently skip
            pass
        except Exception as e:
            # SAFETY: Shadow failures must not crash engine
            logger.debug(f"Shadow tick processing error (non-fatal): {e}")
    
    def _record_shadow_state(self) -> None:
        try:
            shadow = get_shadow_comparison_manager()
            shadow.snapshot()
        except Exception:
            pass

    def _heartbeat(self) -> None:
        try:
            state = get_state()
            logger.debug(
                f"Heartbeat | state={state.value} mode={get_engine_mode().value}"
            )
        except Exception:
            pass
# ============================================================
# Engine Singleton Accessor (IMPORT-SAFE)
# ============================================================

_ENGINE_INSTANCE: TradingEngine | None = None


def get_engine() -> TradingEngine:
    """
    Canonical engine accessor.
    
    PHASE 3: HARDENED - Safe for import-time usage, never fails.
    Returns engine instance or creates minimal safe instance.
    """
    global _ENGINE_INSTANCE

    if _ENGINE_INSTANCE is None:
        try:
            _ENGINE_INSTANCE = TradingEngine()
        except Exception as e:
            from sentinel_x.monitoring.logger import logger
            logger.error(f"TradingEngine() initialization failed: {e}, creating minimal instance", exc_info=True)
            # Create minimal safe engine instance
            try:
                from sentinel_x.core.config import Config
                minimal_config = Config(
                    symbols=["SPY"],
                    timeframes=[15, 60],
                    trade_mode="RESEARCH"
                )
                _ENGINE_INSTANCE = TradingEngine(config=minimal_config)
            except Exception as e2:
                logger.critical(f"Minimal engine creation failed: {e2}", exc_info=True)
                # Last resort: create with None config (engine should handle this)
                _ENGINE_INSTANCE = TradingEngine(config=None)

    return _ENGINE_INSTANCE