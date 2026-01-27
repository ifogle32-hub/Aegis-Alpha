"""
PHASE 8 — PERSISTENCE & AUDIT TRAIL

ShadowPersistence for storing all shadow data with restart-safe design.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import sqlite3
import json
import threading
import os
from pathlib import Path

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.scorer import PerformanceMetrics
from sentinel_x.shadow.regime import RegimeSnapshot
from sentinel_x.shadow.definitions import PromotionState


class ShadowPersistence:
    """
    Shadow data persistence layer.
    
    Features:
    - SQLite database (can be upgraded to Postgres)
    - Append-only logs
    - Strategy snapshots
    - Metric timelines
    - Promotion eligibility markers
    - Restart-safe
    - Queryable by time, strategy, regime
    - Exportable for compliance/review
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize persistence layer.
        
        Args:
            db_path: Optional database path (default: sentinel_x_shadow.db)
        """
        if db_path is None:
            db_path = os.path.join(os.getcwd(), "sentinel_x_shadow.db")
        
        self.db_path = db_path
        self._lock = threading.RLock()
        
        # Initialize database
        self._init_database()
        
        logger.info(f"ShadowPersistence initialized: {db_path}")
    
    def _init_database(self) -> None:
        """Initialize database schema."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Strategy snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    version_hash TEXT NOT NULL,
                    snapshot_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Metric timelines table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metric_timelines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    window_start TIMESTAMP NOT NULL,
                    window_end TIMESTAMP NOT NULL,
                    metrics_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Regime snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS regime_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    regime TEXT NOT NULL,
                    snapshot_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Promotion eligibility table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS promotion_eligibility (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    evaluation_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Audit log table (append-only)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    strategy_id TEXT,
                    event_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Trade history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    fill_price REAL NOT NULL,
                    pnl REAL,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_snapshots_strategy_id 
                ON strategy_snapshots(strategy_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_metric_timelines_strategy_id 
                ON metric_timelines(strategy_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_metric_timelines_window 
                ON metric_timelines(window_start, window_end)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_regime_snapshots_timestamp 
                ON regime_snapshots(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_promotion_eligibility_strategy_id 
                ON promotion_eligibility(strategy_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_history_strategy_id 
                ON trade_history(strategy_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_history_timestamp 
                ON trade_history(timestamp)
            """)
            
            conn.commit()
            conn.close()
    
    def save_strategy_snapshot(
        self,
        strategy_id: str,
        version_hash: str,
        snapshot_data: Dict[str, Any],
    ) -> None:
        """
        Save strategy snapshot.
        
        Args:
            strategy_id: Strategy identifier
            version_hash: Strategy version hash
            snapshot_data: Snapshot data dictionary
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO strategy_snapshots (strategy_id, version_hash, snapshot_data)
                VALUES (?, ?, ?)
            """, (strategy_id, version_hash, json.dumps(snapshot_data)))
            
            conn.commit()
            conn.close()
    
    def save_metrics(
        self,
        metrics: PerformanceMetrics,
    ) -> None:
        """
        Save performance metrics.
        
        Args:
            metrics: PerformanceMetrics instance
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO metric_timelines 
                (strategy_id, window_start, window_end, metrics_data)
                VALUES (?, ?, ?, ?)
            """, (
                metrics.strategy_id,
                metrics.window_start.isoformat(),
                metrics.window_end.isoformat(),
                json.dumps(metrics.to_dict()),
            ))
            
            conn.commit()
            conn.close()
    
    def save_regime_snapshot(
        self,
        snapshot: RegimeSnapshot,
    ) -> None:
        """
        Save regime snapshot.
        
        Args:
            snapshot: RegimeSnapshot instance
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO regime_snapshots (timestamp, regime, snapshot_data)
                VALUES (?, ?, ?)
            """, (
                snapshot.timestamp.isoformat(),
                snapshot.regime,
                json.dumps(snapshot.to_dict()),
            ))
            
            conn.commit()
            conn.close()
    
    def save_promotion_evaluation(
        self,
        strategy_id: str,
        state: PromotionState,
        evaluation_data: Dict[str, Any],
    ) -> None:
        """
        Save promotion evaluation.
        
        Args:
            strategy_id: Strategy identifier
            state: Promotion state
            evaluation_data: Evaluation data dictionary
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO promotion_eligibility (strategy_id, state, evaluation_data)
                VALUES (?, ?, ?)
            """, (strategy_id, state.value, json.dumps(evaluation_data)))
            
            conn.commit()
            conn.close()
    
    def log_audit_event(
        self,
        event_type: str,
        strategy_id: Optional[str],
        event_data: Dict[str, Any],
    ) -> None:
        """
        Log audit event (append-only).
        
        Args:
            event_type: Event type
            strategy_id: Optional strategy identifier
            event_data: Event data dictionary
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO audit_log (event_type, strategy_id, event_data)
                VALUES (?, ?, ?)
            """, (event_type, strategy_id, json.dumps(event_data)))
            
            conn.commit()
            conn.close()
    
    def save_trade(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        timestamp: datetime,
        pnl: Optional[float] = None,
    ) -> None:
        """
        Save trade record.
        
        Args:
            strategy_id: Strategy identifier
            symbol: Trading symbol
            side: Trade side
            quantity: Trade quantity
            fill_price: Fill price
            timestamp: Trade timestamp
            pnl: Optional PnL
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO trade_history 
                (strategy_id, symbol, side, quantity, fill_price, pnl, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                strategy_id,
                symbol,
                side,
                quantity,
                fill_price,
                pnl,
                timestamp.isoformat(),
            ))
            
            conn.commit()
            conn.close()
    
    def query_metrics(
        self,
        strategy_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query metrics by strategy and time window.
        
        Args:
            strategy_id: Optional strategy filter
            start_time: Optional start time
            end_time: Optional end time
            
        Returns:
            List of metric dictionaries
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            query = "SELECT * FROM metric_timelines WHERE 1=1"
            params = []
            
            if strategy_id:
                query += " AND strategy_id = ?"
                params.append(strategy_id)
            
            if start_time:
                query += " AND window_start >= ?"
                params.append(start_time.isoformat())
            
            if end_time:
                query += " AND window_end <= ?"
                params.append(end_time.isoformat())
            
            query += " ORDER BY window_start DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Get column names
            columns = [desc[0] for desc in cursor.description]
            
            results = []
            for row in rows:
                result = dict(zip(columns, row))
                result['metrics_data'] = json.loads(result['metrics_data'])
                results.append(result)
            
            conn.close()
            return results
    
    def export_data(
        self,
        output_path: str,
        strategy_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> None:
        """
        Export shadow data for compliance/review.
        
        Args:
            output_path: Output file path
            strategy_id: Optional strategy filter
            start_time: Optional start time
            end_time: Optional end time
        """
        export_data = {
            "export_timestamp": datetime.utcnow().isoformat() + "Z",
            "filters": {
                "strategy_id": strategy_id,
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None,
            },
            "metrics": self.query_metrics(strategy_id, start_time, end_time),
        }
        
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"Exported shadow data to {output_path}")


# Global persistence instance
_persistence: Optional[ShadowPersistence] = None
_persistence_lock = threading.Lock()


def get_shadow_persistence(db_path: Optional[str] = None) -> ShadowPersistence:
    """
    Get global shadow persistence instance (singleton).
    
    Args:
        db_path: Optional database path
        
    Returns:
        ShadowPersistence instance
    """
    global _persistence
    
    if _persistence is None:
        with _persistence_lock:
            if _persistence is None:
                _persistence = ShadowPersistence(db_path)
    
    return _persistence
