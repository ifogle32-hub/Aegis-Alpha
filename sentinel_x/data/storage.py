"""Data storage utilities with SQLite persistence."""
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from sentinel_x.monitoring.logger import logger


class Storage:
    """SQLite storage for backtests and strategy status."""
    
    def __init__(self, db_path: str = "sentinel_x.db"):
        """
        Initialize storage.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._init_lock = threading.Lock()
        self._initialized = False
        with self._init_lock:
            if not self._initialized:
                self._init_database()
                self._initialized = True
        logger.info(f"Storage initialized: {self.db_path}")
    
    def _init_database(self) -> None:
        """Initialize database tables."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # One-time PRAGMA migration guard
        try:
            # Check current journal_mode
            cursor.execute("PRAGMA journal_mode")
            current_journal = cursor.fetchone()[0].upper()
            
            # Check current synchronous
            cursor.execute("PRAGMA synchronous")
            current_sync = cursor.fetchone()[0]
            
            # Only set if not already configured
            if current_journal != "WAL":
                cursor.execute("PRAGMA journal_mode=WAL")
            
            if current_sync != 1:  # 1 = NORMAL
                cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception as e:
            logger.debug(f"PRAGMA migration check failed (non-fatal): {e}")
            # Continue - PRAGMA failures are non-fatal
        
        # Create backtests table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backtests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                symbol TEXT NOT NULL,
                sharpe REAL,
                drawdown REAL,
                expectancy REAL,
                score REAL,
                timestamp TIMESTAMP NOT NULL,
                UNIQUE(strategy, symbol, timestamp)
            )
        """)
        
        # Create strategies table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL,
                last_score REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                order_type TEXT NOT NULL,
                status TEXT NOT NULL,
                strategy TEXT,
                timestamp TIMESTAMP NOT NULL,
                filled_at TIMESTAMP,
                filled_qty REAL,
                filled_price REAL
            )
        """)
        
        # Create daily_pnl table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE UNIQUE NOT NULL,
                equity REAL NOT NULL,
                daily_pnl REAL NOT NULL,
                buying_power REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtests_timestamp ON backtests(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtests_strategy_symbol ON backtests(strategy, symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_timestamp ON orders(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_pnl_date ON daily_pnl(date)")
        
        conn.commit()
        conn.close()
    
    def _ensure_initialized(self) -> None:
        """Ensure database is initialized before writes (thread-safe)."""
        with self._init_lock:
            if not self._initialized:
                self._init_database()
                self._initialized = True
    
    def save_backtest(self, strategy: str, symbol: str, sharpe: float, 
                     drawdown: float, expectancy: float, score: float,
                     timestamp: Optional[datetime] = None) -> None:
        """
        Save backtest results.
        
        Args:
            strategy: Strategy name
            symbol: Trading symbol
            sharpe: Sharpe ratio
            drawdown: Maximum drawdown
            expectancy: Trade expectancy
            score: Composite score
            timestamp: Timestamp (default: now)
        """
        self._ensure_initialized()
        
        if timestamp is None:
            timestamp = datetime.now()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO backtests (strategy, symbol, sharpe, drawdown, expectancy, score, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (strategy, symbol, sharpe, drawdown, expectancy, score, timestamp))
            
            conn.commit()
        except sqlite3.IntegrityError:
            # Update if exists
            cursor.execute("""
                UPDATE backtests
                SET sharpe=?, drawdown=?, expectancy=?, score=?
                WHERE strategy=? AND symbol=? AND timestamp=?
            """, (sharpe, drawdown, expectancy, score, strategy, symbol, timestamp))
            conn.commit()
        finally:
            conn.close()
    
    def get_latest_backtests(self, strategy: Optional[str] = None, 
                            symbol: Optional[str] = None) -> List[Dict]:
        """
        Get latest backtest results.
        
        Args:
            strategy: Filter by strategy (optional)
            symbol: Filter by symbol (optional)
            
        Returns:
            List of backtest dictionaries
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = """
            SELECT * FROM backtests
            WHERE 1=1
        """
        params = []
        
        if strategy:
            query += " AND strategy=?"
            params.append(strategy)
        
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        
        query += " ORDER BY timestamp DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def update_strategy_status(self, name: str, status: str, last_score: Optional[float] = None) -> None:
        """
        Update strategy status.
        
        Args:
            name: Strategy name
            status: Status (ACTIVE/DISABLED)
            last_score: Last composite score (optional)
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO strategies (name, status, last_score, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET
                status=excluded.status,
                last_score=excluded.last_score,
                updated_at=CURRENT_TIMESTAMP
        """, (name, status, last_score))
        
        conn.commit()
        conn.close()
    
    def get_strategy_status(self, name: str) -> Optional[Tuple[str, Optional[float]]]:
        """
        Get strategy status.
        
        Args:
            name: Strategy name
            
        Returns:
            Tuple of (status, last_score) or None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT status, last_score FROM strategies WHERE name=?
        """, (name,))
        
        result = cursor.fetchone()
        conn.close()
        
        return result if result else None
    
    def get_all_strategy_statuses(self) -> Dict[str, str]:
        """
        Get all strategy statuses.
        
        Returns:
            Dictionary mapping strategy name to status
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT name, status FROM strategies
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        return {name: status for name, status in rows}
    
    def get_strategy_history(self, strategy: str, limit: int = 100) -> List[Dict]:
        """
        Get backtest history for a strategy.
        
        Args:
            strategy: Strategy name
            limit: Maximum number of results
            
        Returns:
            List of backtest dictionaries
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM backtests
            WHERE strategy=?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (strategy, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def latest_metrics(self, limit: int = 100) -> List[Dict]:
        """
        Get latest metrics snapshot from storage (read-only).
        
        Args:
            limit: Maximum number of results per strategy-symbol pair
            
        Returns:
            List of metric dictionaries with sharpe, drawdown, expectancy, score, strategy, symbol, timestamp
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get latest metrics per strategy-symbol pair
        cursor.execute("""
            SELECT strategy, symbol, sharpe, drawdown, expectancy, score, timestamp
            FROM backtests
            WHERE id IN (
                SELECT MAX(id)
                FROM backtests
                GROUP BY strategy, symbol
            )
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def save_order(self, order_id: str, symbol: str, side: str, qty: float,
                   order_type: str, status: str, timestamp: datetime,
                   strategy: Optional[str] = None, filled_at: Optional[datetime] = None,
                   filled_qty: Optional[float] = None, filled_price: Optional[float] = None) -> None:
        """
        Save order to storage.
        
        Args:
            order_id: Order ID
            symbol: Trading symbol
            side: Order side (buy/sell)
            qty: Order quantity
            order_type: Order type
            status: Order status
            timestamp: Order timestamp
            strategy: Strategy name (optional)
            filled_at: Fill timestamp (optional)
            filled_qty: Filled quantity (optional)
            filled_price: Fill price (optional)
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO orders (order_id, symbol, side, qty, order_type, status, strategy, timestamp, filled_at, filled_qty, filled_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status=excluded.status,
                    filled_at=excluded.filled_at,
                    filled_qty=excluded.filled_qty,
                    filled_price=excluded.filled_price
            """, (order_id, symbol, side, qty, order_type, status, strategy, timestamp, filled_at, filled_qty, filled_price))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error saving order: {e}")
        finally:
            conn.close()
    
    def update_order_fill(self, order_id: str, filled_at: datetime,
                         filled_qty: float, filled_price: float) -> None:
        """
        Update order with fill information.
        
        Args:
            order_id: Order ID
            filled_at: Fill timestamp
            filled_qty: Filled quantity
            filled_price: Fill price
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE orders
                SET status='filled', filled_at=?, filled_qty=?, filled_price=?
                WHERE order_id=?
            """, (filled_at, filled_qty, filled_price, order_id))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error updating order fill: {e}")
        finally:
            conn.close()
    
    def save_daily_pnl(self, date: datetime.date, equity: float, daily_pnl: float,
                       buying_power: Optional[float] = None) -> None:
        """
        Save daily P&L snapshot.
        
        Args:
            date: Date
            equity: Account equity
            daily_pnl: Daily P&L
            buying_power: Buying power (optional)
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO daily_pnl (date, equity, daily_pnl, buying_power)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    equity=excluded.equity,
                    daily_pnl=excluded.daily_pnl,
                    buying_power=excluded.buying_power,
                    timestamp=CURRENT_TIMESTAMP
            """, (date, equity, daily_pnl, buying_power))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error saving daily P&L: {e}")
        finally:
            conn.close()
    
    def get_orders(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """
        Get orders from storage.
        
        Args:
            symbol: Filter by symbol (optional)
            limit: Maximum number of results
            
        Returns:
            List of order dictionaries
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if symbol:
            cursor.execute("""
                SELECT * FROM orders
                WHERE symbol=?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (symbol, limit))
        else:
            cursor.execute("""
                SELECT * FROM orders
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# Global storage instance
_storage = None


def get_storage(db_path: str = "sentinel_x.db") -> Storage:
    """Get global storage instance."""
    global _storage
    if _storage is None:
        _storage = Storage(db_path)
    return _storage

