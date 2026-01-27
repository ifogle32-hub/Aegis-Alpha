"""
PHASE 2 — HISTORICAL REPLAY → SHADOW BRIDGE

Wire historical replay feed to shadow training.

Ensures:
- HistoricalReplayFeed → Engine → ShadowTrainer
- Replay timestamps drive engine ticks
- ShadowTrainer subscribes passively to ticks
- Shadow training works identically in replay or live shadow

Rules:
- Replay must be deterministic
- Replay must block live feeds
- Replay progress must be observable
- Restart resumes or restarts replay safely
"""

import threading
from typing import Optional, Dict, Any, List
from datetime import datetime

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.controller import ShadowTrainingController, get_shadow_training_controller
from sentinel_x.shadow.replay import HistoricalReplayFeed, ReplayMode, create_historical_replay_feed
from sentinel_x.shadow.feed import MarketTick


class ReplayBridge:
    """
    Bridge between historical replay and shadow training.
    
    Responsibilities:
    - Create and configure replay feed
    - Wire replay feed to shadow trainer
    - Block live feeds during replay
    - Track replay progress
    """
    
    def __init__(self, controller: Optional[ShadowTrainingController] = None):
        """
        Initialize replay bridge.
        
        Args:
            controller: Optional shadow training controller
        """
        self.controller = controller or get_shadow_training_controller()
        self._lock = threading.RLock()
        self._replay_feed: Optional[HistoricalReplayFeed] = None
        
        logger.info("ReplayBridge initialized")
    
    def start_replay(
        self,
        symbols: List[str],
        historical_data: Dict[str, Any],
        start_date: datetime,
        end_date: datetime,
        replay_mode: ReplayMode = ReplayMode.STRICT,
        speed_multiplier: float = 1.0,
        seed: Optional[int] = None,
    ) -> bool:
        """
        Start historical replay for shadow training.
        
        Args:
            symbols: List of symbols to replay
            historical_data: Dict mapping symbol to DataFrame with OHLCV data
            start_date: Replay start date
            end_date: Replay end date
            replay_mode: Replay mode (STRICT, ACCELERATED, STEP)
            speed_multiplier: Speed multiplier for accelerated mode
            seed: Random seed for determinism
        
        Returns:
            True if started successfully, False otherwise
        
        SAFETY:
        - Replay blocks live feeds
        - Replay is deterministic
        - Replay cannot execute trades
        """
        with self._lock:
            try:
                # Create replay feed
                self._replay_feed = create_historical_replay_feed(
                    symbols=symbols,
                    historical_data=historical_data,
                    start_date=start_date,
                    end_date=end_date,
                    replay_mode=replay_mode,
                    speed_multiplier=speed_multiplier,
                    seed=seed,
                )
                
                # Start shadow training with replay feed
                success = self.controller.start(
                    symbols=symbols,
                    replay_feed=self._replay_feed,
                    replay_mode=True,
                )
                
                if success:
                    logger.info(
                        f"Replay started for shadow training | "
                        f"symbols={symbols} | "
                        f"start={start_date} | end={end_date} | "
                        f"mode={replay_mode.value}"
                    )
                
                return success
                
            except Exception as e:
                logger.error(f"Error starting replay: {e}", exc_info=True)
                return False
    
    def stop_replay(self) -> None:
        """Stop historical replay."""
        with self._lock:
            try:
                if self._replay_feed:
                    self._replay_feed.stop()
                
                self.controller.stop()
                
                logger.info("Replay stopped")
                
            except Exception as e:
                logger.error(f"Error stopping replay: {e}", exc_info=True)
    
    def get_replay_progress(self) -> Dict[str, Any]:
        """
        Get replay progress.
        
        Returns:
            Progress dictionary with:
            - current_tick: int
            - total_ticks: int
            - progress_pct: float
            - current_timestamp: str
            - start_timestamp: str
            - end_timestamp: str
            - time_progress_pct: float
            - mode: str
            - playing: bool
        """
        with self._lock:
            if not self._replay_feed:
                return {
                    "replay_active": False,
                    "progress": None,
                }
            
            try:
                progress = self._replay_feed.get_progress()
                return {
                    "replay_active": self._replay_feed.running,
                    "progress": progress,
                }
            except Exception as e:
                logger.error(f"Error getting replay progress: {e}", exc_info=True)
                return {
                    "replay_active": False,
                    "progress": None,
                    "error": str(e),
                }
    
    def get_replay_feed(self) -> Optional[HistoricalReplayFeed]:
        """Get current replay feed (for engine integration)."""
        with self._lock:
            return self._replay_feed


# Global replay bridge instance
_replay_bridge: Optional[ReplayBridge] = None
_replay_bridge_lock = threading.Lock()


def get_replay_bridge() -> ReplayBridge:
    """
    Get global replay bridge instance (singleton).
    
    Returns:
        ReplayBridge instance
    """
    global _replay_bridge
    
    if _replay_bridge is None:
        with _replay_bridge_lock:
            if _replay_bridge is None:
                _replay_bridge = ReplayBridge()
    
    return _replay_bridge
