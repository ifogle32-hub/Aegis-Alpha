"""
PHASE 3 — ASSET METADATA ENGINE

Metadata loaders for contracts, calendars, and FX.

contracts.yaml defines:
- asset_type (equity | future | crypto | fx)
- tick_size
- multiplier
- fees
- currency
- rollover rules (futures)
- funding model (crypto)

FX metadata defines:
- base_currency
- quote_currency
- normalization rules
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import yaml
import threading

from sentinel_x.monitoring.logger import logger


class AssetType(str, Enum):
    """Asset types."""
    EQUITY = "equity"
    FUTURE = "future"
    CRYPTO = "crypto"
    FX = "fx"


@dataclass
class ContractMetadata:
    """
    Contract metadata for an asset.
    """
    symbol: str
    asset_type: AssetType
    tick_size: float
    multiplier: float
    currency: str
    fee_per_contract: float = 0.0
    fee_percentage: float = 0.0
    rollover_rule: Optional[str] = None  # For futures
    funding_model: Optional[str] = None  # For crypto
    base_currency: Optional[str] = None  # For FX
    quote_currency: Optional[str] = None  # For FX
    
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
            "rollover_rule": self.rollover_rule,
            "funding_model": self.funding_model,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
        }


@dataclass
class FXMetadata:
    """
    FX pair metadata.
    """
    symbol: str
    base_currency: str
    quote_currency: str
    normalization_base: str = "USD"  # Normalize to USD by default
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "normalization_base": self.normalization_base,
        }


class MetadataLoader:
    """
    Metadata loader for contracts, calendars, and FX.
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialize metadata loader.
        
        Args:
            data_dir: Data directory path (default: data/historical)
        """
        if data_dir is None:
            data_dir = Path("data/historical")
        
        self.data_dir = Path(data_dir)
        self.metadata_dir = self.data_dir / "metadata"
        
        self.contracts: Dict[str, ContractMetadata] = {}
        self.fx_metadata: Dict[str, FXMetadata] = {}
        
        self._lock = threading.RLock()
        
        # Load metadata
        self._load_metadata()
    
    def _load_metadata(self) -> None:
        """Load metadata from YAML files."""
        try:
            # Load contracts
            contracts_file = self.metadata_dir / "contracts.yaml"
            if contracts_file.exists():
                with open(contracts_file, 'r') as f:
                    contracts_data = yaml.safe_load(f) or {}
                
                for symbol, data in contracts_data.items():
                    try:
                        contract = ContractMetadata(
                            symbol=symbol,
                            asset_type=AssetType(data.get("asset_type", "equity")),
                            tick_size=float(data.get("tick_size", 0.01)),
                            multiplier=float(data.get("multiplier", 1.0)),
                            currency=data.get("currency", "USD"),
                            fee_per_contract=float(data.get("fee_per_contract", 0.0)),
                            fee_percentage=float(data.get("fee_percentage", 0.0)),
                            rollover_rule=data.get("rollover_rule"),
                            funding_model=data.get("funding_model"),
                            base_currency=data.get("base_currency"),
                            quote_currency=data.get("quote_currency"),
                        )
                        self.contracts[symbol] = contract
                    except Exception as e:
                        logger.error(f"Error loading contract metadata for {symbol}: {e}")
            
            # Load FX metadata
            fx_file = self.metadata_dir / "fx.yaml"
            if fx_file.exists():
                with open(fx_file, 'r') as f:
                    fx_data = yaml.safe_load(f) or {}
                
                for symbol, data in fx_data.items():
                    try:
                        fx_meta = FXMetadata(
                            symbol=symbol,
                            base_currency=data.get("base_currency", "EUR"),
                            quote_currency=data.get("quote_currency", "USD"),
                            normalization_base=data.get("normalization_base", "USD"),
                        )
                        self.fx_metadata[symbol] = fx_meta
                    except Exception as e:
                        logger.error(f"Error loading FX metadata for {symbol}: {e}")
            
            logger.info(f"Loaded {len(self.contracts)} contracts and {len(self.fx_metadata)} FX pairs")
        
        except Exception as e:
            logger.error(f"Error loading metadata: {e}", exc_info=True)
    
    def get_contract(self, symbol: str) -> Optional[ContractMetadata]:
        """
        Get contract metadata.
        
        Args:
            symbol: Symbol name
            
        Returns:
            ContractMetadata or None
        """
        with self._lock:
            return self.contracts.get(symbol)
    
    def get_fx_metadata(self, symbol: str) -> Optional[FXMetadata]:
        """
        Get FX metadata.
        
        Args:
            symbol: FX pair symbol
            
        Returns:
            FXMetadata or None
        """
        with self._lock:
            return self.fx_metadata.get(symbol)
    
    def get_all_contracts(self) -> Dict[str, ContractMetadata]:
        """
        Get all contract metadata.
        
        Returns:
            Dictionary of contracts
        """
        with self._lock:
            return self.contracts.copy()
    
    def reload(self) -> None:
        """Reload metadata from files."""
        with self._lock:
            self.contracts.clear()
            self.fx_metadata.clear()
            self._load_metadata()


# Global metadata loader instance
_metadata_loader: Optional[MetadataLoader] = None
_metadata_loader_lock = threading.Lock()


def get_metadata_loader(data_dir: Optional[Path] = None) -> MetadataLoader:
    """
    Get global metadata loader instance (singleton).
    
    Args:
        data_dir: Optional data directory path
        
    Returns:
        MetadataLoader instance
    """
    global _metadata_loader
    
    if _metadata_loader is None:
        with _metadata_loader_lock:
            if _metadata_loader is None:
                _metadata_loader = MetadataLoader(data_dir)
    
    return _metadata_loader
