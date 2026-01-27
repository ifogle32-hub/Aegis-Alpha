"""
Shadow vs Live Comparison System

OBSERVATIONAL ONLY - Zero execution coupling.
Shadow trading is ALWAYS enabled, NEVER executes orders.
"""
import time
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque
import json
import sqlite3
from pathlib import Path
from sentinel_x.monitoring.logger import logger


@dataclass
class ShadowTrade:
    """Immutable shadow trade record."""
    strategy: str
    symbol: str
    timestamp: datetime
    side: str  # "BUY" or "SELL"
    size: float
    shadow_price: float
    shadow_pnl: float = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'strategy': self.strategy,
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat() + "Z",
            'side': self.side,
            'size': self.size,
            'shadow_price': self.shadow_price,
            'shadow_pnl': self.shadow_pnl
        }


@dataclass
class ExecutionTrade:
    """Immutable execution trade record."""
    strategy: str
    symbol: str
    timestamp: datetime
    side: str  # "BUY" or "SELL"
    size: float
    fill_price: float
    realized_pnl: float = 0.0
    mode: str | None = None  # "PAPER" | "LIVE" | None
    execution_latency_ms: float = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'strategy': self.strategy,
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat() + "Z",
            'side': self.side,
            'size': self.size,
            'fill_price': self.fill_price,
            'realized_pnl': self.realized_pnl,
            'mode': self.mode or "PAPER",  # Default to PAPER if None
            'execution_latency_ms': self.execution_latency_ms
        }


@dataclass
class ComparisonSnapshot:
    """Immutable comparison snapshot record."""
    strategy: str
    symbol: str
    timestamp: datetime
    shadow_pnl: float
    execution_pnl: float
    pnl_delta: float
    slippage: float  # execution_price - shadow_price
    execution_latency_ms: float
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'strategy': self.strategy,
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat() + "Z",
            'shadow_pnl': self.shadow_pnl,
            'execution_pnl': self.execution_pnl,
            'pnl_delta': self.pnl_delta,
            'slippage': self.slippage,
            'execution_latency_ms': self.execution_latency_ms
        }


class ShadowComparisonManager:
    """
    Manages shadow vs execution comparison.
    
    RULES:
    - Shadow ALWAYS records (always-on)
    - Execution records only if trade executed
    - Comparison never blocks execution
    - Missing execution trades are allowed
    """
    
    def __init__(self, db_path: str = "sentinel_x_shadow_comparison.db"):
        """
        Initialize shadow comparison manager.
        
        Args:
            db_path: Path to SQLite database for audit persistence
        """
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        
        # In-memory tracking (for real-time access)
        self.shadow_trades: deque = deque(maxlen=10000)  # Last 10k shadow trades
        self.execution_trades: deque = deque(maxlen=10000)  # Last 10k execution trades
        self.comparison_snapshots: deque = deque(maxlen=5000)  # Last 5k snapshots
        
        # Strategy-level tracking
        self.strategy_shadow_pnl: Dict[str, float] = {}  # strategy -> cumulative shadow PnL
        self.strategy_execution_pnl: Dict[str, float] = {}  # strategy -> cumulative execution PnL
        
        # Divergence tracking
        self.divergence_alerts: deque = deque(maxlen=1000)  # Last 1k divergence alerts
        
        # Initialize database
        self._init_database()
        
        logger.info(f"ShadowComparisonManager initialized: db={self.db_path}")
    
    def _init_database(self) -> None:
        """Initialize audit database (append-only, immutable records)."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            cursor = conn.cursor()
            
            # Enable WAL mode for better concurrency
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            
            # Shadow trades table (append-only)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shadow_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    side TEXT NOT NULL,
                    size REAL NOT NULL,
                    shadow_price REAL NOT NULL,
                    shadow_pnl REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            
            # Execution trades table (append-only)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS execution_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    side TEXT NOT NULL,
                    size REAL NOT NULL,
                    fill_price REAL NOT NULL,
                    realized_pnl REAL NOT NULL DEFAULT 0.0,
                    mode TEXT NOT NULL,
                    execution_latency_ms REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            
            # Comparison snapshots table (append-only)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS comparison_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    shadow_pnl REAL NOT NULL,
                    execution_pnl REAL NOT NULL,
                    pnl_delta REAL NOT NULL,
                    slippage REAL NOT NULL,
                    execution_latency_ms REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            
            # Divergence alerts table (append-only)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS divergence_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    shadow_pnl REAL NOT NULL,
                    execution_pnl REAL NOT NULL,
                    pnl_delta REAL NOT NULL,
                    threshold REAL NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_trades_strategy ON shadow_trades(strategy)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_shadow_trades_timestamp ON shadow_trades(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_trades_strategy ON execution_trades(strategy)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_trades_timestamp ON execution_trades(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_comparison_snapshots_strategy ON comparison_snapshots(strategy)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_comparison_snapshots_timestamp ON comparison_snapshots(timestamp)")
            
            conn.commit()
            conn.close()
            
            logger.info("Shadow comparison database initialized")
        except Exception as e:
            logger.error(f"Error initializing shadow comparison database: {e}", exc_info=True)
            # Non-fatal - continue without persistence
    
    def record_shadow_trade(
        self,
        strategy: str,
        symbol: str,
        side: str,
        size: float,
        shadow_price: float,
        shadow_pnl: float = 0.0
    ) -> None:
        """
        Record a shadow trade (ALWAYS called on every strategy signal).
        
        This is NON-BLOCKING and NEVER fails.
        Shadow trades are ALWAYS recorded, even if execution fails.
        """
        try:
            timestamp = datetime.utcnow()
            trade = ShadowTrade(
                strategy=strategy,
                symbol=symbol,
                timestamp=timestamp,
                side=side.upper(),
                size=abs(size),
                shadow_price=shadow_price,
                shadow_pnl=shadow_pnl
            )
            
            with self._lock:
                self.shadow_trades.append(trade)
                
                # Update strategy PnL
                if strategy not in self.strategy_shadow_pnl:
                    self.strategy_shadow_pnl[strategy] = 0.0
                self.strategy_shadow_pnl[strategy] += shadow_pnl
            
            # Persist to database (non-blocking, fire-and-forget)
            self._persist_shadow_trade(trade)
            
        except Exception as e:
            # Shadow recording failures are non-fatal - log and continue
            logger.error(f"Error recording shadow trade: {e}", exc_info=True)
    
    def record_execution_trade(
        self,
        strategy: str,
        symbol: str,
        side: str,
        size: float,
        fill_price: float,
        realized_pnl: float | None = None,
        mode: str | None = None,
        execution_latency_ms: float = 0.0
    ) -> None:
        """
        Record an execution trade (only if trade actually executed).
        
        PHASE 1: SAFE SIGNATURE - realized_pnl and mode are optional.
        Analytics layers infer values if needed. Execution never depends on them.
        
        This is NON-BLOCKING and NEVER fails.
        Missing execution trades are allowed (shadow-only scenario).
        """
        try:
            # PHASE 1: Safe defaults - never require realized_pnl or mode
            safe_realized_pnl = realized_pnl if realized_pnl is not None else 0.0
            
            # Lazy resolution: Get mode from engine if not provided
            if mode is None:
                try:
                    from sentinel_x.core.engine_mode import get_engine_mode
                    engine_mode = get_engine_mode()
                    safe_mode = engine_mode.value  # Use current engine mode
                except Exception:
                    safe_mode = "PAPER"  # Fallback if engine mode unavailable
            else:
                safe_mode = mode.upper()
            
            timestamp = datetime.utcnow()
            trade = ExecutionTrade(
                strategy=strategy,
                symbol=symbol,
                timestamp=timestamp,
                side=side.upper(),
                size=abs(size),
                fill_price=fill_price,
                realized_pnl=safe_realized_pnl,
                mode=safe_mode,
                execution_latency_ms=execution_latency_ms
            )
            
            with self._lock:
                self.execution_trades.append(trade)
                
                # Update strategy PnL
                if strategy not in self.strategy_execution_pnl:
                    self.strategy_execution_pnl[strategy] = 0.0
                self.strategy_execution_pnl[strategy] += safe_realized_pnl  # Use safe value
            
            # Persist to database (non-blocking)
            self._persist_execution_trade(trade)
            
            # Compute comparison snapshot (non-blocking)
            self._compute_comparison_snapshot(strategy, symbol, timestamp)
            
        except Exception as e:
            # Execution recording failures are non-fatal - log and continue
            logger.error(f"Error recording execution trade: {e}", exc_info=True)
    
    def _compute_comparison_snapshot(
        self,
        strategy: str,
        symbol: str,
        timestamp: datetime
    ) -> None:
        """
        Compute comparison snapshot when execution trade occurs.
        
        Finds matching shadow trade and computes differences.
        """
        try:
            # Find most recent shadow trade for this strategy/symbol
            shadow_trade = None
            with self._lock:
                for trade in reversed(self.shadow_trades):
                    if trade.strategy == strategy and trade.symbol == symbol:
                        shadow_trade = trade
                        break
            
            if not shadow_trade:
                # No shadow trade found - execution without shadow (allowed)
                # This can happen if shadow recording failed or was skipped
                return
            
            # Find matching execution trade (the one that just was recorded)
            execution_trade = None
            execution_pnl = 0.0
            execution_latency_ms = 0.0
            fill_price = 0.0
            
            with self._lock:
                for trade in reversed(self.execution_trades):
                    if trade.strategy == strategy and trade.symbol == symbol:
                        execution_trade = trade
                        execution_pnl = trade.realized_pnl
                        execution_latency_ms = trade.execution_latency_ms
                        fill_price = trade.fill_price
                        break
            
            if not execution_trade:
                # No execution trade found (shouldn't happen since we just recorded it)
                return
            
            # Calculate slippage (execution_price - shadow_price)
            slippage = fill_price - shadow_trade.shadow_price
            
            # Calculate PnL delta (execution_pnl - shadow_pnl)
            pnl_delta = execution_pnl - shadow_pnl
            
            # Create snapshot
            snapshot = ComparisonSnapshot(
                strategy=strategy,
                symbol=symbol,
                timestamp=timestamp,
                shadow_pnl=shadow_pnl,
                execution_pnl=execution_pnl,
                pnl_delta=pnl_delta,
                slippage=slippage,
                execution_latency_ms=execution_trade.execution_latency_ms if execution_trade else 0.0
            )
            
            with self._lock:
                self.comparison_snapshots.append(snapshot)
            
            # Persist snapshot
            self._persist_comparison_snapshot(snapshot)
            
            # Check for divergence (non-blocking)
            self._check_divergence(snapshot)
            
        except Exception as e:
            # Comparison computation failures are non-fatal
            logger.error(f"Error computing comparison snapshot: {e}", exc_info=True)
    
    def _check_divergence(self, snapshot: ComparisonSnapshot) -> None:
        """
        Check for divergence between shadow and execution.
        
        Divergence rules:
        - |pnl_delta| > threshold (default: 100.0)
        - |slippage| > max_slippage (default: 0.5% of price)
        """
        try:
            DIVERGENCE_PNL_THRESHOLD = 100.0  # $100 PnL delta threshold
            DIVERGENCE_SLIPPAGE_THRESHOLD = 0.005  # 0.5% slippage threshold
            
            has_divergence = False
            alert_type = None
            threshold = 0.0
            
            # Check PnL divergence
            if abs(snapshot.pnl_delta) > DIVERGENCE_PNL_THRESHOLD:
                has_divergence = True
                alert_type = "pnl_divergence"
                threshold = DIVERGENCE_PNL_THRESHOLD
            
            # Check slippage divergence (if execution price available)
            if snapshot.slippage != 0.0:
                # Find shadow trade to get shadow price for percentage calculation
                shadow_price = 0.0
                with self._lock:
                    for trade in reversed(self.shadow_trades):
                        if trade.strategy == snapshot.strategy and trade.symbol == snapshot.symbol:
                            shadow_price = trade.shadow_price
                            break
                
                if shadow_price > 0:
                    slippage_pct = abs(snapshot.slippage) / shadow_price
                    if slippage_pct > DIVERGENCE_SLIPPAGE_THRESHOLD:
                        has_divergence = True
                        if alert_type is None:
                            alert_type = "slippage_divergence"
                            threshold = DIVERGENCE_SLIPPAGE_THRESHOLD
            
            if has_divergence:
                alert = {
                    'strategy': snapshot.strategy,
                    'symbol': snapshot.symbol,
                    'timestamp': snapshot.timestamp.isoformat() + "Z",
                    'alert_type': alert_type,
                    'shadow_pnl': snapshot.shadow_pnl,
                    'execution_pnl': snapshot.execution_pnl,
                    'pnl_delta': snapshot.pnl_delta,
                    'threshold': threshold,
                    'metadata': {
                        'slippage': snapshot.slippage,
                        'execution_latency_ms': snapshot.execution_latency_ms
                    }
                }
                
                with self._lock:
                    self.divergence_alerts.append(alert)
                
                # Persist alert
                self._persist_divergence_alert(alert)
                
                # Emit alert event (non-blocking)
                logger.warning(
                    f"DIVERGENCE_ALERT | strategy={snapshot.strategy} | "
                    f"symbol={snapshot.symbol} | type={alert_type} | "
                    f"pnl_delta={snapshot.pnl_delta:.2f} | slippage={snapshot.slippage:.4f}"
                )
                
        except Exception as e:
            # Divergence check failures are non-fatal
            logger.error(f"Error checking divergence: {e}", exc_info=True)
    
    def get_comparison_summary(self) -> Dict:
        """
        Get real-time comparison summary for WebSocket streaming.
        
        Returns:
            Dict with per-strategy PnL deltas, aggregate equity, slippage, latency
        """
        try:
            with self._lock:
                # Per-strategy PnL deltas
                strategy_deltas = {}
                for strategy in set(list(self.strategy_shadow_pnl.keys()) + list(self.strategy_execution_pnl.keys())):
                    shadow_pnl = self.strategy_shadow_pnl.get(strategy, 0.0)
                    execution_pnl = self.strategy_execution_pnl.get(strategy, 0.0)
                    strategy_deltas[strategy] = {
                        'shadow_pnl': shadow_pnl,
                        'execution_pnl': execution_pnl,
                        'pnl_delta': execution_pnl - shadow_pnl
                    }
                
                # Aggregate equity
                total_shadow_pnl = sum(self.strategy_shadow_pnl.values())
                total_execution_pnl = sum(self.strategy_execution_pnl.values())
                
                # Slippage distribution (from recent snapshots)
                slippages = [s.slippage for s in self.comparison_snapshots if s.slippage != 0.0]
                avg_slippage = sum(slippages) / len(slippages) if slippages else 0.0
                max_slippage = max(slippages) if slippages else 0.0
                
                # Execution latency histogram (from recent snapshots)
                latencies = [s.execution_latency_ms for s in self.comparison_snapshots if s.execution_latency_ms > 0]
                avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
                max_latency = max(latencies) if latencies else 0.0
                
                # Recent divergence count
                recent_divergences = len([a for a in self.divergence_alerts])
                
                return {
                    'strategy_deltas': strategy_deltas,
                    'aggregate_shadow_pnl': total_shadow_pnl,
                    'aggregate_execution_pnl': total_execution_pnl,
                    'aggregate_pnl_delta': total_execution_pnl - total_shadow_pnl,
                    'slippage': {
                        'avg': avg_slippage,
                        'max': max_slippage,
                        'count': len(slippages)
                    },
                    'execution_latency': {
                        'avg_ms': avg_latency,
                        'max_ms': max_latency,
                        'count': len(latencies)
                    },
                    'divergence_alerts_count': recent_divergences,
                    'timestamp': datetime.utcnow().isoformat() + "Z"
                }
        except Exception as e:
            logger.error(f"Error getting comparison summary: {e}", exc_info=True)
            return {
                'strategy_deltas': {},
                'aggregate_shadow_pnl': 0.0,
                'aggregate_execution_pnl': 0.0,
                'aggregate_pnl_delta': 0.0,
                'slippage': {'avg': 0.0, 'max': 0.0, 'count': 0},
                'execution_latency': {'avg_ms': 0.0, 'max_ms': 0.0, 'count': 0},
                'divergence_alerts_count': 0,
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }
    
    # Persistence methods (non-blocking, fire-and-forget)
    
    def _persist_shadow_trade(self, trade: ShadowTrade) -> None:
        """Persist shadow trade to database (non-blocking)."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=1.0)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO shadow_trades 
                (strategy, symbol, timestamp, side, size, shadow_price, shadow_pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.strategy,
                trade.symbol,
                trade.timestamp.isoformat() + "Z",
                trade.side,
                trade.size,
                trade.shadow_price,
                trade.shadow_pnl
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Error persisting shadow trade (non-fatal): {e}")
    
    def _persist_execution_trade(self, trade: ExecutionTrade) -> None:
        """Persist execution trade to database (non-blocking)."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=1.0)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO execution_trades 
                (strategy, symbol, timestamp, side, size, fill_price, realized_pnl, mode, execution_latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.strategy,
                trade.symbol,
                trade.timestamp.isoformat() + "Z",
                trade.side,
                trade.size,
                trade.fill_price,
                trade.realized_pnl,
                trade.mode or "PAPER",  # Default to PAPER if None
                trade.execution_latency_ms
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Error persisting execution trade (non-fatal): {e}")
    
    def _persist_comparison_snapshot(self, snapshot: ComparisonSnapshot) -> None:
        """Persist comparison snapshot to database (non-blocking)."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=1.0)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO comparison_snapshots 
                (strategy, symbol, timestamp, shadow_pnl, execution_pnl, pnl_delta, slippage, execution_latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.strategy,
                snapshot.symbol,
                snapshot.timestamp.isoformat() + "Z",
                snapshot.shadow_pnl,
                snapshot.execution_pnl,
                snapshot.pnl_delta,
                snapshot.slippage,
                snapshot.execution_latency_ms
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Error persisting comparison snapshot (non-fatal): {e}")
    
    def _persist_divergence_alert(self, alert: Dict) -> None:
        """Persist divergence alert to database (non-blocking)."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=1.0)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO divergence_alerts 
                (strategy, symbol, timestamp, alert_type, shadow_pnl, execution_pnl, pnl_delta, threshold, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert['strategy'],
                alert['symbol'],
                alert['timestamp'],
                alert['alert_type'],
                alert['shadow_pnl'],
                alert['execution_pnl'],
                alert['pnl_delta'],
                alert['threshold'],
                json.dumps(alert.get('metadata', {}))
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Error persisting divergence alert (non-fatal): {e}")


# Global instance
_shadow_comparison_manager: Optional[ShadowComparisonManager] = None
_shadow_comparison_lock = threading.Lock()


def get_shadow_comparison_manager() -> ShadowComparisonManager:
    """Get global ShadowComparisonManager instance."""
    global _shadow_comparison_manager
    if _shadow_comparison_manager is None:
        with _shadow_comparison_lock:
            if _shadow_comparison_manager is None:
                _shadow_comparison_manager = ShadowComparisonManager()
    return _shadow_comparison_manager
