# api/strategies/registry.py

from enum import Enum
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional


class StrategyMode(str, Enum):
    DISABLED = "DISABLED"
    SHADOW = "SHADOW"
    PAPER = "PAPER"


class StrategyRegistry:
    def __init__(self):
        self._strategies: Dict[str, dict] = {}
        self._lock = Lock()

    def register(
        self,
        strategy_id: str,
        name: str,
        description: str = "",
        default_mode: StrategyMode = StrategyMode.SHADOW,
    ) -> dict:
        with self._lock:
            if strategy_id in self._strategies:
                return self._strategies[strategy_id]

            self._strategies[strategy_id] = {
                "id": strategy_id,
                "name": name,
                "description": description,
                "mode": default_mode.value,  # Store as string value for JSON serialization
                "last_updated": self._now(),
            }
            return self._strategies[strategy_id]

    def list(self) -> List[dict]:
        with self._lock:
            return list(self._strategies.values())
    
    def get_strategy(self, strategy_id: str) -> Optional[dict]:
        """Get strategy by ID"""
        with self._lock:
            return self._strategies.get(strategy_id)
    
    def get_strategy_mode(self, strategy_id: str) -> Optional[StrategyMode]:
        """Get strategy mode as enum"""
        with self._lock:
            strategy = self._strategies.get(strategy_id)
            if strategy:
                mode_str = strategy.get("mode")
                try:
                    return StrategyMode(mode_str)
                except (ValueError, KeyError):
                    return None
            return None

    def set_mode(self, strategy_id: str, mode: StrategyMode) -> Optional[dict]:
        with self._lock:
            if strategy_id not in self._strategies:
                return None

            self._strategies[strategy_id]["mode"] = mode.value  # Store as string value
            self._strategies[strategy_id]["last_updated"] = self._now()
            return self._strategies[strategy_id]

    def get_strategy_modes_dict(self) -> Dict[str, str]:
        """Compatibility function for status endpoint"""
        with self._lock:
            return {
                strategy_id: strategy_data["mode"]
                for strategy_id, strategy_data in self._strategies.items()
            }

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat() + "Z"


# ---- singleton registry (authoritative) ----

_REGISTRY = StrategyRegistry()


def get_strategy_registry() -> StrategyRegistry:
    return _REGISTRY