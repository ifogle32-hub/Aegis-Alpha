"""
PHASE 4 — MULTI-ASSET HARDENING

Extend Shadow Training to support:
- Equities
- Futures
- Crypto
- FX (spot)

Implement:
- Asset abstraction layer
- Contract specs (tick size, multiplier, fees)
- Currency normalization
- Cross-asset PnL aggregation
- Correlation tracking across assets

Risk controls per asset:
- Max exposure
- Volatility scaling
- Liquidity penalty
- Asset-specific slippage models
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import threading
import numpy as np

from sentinel_x.monitoring.logger import logger


class AssetType(str, Enum):
    """Asset types."""
    EQUITY = "EQUITY"
    FUTURE = "FUTURE"
    CRYPTO = "CRYPTO"
    FX = "FX"


@dataclass
class ContractSpec:
    """
    Contract specification for an asset.
    """
    symbol: str
    asset_type: AssetType
    tick_size: float  # Minimum price increment
    multiplier: float  # Contract multiplier (1.0 for equities, 50 for ES futures, etc.)
    currency: str  # Base currency (USD, EUR, etc.)
    fee_per_contract: float = 0.0  # Fee per contract/trade
    fee_percentage: float = 0.0  # Fee as percentage of notional
    min_trade_size: float = 1.0  # Minimum trade size
    max_trade_size: float = 1000000.0  # Maximum trade size
    
    def calculate_fee(self, notional: float, quantity: float) -> float:
        """
        Calculate trading fee.
        
        Args:
            notional: Trade notional value
            quantity: Trade quantity
            
        Returns:
            Total fee
        """
        contract_fee = self.fee_per_contract * abs(quantity)
        percentage_fee = notional * (self.fee_percentage / 100.0)
        return contract_fee + percentage_fee
    
    def normalize_price(self, price: float) -> float:
        """
        Normalize price to tick size.
        
        Args:
            price: Raw price
            
        Returns:
            Normalized price
        """
        if self.tick_size > 0:
            return round(price / self.tick_size) * self.tick_size
        return price
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "asset_type": self.asset_type.value,
            "tick_size": self.tick_size,
            "multiplier": self.multiplier,
            "currency": self.currency,
            "fee_per_contract": self.fee_per_contract,
            "fee_percentage": self.fee_percentage,
            "min_trade_size": self.min_trade_size,
            "max_trade_size": self.max_trade_size,
        }


@dataclass
class AssetRiskLimits:
    """
    Risk limits per asset.
    """
    symbol: str
    max_exposure: float  # Maximum position exposure
    volatility_scaling: float = 1.0  # Volatility scaling factor
    liquidity_penalty: float = 0.0  # Liquidity penalty (bps)
    slippage_multiplier: float = 1.0  # Asset-specific slippage multiplier
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "max_exposure": self.max_exposure,
            "volatility_scaling": self.volatility_scaling,
            "liquidity_penalty": self.liquidity_penalty,
            "slippage_multiplier": self.slippage_multiplier,
        }


class AssetRegistry:
    """
    Asset registry for multi-asset support.
    
    Manages contract specs, risk limits, and currency normalization.
    """
    
    def __init__(self):
        """Initialize asset registry."""
        self.contract_specs: Dict[str, ContractSpec] = {}
        self.risk_limits: Dict[str, AssetRiskLimits] = {}
        self.currency_rates: Dict[str, float] = {"USD": 1.0}  # Base currency
        self.correlation_matrix: Dict[Tuple[str, str], float] = {}
        
        self._lock = threading.RLock()
        
        logger.info("AssetRegistry initialized")
    
    def register_contract(self, spec: ContractSpec) -> None:
        """
        Register contract specification.
        
        Args:
            spec: ContractSpec instance
        """
        with self._lock:
            self.contract_specs[spec.symbol] = spec
            logger.info(f"Registered contract: {spec.symbol} ({spec.asset_type.value})")
    
    def register_risk_limits(self, limits: AssetRiskLimits) -> None:
        """
        Register risk limits for asset.
        
        Args:
            limits: AssetRiskLimits instance
        """
        with self._lock:
            self.risk_limits[limits.symbol] = limits
            logger.info(f"Registered risk limits: {limits.symbol}")
    
    def get_contract_spec(self, symbol: str) -> Optional[ContractSpec]:
        """
        Get contract specification.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            ContractSpec or None
        """
        with self._lock:
            return self.contract_specs.get(symbol)
    
    def get_risk_limits(self, symbol: str) -> Optional[AssetRiskLimits]:
        """
        Get risk limits for asset.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            AssetRiskLimits or None
        """
        with self._lock:
            return self.risk_limits.get(symbol)
    
    def normalize_currency(
        self,
        amount: float,
        from_currency: str,
        to_currency: str = "USD",
    ) -> float:
        """
        Normalize currency amount.
        
        Args:
            amount: Amount in from_currency
            from_currency: Source currency
            to_currency: Target currency (default: USD)
            
        Returns:
            Amount in to_currency
        """
        with self._lock:
            if from_currency == to_currency:
                return amount
            
            # Get exchange rates
            from_rate = self.currency_rates.get(from_currency, 1.0)
            to_rate = self.currency_rates.get(to_currency, 1.0)
            
            # Convert via USD
            usd_amount = amount / from_rate
            return usd_amount * to_rate
    
    def set_currency_rate(self, currency: str, rate_to_usd: float) -> None:
        """
        Set currency exchange rate.
        
        Args:
            currency: Currency code
            rate_to_usd: Rate to USD
        """
        with self._lock:
            self.currency_rates[currency] = rate_to_usd
            logger.debug(f"Set currency rate: {currency} = {rate_to_usd}")
    
    def update_correlation(self, symbol1: str, symbol2: str, correlation: float) -> None:
        """
        Update correlation between two assets.
        
        Args:
            symbol1: First symbol
            symbol2: Second symbol
            correlation: Correlation coefficient (-1 to 1)
        """
        with self._lock:
            key = (min(symbol1, symbol2), max(symbol1, symbol2))
            self.correlation_matrix[key] = correlation
    
    def get_correlation(self, symbol1: str, symbol2: str) -> float:
        """
        Get correlation between two assets.
        
        Args:
            symbol1: First symbol
            symbol2: Second symbol
            
        Returns:
            Correlation coefficient (0 if not found)
        """
        with self._lock:
            key = (min(symbol1, symbol2), max(symbol1, symbol2))
            return self.correlation_matrix.get(key, 0.0)
    
    def calculate_portfolio_pnl(
        self,
        positions: Dict[str, Dict[str, Any]],
        current_prices: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Calculate cross-asset portfolio PnL.
        
        Args:
            positions: Dict mapping symbol to position data
            current_prices: Dict mapping symbol to current price
            
        Returns:
            Portfolio PnL dictionary
        """
        total_pnl_usd = 0.0
        asset_pnl: Dict[str, float] = {}
        
        with self._lock:
            for symbol, position in positions.items():
                if symbol not in current_prices:
                    continue
                
                spec = self.contract_specs.get(symbol)
                if not spec:
                    continue
                
                quantity = position.get("quantity", 0.0)
                avg_price = position.get("avg_price", 0.0)
                current_price = current_prices[symbol]
                
                # Calculate PnL
                pnl = (current_price - avg_price) * quantity * spec.multiplier
                
                # Normalize to USD
                pnl_usd = self.normalize_currency(pnl, spec.currency, "USD")
                
                asset_pnl[symbol] = pnl_usd
                total_pnl_usd += pnl_usd
        
        return {
            "total_pnl_usd": total_pnl_usd,
            "asset_pnl": asset_pnl,
        }
    
    def validate_trade(
        self,
        symbol: str,
        quantity: float,
        price: float,
        current_exposure: float,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate trade against risk limits.
        
        Args:
            symbol: Trading symbol
            quantity: Trade quantity
            price: Trade price
            current_exposure: Current position exposure
            
        Returns:
            Tuple of (is_valid, rejection_reason)
        """
        with self._lock:
            spec = self.contract_specs.get(symbol)
            if not spec:
                return False, f"Contract spec not found for {symbol}"
            
            # Check trade size limits
            if abs(quantity) < spec.min_trade_size:
                return False, f"Quantity {quantity} below minimum {spec.min_trade_size}"
            
            if abs(quantity) > spec.max_trade_size:
                return False, f"Quantity {quantity} above maximum {spec.max_trade_size}"
            
            # Check exposure limits
            limits = self.risk_limits.get(symbol)
            if limits:
                notional = abs(quantity) * price * spec.multiplier
                new_exposure = current_exposure + notional
                
                if new_exposure > limits.max_exposure:
                    return False, f"Exposure {new_exposure} exceeds limit {limits.max_exposure}"
            
            return True, None


# Global asset registry instance
_asset_registry: Optional[AssetRegistry] = None
_asset_registry_lock = threading.Lock()


def get_asset_registry() -> AssetRegistry:
    """
    Get global asset registry instance (singleton).
    
    Returns:
        AssetRegistry instance
    """
    global _asset_registry
    
    if _asset_registry is None:
        with _asset_registry_lock:
            if _asset_registry is None:
                _asset_registry = AssetRegistry()
    
    return _asset_registry


# Default contract specs for common assets
DEFAULT_EQUITY_SPEC = ContractSpec(
    symbol="EQUITY_DEFAULT",
    asset_type=AssetType.EQUITY,
    tick_size=0.01,
    multiplier=1.0,
    currency="USD",
    fee_per_contract=0.0,
    fee_percentage=0.1,  # 0.1% commission
)

DEFAULT_FUTURE_SPEC = ContractSpec(
    symbol="FUTURE_DEFAULT",
    asset_type=AssetType.FUTURE,
    tick_size=0.25,
    multiplier=50.0,
    currency="USD",
    fee_per_contract=2.0,
    fee_percentage=0.0,
)

DEFAULT_CRYPTO_SPEC = ContractSpec(
    symbol="CRYPTO_DEFAULT",
    asset_type=AssetType.CRYPTO,
    tick_size=0.01,
    multiplier=1.0,
    currency="USD",
    fee_per_contract=0.0,
    fee_percentage=0.1,  # 0.1% fee
)

DEFAULT_FX_SPEC = ContractSpec(
    symbol="FX_DEFAULT",
    asset_type=AssetType.FX,
    tick_size=0.0001,  # 1 pip
    multiplier=1.0,
    currency="USD",
    fee_per_contract=0.0,
    fee_percentage=0.02,  # 2 pips spread
)
