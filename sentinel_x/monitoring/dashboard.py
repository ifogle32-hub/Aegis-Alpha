"""
PHASE 1-10 — STRATEGY PERFORMANCE DASHBOARD (READ-ONLY)

SAFETY: dashboard is read-only
SAFETY: no execution dependency
REGRESSION LOCK — OBSERVABILITY ONLY

The dashboard MUST:
- Reflect reality (no derived control logic)
- Be passive and non-interactive
- Never call execution paths
- Never mutate strategy state

The dashboard MUST NOT:
- Start / stop engine
- Enable / disable strategies
- Modify capital allocation
- Trigger promotions or demotions

Invariant: "Dashboard must never influence trading decisions."

PHASE 9 — REGRESSION LOCKS:
# SAFETY: dashboard layer is read-only
# SAFETY: no execution dependency
# REGRESSION LOCK — OBSERVABILITY ONLY

Document invariant:
"Dashboard must never influence trading decisions."
"""

# ============================================================
# REGRESSION LOCK — OBSERVABILITY ONLY
# ============================================================
# Dashboard layer is read-only.
# No execution behavior modified.
# Changes require architectural review.
# ============================================================
# NO future changes may:
#   • Add write operations
#   • Call execution paths
#   • Mutate strategy state
#   • Block engine loop
#   • Add control buttons
# ============================================================

import sqlite3
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from sentinel_x.intelligence.strategy_manager import get_strategy_manager
except Exception:
    get_strategy_manager = None

try:
    from sentinel_x.monitoring.metrics_store import get_metrics_store
except Exception:
    get_metrics_store = None

try:
    from sentinel_x.monitoring.pnl import get_pnl_engine
except Exception:
    get_pnl_engine = None

try:
    from sentinel_x.monitoring.heartbeat import read_heartbeat
except Exception:
    read_heartbeat = None

try:
    from sentinel_x.core.engine_mode import get_engine_mode
    from sentinel_x.core.engine import TradingEngine
except Exception:
    get_engine_mode = None
    TradingEngine = None


# ============================================================
# PHASE 3 — DASHBOARD DATA MODELS (IMMUTABLE DTOS)
# ============================================================
# SAFETY: No business logic
# SAFETY: No execution references
# SAFETY: Snapshots only
# ============================================================

@dataclass(frozen=True)
class StrategyPerformanceView:
    """
    PHASE 3: Immutable strategy performance view (read-only snapshot).
    
    SAFETY: dashboard layer is read-only
    SAFETY: no execution dependency
    """
    strategy_name: str
    lifecycle_state: str  # TRAINING, DISABLED, SHADOW, APPROVED
    status: str  # ACTIVE, DISABLED, AUTO_DISABLED
    trades_count: int
    realized_pnl: float
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    expectancy: float = 0.0
    sharpe: Optional[float] = None
    max_drawdown: float = 0.0
    composite_score: float = 0.0
    capital_weight: float = 0.0
    ranking: Optional[int] = None
    last_trade_time: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    consecutive_losses: int = 0
    promotion_eligible: bool = False
    demotion_evaluation: bool = False
    last_disable_reason: Optional[str] = None


@dataclass(frozen=True)
class StrategyRankingView:
    """
    PHASE 4: Strategy ranking view (display only, no control).
    
    SAFETY: ranking does NOT affect lifecycle
    SAFETY: rankings do NOT affect promotion logic
    SAFETY: purely informational
    """
    strategy_name: str
    rank: int
    composite_score: float
    realized_pnl: float
    sharpe: Optional[float]
    max_drawdown: float
    lifecycle_state: str
    sort_key: str  # Which metric this ranking is based on


@dataclass(frozen=True)
class SystemPerformanceView:
    """
    PHASE 2: Global system performance view (read-only snapshot).
    
    SAFETY: dashboard layer is read-only
    SAFETY: no execution dependency
    """
    total_strategies: int
    active_strategies: int
    disabled_strategies: int
    training_strategies: int
    total_realized_pnl: float
    total_unrealized_pnl: float
    total_pnl: float
    system_drawdown: float
    system_max_drawdown: float
    training_duration_seconds: Optional[float] = None
    engine_mode: str = "UNKNOWN"
    last_update: datetime = field(default_factory=datetime.now)


# ============================================================
# PHASE 2 — METRICS ACCESS LAYER (READ-ONLY)
# ============================================================
# SAFETY: Metrics are read-only
# SAFETY: No writes allowed from dashboard
# ============================================================

class StrategyDashboard:
    """
    PHASE 1-10: Read-only strategy performance dashboard.
    
    SAFETY: dashboard is read-only
    SAFETY: no execution dependency
    REGRESSION LOCK — OBSERVABILITY ONLY
    
    Provides:
    - Per-strategy performance metrics
    - Global system metrics
    - Strategy rankings (display only)
    - Historical snapshots
    - Audit trail visibility
    
    Never:
    - Mutates strategy state
    - Calls execution paths
    - Blocks engine loop
    - Affects trading decisions
    """
    
    def __init__(self, 
                 metrics_store_path: str = "sentinel_x_metrics.db",
                 cache_ttl_seconds: float = 5.0):
        """
        Initialize dashboard (read-only).
        
        Args:
            metrics_store_path: Path to metrics database
            cache_ttl_seconds: Cache TTL for queries (default 5s)
        """
        self.metrics_store_path = Path(metrics_store_path)
        self.cache_ttl_seconds = cache_ttl_seconds
        
        # PHASE 7: Simple cache for non-blocking queries
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_lock = type('Lock', (), {'acquire': lambda: None, 'release': lambda: None})()
        
        logger.info(f"StrategyDashboard initialized (read-only, cache_ttl={cache_ttl_seconds}s)")
    
    def get_strategy_lifecycle_history(self, strategy_name: str) -> List[Dict[str, Any]]:
        """
        PHASE 8: Get strategy lifecycle history (audit trail, read-only).
        
        SAFETY: dashboard is read-only
        SAFETY: no execution dependency
        
        Exposes:
        - Promotion / demotion history
        - Strategy lifecycle transitions
        - Timestamped state changes
        
        Purpose:
        - Explainability
        - Debugging
        - Future compliance
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            List of lifecycle transition records
        """
        try:
            strategy_manager = get_strategy_manager() if get_strategy_manager else None
            if not strategy_manager:
                return []
            
            # Get lifecycle history (read-only)
            history = strategy_manager.lifecycle_history.get(strategy_name, [])
            
            # Return as list of dicts (immutable snapshots)
            return [
                {
                    'from': transition.get('from'),
                    'to': transition.get('to'),
                    'action': transition.get('action'),
                    'reason': transition.get('reason'),
                    'timestamp': transition.get('timestamp'),
                    'score': transition.get('score'),
                    'capital_weight': transition.get('capital_weight')
                }
                for transition in history
            ]
            
        except Exception as e:
            logger.error(f"Error getting lifecycle history for {strategy_name}: {e}", exc_info=True)
            return []
    
    def get_strategy_performance(self, strategy_name: str) -> Optional[StrategyPerformanceView]:
        """
        PHASE 2: Get per-strategy performance metrics (read-only).
        
        SAFETY: dashboard is read-only
        SAFETY: no execution dependency
        
        Exposes:
        - lifecycle_state
        - trades_count
        - realized_pnl
        - unrealized_pnl (if available)
        - win_rate
        - expectancy
        - sharpe (if computed)
        - max_drawdown
        - last_trade_time
        - last_heartbeat
        
        Args:
            strategy_name: Strategy name
            
        Returns:
            StrategyPerformanceView or None if strategy not found
        """
        try:
            # Check cache first (non-blocking)
            cache_key = f"strategy_perf_{strategy_name}"
            cached_result = self._get_from_cache(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Get strategy manager (safe - read-only)
            strategy_manager = get_strategy_manager() if get_strategy_manager else None
            if not strategy_manager:
                logger.warning("StrategyManager not available for dashboard")
                return None
            
            # Get governance summary (read-only)
            governance_summary = strategy_manager.get_strategy_governance_summary(strategy_name)
            if 'error' in governance_summary:
                return None
            
            # Get normalized metrics (read-only)
            metrics = strategy_manager.compute_normalized_metrics(strategy_name)
            
            # Get rolling performance (read-only)
            rolling_perf = strategy_manager.get_rolling_performance(strategy_name)
            
            # PHASE 6: Get capital allocation for this strategy (read-only, simulated)
            capital_weight = governance_summary.get('capital_weight', 0.0)
            try:
                from sentinel_x.intelligence.capital_allocator import get_capital_allocator
                allocator = get_capital_allocator() if get_capital_allocator else None
                if allocator:
                    # Get latest allocation snapshot (read-only)
                    snapshot = allocator.get_latest_allocation_snapshot()
                    if not snapshot:
                        # Compute new allocation (read-only, non-blocking)
                        snapshot = allocator.allocate_from_strategy_manager()
                    
                    if snapshot:
                        # Get allocation for this strategy (read-only)
                        for alloc in snapshot.allocations:
                            if alloc.get('strategy_name') == strategy_name:
                                capital_weight = alloc.get('recommended_weight', 0.0)
                                break
            except Exception as e:
                logger.debug(f"Error getting capital allocation for {strategy_name} (non-fatal): {e}")
            
            # Get PnL engine for unrealized PnL (read-only)
            unrealized_pnl = 0.0
            try:
                pnl_engine = get_pnl_engine() if get_pnl_engine else None
                if pnl_engine:
                    # Get unrealized PnL for this strategy (non-blocking read)
                    strategy_positions = pnl_engine.positions if hasattr(pnl_engine, 'positions') else {}
                    for symbol, position in strategy_positions.items():
                        # This is approximate - would need strategy-to-position mapping
                        current_price = position.get('current_price', position.get('avg_price', 0))
                        entry_price = position.get('avg_price', 0)
                        qty = position.get('qty', 0)
                        if current_price > 0 and entry_price > 0:
                            unrealized_pnl += qty * (current_price - entry_price)
            except Exception as e:
                logger.debug(f"Error getting unrealized PnL (non-fatal): {e}")
            
            # Get last trade time from metrics store (read-only, non-blocking)
            last_trade_time = None
            try:
                last_trade_time = self._get_last_trade_time(strategy_name)
            except Exception as e:
                logger.debug(f"Error getting last trade time (non-fatal): {e}")
            
            # Get last heartbeat (read-only)
            last_heartbeat = None
            try:
                heartbeat = read_heartbeat() if read_heartbeat else None
                if heartbeat and 'strategy_heartbeats' in heartbeat:
                    strategy_hb = heartbeat['strategy_heartbeats'].get(strategy_name, {})
                    if 'last_tick_ts' in strategy_hb:
                        # Convert monotonic time to datetime (approximate)
                        last_heartbeat = datetime.now()  # Would need engine start time for exact conversion
            except Exception as e:
                logger.debug(f"Error getting last heartbeat (non-fatal): {e}")
            
            # Build performance view (immutable)
            view = StrategyPerformanceView(
                strategy_name=strategy_name,
                lifecycle_state=governance_summary.get('lifecycle_state', 'TRAINING'),
                status=governance_summary.get('status', 'DISABLED'),
                trades_count=metrics.get('trades_count', 0),
                realized_pnl=rolling_perf.get('pnl', 0.0),
                unrealized_pnl=unrealized_pnl,
                total_pnl=rolling_perf.get('pnl', 0.0) + unrealized_pnl,
                win_rate=metrics.get('win_rate', 0.0),
                expectancy=metrics.get('expectancy', 0.0),
                sharpe=metrics.get('sharpe'),
                max_drawdown=metrics.get('max_drawdown', 0.0),
                composite_score=governance_summary.get('composite_score', 0.0),
                capital_weight=capital_weight,  # PHASE 6: Simulated capital allocation (read-only, advisory only)
                ranking=governance_summary.get('ranking_position'),
                last_trade_time=last_trade_time,
                last_heartbeat=last_heartbeat,
                consecutive_losses=rolling_perf.get('consecutive_losses', 0),
                promotion_eligible=governance_summary.get('promotion_eligibility', {}).get('eligible', False),
                demotion_evaluation=governance_summary.get('demotion_evaluation', {}).get('should_demote', False),
                last_disable_reason=governance_summary.get('last_disable_reason')
            )
            
            # Cache result (non-blocking)
            self._set_cache(cache_key, view)
            
            return view
            
        except Exception as e:
            logger.error(f"Error getting strategy performance for {strategy_name}: {e}", exc_info=True)
            return None
    
    def get_all_strategies_performance(self) -> List[StrategyPerformanceView]:
        """
        PHASE 2: Get performance metrics for all strategies (read-only).
        
        SAFETY: dashboard is read-only
        SAFETY: no execution dependency
        
        Returns:
            List of StrategyPerformanceView (sorted by ranking)
        """
        try:
            strategy_manager = get_strategy_manager() if get_strategy_manager else None
            if not strategy_manager:
                return []
            
            # Get all strategy names (read-only)
            strategies_list = strategy_manager.list_strategies()
            strategy_names = [s['name'] for s in strategies_list]
            
            # Get performance for each (non-blocking reads)
            performances = []
            for name in strategy_names:
                perf = self.get_strategy_performance(name)
                if perf:
                    performances.append(perf)
            
            # Sort by ranking (display only - no control)
            performances.sort(key=lambda x: (x.ranking if x.ranking is not None else 9999, -x.composite_score))
            
            return performances
            
        except Exception as e:
            logger.error(f"Error getting all strategies performance: {e}", exc_info=True)
            return []
    
    def get_strategy_rankings(self, sort_by: str = "composite_score") -> List[StrategyRankingView]:
        """
        PHASE 4: Get strategy rankings (display only, no control).
        
        SAFETY: ranking does NOT affect lifecycle
        SAFETY: rankings do NOT affect promotion logic
        SAFETY: purely informational
        
        Sort by:
        - composite_score (default)
        - realized_pnl
        - sharpe
        - drawdown (inverse - lower is better)
        
        Args:
            sort_by: Sort key ("composite_score", "realized_pnl", "sharpe", "drawdown")
            
        Returns:
            List of StrategyRankingView (sorted)
        """
        try:
            performances = self.get_all_strategies_performance()
            
            # Sort by requested metric (display only)
            if sort_by == "composite_score":
                performances.sort(key=lambda x: -x.composite_score)
            elif sort_by == "realized_pnl":
                performances.sort(key=lambda x: -x.realized_pnl)
            elif sort_by == "sharpe":
                performances.sort(key=lambda x: -(x.sharpe if x.sharpe is not None else -999))
            elif sort_by == "drawdown":
                performances.sort(key=lambda x: x.max_drawdown)  # Lower is better
            else:
                # Default to composite_score
                performances.sort(key=lambda x: -x.composite_score)
            
            # Build ranking views (immutable)
            rankings = []
            for idx, perf in enumerate(performances):
                rankings.append(StrategyRankingView(
                    strategy_name=perf.strategy_name,
                    rank=idx + 1,
                    composite_score=perf.composite_score,
                    realized_pnl=perf.realized_pnl,
                    sharpe=perf.sharpe,
                    max_drawdown=perf.max_drawdown,
                    lifecycle_state=perf.lifecycle_state,
                    sort_key=sort_by
                ))
            
            return rankings
            
        except Exception as e:
            logger.error(f"Error getting strategy rankings: {e}", exc_info=True)
            return []
    
    def get_capital_allocation(self) -> Optional[Dict[str, Any]]:
        """
        PHASE 6: Get capital allocation snapshot (read-only, advisory only).
        
        SAFETY: allocation is simulated only
        SAFETY: no execution influence
        
        Returns:
            CapitalAllocationSnapshot as dict (read-only)
        """
        try:
            from sentinel_x.intelligence.capital_allocator import get_capital_allocator
            
            allocator = get_capital_allocator() if get_capital_allocator else None
            if not allocator:
                return None
            
            # Get latest snapshot or compute new one (read-only)
            snapshot = allocator.get_latest_allocation_snapshot()
            if not snapshot:
                # Compute new allocation (read-only)
                snapshot = allocator.allocate_from_strategy_manager()
            
            if not snapshot:
                return None
            
            # Return as dict (read-only)
            return snapshot.to_dict()
            
        except Exception as e:
            logger.error(f"Error getting capital allocation: {e}", exc_info=True)
            return None
    
    def get_system_performance(self) -> SystemPerformanceView:
        """
        PHASE 2: Get global system performance metrics (read-only).
        
        SAFETY: dashboard is read-only
        SAFETY: no execution dependency
        
        Exposes:
        - total strategies
        - active vs disabled count
        - total PnL
        - drawdown
        - training duration
        
        Returns:
            SystemPerformanceView
        """
        try:
            # Check cache first (non-blocking)
            cache_key = "system_performance"
            cached_result = self._get_from_cache(cache_key)
            if cached_result is not None:
                return cached_result
            
            strategy_manager = get_strategy_manager() if get_strategy_manager else None
            if not strategy_manager:
                return SystemPerformanceView(
                    total_strategies=0,
                    active_strategies=0,
                    disabled_strategies=0,
                    training_strategies=0,
                    total_realized_pnl=0.0,
                    total_unrealized_pnl=0.0,
                    total_pnl=0.0,
                    system_drawdown=0.0,
                    system_max_drawdown=0.0,
                    engine_mode="UNKNOWN"
                )
            
            # Get all strategies (read-only)
            strategies_list = strategy_manager.list_strategies()
            
            # Count strategies by state (read-only)
            total_strategies = len(strategies_list)
            active_strategies = len([s for s in strategies_list if s['status'] == 'ACTIVE'])
            disabled_strategies = len([s for s in strategies_list if s['status'] in ('DISABLED', 'AUTO_DISABLED')])
            training_strategies = len([s for s in strategies_list if s.get('lifecycle_state') == 'TRAINING'])
            
            # Get all performances (read-only)
            performances = self.get_all_strategies_performance()
            
            # Aggregate PnL (read-only)
            total_realized_pnl = sum(p.realized_pnl for p in performances)
            total_unrealized_pnl = sum(p.unrealized_pnl for p in performances)
            total_pnl = total_realized_pnl + total_unrealized_pnl
            
            # Calculate system drawdown (read-only, approximate)
            system_drawdown = max((p.max_drawdown for p in performances), default=0.0)
            system_max_drawdown = system_drawdown  # Would need historical tracking for true max
            
            # Get training duration (read-only)
            training_duration_seconds = None
            try:
                heartbeat = read_heartbeat() if read_heartbeat else None
                if heartbeat and 'timestamp' in heartbeat:
                    # Approximate - would need engine start time
                    training_duration_seconds = None  # Would calculate from engine start
            except Exception as e:
                logger.debug(f"Error getting training duration (non-fatal): {e}")
            
            # Get engine mode (read-only)
            engine_mode = "UNKNOWN"
            try:
                if get_engine_mode:
                    mode = get_engine_mode()
                    engine_mode = mode.value if hasattr(mode, 'value') else str(mode)
            except Exception as e:
                logger.debug(f"Error getting engine mode (non-fatal): {e}")
            
            view = SystemPerformanceView(
                total_strategies=total_strategies,
                active_strategies=active_strategies,
                disabled_strategies=disabled_strategies,
                training_strategies=training_strategies,
                total_realized_pnl=total_realized_pnl,
                total_unrealized_pnl=total_unrealized_pnl,
                total_pnl=total_pnl,
                system_drawdown=system_drawdown,
                system_max_drawdown=system_max_drawdown,
                training_duration_seconds=training_duration_seconds,
                engine_mode=engine_mode
            )
            
            # Cache result (non-blocking)
            self._set_cache(cache_key, view)
            
            return view
            
        except Exception as e:
            logger.error(f"Error getting system performance: {e}", exc_info=True)
            return SystemPerformanceView(
                total_strategies=0,
                active_strategies=0,
                disabled_strategies=0,
                training_strategies=0,
                total_realized_pnl=0.0,
                total_unrealized_pnl=0.0,
                total_pnl=0.0,
                system_drawdown=0.0,
                system_max_drawdown=0.0,
                engine_mode="UNKNOWN"
            )
    
    def _get_last_trade_time(self, strategy_name: str) -> Optional[datetime]:
        """
        PHASE 2: Get last trade time for strategy (read-only, non-blocking).
        
        SAFETY: dashboard is read-only
        SAFETY: no execution dependency
        """
        try:
            if not self.metrics_store_path.exists():
                return None
            
            conn = sqlite3.connect(self.metrics_store_path, timeout=2.0)
            cursor = conn.cursor()
            
            # Get latest fill timestamp for strategy (read-only)
            cursor.execute("""
                SELECT MAX(timestamp) 
                FROM fills 
                WHERE strategy = ?
            """, (strategy_name,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0]:
                try:
                    return datetime.fromisoformat(result[0].replace('Z', '+00:00'))
                except Exception:
                    return None
            
            return None
            
        except Exception as e:
            logger.debug(f"Error querying last trade time (non-fatal): {e}")
            return None
    
    def _get_from_cache(self, key: str) -> Optional[Any]:
        """PHASE 7: Get from cache (non-blocking, thread-safe approximation)."""
        try:
            if key in self._cache:
                value, timestamp = self._cache[key]
                age = time.time() - timestamp
                if age < self.cache_ttl_seconds:
                    return value
                else:
                    # Expired, remove from cache
                    del self._cache[key]
            return None
        except Exception:
            return None
    
    def _set_cache(self, key: str, value: Any) -> None:
        """PHASE 7: Set cache (non-blocking, thread-safe approximation)."""
        try:
            # Simple cache with size limit (prevent memory growth)
            if len(self._cache) > 100:
                # Clear oldest entries (simple FIFO approximation)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            
            self._cache[key] = (value, time.time())
        except Exception:
            pass  # Cache failures are non-fatal


# Global dashboard instance
_dashboard: Optional[StrategyDashboard] = None


def get_strategy_dashboard(metrics_store_path: str = "sentinel_x_metrics.db",
                          cache_ttl_seconds: float = 5.0) -> StrategyDashboard:
    """
    PHASE 1: Get global strategy dashboard instance (read-only).
    
    SAFETY: dashboard is read-only
    SAFETY: no execution dependency
    """
    global _dashboard
    if _dashboard is None:
        _dashboard = StrategyDashboard(metrics_store_path, cache_ttl_seconds)
    return _dashboard
