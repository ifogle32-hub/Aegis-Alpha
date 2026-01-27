"""
PHASE 1-2: Execution Metrics Tracking and Quality Scoring

For each strategy track:
- Average slippage (bps)
- Slippage variance
- Fill ratio
- Execution latency (ms)
- Missed fills
- Cancel rates

Metrics must be time-windowed and persistent.

ExecutionQualityScore ∈ [0, 1]:
- Slippage vs benchmark
- Latency stability
- Fill consistency
- Divergence vs shadow

Poor execution lowers score regardless of PnL.
"""

import sqlite3
import threading
import time
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sentinel_x.monitoring.logger import logger
from sentinel_x.execution.models import ExecutionRecord, ExecutionStatus


@dataclass
class ExecutionMetrics:
    """Execution metrics for a strategy over a time window."""
    strategy_name: str
    window_start: datetime
    window_end: datetime
    
    # Slippage metrics
    avg_slippage_bps: float = 0.0  # Average slippage in basis points
    slippage_variance: float = 0.0  # Variance of slippage
    max_slippage_bps: float = 0.0  # Maximum slippage
    
    # Fill metrics
    fill_ratio: float = 0.0  # filled_qty / requested_qty
    total_requests: int = 0  # Total order intents
    total_fills: int = 0  # Total filled orders
    total_partial_fills: int = 0  # Total partially filled orders
    missed_fills: int = 0  # Orders that didn't fill
    
    # Latency metrics
    avg_latency_ms: float = 0.0  # Average execution latency
    latency_std_ms: float = 0.0  # Standard deviation of latency
    max_latency_ms: float = 0.0  # Maximum latency
    
    # Cancel metrics
    cancel_rate: float = 0.0  # cancelled / total
    
    # Shadow comparison
    shadow_divergence_bps: float = 0.0  # Average divergence vs shadow (bps)
    
    # Execution quality score
    execution_quality_score: float = 0.0  # [0, 1]
    
    calculated_at: datetime = field(default_factory=datetime.utcnow)


class ExecutionMetricsTracker:
    """
    Tracks execution metrics per strategy with time-windowed aggregation.
    
    PHASE 1: Time-windowed metrics tracking
    PHASE 2: Execution quality score calculation
    """
    
    def __init__(self, db_path: str = "sentinel_x_execution_metrics.db", window_hours: int = 24):
        """
        Initialize execution metrics tracker.
        
        Args:
            db_path: Path to SQLite database for persistence
            window_hours: Time window for metrics aggregation (default: 24 hours)
        """
        self.db_path = Path(db_path)
        self.window_hours = window_hours
        self._lock = threading.Lock()
        
        # In-memory tracking (rolling window)
        self.execution_records: Dict[str, deque] = {}  # strategy -> deque of ExecutionRecord
        self.max_records_per_strategy = 10000  # Keep last 10k records
        
        # Initialize database
        self._init_database()
        
        logger.info(f"ExecutionMetricsTracker initialized: window={window_hours}h, db={self.db_path}")
    
    def _init_database(self) -> None:
        """Initialize database for metrics persistence."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            cursor = conn.cursor()
            
            # Enable WAL mode
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            
            # Execution records table (append-only)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS execution_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent_id TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_qty REAL NOT NULL,
                    filled_qty REAL NOT NULL,
                    avg_fill_price REAL,
                    slippage_bps REAL,
                    execution_latency_ms REAL,
                    rejection_reason TEXT,
                    timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            
            # Metrics snapshots table (time-windowed)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metrics_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    avg_slippage_bps REAL,
                    slippage_variance REAL,
                    fill_ratio REAL,
                    avg_latency_ms REAL,
                    latency_std_ms REAL,
                    cancel_rate REAL,
                    shadow_divergence_bps REAL,
                    execution_quality_score REAL,
                    calculated_at TEXT NOT NULL,
                    UNIQUE(strategy_name, window_start)
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_records_strategy ON execution_records(strategy_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_records_timestamp ON execution_records(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_snapshots_strategy ON metrics_snapshots(strategy_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_snapshots_window ON metrics_snapshots(window_start, window_end)")
            
            conn.commit()
            conn.close()
            
            logger.info("Execution metrics database initialized")
        except Exception as e:
            logger.error(f"Error initializing execution metrics database: {e}", exc_info=True)
    
    def record_execution(self, record: ExecutionRecord, strategy_name: str, symbol: str) -> None:
        """
        Record an execution for metrics tracking.
        
        PHASE 1: Append-only recording of execution records.
        """
        try:
            with self._lock:
                # Add to in-memory tracking
                if strategy_name not in self.execution_records:
                    self.execution_records[strategy_name] = deque(maxlen=self.max_records_per_strategy)
                
                # Store full record (not just dict)
                self.execution_records[strategy_name].append(record)
            
            # Persist to database (non-blocking, fire-and-forget)
            self._persist_execution_record(record, strategy_name, symbol)
        
        except Exception as e:
            logger.error(f"Error recording execution: {e}", exc_info=True)
    
    def _persist_execution_record(self, record: ExecutionRecord, strategy_name: str, symbol: str) -> None:
        """Persist execution record to database."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=1.0)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO execution_records 
                (intent_id, strategy_name, symbol, status, requested_qty, filled_qty, 
                 avg_fill_price, slippage_bps, execution_latency_ms, rejection_reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.intent_id,
                strategy_name,
                symbol,
                record.status.value,
                record.requested_qty,
                record.filled_qty,
                record.avg_fill_price,
                record.slippage_bps,
                record.execution_latency_ms,
                record.rejection_reason,
                record.submitted_at.isoformat() + "Z" if record.submitted_at else record.created_at.isoformat() + "Z"
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Error persisting execution record (non-fatal): {e}")
    
    def calculate_metrics(
        self,
        strategy_name: str,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
        window_hours: Optional[int] = None
    ) -> ExecutionMetrics:
        """
        Calculate execution metrics for a strategy over a time window.
        
        PHASE 1: Time-windowed metrics calculation.
        
        Args:
            strategy_name: Strategy name
            window_start: Window start time (default: now - window_hours)
            window_end: Window end time (default: now)
            
        Returns:
            ExecutionMetrics object
        """
        if window_end is None:
            window_end = datetime.utcnow()
        if window_start is None:
            window_hours_actual = window_hours if window_hours is not None else self.window_hours
            window_start = window_end - timedelta(hours=window_hours_actual)
        
        try:
            with self._lock:
                records = list(self.execution_records.get(strategy_name, []))
            
            # Filter records by time window
            window_records = [
                r for r in records
                if r.submitted_at and window_start <= r.submitted_at <= window_end
            ]
            
            if not window_records:
                # Return default metrics if no records
                return ExecutionMetrics(
                    strategy_name=strategy_name,
                    window_start=window_start,
                    window_end=window_end,
                    execution_quality_score=0.5  # Neutral score
                )
            
            # Calculate slippage metrics
            slippages = [r.slippage_bps for r in window_records if r.slippage_bps != 0.0]
            if slippages:
                avg_slippage_bps = sum(slippages) / len(slippages)
                if len(slippages) > 1:
                    mean = avg_slippage_bps
                    variance = sum((x - mean) ** 2 for x in slippages) / (len(slippages) - 1)
                    slippage_variance = variance
                else:
                    slippage_variance = 0.0
                max_slippage_bps = max(abs(s) for s in slippages)
            else:
                avg_slippage_bps = 0.0
                slippage_variance = 0.0
                max_slippage_bps = 0.0
            
            # Calculate fill metrics
            total_requests = len(window_records)
            filled_records = [r for r in window_records if r.status in (ExecutionStatus.FILLED, ExecutionStatus.PARTIALLY_FILLED)]
            total_fills = len([r for r in filled_records if r.status == ExecutionStatus.FILLED])
            total_partial_fills = len([r for r in filled_records if r.status == ExecutionStatus.PARTIALLY_FILLED])
            missed_fills = len([r for r in window_records if r.status in (ExecutionStatus.REJECTED, ExecutionStatus.EXPIRED)])
            
            total_filled_qty = sum(r.filled_qty for r in filled_records)
            total_requested_qty = sum(r.requested_qty for r in window_records)
            fill_ratio = total_filled_qty / total_requested_qty if total_requested_qty > 0 else 0.0
            
            # Calculate latency metrics
            latencies = [r.execution_latency_ms for r in window_records if r.execution_latency_ms > 0]
            if latencies:
                avg_latency_ms = sum(latencies) / len(latencies)
                if len(latencies) > 1:
                    mean = avg_latency_ms
                    variance = sum((x - mean) ** 2 for x in latencies) / (len(latencies) - 1)
                    latency_std_ms = math.sqrt(variance)
                else:
                    latency_std_ms = 0.0
                max_latency_ms = max(latencies)
            else:
                avg_latency_ms = 0.0
                latency_std_ms = 0.0
                max_latency_ms = 0.0
            
            # Calculate cancel rate
            cancelled = len([r for r in window_records if r.status == ExecutionStatus.CANCELLED])
            cancel_rate = cancelled / total_requests if total_requests > 0 else 0.0
            
            # PHASE 4: Calculate shadow divergence (shadow vs execution)
            shadow_divergence_bps = 0.0
            try:
                from sentinel_x.monitoring.shadow_comparison import get_shadow_comparison_manager
                shadow_manager = get_shadow_comparison_manager()
                comparison_summary = shadow_manager.get_comparison_summary()
                
                # Get divergence for this strategy
                strategy_deltas = comparison_summary.get('strategy_deltas', {})
                strategy_delta = strategy_deltas.get(strategy_name)
                
                if strategy_delta:
                    # Calculate divergence as average PnL delta per trade (converted to bps)
                    # This is a simplified calculation - in production, would use actual price deltas
                    pnl_delta = strategy_delta.get('pnl_delta', 0.0)
                    shadow_pnl = strategy_delta.get('shadow_pnl', 0.0)
                    
                    if shadow_pnl != 0 and total_fills > 0:
                        # Approximate divergence in bps (simplified)
                        # Would need actual price deltas for accurate bps calculation
                        avg_pnl_delta = abs(pnl_delta) / total_fills
                        # Estimate bps from PnL delta (rough approximation)
                        shadow_divergence_bps = avg_pnl_delta / 100.0  # Simplified conversion
            except Exception as e:
                logger.debug(f"Error calculating shadow divergence (non-fatal): {e}")
            
            # Calculate execution quality score
            execution_quality_score = self._calculate_execution_quality_score(
                avg_slippage_bps=avg_slippage_bps,
                slippage_variance=slippage_variance,
                fill_ratio=fill_ratio,
                avg_latency_ms=avg_latency_ms,
                latency_std_ms=latency_std_ms,
                cancel_rate=cancel_rate,
                shadow_divergence_bps=shadow_divergence_bps
            )
            
            metrics = ExecutionMetrics(
                strategy_name=strategy_name,
                window_start=window_start,
                window_end=window_end,
                avg_slippage_bps=avg_slippage_bps,
                slippage_variance=slippage_variance,
                max_slippage_bps=max_slippage_bps,
                fill_ratio=fill_ratio,
                total_requests=total_requests,
                total_fills=total_fills,
                total_partial_fills=total_partial_fills,
                missed_fills=missed_fills,
                avg_latency_ms=avg_latency_ms,
                latency_std_ms=latency_std_ms,
                max_latency_ms=max_latency_ms,
                cancel_rate=cancel_rate,
                shadow_divergence_bps=shadow_divergence_bps,
                execution_quality_score=execution_quality_score
            )
            
            # Persist metrics snapshot
            self._persist_metrics_snapshot(metrics)
            
            return metrics
        
        except Exception as e:
            logger.error(f"Error calculating execution metrics: {e}", exc_info=True)
            return ExecutionMetrics(
                strategy_name=strategy_name,
                window_start=window_start or datetime.utcnow(),
                window_end=window_end or datetime.utcnow(),
                execution_quality_score=0.0  # Failed calculation = 0 score
            )
    
    def _calculate_execution_quality_score(
        self,
        avg_slippage_bps: float,
        slippage_variance: float,
        fill_ratio: float,
        avg_latency_ms: float,
        latency_std_ms: float,
        cancel_rate: float,
        shadow_divergence_bps: float
    ) -> float:
        """
        PHASE 2: Calculate ExecutionQualityScore ∈ [0, 1].
        
        Formula:
        - Slippage component: penalty for high slippage/variance
        - Latency component: penalty for high/variable latency
        - Fill component: reward for high fill ratio
        - Cancel component: penalty for high cancel rate
        - Shadow divergence component: penalty for divergence
        
        Returns:
            Score in [0, 1] where 1.0 is perfect execution
        """
        # Slippage component (0.0 - 1.0, lower slippage = higher score)
        # Target: < 5 bps average, < 10 bps variance
        slippage_score = 1.0 - min(abs(avg_slippage_bps) / 50.0, 1.0)  # Penalize > 50 bps
        slippage_stability = 1.0 - min(slippage_variance / 100.0, 1.0)  # Penalize > 100 bps variance
        slippage_component = (slippage_score + slippage_stability) / 2.0
        
        # Latency component (0.0 - 1.0, lower latency = higher score)
        # Target: < 100ms average, < 50ms std dev
        latency_score = 1.0 - min(avg_latency_ms / 500.0, 1.0)  # Penalize > 500ms
        latency_stability = 1.0 - min(latency_std_ms / 200.0, 1.0)  # Penalize > 200ms std dev
        latency_component = (latency_score + latency_stability) / 2.0
        
        # Fill component (0.0 - 1.0, higher fill ratio = higher score)
        # Target: > 0.95 fill ratio
        fill_component = min(fill_ratio / 0.95, 1.0) if fill_ratio > 0 else 0.0
        
        # Cancel component (0.0 - 1.0, lower cancel rate = higher score)
        # Target: < 0.05 cancel rate
        cancel_component = 1.0 - min(cancel_rate / 0.1, 1.0)  # Penalize > 10% cancel rate
        
        # Shadow divergence component (0.0 - 1.0, lower divergence = higher score)
        # Target: < 10 bps divergence
        divergence_component = 1.0 - min(abs(shadow_divergence_bps) / 50.0, 1.0)  # Penalize > 50 bps
        
        # Weighted composite
        weights = {
            'slippage': 0.3,
            'latency': 0.2,
            'fill': 0.25,
            'cancel': 0.15,
            'divergence': 0.1
        }
        
        score = (
            slippage_component * weights['slippage'] +
            latency_component * weights['latency'] +
            fill_component * weights['fill'] +
            cancel_component * weights['cancel'] +
            divergence_component * weights['divergence']
        )
        
        return max(0.0, min(1.0, score))  # Clamp to [0, 1]
    
    def _persist_metrics_snapshot(self, metrics: ExecutionMetrics) -> None:
        """Persist metrics snapshot to database."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=1.0)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO metrics_snapshots
                (strategy_name, window_start, window_end, avg_slippage_bps, slippage_variance,
                 fill_ratio, avg_latency_ms, latency_std_ms, cancel_rate, shadow_divergence_bps,
                 execution_quality_score, calculated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics.strategy_name,
                metrics.window_start.isoformat() + "Z",
                metrics.window_end.isoformat() + "Z",
                metrics.avg_slippage_bps,
                metrics.slippage_variance,
                metrics.fill_ratio,
                metrics.avg_latency_ms,
                metrics.latency_std_ms,
                metrics.cancel_rate,
                metrics.shadow_divergence_bps,
                metrics.execution_quality_score,
                metrics.calculated_at.isoformat() + "Z"
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Error persisting metrics snapshot (non-fatal): {e}")
    
    def get_latest_metrics(self, strategy_name: str) -> Optional[ExecutionMetrics]:
        """Get latest metrics for a strategy."""
        return self.calculate_metrics(strategy_name)


# Global execution metrics tracker instance
_execution_metrics_tracker: Optional[ExecutionMetricsTracker] = None
_execution_metrics_lock = threading.Lock()


def get_execution_metrics_tracker(db_path: str = "sentinel_x_execution_metrics.db") -> ExecutionMetricsTracker:
    """Get global execution metrics tracker instance."""
    global _execution_metrics_tracker
    if _execution_metrics_tracker is None:
        with _execution_metrics_lock:
            if _execution_metrics_tracker is None:
                _execution_metrics_tracker = ExecutionMetricsTracker(db_path)
    return _execution_metrics_tracker
