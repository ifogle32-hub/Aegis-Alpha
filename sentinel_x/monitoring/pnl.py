"""Real-time PnL tracking engine."""
from typing import Dict, Optional, List
from datetime import datetime
from collections import defaultdict
from sentinel_x.monitoring.logger import logger
from sentinel_x.monitoring.event_bus import get_event_bus
import asyncio
from sentinel_x.utils import safe_emit


class PnLEngine:
    """
    Non-blocking PnL calculator.
    
    Tracks:
    - Realized PnL from fills
    - Unrealized PnL from positions + market data
    - Per-strategy metrics
    """
    
    def __init__(self):
        """Initialize PnL engine."""
        # Realized PnL tracking
        self.total_realized: float = 0.0
        self.strategy_realized: Dict[str, float] = defaultdict(float)
        
        # Trade tracking per strategy
        self.strategy_trades: Dict[str, List[Dict]] = defaultdict(list)
        self.strategy_wins: Dict[str, int] = defaultdict(int)
        self.strategy_losses: Dict[str, int] = defaultdict(int)
        
        # Current positions (for unrealized PnL)
        self.positions: Dict[str, Dict] = {}
        
        self.event_bus = get_event_bus()
        logger.info("PnL engine initialized")
    
    def record_fill(self, fill: Dict, position_update: Optional[Dict] = None) -> None:
        """
        Record a fill and update PnL.
        
        Args:
            fill: Fill dict with symbol, side, qty, price, strategy, timestamp
            position_update: Optional position update after fill
        """
        try:
            symbol = fill.get('symbol')
            side = fill.get('side', '').upper()
            qty = float(fill.get('qty', 0))
            price = float(fill.get('price', 0))
            strategy = fill.get('strategy', 'unknown')
            timestamp = fill.get('timestamp')
            
            if not symbol or qty <= 0 or price <= 0:
                return
            
            # Record trade
            trade = {
                'symbol': symbol,
                'side': side,
                'qty': qty,
                'price': price,
                'timestamp': timestamp or datetime.utcnow().isoformat(),
            }
            self.strategy_trades[strategy].append(trade)
            
            # Calculate realized PnL if closing position
            if position_update:
                # Check if position was closed (qty becomes 0)
                old_qty = self.positions.get(symbol, {}).get('qty', 0)
                new_qty = position_update.get('qty', 0)
                
                if old_qty != 0 and new_qty == 0:
                    # Position closed - calculate realized PnL
                    entry_price = self.positions.get(symbol, {}).get('avg_price', price)
                    if side == "SELL":
                        realized_pnl = old_qty * (price - entry_price)
                    else:
                        realized_pnl = abs(old_qty) * (entry_price - price)
                    
                    self.total_realized += realized_pnl
                    self.strategy_realized[strategy] += realized_pnl
                    
                    # Track win/loss
                    if realized_pnl > 0:
                        self.strategy_wins[strategy] += 1
                    elif realized_pnl < 0:
                        self.strategy_losses[strategy] += 1
            
            # Update position tracking
            if position_update:
                if position_update.get('qty', 0) == 0:
                    # Position closed
                    if symbol in self.positions:
                        del self.positions[symbol]
                else:
                    # Position open/updated
                    self.positions[symbol] = {
                        'qty': position_update.get('qty', 0),
                        'avg_price': position_update.get('avg_price', price),
                        'current_price': position_update.get('current_price', price),
                    }
            
            # Emit PnL update event (non-blocking)
            self._emit_pnl_update()
            
        except Exception as e:
            logger.error(f"Error recording fill in PnL engine: {e}", exc_info=True)
    
    def update_unrealized(self, positions: List[Dict]) -> None:
        """
        Update unrealized PnL from current positions.
        
        Args:
            positions: List of position dicts with symbol, qty, avg_price, current_price, unrealized_pnl
        """
        try:
            # Update position tracking
            for pos in positions:
                symbol = pos.get('symbol')
                if symbol:
                    self.positions[symbol] = {
                        'qty': pos.get('qty', 0),
                        'avg_price': pos.get('avg_price', 0),
                        'current_price': pos.get('current_price', 0),
                    }
            
            # Emit PnL update event (non-blocking)
            self._emit_pnl_update()
            
        except Exception as e:
            logger.error(f"Error updating unrealized PnL: {e}", exc_info=True)
    
    def get_total_unrealized(self) -> float:
        """Calculate total unrealized PnL from positions."""
        total = 0.0
        for pos in self.positions.values():
            qty = pos.get('qty', 0)
            avg_price = pos.get('avg_price', 0)
            current_price = pos.get('current_price', 0)
            if qty != 0 and avg_price > 0 and current_price > 0:
                total += qty * (current_price - avg_price)
        return total
    
    def get_strategy_metrics(self, strategy: str) -> Dict:
        """Get metrics for a specific strategy."""
        trades = self.strategy_trades.get(strategy, [])
        wins = self.strategy_wins.get(strategy, 0)
        losses = self.strategy_losses.get(strategy, 0)
        total_trades = len(trades)
        
        win_rate = wins / total_trades if total_trades > 0 else 0.0
        realized = self.strategy_realized.get(strategy, 0.0)
        
        # Calculate average return per trade
        avg_return = realized / total_trades if total_trades > 0 else 0.0
        
        # Calculate max drawdown (simplified - tracks max loss streak)
        max_drawdown = 0.0
        if trades:
            running_pnl = 0.0
            peak = 0.0
            for trade in trades:
                # Simplified: assume each trade has some PnL
                # In production, track actual trade PnL
                running_pnl += realized / total_trades if total_trades > 0 else 0.0
                if running_pnl > peak:
                    peak = running_pnl
                drawdown = peak - running_pnl
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
        
        last_trade_ts = trades[-1].get('timestamp') if trades else None
        
        return {
            'trades_count': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'avg_return': avg_return,
            'realized_pnl': realized,
            'max_drawdown': max_drawdown,
            'last_trade_ts': last_trade_ts,
        }
    
    def get_all_metrics(self) -> Dict:
        """Get all PnL metrics."""
        total_unrealized = self.get_total_unrealized()
        
        by_strategy = {}
        all_strategies = set(list(self.strategy_trades.keys()) + list(self.strategy_realized.keys()))
        
        for strategy in all_strategies:
            by_strategy[strategy] = self.get_strategy_metrics(strategy)
        
        return {
            'total_realized': self.total_realized,
            'total_unrealized': total_unrealized,
            'total_pnl': self.total_realized + total_unrealized,
            'by_strategy': by_strategy,
        }
    
    def _emit_pnl_update(self) -> None:
        """Emit PnL update event (non-blocking)."""
        try:
            from sentinel_x.core.state import get_state
            
            metrics = self.get_all_metrics()
            current_state = get_state()
            
            # PHASE 1: Event must include type, timestamp, engine_state, payload
            event = {
                'type': 'pnl_update',
                'timestamp': datetime.utcnow().isoformat() + "Z",
                'engine_state': current_state.value,
                'payload': {
                    'total_realized': metrics['total_realized'],
                    'total_unrealized': metrics['total_unrealized'],
                    'total_pnl': metrics['total_pnl'],
                    'by_strategy': metrics['by_strategy'],
                }
            }
            
            # Non-blocking publish
            safe_emit(self.event_bus.publish(event))
            
            # Also emit strategy_metrics events
            for strategy_name, strategy_metrics in metrics['by_strategy'].items():
                try:
                    strategy_event = {
                        'type': 'strategy_metrics',
                        'timestamp': datetime.utcnow().isoformat() + "Z",
                        'engine_state': current_state.value,
                        'payload': {
                            'strategy': strategy_name,
                            'trades_count': strategy_metrics['trades_count'],
                            'wins': strategy_metrics['wins'],
                            'losses': strategy_metrics['losses'],
                            'win_rate': strategy_metrics['win_rate'],
                            'avg_return': strategy_metrics['avg_return'],
                            'realized_pnl': strategy_metrics['realized_pnl'],
                            'max_drawdown': strategy_metrics['max_drawdown'],
                            'last_trade_ts': strategy_metrics['last_trade_ts'],
                        }
                    }
                    safe_emit(self.event_bus.publish(strategy_event))
                except Exception as e:
                    logger.error(f"Error emitting strategy metrics for {strategy_name}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error emitting PnL update: {e}", exc_info=True)
    
    def reset(self) -> None:
        """Reset PnL tracking (for restart)."""
        self.total_realized = 0.0
        self.strategy_realized.clear()
        self.strategy_trades.clear()
        self.strategy_wins.clear()
        self.strategy_losses.clear()
        self.positions.clear()
        logger.info("PnL engine reset")


# Global PnL engine instance
_pnl_engine: Optional[PnLEngine] = None


def get_pnl_engine() -> PnLEngine:
    """Get global PnL engine instance."""
    global _pnl_engine
    if _pnl_engine is None:
        _pnl_engine = PnLEngine()
    return _pnl_engine
