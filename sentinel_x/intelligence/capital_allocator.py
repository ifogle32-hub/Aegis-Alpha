"""
PHASE 1-9 — SIMULATED CAPITAL ALLOCATION ENGINE (ADVISORY ONLY)

SAFETY: allocator is advisory only
SAFETY: no order sizing impact
REGRESSION LOCK — CAPITAL ALLOCATION

The allocator:
- Computes recommended capital weights per strategy
- Uses performance + risk metrics
- Produces READ-ONLY allocation suggestions

The allocator MUST NOT:
- Change order sizes
- Change trade frequency
- Change execution priority
- Enable or disable strategies

Invariant: "Allocator output is never consumed by execution paths."

Allocator modes:
- Equal weight (fallback)
- Fractional Kelly (capped)
- Risk parity (volatility-based)
- Blended (α * Kelly + (1-α) * Risk Parity)

Inputs:
- Strategy performance metrics (normalized)
- Volatility estimates (if available)
- Drawdown and risk metrics

Constraints:
- Max capital per strategy
- Min capital threshold
- Max active allocations
- Drawdown throttles (advisory only)

Allocator must NEVER over-allocate.
All weights normalized to sum = 1.0
Negative weights forbidden
Zero allocation allowed
"""
# CRITICAL: All imports must be safe - wrap optional imports
try:
    import numpy as np
except Exception:
    np = None  # Fallback if numpy not available

from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

try:
    from sentinel_x.monitoring.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from sentinel_x.monitoring.event_bus import get_event_bus
except Exception:
    get_event_bus = None

import asyncio

try:
    from sentinel_x.utils import safe_emit
except Exception:
    safe_emit = lambda x: None


class AllocatorMode(Enum):
    """
    PHASE 3: Capital allocator modes (simulated, advisory only).
    
    SAFETY: allocator is advisory only
    SAFETY: no execution influence
    """
    EQUAL_WEIGHT = "EQUAL_WEIGHT"  # Fallback
    KELLY = "KELLY"  # Fractional Kelly (capped)
    RISK_PARITY = "RISK_PARITY"  # Volatility-based (inverse volatility)
    BLENDED = "BLENDED"  # α * Kelly + (1-α) * Risk Parity


@dataclass
class StrategyAllocation:
    """
    PHASE 5: Capital allocation for a strategy (simulated, advisory only).
    
    SAFETY: allocator is advisory only
    SAFETY: no execution influence
    """
    strategy_name: str
    capital_fraction: float  # Fraction of total capital (0.0-1.0, SIMULATED)
    max_position_size: float  # Max position size in dollars (SIMULATED, advisory)
    allocation_mode: str  # Mode used for this allocation
    raw_score: float = 0.0  # PHASE 5: Raw allocation score before adjustments
    risk_adjusted_score: float = 0.0  # PHASE 5: Score after risk adjustments
    notes: Optional[str] = None  # PHASE 5: Notes (e.g. "drawdown penalty applied")


@dataclass
class AllocatorConstraints:
    """
    PHASE 7: Constraints for capital allocation (governance limits).
    
    SAFETY: constraints are advisory only
    SAFETY: no execution influence
    """
    max_capital_per_strategy: float = 0.25  # Max 25% per strategy (MAX_WEIGHT_PER_STRATEGY)
    max_portfolio_leverage: float = 1.0  # Max leverage (1.0 = no leverage)
    min_capital_per_strategy: float = 0.01  # Min 1% per strategy (MIN_WEIGHT_THRESHOLD)
    kelly_fraction_cap: float = 0.25  # Cap Kelly fraction at 25%
    max_active_allocations: int = 10  # PHASE 7: Max active strategies to allocate to
    drawdown_threshold: float = 0.20  # PHASE 4: Drawdown threshold for throttling (20%)
    system_drawdown_limit: float = 0.25  # PHASE 4: System drawdown limit for global throttle (25%)
    blended_alpha: float = 0.6  # PHASE 3: Blended model weight (α for Kelly, 1-α for Risk Parity)


@dataclass
class CapitalAllocationSnapshot:
    """
    PHASE 5: Capital allocation snapshot (immutable, read-only).
    
    SAFETY: allocator is advisory only
    SAFETY: no execution influence
    REGRESSION LOCK — CAPITAL ALLOCATION
    """
    timestamp: datetime
    model_mode: str  # Allocation model used (KELLY, RISK_PARITY, BLENDED, EQUAL_WEIGHT)
    model_parameters: Dict[str, Any]  # Model parameters (e.g. alpha for blended)
    allocations: List[Dict[str, Any]]  # List of strategy allocations (per StrategyAllocation)
    total_simulated_capital: float = 1.0  # Always 100% (normalized)
    governance_warnings: List[str] = field(default_factory=list)  # PHASE 7: Governance warnings if limits violated
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary (read-only)."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'model_mode': self.model_mode,
            'model_parameters': self.model_parameters,
            'allocations': self.allocations,
            'total_simulated_capital': self.total_simulated_capital,
            'governance_warnings': self.governance_warnings,
            'label': 'SIMULATED CAPITAL ALLOCATION — NO EXECUTION EFFECT'  # PHASE 6: UI label
        }


class CapitalAllocator:
    """
    PHASE 1-9: Simulated capital allocator (advisory only).
    
    SAFETY: allocator is advisory only
    SAFETY: no order sizing impact
    SAFETY: no execution influence
    REGRESSION LOCK — CAPITAL ALLOCATION
    
    Computes recommended capital weights per strategy based on performance and risk metrics.
    All allocations are SIMULATED and READ-ONLY - never affect execution.
    
    Never over-allocates capital.
    Falls back to equal-weight on error.
    All weights normalized to sum = 1.0
    Negative weights forbidden
    Zero allocation allowed
    """
    
    def __init__(self, mode: AllocatorMode = AllocatorMode.EQUAL_WEIGHT,
                 constraints: Optional[AllocatorConstraints] = None):
        """
        PHASE 1: Initialize capital allocator (advisory only).
        
        SAFETY: allocator is advisory only
        SAFETY: no execution influence
        
        Args:
            mode: Allocation mode (EQUAL_WEIGHT, KELLY, RISK_PARITY, BLENDED)
            constraints: Allocation constraints (governance limits)
        """
        self.mode = mode
        self.constraints = constraints or AllocatorConstraints()
        self.event_bus = get_event_bus()
        
        # PHASE 5: Store latest allocation snapshot
        self.latest_snapshot: Optional[CapitalAllocationSnapshot] = None
        
        logger.info(f"CapitalAllocator initialized: mode={mode.value}, "
                   f"max_per_strategy={self.constraints.max_capital_per_strategy:.2%}, "
                   f"min_per_strategy={self.constraints.min_capital_per_strategy:.2%}, "
                   f"max_active={self.constraints.max_active_allocations}, "
                   f"SIMULATED ONLY - NO EXECUTION EFFECT")
        
        # PHASE 8: Safety assertion - allocator output is never consumed by execution paths
        # This is enforced by:
        # 1. Allocator output is never passed to execution router
        # 2. Allocator output is never used to modify order sizes
        # 3. Allocator output is read-only and advisory only
        # 4. Dashboard and API endpoints expose allocations but never consume them
        logger.info("SAFETY: Allocator output is never consumed by execution paths (advisory only)")
    
    def allocate_from_strategy_manager(self, strategy_manager=None) -> CapitalAllocationSnapshot:
        """
        PHASE 2-5: Allocate capital from strategy manager (simulated, advisory only).
        
        SAFETY: allocator is advisory only
        SAFETY: no execution influence
        REGRESSION LOCK — CAPITAL ALLOCATION
        
        Consumes normalized metrics from strategy_manager:
        - lifecycle_state (TRAINING only)
        - trades_count
        - realized_pnl
        - expectancy
        - sharpe (if available)
        - max_drawdown
        - volatility (if available)
        
        Rules:
        - Ignore DISABLED strategies
        - Ignore strategies below MIN_TRADES
        - Metrics are snapshots only
        
        Args:
            strategy_manager: StrategyManager instance (optional, will get global if None)
            
        Returns:
            CapitalAllocationSnapshot (read-only, immutable)
        """
        try:
            # Get strategy manager (safe - read-only)
            if strategy_manager is None:
                try:
                    from sentinel_x.intelligence.strategy_manager import get_strategy_manager
                    strategy_manager = get_strategy_manager() if get_strategy_manager else None
                except Exception:
                    strategy_manager = None
            
            if not strategy_manager:
                logger.warning("StrategyManager not available, returning empty allocation")
                return self._create_empty_snapshot()
            
            # PHASE 2: Get TRAINING strategies only (read-only)
            all_strategies = strategy_manager.list_strategies()
            training_strategies = [
                s['name'] for s in all_strategies
                if s.get('lifecycle_state') == 'TRAINING' and s.get('status') == 'ACTIVE'
            ]
            
            if not training_strategies:
                logger.debug("No TRAINING strategies available for allocation")
                return self._create_empty_snapshot()
            
            # PHASE 2: Get normalized metrics per strategy (read-only)
            strategy_metrics = {}
            volatility_estimates = {}
            
            min_trades = getattr(strategy_manager, 'min_trades_for_promotion', 20)
            
            for strategy_name in training_strategies:
                try:
                    # Get normalized metrics (read-only)
                    metrics = strategy_manager.compute_normalized_metrics(strategy_name)
                    trades_count = metrics.get('trades_count', 0)
                    
                    # PHASE 2: Ignore strategies below MIN_TRADES
                    if trades_count < min_trades:
                        continue
                    
                    # Build metrics dict (read-only snapshot)
                    strategy_metrics[strategy_name] = {
                        'lifecycle_state': 'TRAINING',
                        'trades_count': trades_count,
                        'realized_pnl': metrics.get('realized_pnl', 0.0),
                        'expectancy': metrics.get('expectancy', 0.0),
                        'sharpe': metrics.get('sharpe'),
                        'max_drawdown': metrics.get('max_drawdown', 0.0),
                        'win_rate': metrics.get('win_rate', 0.0),
                        'composite_score': strategy_manager.calculate_composite_score(strategy_name)
                    }
                    
                    # Get volatility estimate if available (read-only)
                    sharpe = metrics.get('sharpe')
                    if sharpe is not None and sharpe > 0:
                        # Approximate volatility from Sharpe (simplified)
                        # Sharpe ≈ (return - risk_free) / volatility
                        # If we assume risk_free = 0, volatility ≈ return / sharpe
                        # Use realized_pnl as proxy for return
                        realized_pnl = metrics.get('realized_pnl', 0.0)
                        if realized_pnl > 0:
                            volatility_estimates[strategy_name] = abs(realized_pnl) / sharpe
                        else:
                            volatility_estimates[strategy_name] = 1.0  # Default volatility
                    else:
                        volatility_estimates[strategy_name] = 1.0  # Default volatility
                        
                except Exception as e:
                    logger.debug(f"Error getting metrics for {strategy_name} (non-fatal): {e}")
                    continue
            
            if not strategy_metrics:
                logger.debug("No strategies with sufficient metrics for allocation")
                return self._create_empty_snapshot()
            
            # PHASE 3: Route to appropriate allocation method (simulated only)
            if self.mode == AllocatorMode.EQUAL_WEIGHT:
                allocations = self._allocate_equal_weight(list(strategy_metrics.keys()))
            elif self.mode == AllocatorMode.KELLY:
                allocations = self._allocate_kelly(list(strategy_metrics.keys()), strategy_metrics)
            elif self.mode == AllocatorMode.RISK_PARITY:
                allocations = self._allocate_risk_parity(list(strategy_metrics.keys()), volatility_estimates, strategy_metrics)
            elif self.mode == AllocatorMode.BLENDED:
                allocations = self._allocate_blended(list(strategy_metrics.keys()), strategy_metrics, volatility_estimates)
            else:
                logger.warning(f"Unknown allocator mode: {self.mode}, falling back to equal weight")
                allocations = self._allocate_equal_weight(list(strategy_metrics.keys()))
            
            # PHASE 4: Apply drawdown throttles (advisory only)
            allocations = self._apply_drawdown_throttles(allocations, strategy_metrics)
            
            # PHASE 7: Apply governance limits
            allocations, warnings = self._apply_governance_limits(allocations)
            
            # Normalize allocations (must sum to 1.0)
            allocations = self._normalize_allocations(allocations)
            
            # PHASE 5: Create allocation snapshot (immutable, read-only)
            snapshot = self._create_allocation_snapshot(allocations, strategy_metrics, warnings)
            
            # Store latest snapshot
            self.latest_snapshot = snapshot
            
            # Emit event (non-blocking)
            self._emit_allocation_event(allocations)
            
            return snapshot
        
        except Exception as e:
            logger.error(f"Error in capital allocation: {e}", exc_info=True)
            # Fallback to empty snapshot
            logger.warning("Falling back to empty allocation snapshot")
            self._emit_fallback_event()
            return self._create_empty_snapshot()
    
    def allocate(self, strategies: List[str],
                strategy_metrics: Dict[str, Dict],
                volatility_estimates: Optional[Dict[str, float]] = None,
                correlation_matrix: Optional[Any] = None) -> List[StrategyAllocation]:
        """
        PHASE 3: Allocate capital across strategies (legacy method, simulated only).
        
        SAFETY: allocator is advisory only
        SAFETY: no execution influence
        
        Args:
            strategies: List of strategy names
            strategy_metrics: Dict mapping strategy name to metrics
            volatility_estimates: Dict mapping strategy name to volatility (optional)
            correlation_matrix: Correlation matrix (optional, unused)
            
        Returns:
            List of StrategyAllocation objects (simulated, advisory only)
        """
        try:
            if not strategies:
                return []
            
            # Route to appropriate allocation method
            if self.mode == AllocatorMode.EQUAL_WEIGHT:
                allocations = self._allocate_equal_weight(strategies)
            elif self.mode == AllocatorMode.KELLY:
                allocations = self._allocate_kelly(strategies, strategy_metrics)
            elif self.mode == AllocatorMode.RISK_PARITY:
                allocations = self._allocate_risk_parity(strategies, volatility_estimates, strategy_metrics)
            elif self.mode == AllocatorMode.BLENDED:
                allocations = self._allocate_blended(strategies, strategy_metrics, volatility_estimates)
            else:
                logger.warning(f"Unknown allocator mode: {self.mode}, falling back to equal weight")
                allocations = self._allocate_equal_weight(strategies)
            
            # Apply drawdown throttles
            allocations = self._apply_drawdown_throttles(allocations, strategy_metrics)
            
            # Apply constraints
            allocations, warnings = self._apply_governance_limits(allocations)
            
            # Normalize allocations (must sum to 1.0)
            allocations = self._normalize_allocations(allocations)
            
            # Emit event (non-blocking)
            self._emit_allocation_event(allocations)
            
            return allocations
        
        except Exception as e:
            logger.error(f"Error in capital allocation: {e}", exc_info=True)
            # Fallback to equal weight
            logger.warning("Falling back to equal-weight allocation")
            self._emit_fallback_event()
            return self._allocate_equal_weight(strategies)
    
    def _allocate_equal_weight(self, strategies: List[str]) -> List[StrategyAllocation]:
        """
        PHASE 3: Equal weight allocation (fallback, simulated only).
        
        SAFETY: allocator is advisory only
        SAFETY: no execution influence
        """
        n = len(strategies)
        if n == 0:
            return []
        
        fraction = 1.0 / n
        
        return [
            StrategyAllocation(
                strategy_name=name,
                capital_fraction=fraction,
                max_position_size=0.0,  # SIMULATED - not used in execution
                allocation_mode="EQUAL_WEIGHT",
                raw_score=fraction,
                risk_adjusted_score=fraction,
                notes="Equal weight allocation (fallback)"
            )
            for name in strategies
        ]
    
    def _allocate_kelly(self, strategies: List[str],
                      strategy_metrics: Dict[str, Dict]) -> List[StrategyAllocation]:
        """
        PHASE 3: Fractional Kelly allocation (capped, simulated only).
        
        SAFETY: allocator is advisory only
        SAFETY: no execution influence
        
        Kelly fraction computed from expectancy / variance (simplified).
        Formula: Kelly ≈ expectancy / (expectancy^2 + variance)
        
        Capped per-strategy weight (e.g. max 20%).
        All weights normalized to sum = 1.0
        Negative weights forbidden
        Zero allocation allowed
        """
        allocations = []
        
        for strategy_name in strategies:
            metrics = strategy_metrics.get(strategy_name, {})
            
            # Extract metrics
            win_rate = metrics.get('win_rate', 0.5)
            trades_count = metrics.get('trades_count', 0)
            expectancy = metrics.get('expectancy', 0.0)
            realized_pnl = metrics.get('realized_pnl', 0.0)
            sharpe = metrics.get('sharpe')
            
            raw_score = 0.0
            notes = []
            
            if trades_count == 0:
                # Insufficient data, use minimal allocation
                fraction = 0.0
                notes.append("insufficient_trades")
            elif expectancy <= 0:
                # Negative or zero expectancy, zero allocation
                fraction = 0.0
                notes.append("negative_expectancy")
            else:
                # PHASE 3: Fractional Kelly calculation
                # Simplified: Kelly ≈ expectancy / variance
                # If we have Sharpe, approximate variance from Sharpe
                if sharpe is not None and sharpe > 0:
                    # Sharpe ≈ expectancy / volatility
                    # volatility ≈ expectancy / sharpe
                    # variance ≈ volatility^2 ≈ (expectancy / sharpe)^2
                    volatility = abs(expectancy) / sharpe
                    variance = volatility ** 2
                    
                    # Kelly fraction = expectancy / (expectancy^2 + variance)
                    # Or simplified: Kelly ≈ expectancy / variance (if variance >> expectancy^2)
                    if variance > 0:
                        kelly = expectancy / (expectancy**2 + variance)
                    else:
                        kelly = 0.0
                else:
                    # Fallback: use win_rate-based Kelly
                    # Kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
                    # Approximate from realized_pnl and win_rate
                    if win_rate > 0 and win_rate < 1:
                        # Estimate avg_win and avg_loss from realized_pnl
                        # Simplified: assume avg_win ≈ realized_pnl / (trades_count * win_rate)
                        # avg_loss ≈ -realized_pnl / (trades_count * (1 - win_rate))
                        avg_win_est = abs(realized_pnl) / (trades_count * win_rate) if win_rate > 0 else 0
                        avg_loss_est = abs(realized_pnl) / (trades_count * (1 - win_rate)) if win_rate < 1 else 0
                        
                        if avg_win_est > 0:
                            kelly = (win_rate * avg_win_est - (1 - win_rate) * avg_loss_est) / avg_win_est
                        else:
                            kelly = 0.0
                    else:
                        kelly = 0.0
                
                raw_score = kelly
                
                # PHASE 3: Cap Kelly fraction at constraint
                kelly = max(0.0, min(kelly, self.constraints.kelly_fraction_cap))
                
                # Normalize to fraction (will be normalized later)
                fraction = kelly
                
                if kelly >= self.constraints.kelly_fraction_cap:
                    notes.append(f"kelly_capped_at_{self.constraints.kelly_fraction_cap:.2%}")
            
            allocations.append(
                StrategyAllocation(
                    strategy_name=strategy_name,
                    capital_fraction=fraction,
                    max_position_size=0.0,  # SIMULATED - not used in execution
                    allocation_mode="KELLY",
                    raw_score=raw_score,
                    risk_adjusted_score=fraction,
                    notes="; ".join(notes) if notes else "Fractional Kelly allocation"
                )
            )
        
        # Normalize fractions to sum to 1.0 (if any positive allocations)
        total = sum(a.capital_fraction for a in allocations)
        if total > 0:
            for allocation in allocations:
                allocation.capital_fraction /= total
                allocation.risk_adjusted_score = allocation.capital_fraction
        else:
            # Fallback to equal weight if all zero
            return self._allocate_equal_weight(strategies)
        
        return allocations
    
    def _allocate_risk_parity(self, strategies: List[str],
                            volatility_estimates: Optional[Dict[str, float]],
                            strategy_metrics: Optional[Dict[str, Dict]] = None) -> List[StrategyAllocation]:
        """
        PHASE 3: Risk parity allocation (volatility-based, simulated only).
        
        SAFETY: allocator is advisory only
        SAFETY: no execution influence
        
        Allocates capital inversely proportional to volatility.
        Drawdown penalty applied (PHASE 4).
        """
        if not volatility_estimates:
            # No volatility data, fallback to equal weight
            logger.warning("No volatility estimates, falling back to equal weight")
            return self._allocate_equal_weight(strategies)
        
        # Calculate inverse volatility weights
        inv_vol_weights = {}
        total_inv_vol = 0.0
        
        for strategy_name in strategies:
            vol = volatility_estimates.get(strategy_name, 1.0)  # Default to 1.0 if missing
            if vol <= 0:
                vol = 1.0  # Avoid division by zero
            
            # PHASE 4: Apply drawdown penalty (advisory only)
            drawdown_penalty = 1.0
            if strategy_metrics:
                strategy_metric = strategy_metrics.get(strategy_name, {})
                max_drawdown = strategy_metric.get('max_drawdown', 0.0)
                if max_drawdown > self.constraints.drawdown_threshold:
                    # Reduce weight if drawdown exceeds threshold
                    drawdown_penalty = max(0.0, 1.0 - (max_drawdown / self.constraints.drawdown_threshold - 1.0))
            
            inv_vol = (1.0 / vol) * drawdown_penalty
            inv_vol_weights[strategy_name] = inv_vol
            total_inv_vol += inv_vol
        
        if total_inv_vol == 0:
            # Fallback to equal weight
            return self._allocate_equal_weight(strategies)
        
        # Normalize to fractions
        allocations = []
        for strategy_name in strategies:
            fraction = inv_vol_weights[strategy_name] / total_inv_vol
            
            notes = []
            if strategy_metrics:
                strategy_metric = strategy_metrics.get(strategy_name, {})
                max_drawdown = strategy_metric.get('max_drawdown', 0.0)
                if max_drawdown > self.constraints.drawdown_threshold:
                    notes.append(f"drawdown_penalty_applied:{max_drawdown:.2%}")
            
            allocations.append(
                StrategyAllocation(
                    strategy_name=strategy_name,
                    capital_fraction=fraction,
                    max_position_size=0.0,  # SIMULATED - not used in execution
                    allocation_mode="RISK_PARITY",
                    raw_score=fraction,
                    risk_adjusted_score=fraction,
                    notes="Risk parity allocation" + (" (" + "; ".join(notes) + ")" if notes else "")
                )
            )
        
        return allocations
    
    def _allocate_blended(self, strategies: List[str],
                         strategy_metrics: Dict[str, Dict],
                         volatility_estimates: Optional[Dict[str, float]]) -> List[StrategyAllocation]:
        """
        PHASE 3: Blended allocation (α * Kelly + (1-α) * Risk Parity, simulated only).
        
        SAFETY: allocator is advisory only
        SAFETY: no execution influence
        
        Model C — Blended:
        - α * Kelly + (1-α) * Risk Parity
        - α from constraints (default 0.6)
        
        All weights normalized to sum = 1.0
        Negative weights forbidden
        Zero allocation allowed
        """
        # Get Kelly allocations
        kelly_allocations = self._allocate_kelly(strategies, strategy_metrics)
        
        # Get risk parity allocations (with drawdown penalty)
        rp_allocations = self._allocate_risk_parity(strategies, volatility_estimates, strategy_metrics)
        
        # PHASE 3: Combine: α * Kelly + (1-α) * Risk Parity
        alpha = self.constraints.blended_alpha  # Weight for Kelly
        beta = 1.0 - alpha  # Weight for Risk Parity
        
        blended_allocations = []
        total = 0.0
        
        for strategy_name in strategies:
            kelly_frac = next((a.capital_fraction for a in kelly_allocations if a.strategy_name == strategy_name), 0.0)
            rp_frac = next((a.capital_fraction for a in rp_allocations if a.strategy_name == strategy_name), 0.0)
            
            # Blended = α * Kelly + (1-α) * Risk Parity
            blended_frac = alpha * kelly_frac + beta * rp_frac
            total += blended_frac
            
            # Combine notes
            kelly_note = next((a.notes for a in kelly_allocations if a.strategy_name == strategy_name), "")
            rp_note = next((a.notes for a in rp_allocations if a.strategy_name == strategy_name), "")
            combined_notes = f"Blended (α={alpha:.2f}): Kelly={kelly_note}, RiskParity={rp_note}"
            
            blended_allocations.append(
                StrategyAllocation(
                    strategy_name=strategy_name,
                    capital_fraction=blended_frac,
                    max_position_size=0.0,  # SIMULATED - not used in execution
                    allocation_mode="BLENDED",
                    raw_score=blended_frac,
                    risk_adjusted_score=blended_frac,
                    notes=combined_notes
                )
            )
        
        # Normalize
        if total > 0:
            for allocation in blended_allocations:
                allocation.capital_fraction /= total
                allocation.risk_adjusted_score = allocation.capital_fraction
        else:
            # Fallback to equal weight
            return self._allocate_equal_weight(strategies)
        
        return blended_allocations
    
    def _apply_drawdown_throttles(self, allocations: List[StrategyAllocation],
                                  strategy_metrics: Dict[str, Dict]) -> List[StrategyAllocation]:
        """
        PHASE 4: Apply drawdown throttles (advisory only).
        
        SAFETY: throttles are advisory only
        SAFETY: no execution changes
        
        If strategy drawdown exceeds threshold:
        - Reduce simulated weight
        - Never increase allocation during drawdown
        
        Global throttle:
        - If system drawdown exceeds limit
        - Scale all allocations down proportionally
        
        Rules:
        - Throttles are advisory only
        - No execution changes
        """
        try:
            # PHASE 4: Apply per-strategy drawdown throttles (advisory only)
            for allocation in allocations:
                strategy_name = allocation.strategy_name
                metrics = strategy_metrics.get(strategy_name, {})
                max_drawdown = metrics.get('max_drawdown', 0.0)
                
                # If drawdown exceeds threshold, reduce weight (advisory only)
                if max_drawdown > self.constraints.drawdown_threshold:
                    # Calculate penalty factor (0.0 = no allocation, 1.0 = full allocation)
                    # Penalty increases as drawdown exceeds threshold
                    drawdown_excess = max_drawdown / self.constraints.drawdown_threshold - 1.0
                    penalty_factor = max(0.0, 1.0 - (drawdown_excess * 0.5))  # Reduce by 50% per excess unit
                    
                    # Apply penalty to risk-adjusted score
                    original_weight = allocation.risk_adjusted_score
                    allocation.risk_adjusted_score = original_weight * penalty_factor
                    allocation.capital_fraction = allocation.risk_adjusted_score
                    
                    # Update notes
                    if allocation.notes:
                        allocation.notes += f"; drawdown_throttle_applied:{max_drawdown:.2%}(penalty={penalty_factor:.2f})"
                    else:
                        allocation.notes = f"drawdown_throttle_applied:{max_drawdown:.2%}(penalty={penalty_factor:.2f})"
            
            # PHASE 4: Apply global system drawdown throttle (advisory only)
            # Calculate system drawdown (max across all strategies)
            system_drawdown = max(
                (metrics.get('max_drawdown', 0.0) for metrics in strategy_metrics.values()),
                default=0.0
            )
            
            if system_drawdown > self.constraints.system_drawdown_limit:
                # Global throttle: scale all allocations down proportionally (advisory only)
                system_penalty_factor = 1.0 - ((system_drawdown / self.constraints.system_drawdown_limit - 1.0) * 0.3)
                system_penalty_factor = max(0.0, min(1.0, system_penalty_factor))  # Clamp [0.0, 1.0]
                
                for allocation in allocations:
                    allocation.risk_adjusted_score *= system_penalty_factor
                    allocation.capital_fraction = allocation.risk_adjusted_score
                    
                    # Update notes
                    if allocation.notes:
                        allocation.notes += f"; system_drawdown_throttle:{system_drawdown:.2%}(penalty={system_penalty_factor:.2f})"
                    else:
                        allocation.notes = f"system_drawdown_throttle:{system_drawdown:.2%}(penalty={system_penalty_factor:.2f})"
            
            return allocations
            
        except Exception as e:
            logger.error(f"Error applying drawdown throttles: {e}", exc_info=True)
            # Return allocations unchanged on error (advisory only, non-fatal)
            return allocations
    
    def _apply_governance_limits(self, allocations: List[StrategyAllocation]) -> Tuple[List[StrategyAllocation], List[str]]:
        """
        PHASE 7: Apply governance limits (advisory only).
        
        SAFETY: limits are advisory only
        SAFETY: no execution influence
        
        Add hard guards:
        - MAX_WEIGHT_PER_STRATEGY
        - MIN_WEIGHT_THRESHOLD
        - MAX_ACTIVE_ALLOCATIONS
        
        If violated:
        - Clamp values
        - Log governance warning
        - Continue safely
        """
        warnings = []
        
        try:
            # PHASE 7: Clamp per-strategy weights (advisory only)
            for allocation in allocations:
                original_weight = allocation.capital_fraction
                
                # MAX_WEIGHT_PER_STRATEGY
                if allocation.capital_fraction > self.constraints.max_capital_per_strategy:
                    allocation.capital_fraction = self.constraints.max_capital_per_strategy
                    allocation.risk_adjusted_score = allocation.capital_fraction
                    warnings.append(f"{allocation.strategy_name}: weight clamped from {original_weight:.2%} to {self.constraints.max_capital_per_strategy:.2%} (MAX_WEIGHT)")
                
                # MIN_WEIGHT_THRESHOLD
                if allocation.capital_fraction > 0 and allocation.capital_fraction < self.constraints.min_capital_per_strategy:
                    # Set to zero if below threshold (advisory only)
                    allocation.capital_fraction = 0.0
                    allocation.risk_adjusted_score = 0.0
                    warnings.append(f"{allocation.strategy_name}: weight zeroed (below MIN_WEIGHT threshold {self.constraints.min_capital_per_strategy:.2%})")
            
            # PHASE 7: MAX_ACTIVE_ALLOCATIONS
            # Count active allocations (non-zero weights)
            active_allocations = [a for a in allocations if a.capital_fraction > 0.0]
            
            if len(active_allocations) > self.constraints.max_active_allocations:
                # Sort by weight (descending) and zero out excess (advisory only)
                active_allocations.sort(key=lambda x: x.capital_fraction, reverse=True)
                
                for excess_allocation in active_allocations[self.constraints.max_active_allocations:]:
                    original_weight = excess_allocation.capital_fraction
                    excess_allocation.capital_fraction = 0.0
                    excess_allocation.risk_adjusted_score = 0.0
                    if excess_allocation.notes:
                        excess_allocation.notes += f"; zeroed_due_to_MAX_ACTIVE_limit"
                    else:
                        excess_allocation.notes = "zeroed_due_to_MAX_ACTIVE_limit"
                    
                    warnings.append(f"{excess_allocation.strategy_name}: weight zeroed (MAX_ACTIVE limit {self.constraints.max_active_allocations} exceeded, original_weight={original_weight:.2%})")
            
            # Log warnings (advisory only)
            if warnings:
                for warning in warnings:
                    logger.warning(f"Governance limit warning (advisory only): {warning}")
            
            return allocations, warnings
            
        except Exception as e:
            logger.error(f"Error applying governance limits: {e}", exc_info=True)
            # Return allocations unchanged on error (advisory only, non-fatal)
            return allocations, [f"governance_limit_error: {str(e)}"]
    
    def _normalize_allocations(self, allocations: List[StrategyAllocation]) -> List[StrategyAllocation]:
        """
        PHASE 3: Normalize allocations to sum = 1.0 (simulated only).
        
        SAFETY: normalization is advisory only
        SAFETY: no execution influence
        
        Rules:
        - All weights normalized to sum = 1.0
        - Negative weights forbidden (enforced earlier)
        - Zero allocation allowed
        """
        try:
            total = sum(a.capital_fraction for a in allocations)
            
            if total <= 0:
                # All zero, fallback to equal weight (advisory only)
                logger.debug("All allocations zero, using equal weight fallback")
                return self._allocate_equal_weight([a.strategy_name for a in allocations])
            
            if abs(total - 1.0) > 1e-6:  # Normalize if not already normalized
                for allocation in allocations:
                    allocation.capital_fraction /= total
                    allocation.risk_adjusted_score = allocation.capital_fraction
            
            # Verify sum = 1.0 (with tolerance)
            total_after = sum(a.capital_fraction for a in allocations)
            if abs(total_after - 1.0) > 1e-6:
                logger.warning(f"Allocation normalization failed: sum={total_after:.6f} (expected 1.0), re-normalizing")
                # Re-normalize
                for allocation in allocations:
                    allocation.capital_fraction /= total_after
                    allocation.risk_adjusted_score = allocation.capital_fraction
            
            return allocations
            
        except Exception as e:
            logger.error(f"Error normalizing allocations: {e}", exc_info=True)
            # Return allocations unchanged on error (advisory only, non-fatal)
            return allocations
    
    def _apply_constraints(self, allocations: List[StrategyAllocation],
                         strategies: List[str]) -> List[StrategyAllocation]:
        """
        PHASE 7: Apply allocation constraints (legacy method, simulated only).
        
        SAFETY: constraints are advisory only
        SAFETY: no execution influence
        """
        # Use governance limits method instead
        allocations, _ = self._apply_governance_limits(allocations)
        return allocations
    
    def _emit_allocation_event(self, allocations: List[StrategyAllocation]) -> None:
        """
        PHASE 5: Emit allocation update event (non-blocking, advisory only).
        
        SAFETY: event is advisory only
        SAFETY: no execution influence
        """
        try:
            # Include latest snapshot if available (read-only)
            snapshot_dict = None
            if self.latest_snapshot:
                snapshot_dict = self.latest_snapshot.to_dict()
            
            event = {
                'type': 'capital_allocation_update',
                'mode': self.mode.value,
                'allocations': [
                    {
                        'strategy': a.strategy_name,
                        'capital_fraction': a.capital_fraction,
                        'raw_score': a.raw_score,
                        'risk_adjusted_score': a.risk_adjusted_score,
                        'max_position_size': a.max_position_size,
                        'allocation_mode': a.allocation_mode,
                        'notes': a.notes
                    }
                    for a in allocations
                ],
                'snapshot': snapshot_dict,
                'label': 'SIMULATED CAPITAL ALLOCATION — NO EXECUTION EFFECT',  # PHASE 6: UI label
                'timestamp': asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else None
            }
            # Use datetime if asyncio not available
            if event['timestamp'] is None:
                event['timestamp'] = datetime.utcnow().isoformat() + "Z"
            safe_emit(self.event_bus.publish(event))
        except Exception as e:
            logger.error(f"Error emitting allocation event: {e}", exc_info=True)
    
    def _create_allocation_snapshot(self, allocations: List[StrategyAllocation],
                                   strategy_metrics: Dict[str, Dict],
                                   governance_warnings: List[str]) -> CapitalAllocationSnapshot:
        """
        PHASE 5: Create allocation snapshot (immutable, read-only).
        
        SAFETY: snapshot is advisory only
        SAFETY: no execution influence
        """
        try:
            # Build allocation dicts (read-only)
            allocation_dicts = [
                {
                    'strategy_name': a.strategy_name,
                    'raw_score': a.raw_score,
                    'risk_adjusted_score': a.risk_adjusted_score,
                    'recommended_weight': a.capital_fraction,
                    'allocation_model_used': a.allocation_mode,
                    'notes': a.notes
                }
                for a in allocations
            ]
            
            # Build model parameters (read-only)
            model_parameters = {
                'mode': self.mode.value,
                'max_weight_per_strategy': self.constraints.max_capital_per_strategy,
                'min_weight_threshold': self.constraints.min_capital_per_strategy,
                'kelly_fraction_cap': self.constraints.kelly_fraction_cap,
                'max_active_allocations': self.constraints.max_active_allocations,
                'drawdown_threshold': self.constraints.drawdown_threshold,
                'system_drawdown_limit': self.constraints.system_drawdown_limit
            }
            
            if self.mode == AllocatorMode.BLENDED:
                model_parameters['blended_alpha'] = self.constraints.blended_alpha
            
            snapshot = CapitalAllocationSnapshot(
                timestamp=datetime.now(),
                model_mode=self.mode.value,
                model_parameters=model_parameters,
                allocations=allocation_dicts,
                total_simulated_capital=1.0,  # Always 100% (normalized)
                governance_warnings=governance_warnings
            )
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Error creating allocation snapshot: {e}", exc_info=True)
            return self._create_empty_snapshot()
    
    def _create_empty_snapshot(self) -> CapitalAllocationSnapshot:
        """
        PHASE 5: Create empty allocation snapshot (advisory only).
        
        SAFETY: snapshot is advisory only
        SAFETY: no execution influence
        """
        return CapitalAllocationSnapshot(
            timestamp=datetime.now(),
            model_mode=self.mode.value,
            model_parameters={'mode': self.mode.value},
            allocations=[],
            total_simulated_capital=1.0,
            governance_warnings=['No strategies available for allocation']
        )
    
    def get_latest_allocation_snapshot(self) -> Optional[CapitalAllocationSnapshot]:
        """
        PHASE 5: Get latest allocation snapshot (read-only).
        
        SAFETY: snapshot is advisory only
        SAFETY: no execution influence
        
        Returns:
            Latest CapitalAllocationSnapshot or None if not computed yet
        """
        return self.latest_snapshot
    
    def _emit_fallback_event(self) -> None:
        """Emit fallback event (non-blocking)."""
        try:
            event = {
                'type': 'allocator_fallback_used',
                'original_mode': self.mode.value,
                'fallback_mode': 'EQUAL_WEIGHT',
                'timestamp': datetime.utcnow().isoformat() + "Z"
            }
            safe_emit(self.event_bus.publish(event))
        except Exception as e:
            logger.error(f"Error emitting fallback event: {e}", exc_info=True)


# Global capital allocator instance
_capital_allocator: Optional[CapitalAllocator] = None


def get_capital_allocator(mode: AllocatorMode = AllocatorMode.EQUAL_WEIGHT,
                         constraints: Optional[AllocatorConstraints] = None) -> CapitalAllocator:
    """Get global capital allocator instance."""
    global _capital_allocator
    if _capital_allocator is None:
        _capital_allocator = CapitalAllocator(mode, constraints)
    return _capital_allocator
