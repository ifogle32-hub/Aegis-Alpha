"""
PHASE 2: Pre-Trade Risk Gate

Before execution:
- Validate cash
- Validate exposure
- Validate daily loss
- Validate engine mode
- Validate kill-switch

If any check fails:
- Log rejection
- Abort execution safely

Risk engine ALWAYS decides execution eligibility.
"""

import time
from datetime import datetime, date
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.core.kill_switch import is_killed
from sentinel_x.core.engine_mode import EngineMode, get_engine_mode
from sentinel_x.execution.order_intent import OrderIntent
from sentinel_x.execution.broker_base import BaseBroker


@dataclass
class RiskCheckResult:
    """Result of risk check."""
    passed: bool
    reason: str = ""
    rejected_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.rejected_at is None and not self.passed:
            self.rejected_at = datetime.utcnow()


class PreTradeRiskGate:
    """
    Pre-trade risk gate - validates all orders before execution.
    
    SAFETY: Risk engine ALWAYS decides execution eligibility.
    If any check fails, execution is aborted safely.
    """
    
    def __init__(
        self,
        max_position_size: float = 10000.0,  # Max position size in USD
        max_portfolio_exposure: float = 0.5,  # Max 50% of portfolio in positions
        max_daily_loss: float = 0.05,  # Max 5% daily loss
        max_daily_loss_absolute: Optional[float] = None  # Absolute daily loss limit
    ):
        """
        Initialize risk gate.
        
        Args:
            max_position_size: Maximum position size in USD
            max_portfolio_exposure: Maximum portfolio exposure (0.0 - 1.0)
            max_daily_loss: Maximum daily loss percentage (0.0 - 1.0)
            max_daily_loss_absolute: Maximum daily loss in absolute USD (optional)
        """
        self.max_position_size = max_position_size
        self.max_portfolio_exposure = max_portfolio_exposure
        self.max_daily_loss = max_daily_loss
        self.max_daily_loss_absolute = max_daily_loss_absolute
        
        # Daily loss tracking
        self.daily_pnl_start: Dict[date, float] = {}  # date -> starting equity
        self.daily_pnl_timestamp: Optional[date] = None
        
        logger.info(
            f"PreTradeRiskGate initialized: "
            f"max_position=${max_position_size:,.2f}, "
            f"max_exposure={max_portfolio_exposure:.1%}, "
            f"max_daily_loss={max_daily_loss:.1%}"
        )
    
    def check(self, intent: OrderIntent, executor: Optional[BaseBroker] = None) -> RiskCheckResult:
        """
        Perform all risk checks on an order intent.
        
        Args:
            intent: Order intent to check
            executor: Broker executor (optional, for account/position data)
            
        Returns:
            RiskCheckResult with passed=True if all checks pass, False otherwise
        """
        # Check 1: Kill-switch (supremacy - overrides everything)
        if is_killed():
            logger.warning(f"Risk check FAILED: Kill-switch active | intent_id={intent.intent_id}")
            return RiskCheckResult(
                passed=False,
                reason="kill_switch_active"
            )
        
        # Check 2: Engine mode validation
        current_mode = get_engine_mode()
        if intent.engine_mode not in (EngineMode.PAPER, EngineMode.LIVE):
            logger.debug(f"Risk check FAILED: Invalid engine mode | intent_id={intent.intent_id} | mode={intent.engine_mode.value}")
            return RiskCheckResult(
                passed=False,
                reason=f"invalid_engine_mode:{intent.engine_mode.value}"
            )
        
        if current_mode != intent.engine_mode:
            logger.debug(f"Risk check FAILED: Engine mode mismatch | intent_id={intent.intent_id} | intent_mode={intent.engine_mode.value} | current_mode={current_mode.value}")
            return RiskCheckResult(
                passed=False,
                reason=f"engine_mode_mismatch:intent={intent.engine_mode.value},current={current_mode.value}"
            )
        
        # Only allow execution in PAPER or LIVE modes
        if current_mode not in (EngineMode.PAPER, EngineMode.LIVE):
            logger.debug(f"Risk check FAILED: Execution not allowed in mode | intent_id={intent.intent_id} | mode={current_mode.value}")
            return RiskCheckResult(
                passed=False,
                reason=f"execution_not_allowed_in_mode:{current_mode.value}"
            )
        
        # If no executor provided, basic checks pass
        if executor is None:
            logger.debug(f"Risk check PASSED (no executor for detailed checks) | intent_id={intent.intent_id}")
            return RiskCheckResult(passed=True, reason="no_executor_checks")
        
        # Check 3: Cash validation (for BUY orders)
        if intent.side == "BUY":
            cash_check = self._check_cash(intent, executor)
            if not cash_check.passed:
                return cash_check
        
        # Check 4: Position size validation
        position_check = self._check_position_size(intent, executor)
        if not position_check.passed:
            return position_check
        
        # Check 5: Portfolio exposure validation
        exposure_check = self._check_portfolio_exposure(intent, executor)
        if not exposure_check.passed:
            return exposure_check
        
        # Check 6: Daily loss limit validation
        daily_loss_check = self._check_daily_loss_limit(executor)
        if not daily_loss_check.passed:
            return daily_loss_check
        
        # All checks passed
        logger.debug(f"Risk check PASSED | intent_id={intent.intent_id} | strategy={intent.strategy} | symbol={intent.symbol}")
        return RiskCheckResult(passed=True, reason="all_checks_passed")
    
    def _check_cash(self, intent: OrderIntent, executor: BaseBroker) -> RiskCheckResult:
        """Check if sufficient cash is available for BUY order."""
        try:
            account = executor.get_account()
            if not account:
                logger.warning(f"Risk check: Cannot get account for cash validation | intent_id={intent.intent_id}")
                return RiskCheckResult(passed=False, reason="account_unavailable")
            
            cash = account.get('cash') or account.get('buying_power') or 0.0
            
            # Calculate order cost
            if intent.order_type.value == "LIMIT" and intent.limit_price:
                order_cost = intent.qty * intent.limit_price
            else:
                # For market orders, estimate at current position price or use qty * symbol_price
                # This is a simplified check - in production, use market data
                order_cost = intent.qty * 100.0  # Placeholder
            
            if order_cost > cash:
                logger.warning(
                    f"Risk check FAILED: Insufficient cash | "
                    f"intent_id={intent.intent_id} | "
                    f"required=${order_cost:,.2f} | "
                    f"available=${cash:,.2f}"
                )
                return RiskCheckResult(
                    passed=False,
                    reason=f"insufficient_cash:required={order_cost:.2f},available={cash:.2f}"
                )
            
            return RiskCheckResult(passed=True)
            
        except Exception as e:
            logger.error(f"Risk check error in cash validation: {e}", exc_info=True)
            # Fail open safely - reject on error
            return RiskCheckResult(passed=False, reason=f"cash_check_error:{str(e)}")
    
    def _check_position_size(self, intent: OrderIntent, executor: BaseBroker) -> RiskCheckResult:
        """Check if position size is within limits."""
        try:
            # Get current position
            positions = executor.get_positions()
            current_position_qty = 0.0
            current_price = 0.0
            
            for pos in positions:
                if pos['symbol'] == intent.symbol:
                    current_position_qty = pos.get('qty', 0.0)
                    current_price = pos.get('current_price', 0.0) or pos.get('avg_price', 0.0)
                    break
            
            # Calculate new position size
            if intent.side == "BUY":
                new_qty = current_position_qty + intent.qty
            else:  # SELL
                new_qty = current_position_qty - intent.qty
            
            # Calculate position notional value
            if intent.order_type.value == "LIMIT" and intent.limit_price:
                price = intent.limit_price
            else:
                price = current_price if current_price > 0 else 100.0  # Placeholder
            
            position_notional = abs(new_qty) * price
            
            if position_notional > self.max_position_size:
                logger.warning(
                    f"Risk check FAILED: Position size exceeds limit | "
                    f"intent_id={intent.intent_id} | "
                    f"position_notional=${position_notional:,.2f} | "
                    f"limit=${self.max_position_size:,.2f}"
                )
                return RiskCheckResult(
                    passed=False,
                    reason=f"position_size_exceeded:notional={position_notional:.2f},limit={self.max_position_size:.2f}"
                )
            
            return RiskCheckResult(passed=True)
            
        except Exception as e:
            logger.error(f"Risk check error in position size validation: {e}", exc_info=True)
            return RiskCheckResult(passed=False, reason=f"position_size_check_error:{str(e)}")
    
    def _check_portfolio_exposure(self, intent: OrderIntent, executor: BaseBroker) -> RiskCheckResult:
        """Check if portfolio exposure is within limits."""
        try:
            account = executor.get_account()
            if not account:
                return RiskCheckResult(passed=False, reason="account_unavailable")
            
            portfolio_value = account.get('portfolio_value') or account.get('equity') or 0.0
            if portfolio_value <= 0:
                return RiskCheckResult(passed=False, reason="invalid_portfolio_value")
            
            # Get total position notional
            positions = executor.get_positions()
            total_position_notional = 0.0
            
            for pos in positions:
                qty = abs(pos.get('qty', 0.0))
                price = pos.get('current_price', 0.0) or pos.get('avg_price', 0.0)
                if price > 0:
                    total_position_notional += qty * price
            
            # Add new order to exposure
            if intent.order_type.value == "LIMIT" and intent.limit_price:
                price = intent.limit_price
            else:
                # Estimate from current position or use placeholder
                current_price = 0.0
                for pos in positions:
                    if pos['symbol'] == intent.symbol:
                        current_price = pos.get('current_price', 0.0) or pos.get('avg_price', 0.0)
                        break
                price = current_price if current_price > 0 else 100.0
            
            new_order_notional = intent.qty * price
            
            # Calculate new exposure
            new_exposure = (total_position_notional + new_order_notional) / portfolio_value
            
            if new_exposure > self.max_portfolio_exposure:
                logger.warning(
                    f"Risk check FAILED: Portfolio exposure exceeds limit | "
                    f"intent_id={intent.intent_id} | "
                    f"exposure={new_exposure:.1%} | "
                    f"limit={self.max_portfolio_exposure:.1%}"
                )
                return RiskCheckResult(
                    passed=False,
                    reason=f"portfolio_exposure_exceeded:exposure={new_exposure:.2f},limit={self.max_portfolio_exposure:.2f}"
                )
            
            return RiskCheckResult(passed=True)
            
        except Exception as e:
            logger.error(f"Risk check error in portfolio exposure validation: {e}", exc_info=True)
            return RiskCheckResult(passed=False, reason=f"exposure_check_error:{str(e)}")
    
    def _check_daily_loss_limit(self, executor: BaseBroker) -> RiskCheckResult:
        """Check if daily loss limit has been exceeded."""
        try:
            account = executor.get_account()
            if not account:
                return RiskCheckResult(passed=False, reason="account_unavailable")
            
            equity = account.get('equity') or account.get('portfolio_value') or 0.0
            if equity <= 0:
                return RiskCheckResult(passed=False, reason="invalid_equity")
            
            # Track daily PnL
            today = date.today()
            
            # Reset daily tracking if new day
            if self.daily_pnl_timestamp != today:
                self.daily_pnl_start[today] = equity
                self.daily_pnl_timestamp = today
            
            # Calculate daily PnL
            daily_start_equity = self.daily_pnl_start.get(today, equity)
            daily_pnl = equity - daily_start_equity
            daily_loss_pct = abs(daily_pnl) / daily_start_equity if daily_start_equity > 0 else 0.0
            
            # Check percentage loss
            if daily_pnl < 0 and daily_loss_pct > self.max_daily_loss:
                logger.warning(
                    f"Risk check FAILED: Daily loss limit exceeded | "
                    f"daily_pnl=${daily_pnl:,.2f} | "
                    f"loss_pct={daily_loss_pct:.1%} | "
                    f"limit={self.max_daily_loss:.1%}"
                )
                return RiskCheckResult(
                    passed=False,
                    reason=f"daily_loss_limit_exceeded:pnl={daily_pnl:.2f},loss_pct={daily_loss_pct:.2f},limit={self.max_daily_loss:.2f}"
                )
            
            # Check absolute loss (if configured)
            if self.max_daily_loss_absolute is not None:
                if daily_pnl < 0 and abs(daily_pnl) > self.max_daily_loss_absolute:
                    logger.warning(
                        f"Risk check FAILED: Daily absolute loss limit exceeded | "
                        f"daily_pnl=${daily_pnl:,.2f} | "
                        f"limit=${self.max_daily_loss_absolute:,.2f}"
                    )
                    return RiskCheckResult(
                        passed=False,
                        reason=f"daily_absolute_loss_exceeded:pnl={daily_pnl:.2f},limit={self.max_daily_loss_absolute:.2f}"
                    )
            
            return RiskCheckResult(passed=True)
            
        except Exception as e:
            logger.error(f"Risk check error in daily loss limit validation: {e}", exc_info=True)
            # Fail open safely - reject on error
            return RiskCheckResult(passed=False, reason=f"daily_loss_check_error:{str(e)}")


# Global risk gate instance
_risk_gate: Optional[PreTradeRiskGate] = None


def get_risk_gate(
    max_position_size: float = 10000.0,
    max_portfolio_exposure: float = 0.5,
    max_daily_loss: float = 0.05,
    max_daily_loss_absolute: Optional[float] = None
) -> PreTradeRiskGate:
    """Get global risk gate instance."""
    global _risk_gate
    if _risk_gate is None:
        _risk_gate = PreTradeRiskGate(
            max_position_size=max_position_size,
            max_portfolio_exposure=max_portfolio_exposure,
            max_daily_loss=max_daily_loss,
            max_daily_loss_absolute=max_daily_loss_absolute
        )
    return _risk_gate
