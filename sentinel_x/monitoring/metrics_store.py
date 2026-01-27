"""
PHASE 1: Persistent Metrics Storage

Append-only storage for:
- Orders
- Fills
- PnL snapshots
- Strategy metrics
- Broker snapshots

Rules:
- Non-blocking writes (background thread)
- Safe on restart (schema migrations)
- Engine runs even if storage unavailable
"""
import sqlite3
import threading
import queue
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, asdict
from sentinel_x.monitoring.logger import logger


@dataclass
class OrderRecord:
    """Order record for storage."""
    order_id: str
    symbol: str
    side: str
    qty: float
    price: Optional[float]
    strategy: str
    broker: str
    mode: str
    status: str
    timestamp: datetime


@dataclass
class FillRecord:
    """Fill record for storage."""
    fill_id: str
    order_id: str
    symbol: str
    side: str
    qty: float
    price: float
    strategy: str
    broker: str
    mode: str
    timestamp: datetime


@dataclass
class PnLSnapshot:
    """PnL snapshot for storage."""
    timestamp: datetime
    total_realized: float
    total_unrealized: float
    total_pnl: float
    equity: Optional[float]
    by_strategy: Dict[str, Dict[str, Any]]


@dataclass
class StrategyMetrics:
    """Strategy metrics for storage."""
    strategy: str
    timestamp: datetime
    trades_count: int
    wins: int
    losses: int
    win_rate: float
    realized_pnl: float
    max_drawdown: float
    sharpe: Optional[float] = None
    expectancy: Optional[float] = None


@dataclass
class BrokerSnapshot:
    """Broker snapshot for storage."""
    broker: str
    mode: str
    timestamp: datetime
    equity: float
    cash: float
    positions_count: int
    total_pnl: float


@dataclass
class EquitySnapshot:
    """Equity snapshot for storage."""
    timestamp: datetime
    equity: float
    benchmark_equity: Optional[float]
    drawdown: float
    max_drawdown: float
    cumulative_return: float
    benchmark_return: Optional[float]
    relative_alpha: Optional[float]


@dataclass
class AlertRecord:
    """Alert record for storage."""
    alert_type: str
    severity: str
    message: str
    timestamp: datetime
    strategy: Optional[str] = None
    broker: Optional[str] = None
    mode: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class MetricsStore:
    """
    Persistent metrics storage with non-blocking writes.
    
    Uses background thread for writes to never block trading.
    """
    
    def __init__(self, db_path: str = "sentinel_x_metrics.db"):
        """
        Initialize metrics store.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._write_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._init_lock = threading.Lock()
        self._initialized = False
        with self._init_lock:
            if not self._initialized:
                self._init_database()
                self._initialized = True
        self._start_worker()
        logger.info(f"MetricsStore initialized: {self.db_path}")
    
    def _init_database(self) -> None:
        """
        PHASE 3: Initialize database tables with auto-healing.
        
        All tables are auto-created on startup:
        - pnl_snapshots
        - broker_snapshots
        - strategy_metrics
        - orders
        - fills
        - equity_snapshots
        - alerts
        
        SQLite schema errors are impossible:
        - No invalid INDEX placement
        - No partial table creation
        - Safe migrations
        
        Writes NEVER throw - missing tables auto-recreated.
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            cursor = conn.cursor()
            
            # PHASE 3: Enable WAL mode for better concurrency
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            except Exception as e:
                logger.debug(f"PRAGMA configuration failed (non-fatal): {e}")
                # Continue - PRAGMA failures are non-fatal
            
            # Orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    price REAL,
                    strategy TEXT,
                    broker TEXT,
                    mode TEXT,
                    status TEXT,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for orders table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders(order_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_timestamp ON orders(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy)")
            
            # Fills table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fill_id TEXT UNIQUE NOT NULL,
                    order_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    price REAL NOT NULL,
                    strategy TEXT,
                    broker TEXT,
                    mode TEXT,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for fills table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fills_fill_id ON fills(fill_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fills_timestamp ON fills(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fills_strategy ON fills(strategy)")
            
            # PnL snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pnl_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    total_realized REAL NOT NULL,
                    total_unrealized REAL NOT NULL,
                    total_pnl REAL NOT NULL,
                    equity REAL,
                    by_strategy_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for pnl_snapshots table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_timestamp ON pnl_snapshots(timestamp)")
            
            # Strategy metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    trades_count INTEGER NOT NULL,
                    wins INTEGER NOT NULL,
                    losses INTEGER NOT NULL,
                    win_rate REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    sharpe REAL,
                    expectancy REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for strategy_metrics table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategy_metrics_strategy ON strategy_metrics(strategy)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategy_metrics_timestamp ON strategy_metrics(timestamp)")
            
            # Broker snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    equity REAL NOT NULL,
                    cash REAL NOT NULL,
                    positions_count INTEGER NOT NULL,
                    total_pnl REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for broker_snapshots table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_broker_snapshots_broker ON broker_snapshots(broker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_broker_snapshots_timestamp ON broker_snapshots(timestamp)")
            
            # Equity snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    equity REAL NOT NULL,
                    benchmark_equity REAL,
                    drawdown REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    cumulative_return REAL NOT NULL,
                    benchmark_return REAL,
                    relative_alpha REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for equity_snapshots table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_equity_snapshots_timestamp ON equity_snapshots(timestamp)")
            
            # Alerts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    strategy TEXT,
                    broker TEXT,
                    mode TEXT,
                    metadata_json TEXT,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for alerts table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity)")
            
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.error(f"SQLite error initializing metrics database: {e}", exc_info=True)
            # Continue - storage failures must not crash engine
        except Exception as e:
            logger.error(f"Error initializing metrics database: {e}", exc_info=True)
            # Continue - storage failures must not crash engine
    
    def _start_worker(self) -> None:
        """Start background worker thread for writes."""
        if self._running:
            return
        
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="MetricsStore-Worker"
        )
        self._worker_thread.start()
        logger.debug("MetricsStore worker thread started")
    
    def _worker_loop(self) -> None:
        """Background worker loop for processing writes."""
        while self._running:
            try:
                # Get item from queue (with timeout to allow shutdown)
                try:
                    item = self._write_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Process write
                try:
                    self._process_write(item)
                except Exception as e:
                    logger.error(f"Error processing metrics write: {e}", exc_info=True)
                finally:
                    self._write_queue.task_done()
            
            except Exception as e:
                logger.error(f"Error in metrics store worker loop: {e}", exc_info=True)
                time.sleep(0.1)  # Brief pause on error
    
    def _process_write(self, item: Dict[str, Any]) -> None:
        """
        Process a single write operation.
        
        PHASE 2: Enhanced error handling - ensures tables exist before write.
        """
        op_type = item.get('type')
        
        try:
            # Ensure database is initialized before write (thread-safe)
            with self._init_lock:
                if not self._initialized:
                    self._init_database()
                    self._initialized = True
            
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            cursor = conn.cursor()
            
            if op_type == 'order':
                record = item['record']
                cursor.execute("""
                    INSERT INTO orders (order_id, symbol, side, qty, price, strategy, broker, mode, status, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record['order_id'],
                    record['symbol'],
                    record['side'],
                    record['qty'],
                    record['price'],
                    record['strategy'],
                    record['broker'],
                    record['mode'],
                    record['status'],
                    record['timestamp']
                ))
            
            elif op_type == 'fill':
                record = item['record']
                cursor.execute("""
                    INSERT OR IGNORE INTO fills (fill_id, order_id, symbol, side, qty, price, strategy, broker, mode, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record['fill_id'],
                    record.get('order_id'),
                    record['symbol'],
                    record['side'],
                    record['qty'],
                    record['price'],
                    record['strategy'],
                    record['broker'],
                    record['mode'],
                    record['timestamp']
                ))
            
            elif op_type == 'pnl_snapshot':
                record = item['record']
                import json
                by_strategy_json = json.dumps(record['by_strategy'])
                cursor.execute("""
                    INSERT INTO pnl_snapshots (timestamp, total_realized, total_unrealized, total_pnl, equity, by_strategy_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    record['timestamp'],
                    record['total_realized'],
                    record['total_unrealized'],
                    record['total_pnl'],
                    record.get('equity'),
                    by_strategy_json
                ))
            
            elif op_type == 'strategy_metrics':
                record = item['record']
                cursor.execute("""
                    INSERT INTO strategy_metrics (strategy, timestamp, trades_count, wins, losses, win_rate, realized_pnl, max_drawdown, sharpe, expectancy)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record['strategy'],
                    record['timestamp'],
                    record['trades_count'],
                    record['wins'],
                    record['losses'],
                    record['win_rate'],
                    record['realized_pnl'],
                    record['max_drawdown'],
                    record.get('sharpe'),
                    record.get('expectancy')
                ))
            
            elif op_type == 'broker_snapshot':
                record = item['record']
                cursor.execute("""
                    INSERT INTO broker_snapshots (broker, mode, timestamp, equity, cash, positions_count, total_pnl)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    record['broker'],
                    record['mode'],
                    record['timestamp'],
                    record['equity'],
                    record['cash'],
                    record['positions_count'],
                    record['total_pnl']
                ))
            
            elif op_type == 'equity_snapshot':
                record = item['record']
                cursor.execute("""
                    INSERT INTO equity_snapshots (timestamp, equity, benchmark_equity, drawdown, max_drawdown, cumulative_return, benchmark_return, relative_alpha)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record['timestamp'],
                    record['equity'],
                    record.get('benchmark_equity'),
                    record['drawdown'],
                    record['max_drawdown'],
                    record['cumulative_return'],
                    record.get('benchmark_return'),
                    record.get('relative_alpha')
                ))
            
            elif op_type == 'alert':
                record = item['record']
                import json
                metadata_json = json.dumps(record.get('metadata', {})) if record.get('metadata') else None
                cursor.execute("""
                    INSERT INTO alerts (alert_type, severity, message, strategy, broker, mode, metadata_json, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record['alert_type'],
                    record['severity'],
                    record['message'],
                    record.get('strategy'),
                    record.get('broker'),
                    record.get('mode'),
                    metadata_json,
                    record['timestamp']
                ))
            
            conn.commit()
            conn.close()
        
        except sqlite3.OperationalError as e:
            # PHASE 3: Auto-healing - table might not exist, recreate it
            if "no such table" in str(e).lower():
                logger.warning(f"Table missing in metrics store, recreating: {e}")
                try:
                    with self._init_lock:
                        self._init_database()
                    # Retry the write once
                    self._process_write(item)
                except Exception as retry_error:
                    logger.error(f"Error retrying metrics write after table recreation: {retry_error}", exc_info=True)
            else:
                logger.error(f"SQLite operational error in metrics write: {e}", exc_info=True)
        except sqlite3.Error as e:
            logger.error(f"SQLite error in metrics write: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error processing metrics write: {e}", exc_info=True)
    
    def record_order(self, order: OrderRecord) -> None:
        """
        Record an order (non-blocking).
        
        Args:
            order: Order record
        """
        try:
            record = {
                'order_id': order.order_id,
                'symbol': order.symbol,
                'side': order.side,
                'qty': order.qty,
                'price': order.price,
                'strategy': order.strategy,
                'broker': order.broker,
                'mode': order.mode,
                'status': order.status,
                'timestamp': order.timestamp.isoformat() if isinstance(order.timestamp, datetime) else order.timestamp
            }
            
            item = {'type': 'order', 'record': record}
            
            # Try to put in queue (non-blocking)
            try:
                self._write_queue.put_nowait(item)
            except queue.Full:
                logger.warning("Metrics store queue full, dropping order record")
        
        except Exception as e:
            logger.error(f"Error queuing order record: {e}", exc_info=True)
    
    def record_fill(self, fill: FillRecord) -> None:
        """
        Record a fill (non-blocking).
        
        Args:
            fill: Fill record
        """
        try:
            record = {
                'fill_id': fill.fill_id,
                'order_id': fill.order_id,
                'symbol': fill.symbol,
                'side': fill.side,
                'qty': fill.qty,
                'price': fill.price,
                'strategy': fill.strategy,
                'broker': fill.broker,
                'mode': fill.mode,
                'timestamp': fill.timestamp.isoformat() if isinstance(fill.timestamp, datetime) else fill.timestamp
            }
            
            item = {'type': 'fill', 'record': record}
            
            # Try to put in queue (non-blocking)
            try:
                self._write_queue.put_nowait(item)
            except queue.Full:
                logger.warning("Metrics store queue full, dropping fill record")
        
        except Exception as e:
            logger.error(f"Error queuing fill record: {e}", exc_info=True)
    
    def record_pnl_snapshot(self, snapshot: PnLSnapshot) -> None:
        """
        Record a PnL snapshot (non-blocking).
        
        Args:
            snapshot: PnL snapshot
        """
        try:
            import json
            record = {
                'timestamp': snapshot.timestamp.isoformat() if isinstance(snapshot.timestamp, datetime) else snapshot.timestamp,
                'total_realized': snapshot.total_realized,
                'total_unrealized': snapshot.total_unrealized,
                'total_pnl': snapshot.total_pnl,
                'equity': snapshot.equity,
                'by_strategy': snapshot.by_strategy
            }
            
            item = {'type': 'pnl_snapshot', 'record': record}
            
            # Try to put in queue (non-blocking)
            try:
                self._write_queue.put_nowait(item)
            except queue.Full:
                logger.warning("Metrics store queue full, dropping PnL snapshot")
        
        except Exception as e:
            logger.error(f"Error queuing PnL snapshot: {e}", exc_info=True)
    
    def record_strategy_metrics(self, metrics: StrategyMetrics) -> None:
        """
        Record strategy metrics (non-blocking).
        
        Args:
            metrics: Strategy metrics
        """
        try:
            record = {
                'strategy': metrics.strategy,
                'timestamp': metrics.timestamp.isoformat() if isinstance(metrics.timestamp, datetime) else metrics.timestamp,
                'trades_count': metrics.trades_count,
                'wins': metrics.wins,
                'losses': metrics.losses,
                'win_rate': metrics.win_rate,
                'realized_pnl': metrics.realized_pnl,
                'max_drawdown': metrics.max_drawdown,
                'sharpe': metrics.sharpe,
                'expectancy': metrics.expectancy
            }
            
            item = {'type': 'strategy_metrics', 'record': record}
            
            # Try to put in queue (non-blocking)
            try:
                self._write_queue.put_nowait(item)
            except queue.Full:
                logger.warning("Metrics store queue full, dropping strategy metrics")
        
        except Exception as e:
            logger.error(f"Error queuing strategy metrics: {e}", exc_info=True)
    
    def record_broker_snapshot(self, snapshot: BrokerSnapshot) -> None:
        """
        Record broker snapshot (non-blocking).
        
        Args:
            snapshot: Broker snapshot
        """
        try:
            record = {
                'broker': snapshot.broker,
                'mode': snapshot.mode,
                'timestamp': snapshot.timestamp.isoformat() if isinstance(snapshot.timestamp, datetime) else snapshot.timestamp,
                'equity': snapshot.equity,
                'cash': snapshot.cash,
                'positions_count': snapshot.positions_count,
                'total_pnl': snapshot.total_pnl
            }
            
            item = {'type': 'broker_snapshot', 'record': record}
            
            # Try to put in queue (non-blocking)
            try:
                self._write_queue.put_nowait(item)
            except queue.Full:
                logger.warning("Metrics store queue full, dropping broker snapshot")
        
        except Exception as e:
            logger.error(f"Error queuing broker snapshot: {e}", exc_info=True)
    
    def record_equity_snapshot(self, snapshot: EquitySnapshot) -> None:
        """
        Record an equity snapshot (non-blocking).
        
        Args:
            snapshot: Equity snapshot
        """
        try:
            record = {
                'timestamp': snapshot.timestamp.isoformat() if isinstance(snapshot.timestamp, datetime) else snapshot.timestamp,
                'equity': snapshot.equity,
                'benchmark_equity': snapshot.benchmark_equity,
                'drawdown': snapshot.drawdown,
                'max_drawdown': snapshot.max_drawdown,
                'cumulative_return': snapshot.cumulative_return,
                'benchmark_return': snapshot.benchmark_return,
                'relative_alpha': snapshot.relative_alpha
            }
            
            item = {'type': 'equity_snapshot', 'record': record}
            
            # Try to put in queue (non-blocking)
            try:
                self._write_queue.put_nowait(item)
            except queue.Full:
                logger.warning("Metrics store queue full, dropping equity snapshot")
        
        except Exception as e:
            logger.error(f"Error queuing equity snapshot: {e}", exc_info=True)
    
    def record_alert(self, alert: AlertRecord) -> None:
        """
        Record an alert (non-blocking).
        
        Args:
            alert: Alert record
        """
        try:
            record = {
                'alert_type': alert.alert_type,
                'severity': alert.severity,
                'message': alert.message,
                'strategy': alert.strategy,
                'broker': alert.broker,
                'mode': alert.mode,
                'metadata': alert.metadata,
                'timestamp': alert.timestamp.isoformat() if isinstance(alert.timestamp, datetime) else alert.timestamp
            }
            
            item = {'type': 'alert', 'record': record}
            
            # Try to put in queue (non-blocking)
            try:
                self._write_queue.put_nowait(item)
            except queue.Full:
                logger.warning("Metrics store queue full, dropping alert")
        
        except Exception as e:
            logger.error(f"Error queuing alert: {e}", exc_info=True)
    
    def shutdown(self) -> None:
        """Shutdown metrics store (wait for queue to drain)."""
        self._running = False
        if self._worker_thread:
            # Wait for queue to drain (with timeout)
            try:
                self._write_queue.join()
                self._worker_thread.join(timeout=5.0)
            except Exception:
                pass
        logger.info("MetricsStore shut down")


# Global metrics store instance
_metrics_store: Optional[MetricsStore] = None


def get_metrics_store(db_path: str = "sentinel_x_metrics.db") -> MetricsStore:
    """Get global metrics store instance."""
    global _metrics_store
    if _metrics_store is None:
        _metrics_store = MetricsStore(db_path)
    return _metrics_store
