"""
PHASE 8 — SHADOW TRAINER INTEGRATION

Wire replay feed into ShadowTrainer:
- Shadow receives replay ticks identically to live ticks
- Shadow strategies emit signals
- Signals are simulated only
- Outcomes scored per asset and cross-asset

Replay must NOT require any changes to strategies.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import threading

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.trainer import ShadowTrainer
from sentinel_x.marketdata.historical_feed import HistoricalMarketFeed, MultiAssetTick
from sentinel_x.shadow.feed import MarketTick


class ShadowReplayIntegration:
    """
    Integration layer between historical replay and shadow training.
    
    Ensures:
    - Replay ticks are fed to shadow trainer identically to live ticks
    - Strategies work without modification
    - Signals are simulated only
    - Outcomes are scored per asset and cross-asset
    """
    
    def __init__(self, trainer: Optional[ShadowTrainer] = None):
        """
        Initialize shadow replay integration.
        
        Args:
            trainer: Optional shadow trainer instance
        """
        self.trainer = trainer
        self.replay_feed: Optional[HistoricalMarketFeed] = None
        self._lock = threading.RLock()
        
        logger.info("ShadowReplayIntegration initialized")
    
    def start_replay(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        replay_mode: str = "STRICT",
        speed_multiplier: float = 1.0,
        seed: Optional[int] = None,
    ) -> None:
        """
        Start historical replay for shadow training.
        
        Args:
            symbols: List of symbols to replay
            start_date: Replay start date
            end_date: Replay end date
            replay_mode: Replay mode (STRICT, ACCELERATED, STEP)
            speed_multiplier: Speed multiplier for accelerated mode
            seed: Random seed for determinism
        """
        from sentinel_x.marketdata.historical_feed import HistoricalMarketFeed, ReplayMode
        
        with self._lock:
            # Create replay feed
            self.replay_feed = HistoricalMarketFeed(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                replay_mode=ReplayMode(replay_mode),
                speed_multiplier=speed_multiplier,
                seed=seed,
            )
            
            # Start replay feed
            self.replay_feed.start()
            
            # Start shadow trainer if not already started
            if self.trainer:
                if not self.trainer.training_active:
                    self.trainer.start(symbols)
                
                # Replace market feed with replay feed
                self.trainer.market_feed = self.replay_feed
            
            logger.info(
                f"Started replay for shadow training | "
                f"symbols={symbols} | "
                f"start={start_date} | end={end_date} | "
                f"mode={replay_mode}"
            )
    
    def stop_replay(self) -> None:
        """Stop historical replay."""
        with self._lock:
            if self.replay_feed:
                self.replay_feed.stop()
            
            if self.trainer:
                self.trainer.stop()
            
            logger.info("Stopped replay for shadow training")
    
    def process_replay_tick(self) -> Optional[MultiAssetTick]:
        """
        Process next replay tick and feed to shadow trainer.
        
        Returns:
            MultiAssetTick or None if at end
        """
        with self._lock:
            if not self.replay_feed or not self.replay_feed.running:
                return None
            
            # Get next multi-asset tick
            multi_tick = self.replay_feed.get_next_tick()
            
            if not multi_tick:
                return None
            
            # Feed each asset tick to shadow trainer
            if self.trainer:
                for symbol, tick in multi_tick.assets.items():
                    try:
                        # Process tick in shadow trainer
                        # This is identical to how live ticks are processed
                        self.trainer.process_tick(tick)
                    except Exception as e:
                        logger.error(
                            f"Error processing replay tick for {symbol}: {e}",
                            exc_info=True,
                        )
            
            return multi_tick
    
    def get_replay_status(self) -> Dict[str, Any]:
        """
        Get replay status.
        
        Returns:
            Status dictionary
        """
        with self._lock:
            if not self.replay_feed:
                return {
                    "replay_active": False,
                    "progress": None,
                }
            
            progress = self.replay_feed.get_progress()
            
            return {
                "replay_active": self.replay_feed.running,
                "progress": progress,
                "trainer_active": self.trainer.training_active if self.trainer else False,
            }


# Global integration instance
_integration: Optional[ShadowReplayIntegration] = None
_integration_lock = threading.Lock()


def get_shadow_replay_integration(
    trainer: Optional[ShadowTrainer] = None,
) -> ShadowReplayIntegration:
    """
    Get global shadow replay integration instance (singleton).
    
    Args:
        trainer: Optional shadow trainer instance
        
    Returns:
        ShadowReplayIntegration instance
    """
    global _integration
    
    if _integration is None:
        with _integration_lock:
            if _integration is None:
                _integration = ShadowReplayIntegration(trainer)
    
    return _integration
