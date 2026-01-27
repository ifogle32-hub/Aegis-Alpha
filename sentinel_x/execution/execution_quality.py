"""
PHASE 1-4: ExecutionQuality Module (Core Design)

Standalone, read-only analytics layer for execution quality measurement.

SAFETY: execution quality is observational only
SAFETY: no execution timing modified
SAFETY: no broker logic modified
SAFETY: no LIVE enablement
REGRESSION LOCK — NO EXECUTION CONTROL

ExecutionQuality MUST NOT:
- Modify orders
- Delay execution
- Influence broker calls
- Trigger retries or cancels
- Block execution path
- Access broker internals directly

Responsibilities:
- Measure execution behavior
- Score fill quality
- Attribute execution performance to strategies
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
from collections import deque
from threading import Lock

from sentinel_x.monitoring.logger import logger
from sentinel_x.execution.models import ExecutionRecord, ExecutionStatus
from sentinel_x.execution.order_intent import OrderIntent


# PHASE 2: Order lifecycle events (passive tracing)
class OrderLifecycleEvent(Enum):
    """Order lifecycle event types for passive tracing."""
    ORDER_INTENT_CREATED = "ORDER_INTENT_CREATED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    ORDER_PARTIAL_FILL = "ORDER_PARTIAL_FILL"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


@dataclass
class OrderLifecycleTrace:
    """
    PHASE 2: Order lifecycle trace record (passive, write-only).
    
    Captured fields:
    - order_id: Order identifier
    - strategy_id: Strategy identifier
    - symbol: Trading symbol
    - side: Order side (BUY/SELL)
    - quantity: Order quantity
    - timestamp_monotonic: Monotonic timestamp (for latency calculation)
    - timestamp_wall: Wall clock timestamp
    - broker_status: Broker status (if available)
    - event_type: Lifecycle event type
    """
    order_id: str  # intent_id or client_order_id
    strategy_id: str
    symbol: str
    side: str
    quantity: float
    timestamp_monotonic: float  # For latency calculation (monotonic clock)
    timestamp_wall: datetime  # For logging/audit (wall clock)
    broker_status: Optional[str] = None
    event_type: OrderLifecycleEvent = OrderLifecycleEvent.ORDER_INTENT_CREATED
    limit_price: Optional[float] = None
    reference_price: Optional[float] = None  # Reference price for slippage calculation


@dataclass
class ExecutionQualityMetrics:
    """
    PHASE 3: Execution metrics per order (passive, computed asynchronously).
    
    Metrics computed:
    - submit_to_ack_latency_ms: Latency from submit to ack (if available)
    - ack_to_fill_latency_ms: Latency from ack to fill
    - total_fill_latency_ms: Total latency from submit to fill
    - slippage_vs_reference_bps: Slippage vs reference price (basis points)
    - partial_fill_ratio: Ratio of partial fills
    - rejection_rate: Rate of rejections
    """
    order_id: str
    strategy_id: str
    symbol: str
    
    # Latency metrics (milliseconds)
    submit_to_ack_latency_ms: Optional[float] = None
    ack_to_fill_latency_ms: Optional[float] = None
    total_fill_latency_ms: Optional[float] = None
    
    # Slippage metrics (basis points)
    slippage_vs_reference_bps: float = 0.0
    
    # Fill metrics
    partial_fill_ratio: float = 0.0  # 0.0 = no partial fills, 1.0 = all partial
    rejection_rate: float = 0.0  # 0.0 = no rejections, 1.0 = all rejected
    
    # Timestamps
    submitted_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    
    # Reference price (for slippage calculation)
    reference_price: Optional[float] = None
    fill_price: Optional[float] = None
    
    # Aggregation window
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


@dataclass
class ExecutionQualityScore:
    """
    PHASE 4: Execution quality score (deterministic, normalized to [0, 1]).
    
    Components:
    - latency_penalty: Penalty for high latency (0.0 = no penalty, 1.0 = max penalty)
    - slippage_penalty: Penalty for high slippage (0.0 = no penalty, 1.0 = max penalty)
    - partial_fill_penalty: Penalty for partial fills (0.0 = no penalty, 1.0 = max penalty)
    - rejection_penalty: Penalty for rejections (0.0 = no penalty, 1.0 = max penalty)
    
    Score normalized to [0, 1] where:
    - 1.0 = perfect execution
    - 0.5 = acceptable execution
    - 0.0 = poor execution
    
    SAFETY: Score is ADVISORY only
    SAFETY: No hard cutoffs yet
    SAFETY: Deterministic & explainable
    """
    strategy_id: str
    symbol: Optional[str] = None
    score: float = 0.5  # Default: neutral score
    latency_penalty: float = 0.0
    slippage_penalty: float = 0.0
    partial_fill_penalty: float = 0.0
    rejection_penalty: float = 0.0
    calculated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Component scores (for explainability)
    latency_score: float = 1.0
    slippage_score: float = 1.0
    fill_score: float = 1.0
    rejection_score: float = 1.0


class ExecutionQuality:
    """
    PHASE 1: ExecutionQuality - Standalone, read-only analytics layer.
    
    SAFETY: execution quality is observational only
    REGRESSION LOCK — NO EXECUTION CONTROL
    
    ExecutionQuality MUST NOT:
    - Modify orders
    - Delay execution
    - Influence broker calls
    - Trigger retries or cancels
    - Block execution path
    
    Responsibilities:
    - Measure execution behavior (passive)
    - Score fill quality (post-hoc)
    - Attribute execution performance to strategies (read-only)
    """
    
    # PHASE 3: Hard limits (governance)
    MAX_TRACES_PER_STRATEGY = 10000  # Max traces to keep in memory
    MAX_AGGREGATION_WINDOW_HOURS = 168  # Max 7 days
    
    def __init__(self):
        """Initialize ExecutionQuality (read-only, passive)."""
        self._lock = Lock()
        
        # PHASE 2: Order lifecycle tracing (passive, append-only)
        self._order_traces: Dict[str, List[OrderLifecycleTrace]] = {}  # order_id -> [traces]
        self._strategy_traces: Dict[str, List[str]] = {}  # strategy_id -> [order_ids]
        self._max_traces_per_order = 20  # Max traces per order (lifecycle events)
        
        # PHASE 3: Execution metrics (computed asynchronously)
        self._execution_metrics: Dict[str, ExecutionQualityMetrics] = {}  # order_id -> metrics
        
        # PHASE 4: Quality scores (per strategy, per symbol)
        self._quality_scores: Dict[str, Dict[str, ExecutionQualityScore]] = {}  # strategy_id -> {symbol: score}
        
        # Aggregation windows
        self._aggregation_window_hours = 24  # Default: 24 hours
        
        logger.info("ExecutionQuality initialized (read-only, passive)")
    
    # PHASE 2: Order lifecycle tracing (passive, write-only)
    
    def trace_intent_created(self, intent: OrderIntent) -> None:
        """
        PHASE 2: Trace order intent creation (passive, non-blocking).
        
        SAFETY: No execution timing modified
        SAFETY: Write-only (append/emit)
        
        Args:
            intent: OrderIntent (immutable)
        """
        try:
            trace = OrderLifecycleTrace(
                order_id=intent.intent_id,
                strategy_id=intent.strategy,
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.qty,
                timestamp_monotonic=time.monotonic(),
                timestamp_wall=datetime.utcnow(),
                event_type=OrderLifecycleEvent.ORDER_INTENT_CREATED,
                limit_price=intent.limit_price,
                reference_price=intent.limit_price if intent.limit_price else None
            )
            
            with self._lock:
                if intent.intent_id not in self._order_traces:
                    self._order_traces[intent.intent_id] = []
                
                traces = self._order_traces[intent.intent_id]
                if len(traces) < self._max_traces_per_order:
                    traces.append(trace)
                
                # Track by strategy
                if intent.strategy not in self._strategy_traces:
                    self._strategy_traces[intent.strategy] = []
                
                strategy_orders = self._strategy_traces[intent.strategy]
                if intent.intent_id not in strategy_orders:
                    strategy_orders.append(intent.intent_id)
                    # Trim old orders if needed
                    if len(strategy_orders) > self.MAX_TRACES_PER_STRATEGY:
                        strategy_orders.pop(0)
        
        except Exception as e:
            # SAFETY: Trace failures must never affect execution
            logger.debug(f"Error tracing intent creation (non-fatal): {e}")
    
    def trace_order_submitted(self, order_id: str, intent: OrderIntent, 
                             broker_status: Optional[str] = None) -> None:
        """
        PHASE 2: Trace order submission (passive, non-blocking).
        
        SAFETY: No execution timing modified
        SAFETY: Write-only (append/emit)
        
        Args:
            order_id: Order identifier (intent_id or client_order_id)
            intent: OrderIntent
            broker_status: Optional broker status
        """
        try:
            trace = OrderLifecycleTrace(
                order_id=order_id,
                strategy_id=intent.strategy,
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.qty,
                timestamp_monotonic=time.monotonic(),
                timestamp_wall=datetime.utcnow(),
                broker_status=broker_status,
                event_type=OrderLifecycleEvent.ORDER_SUBMITTED,
                limit_price=intent.limit_price,
                reference_price=intent.limit_price if intent.limit_price else None
            )
            
            with self._lock:
                if order_id not in self._order_traces:
                    self._order_traces[order_id] = []
                
                traces = self._order_traces[order_id]
                if len(traces) < self._max_traces_per_order:
                    traces.append(trace)
        
        except Exception as e:
            logger.debug(f"Error tracing order submission (non-fatal): {e}")
    
    def trace_order_acknowledged(self, order_id: str, strategy_id: str, 
                                symbol: str, broker_status: Optional[str] = None) -> None:
        """
        PHASE 2: Trace order acknowledgment (passive, non-blocking).
        
        SAFETY: No execution timing modified
        SAFETY: Write-only (append/emit)
        """
        try:
            trace = OrderLifecycleTrace(
                order_id=order_id,
                strategy_id=strategy_id,
                symbol=symbol,
                side="",  # May not be available at ack time
                quantity=0.0,  # May not be available at ack time
                timestamp_monotonic=time.monotonic(),
                timestamp_wall=datetime.utcnow(),
                broker_status=broker_status,
                event_type=OrderLifecycleEvent.ORDER_ACKNOWLEDGED
            )
            
            with self._lock:
                if order_id not in self._order_traces:
                    self._order_traces[order_id] = []
                
                traces = self._order_traces[order_id]
                if len(traces) < self._max_traces_per_order:
                    traces.append(trace)
        
        except Exception as e:
            logger.debug(f"Error tracing order acknowledgment (non-fatal): {e}")
    
    def trace_order_filled(self, execution_record: ExecutionRecord, 
                          strategy_id: str, fill_price: Optional[float] = None) -> None:
        """
        PHASE 2: Trace order fill (passive, non-blocking).
        
        SAFETY: No execution timing modified
        SAFETY: Write-only (append/emit)
        
        Args:
            execution_record: ExecutionRecord
            strategy_id: Strategy identifier
            fill_price: Optional fill price (if not in execution_record)
        """
        try:
            fill_price = fill_price or execution_record.avg_fill_price
            
            trace = OrderLifecycleTrace(
                order_id=execution_record.intent_id,
                strategy_id=strategy_id,
                symbol="",  # May not be in execution_record
                side="",  # May not be in execution_record
                quantity=execution_record.filled_qty,
                timestamp_monotonic=time.monotonic(),
                timestamp_wall=datetime.utcnow(),
                event_type=OrderLifecycleEvent.ORDER_FILLED if execution_record.status == ExecutionStatus.FILLED 
                         else OrderLifecycleEvent.ORDER_PARTIAL_FILL,
                reference_price=fill_price  # Store fill price as reference
            )
            
            with self._lock:
                order_id = execution_record.intent_id
                if order_id not in self._order_traces:
                    self._order_traces[order_id] = []
                
                traces = self._order_traces[order_id]
                if len(traces) < self._max_traces_per_order:
                    traces.append(trace)
                
                # PHASE 3: Trigger metrics computation (asynchronous, non-blocking)
                self._compute_metrics_for_order(order_id, execution_record, strategy_id, fill_price)
        
        except Exception as e:
            logger.debug(f"Error tracing order fill (non-fatal): {e}")
    
    def trace_order_rejected(self, order_id: str, strategy_id: str, 
                            reason: Optional[str] = None) -> None:
        """
        PHASE 2: Trace order rejection (passive, non-blocking).
        
        SAFETY: No execution timing modified
        SAFETY: Write-only (append/emit)
        """
        try:
            trace = OrderLifecycleTrace(
                order_id=order_id,
                strategy_id=strategy_id,
                symbol="",
                side="",
                quantity=0.0,
                timestamp_monotonic=time.monotonic(),
                timestamp_wall=datetime.utcnow(),
                broker_status=reason,
                event_type=OrderLifecycleEvent.ORDER_REJECTED
            )
            
            with self._lock:
                if order_id not in self._order_traces:
                    self._order_traces[order_id] = []
                
                traces = self._order_traces[order_id]
                if len(traces) < self._max_traces_per_order:
                    traces.append(trace)
        
        except Exception as e:
            logger.debug(f"Error tracing order rejection (non-fatal): {e}")
    
    # PHASE 3: Execution metrics (passive, computed asynchronously)
    
    def _compute_metrics_for_order(self, order_id: str, execution_record: ExecutionRecord,
                                   strategy_id: str, fill_price: Optional[float] = None) -> None:
        """
        PHASE 3: Compute execution metrics for an order (asynchronous, non-blocking).
        
        SAFETY: Metrics computed asynchronously or post-hoc
        SAFETY: Missing data handled safely
        SAFETY: Never blocks execution
        
        Args:
            order_id: Order identifier
            execution_record: ExecutionRecord
            strategy_id: Strategy identifier
            fill_price: Optional fill price
        """
        try:
            # Get traces for this order
            traces = self._order_traces.get(order_id, [])
            if not traces:
                return
            
            # Find key events
            submitted_trace = None
            ack_trace = None
            filled_trace = None
            intent_trace = None
            
            for trace in traces:
                if trace.event_type == OrderLifecycleEvent.ORDER_SUBMITTED:
                    submitted_trace = trace
                elif trace.event_type == OrderLifecycleEvent.ORDER_ACKNOWLEDGED:
                    ack_trace = trace
                elif trace.event_type in (OrderLifecycleEvent.ORDER_FILLED, OrderLifecycleEvent.ORDER_PARTIAL_FILL):
                    filled_trace = trace
                elif trace.event_type == OrderLifecycleEvent.ORDER_INTENT_CREATED:
                    intent_trace = trace
            
            # Compute latencies (milliseconds)
            submit_to_ack_latency_ms = None
            ack_to_fill_latency_ms = None
            total_fill_latency_ms = None
            
            if submitted_trace and ack_trace:
                submit_to_ack_latency_ms = (ack_trace.timestamp_monotonic - submitted_trace.timestamp_monotonic) * 1000.0
            
            if ack_trace and filled_trace:
                ack_to_fill_latency_ms = (filled_trace.timestamp_monotonic - ack_trace.timestamp_monotonic) * 1000.0
            
            if submitted_trace and filled_trace:
                total_fill_latency_ms = (filled_trace.timestamp_monotonic - submitted_trace.timestamp_monotonic) * 1000.0
            
            # Compute slippage (basis points)
            slippage_vs_reference_bps = 0.0
            reference_price = intent_trace.reference_price if intent_trace else None
            fill_price_actual = fill_price or execution_record.avg_fill_price
            
            if reference_price and fill_price_actual and reference_price > 0:
                slippage_vs_reference_bps = ((fill_price_actual - reference_price) / reference_price) * 10000.0
            
            # Compute fill metrics
            partial_fill_ratio = 1.0 if execution_record.status == ExecutionStatus.PARTIALLY_FILLED else 0.0
            rejection_rate = 1.0 if execution_record.status == ExecutionStatus.REJECTED else 0.0
            
            # Create metrics
            metrics = ExecutionQualityMetrics(
                order_id=order_id,
                strategy_id=strategy_id,
                symbol=intent_trace.symbol if intent_trace else "",
                submit_to_ack_latency_ms=submit_to_ack_latency_ms,
                ack_to_fill_latency_ms=ack_to_fill_latency_ms,
                total_fill_latency_ms=total_fill_latency_ms,
                slippage_vs_reference_bps=slippage_vs_reference_bps,
                partial_fill_ratio=partial_fill_ratio,
                rejection_rate=rejection_rate,
                submitted_at=submitted_trace.timestamp_wall if submitted_trace else None,
                acknowledged_at=ack_trace.timestamp_wall if ack_trace else None,
                filled_at=filled_trace.timestamp_wall if filled_trace else None,
                reference_price=reference_price,
                fill_price=fill_price_actual,
                window_start=datetime.utcnow() - timedelta(hours=self._aggregation_window_hours),
                window_end=datetime.utcnow()
            )
            
            with self._lock:
                self._execution_metrics[order_id] = metrics
        
        except Exception as e:
            logger.debug(f"Error computing metrics for order {order_id} (non-fatal): {e}")
    
    def get_metrics_for_order(self, order_id: str) -> Optional[ExecutionQualityMetrics]:
        """Get execution metrics for a specific order."""
        with self._lock:
            return self._execution_metrics.get(order_id)
    
    def get_aggregated_metrics(self, strategy_id: str, symbol: Optional[str] = None,
                               window_hours: Optional[int] = None) -> ExecutionQualityMetrics:
        """
        PHASE 3: Get aggregated execution metrics for a strategy (post-hoc).
        
        SAFETY: Metrics computed asynchronously or post-hoc
        SAFETY: Missing data handled safely
        SAFETY: Never blocks execution
        
        Args:
            strategy_id: Strategy identifier
            symbol: Optional symbol filter
            window_hours: Optional aggregation window (default: 24 hours)
            
        Returns:
            Aggregated ExecutionQualityMetrics
        """
        try:
            window_hours = window_hours or self._aggregation_window_hours
            window_start = datetime.utcnow() - timedelta(hours=window_hours)
            window_end = datetime.utcnow()
            
            # Get all order IDs for this strategy
            order_ids = self._strategy_traces.get(strategy_id, [])
            
            # Filter metrics by window and symbol
            relevant_metrics = []
            for order_id in order_ids:
                metrics = self._execution_metrics.get(order_id)
                if metrics:
                    if metrics.submitted_at and window_start <= metrics.submitted_at <= window_end:
                        if symbol is None or metrics.symbol == symbol:
                            relevant_metrics.append(metrics)
            
            if not relevant_metrics:
                # Return default metrics (neutral)
                return ExecutionQualityMetrics(
                    order_id="",
                    strategy_id=strategy_id,
                    symbol=symbol or "",
                    window_start=window_start,
                    window_end=window_end
                )
            
            # Aggregate metrics
            total_orders = len(relevant_metrics)
            
            # Latency aggregation
            latencies_submit_ack = [m.submit_to_ack_latency_ms for m in relevant_metrics 
                                   if m.submit_to_ack_latency_ms is not None]
            latencies_ack_fill = [m.ack_to_fill_latency_ms for m in relevant_metrics 
                                 if m.ack_to_fill_latency_ms is not None]
            latencies_total = [m.total_fill_latency_ms for m in relevant_metrics 
                              if m.total_fill_latency_ms is not None]
            
            avg_submit_ack = sum(latencies_submit_ack) / len(latencies_submit_ack) if latencies_submit_ack else None
            avg_ack_fill = sum(latencies_ack_fill) / len(latencies_ack_fill) if latencies_ack_fill else None
            avg_total = sum(latencies_total) / len(latencies_total) if latencies_total else None
            
            # Slippage aggregation (average)
            slippages = [m.slippage_vs_reference_bps for m in relevant_metrics 
                        if m.slippage_vs_reference_bps != 0.0]
            avg_slippage = sum(slippages) / len(slippages) if slippages else 0.0
            
            # Fill metrics aggregation
            partial_fill_ratio = sum(m.partial_fill_ratio for m in relevant_metrics) / total_orders
            rejection_rate = sum(m.rejection_rate for m in relevant_metrics) / total_orders
            
            # Create aggregated metrics
            return ExecutionQualityMetrics(
                order_id="",  # Aggregated (no single order)
                strategy_id=strategy_id,
                symbol=symbol or "",
                submit_to_ack_latency_ms=avg_submit_ack,
                ack_to_fill_latency_ms=avg_ack_fill,
                total_fill_latency_ms=avg_total,
                slippage_vs_reference_bps=avg_slippage,
                partial_fill_ratio=partial_fill_ratio,
                rejection_rate=rejection_rate,
                window_start=window_start,
                window_end=window_end
            )
        
        except Exception as e:
            logger.error(f"Error aggregating metrics for {strategy_id} (non-fatal): {e}", exc_info=True)
            return ExecutionQualityMetrics(
                order_id="",
                strategy_id=strategy_id,
                symbol=symbol or "",
                window_start=datetime.utcnow() - timedelta(hours=window_hours or 24),
                window_end=datetime.utcnow()
            )
    
    # PHASE 4: Execution quality scoring
    
    def calculate_quality_score(self, strategy_id: str, symbol: Optional[str] = None,
                               window_hours: Optional[int] = None) -> ExecutionQualityScore:
        """
        PHASE 4: Calculate execution quality score (deterministic, normalized to [0, 1]).
        
        SAFETY: Score is ADVISORY only
        SAFETY: No hard cutoffs yet
        SAFETY: Deterministic & explainable
        
        Components:
        - latency_penalty: Penalty for high latency
        - slippage_penalty: Penalty for high slippage
        - partial_fill_penalty: Penalty for partial fills
        - rejection_penalty: Penalty for rejections
        
        Score normalized to [0, 1] where:
        - 1.0 = perfect execution
        - 0.5 = acceptable execution
        - 0.0 = poor execution
        
        Args:
            strategy_id: Strategy identifier
            symbol: Optional symbol filter
            window_hours: Optional aggregation window
            
        Returns:
            ExecutionQualityScore (deterministic, explainable)
        """
        try:
            # Get aggregated metrics
            metrics = self.get_aggregated_metrics(strategy_id, symbol, window_hours)
            
            # PHASE 4: Calculate component penalties (deterministic)
            
            # Latency penalty (0.0 = no penalty, 1.0 = max penalty)
            # Target: < 100ms average, < 200ms max
            latency_penalty = 0.0
            latency_score = 1.0
            if metrics.total_fill_latency_ms is not None:
                if metrics.total_fill_latency_ms > 500.0:  # > 500ms = max penalty
                    latency_penalty = 1.0
                    latency_score = 0.0
                elif metrics.total_fill_latency_ms > 200.0:  # > 200ms = partial penalty
                    latency_penalty = (metrics.total_fill_latency_ms - 200.0) / 300.0  # Linear: 200-500ms
                    latency_score = 1.0 - latency_penalty
                else:  # <= 200ms = no penalty
                    latency_penalty = 0.0
                    latency_score = 1.0
            
            # Slippage penalty (0.0 = no penalty, 1.0 = max penalty)
            # Target: < 5 bps average
            slippage_penalty = 0.0
            slippage_score = 1.0
            abs_slippage = abs(metrics.slippage_vs_reference_bps)
            if abs_slippage > 50.0:  # > 50 bps = max penalty
                slippage_penalty = 1.0
                slippage_score = 0.0
            elif abs_slippage > 5.0:  # > 5 bps = partial penalty
                slippage_penalty = (abs_slippage - 5.0) / 45.0  # Linear: 5-50 bps
                slippage_score = 1.0 - slippage_penalty
            else:  # <= 5 bps = no penalty
                slippage_penalty = 0.0
                slippage_score = 1.0
            
            # Partial fill penalty (0.0 = no penalty, 1.0 = max penalty)
            # Target: < 0.05 partial fill ratio
            partial_fill_penalty = 0.0
            fill_score = 1.0
            if metrics.partial_fill_ratio > 0.2:  # > 20% = max penalty
                partial_fill_penalty = 1.0
                fill_score = 0.0
            elif metrics.partial_fill_ratio > 0.05:  # > 5% = partial penalty
                partial_fill_penalty = (metrics.partial_fill_ratio - 0.05) / 0.15  # Linear: 5-20%
                fill_score = 1.0 - partial_fill_penalty
            else:  # <= 5% = no penalty
                partial_fill_penalty = 0.0
                fill_score = 1.0
            
            # Rejection penalty (0.0 = no penalty, 1.0 = max penalty)
            # Target: < 0.05 rejection rate
            rejection_penalty = 0.0
            rejection_score = 1.0
            if metrics.rejection_rate > 0.2:  # > 20% = max penalty
                rejection_penalty = 1.0
                rejection_score = 0.0
            elif metrics.rejection_rate > 0.05:  # > 5% = partial penalty
                rejection_penalty = (metrics.rejection_rate - 0.05) / 0.15  # Linear: 5-20%
                rejection_score = 1.0 - rejection_penalty
            else:  # <= 5% = no penalty
                rejection_penalty = 0.0
                rejection_score = 1.0
            
            # Weighted composite score
            weights = {
                'latency': 0.25,
                'slippage': 0.30,
                'fill': 0.25,
                'rejection': 0.20
            }
            
            composite_score = (
                latency_score * weights['latency'] +
                slippage_score * weights['slippage'] +
                fill_score * weights['fill'] +
                rejection_score * weights['rejection']
            )
            
            # Clamp to [0, 1]
            composite_score = max(0.0, min(1.0, composite_score))
            
            # Create quality score
            quality_score = ExecutionQualityScore(
                strategy_id=strategy_id,
                symbol=symbol,
                score=composite_score,
                latency_penalty=latency_penalty,
                slippage_penalty=slippage_penalty,
                partial_fill_penalty=partial_fill_penalty,
                rejection_penalty=rejection_penalty,
                latency_score=latency_score,
                slippage_score=slippage_score,
                fill_score=fill_score,
                rejection_score=rejection_score,
                calculated_at=datetime.utcnow()
            )
            
            # Cache score
            with self._lock:
                if strategy_id not in self._quality_scores:
                    self._quality_scores[strategy_id] = {}
                self._quality_scores[strategy_id][symbol or "__ALL__"] = quality_score
            
            return quality_score
        
        except Exception as e:
            logger.error(f"Error calculating quality score for {strategy_id} (non-fatal): {e}", exc_info=True)
            return ExecutionQualityScore(
                strategy_id=strategy_id,
                symbol=symbol,
                score=0.5  # Neutral score on error
            )
    
    def get_quality_score(self, strategy_id: str, symbol: Optional[str] = None) -> ExecutionQualityScore:
        """Get cached quality score or calculate if not available."""
        with self._lock:
            if strategy_id in self._quality_scores:
                scores = self._quality_scores[strategy_id]
                cached = scores.get(symbol or "__ALL__")
                if cached:
                    return cached
        
        # Calculate if not cached
        return self.calculate_quality_score(strategy_id, symbol)


# Global ExecutionQuality instance
_execution_quality: Optional[ExecutionQuality] = None
_execution_quality_lock = Lock()


def get_execution_quality() -> ExecutionQuality:
    """
    Get global ExecutionQuality instance.
    
    SAFETY: ExecutionQuality is read-only
    SAFETY: No execution control
    """
    global _execution_quality
    if _execution_quality is None:
        with _execution_quality_lock:
            if _execution_quality is None:
                _execution_quality = ExecutionQuality()
    return _execution_quality
