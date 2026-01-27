"""
PHASE 4: Shadow Trading Executor

Shadow trading mode: paper + live side-by-side.
- Primary broker = PAPER or LIVE
- Shadow broker = PAPER (always)
- Same orders sent to both
- ONLY primary broker executes capital
- Shadow fills tracked separately

Emit events:
{
  type: "shadow_trade",
  primary_fill,
  shadow_fill,
  slippage_diff,
  latency_diff
}

Rules:
- Shadow trading never places real orders
- Allows live vs paper comparison safely
"""
from typing import Dict, Optional, List
from datetime import datetime
from sentinel_x.monitoring.logger import logger
from sentinel_x.execution.broker_base import BaseBroker
from sentinel_x.execution.paper_executor import PaperExecutor
from sentinel_x.utils import safe_emit


class ShadowExecutor:
    """
    Shadow trading executor that mirrors orders to a shadow broker.
    
    Always uses PAPER broker for shadow, regardless of primary mode.
    """
    
    def __init__(self, primary_broker: BaseBroker, 
                 shadow_initial_capital: float = 100000.0):
        """
        Initialize shadow executor.
        
        Args:
            primary_broker: Primary broker (PAPER or LIVE)
            shadow_initial_capital: Initial capital for shadow broker
        """
        self.primary_broker = primary_broker
        self.shadow_broker = PaperExecutor(shadow_initial_capital)
        
        # Track shadow fills separately
        self.shadow_fills: List[Dict] = []
        self.primary_fills: List[Dict] = []
        
        logger.info(f"ShadowExecutor initialized: primary={primary_broker.name}, shadow=paper")
    
    def submit_order(self, symbol: str, side: str, qty: float,
                     price: Optional[float] = None, strategy: str = "") -> Optional[Dict]:
        """
        Submit order to both primary and shadow brokers.
        
        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            qty: Order quantity
            price: Execution price
            strategy: Strategy name
            
        Returns:
            Primary broker fill result (shadow is tracked separately)
        """
        # Execute on primary broker (this is the real execution)
        primary_fill = None
        try:
            if hasattr(self.primary_broker, 'submit_order'):
                primary_fill = self.primary_broker.submit_order(
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    price=price,
                    strategy=strategy
                )
            elif hasattr(self.primary_broker, 'execute_order'):
                # Handle different broker interfaces
                size = qty if side.upper() == "BUY" else -qty
                primary_fill = self.primary_broker.execute_order(
                    symbol=symbol,
                    size=size,
                    price=price or 0.0,
                    strategy=strategy
                )
        except Exception as e:
            logger.error(f"Error executing order on primary broker: {e}", exc_info=True)
            # Continue - shadow trading should still work even if primary fails
        
        # Execute on shadow broker (always paper, never affects real capital)
        shadow_fill = None
        try:
            shadow_fill = self.shadow_broker.submit_order(
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                strategy=strategy
            )
            
            if shadow_fill:
                self.shadow_fills.append(shadow_fill)
        except Exception as e:
            logger.error(f"Error executing order on shadow broker: {e}", exc_info=True)
            # Shadow failures never block primary
        
        # Track primary fill
        if primary_fill:
            self.primary_fills.append(primary_fill)
        
        # Emit shadow trade event if both fills occurred
        if primary_fill and shadow_fill:
            self._emit_shadow_trade_event(primary_fill, shadow_fill)
        
        # Return primary fill (shadow is tracked separately)
        return primary_fill
    
    def get_positions(self) -> List[Dict]:
        """
        Get positions from primary broker only.
        
        Returns:
            List of position dicts from primary broker
        """
        try:
            if hasattr(self.primary_broker, 'get_positions'):
                return self.primary_broker.get_positions()
            return []
        except Exception as e:
            logger.error(f"Error getting positions from primary broker: {e}", exc_info=True)
            return []
    
    def get_shadow_positions(self) -> List[Dict]:
        """
        Get positions from shadow broker.
        
        Returns:
            List of position dicts from shadow broker
        """
        try:
            return self.shadow_broker.get_positions()
        except Exception as e:
            logger.error(f"Error getting shadow positions: {e}", exc_info=True)
            return []
    
    def get_account(self) -> Optional[Dict]:
        """Get account info from primary broker."""
        try:
            if hasattr(self.primary_broker, 'get_account'):
                return self.primary_broker.get_account()
            return None
        except Exception as e:
            logger.error(f"Error getting account from primary broker: {e}", exc_info=True)
            return None
    
    def get_shadow_account(self) -> Optional[Dict]:
        """Get account info from shadow broker."""
        try:
            return self.shadow_broker.get_account()
        except Exception as e:
            logger.error(f"Error getting shadow account: {e}", exc_info=True)
            return None
    
    def get_shadow_comparison(self) -> Dict:
        """
        Get comparison between primary and shadow brokers.
        
        Returns:
            Dict with primary_pnl, shadow_pnl, slippage_diff, latency_diff
        """
        try:
            # Get primary PnL
            primary_pnl = 0.0
            primary_positions = self.get_positions()
            for pos in primary_positions:
                primary_pnl += pos.get('unrealized_pnl', 0.0)
            
            # Get shadow PnL
            shadow_pnl = 0.0
            shadow_positions = self.get_shadow_positions()
            for pos in shadow_positions:
                shadow_pnl += pos.get('unrealized_pnl', 0.0)
            
            # Calculate slippage difference (simplified - compare fill prices)
            slippage_diff = 0.0
            if len(self.primary_fills) > 0 and len(self.shadow_fills) > 0:
                # Compare average fill prices
                primary_avg = sum(f.get('price', 0) for f in self.primary_fills) / len(self.primary_fills)
                shadow_avg = sum(f.get('price', 0) for f in self.shadow_fills) / len(self.shadow_fills)
                slippage_diff = primary_avg - shadow_avg
            
            # Latency difference (simplified - compare timestamps)
            latency_diff = 0.0
            if len(self.primary_fills) > 0 and len(self.shadow_fills) > 0:
                # Compare last fill timestamps
                primary_ts = self.primary_fills[-1].get('timestamp')
                shadow_ts = self.shadow_fills[-1].get('timestamp')
                if primary_ts and shadow_ts:
                    try:
                        if isinstance(primary_ts, str):
                            primary_dt = datetime.fromisoformat(primary_ts.replace('Z', '+00:00'))
                        else:
                            primary_dt = primary_ts
                        if isinstance(shadow_ts, str):
                            shadow_dt = datetime.fromisoformat(shadow_ts.replace('Z', '+00:00'))
                        else:
                            shadow_dt = shadow_ts
                        latency_diff = (primary_dt - shadow_dt).total_seconds()
                    except Exception:
                        pass
            
            return {
                'primary_pnl': primary_pnl,
                'shadow_pnl': shadow_pnl,
                'pnl_diff': primary_pnl - shadow_pnl,
                'slippage_diff': slippage_diff,
                'latency_diff': latency_diff,
                'primary_fills_count': len(self.primary_fills),
                'shadow_fills_count': len(self.shadow_fills)
            }
        
        except Exception as e:
            logger.error(f"Error getting shadow comparison: {e}", exc_info=True)
            return {
                'primary_pnl': 0.0,
                'shadow_pnl': 0.0,
                'pnl_diff': 0.0,
                'slippage_diff': 0.0,
                'latency_diff': 0.0,
                'primary_fills_count': 0,
                'shadow_fills_count': 0
            }
    
    def _emit_shadow_trade_event(self, primary_fill: Dict, shadow_fill: Dict) -> None:
        """Emit shadow trade event (non-blocking)."""
        try:
            import asyncio
            from sentinel_x.monitoring.event_bus import get_event_bus
            
            # Calculate differences
            primary_price = primary_fill.get('price', 0)
            shadow_price = shadow_fill.get('price', 0)
            slippage_diff = primary_price - shadow_price if primary_price and shadow_price else 0.0
            
            # Latency difference
            latency_diff = 0.0
            primary_ts = primary_fill.get('timestamp')
            shadow_ts = shadow_fill.get('timestamp')
            if primary_ts and shadow_ts:
                try:
                    if isinstance(primary_ts, str):
                        primary_dt = datetime.fromisoformat(primary_ts.replace('Z', '+00:00'))
                    else:
                        primary_dt = primary_ts
                    if isinstance(shadow_ts, str):
                        shadow_dt = datetime.fromisoformat(shadow_ts.replace('Z', '+00:00'))
                    else:
                        shadow_dt = shadow_ts
                    latency_diff = (primary_dt - shadow_dt).total_seconds()
                except Exception:
                    pass
            
            event = {
                'type': 'shadow_trade',
                'primary_fill': primary_fill,
                'shadow_fill': shadow_fill,
                'slippage_diff': slippage_diff,
                'latency_diff': latency_diff,
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }
            
            event_bus = get_event_bus()
            safe_emit(event_bus.publish(event))
        
        except Exception as e:
            logger.error(f"Error emitting shadow trade event: {e}", exc_info=True)
    
    def cancel_all_orders(self) -> int:
        """Cancel all orders on primary broker only."""
        try:
            if hasattr(self.primary_broker, 'cancel_all_orders'):
                return self.primary_broker.cancel_all_orders() or 0
            return 0
        except Exception as e:
            logger.error(f"Error canceling orders on primary broker: {e}", exc_info=True)
            return 0
