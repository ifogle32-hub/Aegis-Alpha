"""
PHASE 2: Broker Health Model

Tracks per-broker:
- Latency
- Fill rate
- Slippage
- Error rate
- Availability

Health scores updated continuously.
"""
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from collections import deque
from sentinel_x.monitoring.logger import logger
from sentinel_x.execution.broker_base import BrokerHealthSnapshot


@dataclass
class BrokerHealthMetrics:
    """Per-broker health metrics."""
    broker: str
    latency_samples: deque = field(default_factory=lambda: deque(maxlen=100))
    fill_count: int = 0
    reject_count: int = 0
    slippage_samples: deque = field(default_factory=lambda: deque(maxlen=100))
    error_count: int = 0
    total_requests: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def latency_ms(self) -> float:
        """Average latency in milliseconds."""
        if not self.latency_samples:
            return 0.0
        return sum(self.latency_samples) / len(self.latency_samples)
    
    @property
    def fill_rate(self) -> float:
        """Fill rate (0.0 to 1.0)."""
        if self.total_requests == 0:
            return 1.0  # Default to perfect if no data
        return self.fill_count / self.total_requests
    
    @property
    def slippage_bps(self) -> float:
        """Average slippage in basis points."""
        if not self.slippage_samples:
            return 0.0
        return sum(self.slippage_samples) / len(self.slippage_samples)
    
    @property
    def error_rate(self) -> float:
        """Error rate (0.0 to 1.0)."""
        if self.total_requests == 0:
            return 0.0
        return self.error_count / self.total_requests
    
    @property
    def availability(self) -> float:
        """Availability score (0.0 to 1.0) based on recent failures."""
        if self.last_success is None:
            return 0.5  # Unknown - assume degraded
        if self.last_failure is None:
            return 1.0  # No failures
        
        # If last failure was recent (< 5 minutes), reduce availability
        time_since_failure = datetime.utcnow() - self.last_failure
        if time_since_failure < timedelta(minutes=5):
            return 0.5
        return 1.0
    
    @property
    def reliability_score(self) -> float:
        """
        Composite reliability score (0.0 to 1.0).
        
        Combines fill_rate, error_rate, and availability.
        """
        fill_weight = 0.4
        error_weight = 0.3
        avail_weight = 0.3
        
        score = (
            self.fill_rate * fill_weight +
            (1.0 - self.error_rate) * error_weight +
            self.availability * avail_weight
        )
        return max(0.0, min(1.0, score))
    
    def get_snapshot(self) -> BrokerHealthSnapshot:
        """Get current health snapshot."""
        return BrokerHealthSnapshot(
            broker=self.broker,
            latency_ms=self.latency_ms,
            fill_rate=self.fill_rate,
            slippage_bps=self.slippage_bps,
            error_rate=self.error_rate,
            availability=self.availability,
            reliability_score=self.reliability_score,
            last_updated=self.last_updated
        )


class BrokerHealthModel:
    """
    PHASE 2: Broker Health Model
    
    Tracks health metrics for all brokers and provides health snapshots
    for routing decisions.
    """
    
    def __init__(self):
        """Initialize broker health model."""
        self._metrics: Dict[str, BrokerHealthMetrics] = {}
        self._lock = threading.Lock()
        logger.info("BrokerHealthModel initialized")
    
    def record_latency(self, broker: str, latency_ms: float) -> None:
        """Record execution latency for a broker."""
        with self._lock:
            if broker not in self._metrics:
                self._metrics[broker] = BrokerHealthMetrics(broker=broker)
            self._metrics[broker].latency_samples.append(latency_ms)
            self._metrics[broker].last_updated = datetime.utcnow()
    
    def record_fill(self, broker: str, slippage_bps: float = 0.0) -> None:
        """Record a successful fill."""
        with self._lock:
            if broker not in self._metrics:
                self._metrics[broker] = BrokerHealthMetrics(broker=broker)
            metrics = self._metrics[broker]
            metrics.fill_count += 1
            metrics.total_requests += 1
            if slippage_bps != 0.0:
                metrics.slippage_samples.append(slippage_bps)
            metrics.last_success = datetime.utcnow()
            metrics.last_updated = datetime.utcnow()
    
    def record_rejection(self, broker: str) -> None:
        """Record an order rejection."""
        with self._lock:
            if broker not in self._metrics:
                self._metrics[broker] = BrokerHealthMetrics(broker=broker)
            metrics = self._metrics[broker]
            metrics.reject_count += 1
            metrics.total_requests += 1
            metrics.last_updated = datetime.utcnow()
    
    def record_error(self, broker: str) -> None:
        """Record an execution error."""
        with self._lock:
            if broker not in self._metrics:
                self._metrics[broker] = BrokerHealthMetrics(broker=broker)
            metrics = self._metrics[broker]
            metrics.error_count += 1
            metrics.total_requests += 1
            metrics.last_failure = datetime.utcnow()
            metrics.last_updated = datetime.utcnow()
    
    def get_health_snapshot(self, broker: str) -> BrokerHealthSnapshot:
        """
        Get health snapshot for a broker.
        
        Returns:
            BrokerHealthSnapshot with current metrics
        """
        with self._lock:
            if broker not in self._metrics:
                # Return default snapshot for unknown broker
                return BrokerHealthSnapshot(
                    broker=broker,
                    latency_ms=0.0,
                    fill_rate=1.0,
                    slippage_bps=0.0,
                    error_rate=0.0,
                    availability=1.0,
                    reliability_score=1.0
                )
            return self._metrics[broker].get_snapshot()
    
    def get_all_health_snapshots(self) -> Dict[str, BrokerHealthSnapshot]:
        """Get health snapshots for all known brokers."""
        with self._lock:
            return {
                broker: metrics.get_snapshot()
                for broker, metrics in self._metrics.items()
            }
    
    def score_broker(self, broker: str, intent_symbol: str, intent_qty: float) -> float:
        """
        PHASE 5: Score a broker for a given intent.
        
        Considers:
        - Latency (lower is better)
        - Fill rate (higher is better)
        - Slippage (lower is better)
        - Reliability (higher is better)
        - Fees (lower is better - if available)
        
        Returns:
            Score (higher is better) for routing decisions
        """
        snapshot = self.get_health_snapshot(broker)
        
        # Normalize latency (assume 100ms is "good", 1000ms is "bad")
        latency_score = max(0.0, 1.0 - (snapshot.latency_ms / 1000.0))
        
        # Fill rate is already 0-1
        fill_score = snapshot.fill_rate
        
        # Normalize slippage (assume 10bps is "good", 50bps is "bad")
        slippage_score = max(0.0, 1.0 - (abs(snapshot.slippage_bps) / 50.0))
        
        # Reliability is already 0-1
        reliability_score = snapshot.reliability_score
        
        # Weighted combination
        weights = {
            'latency': 0.25,
            'fill_rate': 0.25,
            'slippage': 0.25,
            'reliability': 0.25
        }
        
        score = (
            latency_score * weights['latency'] +
            fill_score * weights['fill_rate'] +
            slippage_score * weights['slippage'] +
            reliability_score * weights['reliability']
        )
        
        return max(0.0, min(1.0, score))


# Global broker health model instance
_broker_health_model: Optional[BrokerHealthModel] = None
_health_model_lock = threading.Lock()


def get_broker_health_model() -> BrokerHealthModel:
    """Get global broker health model instance."""
    global _broker_health_model
    if _broker_health_model is None:
        with _health_model_lock:
            if _broker_health_model is None:
                _broker_health_model = BrokerHealthModel()
    return _broker_health_model
