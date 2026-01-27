"""
PHASE 3 — LIVE DASHBOARDS (READ-ONLY)

Local dashboard using Textual for shadow training observability.

Required views:
- Shadow heartbeat (live)
- Active strategies
- Per-strategy metrics
- PnL curves (shadow only)
- Drawdown & risk stats
- Regime breakdown
- Replay progress indicator

Rules:
- Read-only
- No control actions
- No trade buttons
- No mutation of engine state
- Auto-refresh
- Survive engine restarts
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import time
import threading

try:
    from textual.app import App, ComposeResult
    from textual.widgets import Header, Footer, DataTable, Static, Label
    from textual.containers import Container, Horizontal, Vertical
    from textual.reactive import reactive
    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False
    # Fallback for environments without Textual
    pass

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.trainer import get_shadow_trainer
from sentinel_x.shadow.registry import get_strategy_registry
from sentinel_x.shadow.scorer import get_shadow_scorer
from sentinel_x.shadow.promotion import get_promotion_evaluator
from sentinel_x.shadow.heartbeat import get_shadow_heartbeat_monitor
from sentinel_x.shadow.regime import get_regime_analyzer
from sentinel_x.shadow.observability import get_shadow_observability


class ShadowDashboard:
    """
    Shadow training dashboard (read-only).
    
    Features:
    - Live heartbeat monitoring
    - Active strategies view
    - Per-strategy metrics
    - PnL curves
    - Drawdown & risk stats
    - Regime breakdown
    - Replay progress
    """
    
    def __init__(self, refresh_interval: float = 1.0):
        """
        Initialize dashboard.
        
        Args:
            refresh_interval: Refresh interval in seconds
        """
        self.refresh_interval = refresh_interval
        self.running = False
        self._lock = threading.RLock()
        
        logger.info("ShadowDashboard initialized")
    
    def start(self) -> None:
        """Start dashboard."""
        if not HAS_TEXTUAL:
            logger.warning("Textual not available, using text-based dashboard")
            self._start_text_dashboard()
            return
        
        try:
            app = ShadowDashboardApp()
            app.run()
        except Exception as e:
            logger.error(f"Error starting dashboard: {e}", exc_info=True)
            self._start_text_dashboard()
    
    def _start_text_dashboard(self) -> None:
        """Start text-based dashboard (fallback)."""
        self.running = True
        
        try:
            while self.running:
                self._render_text_dashboard()
                time.sleep(self.refresh_interval)
        except KeyboardInterrupt:
            logger.info("Dashboard stopped")
        finally:
            self.running = False
    
    def _render_text_dashboard(self) -> None:
        """Render text-based dashboard."""
        try:
            import os
            os.system('clear' if os.name != 'nt' else 'cls')
            
            print("=" * 80)
            print("SHADOW TRAINING DASHBOARD (READ-ONLY)")
            print("=" * 80)
            print()
            
            # Heartbeat
            heartbeat_monitor = get_shadow_heartbeat_monitor()
            heartbeat = heartbeat_monitor.get_heartbeat()
            
            if heartbeat:
                print(f"Heartbeat: {heartbeat.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Trainer Alive: {heartbeat.trainer_alive}")
                print(f"  Active Strategies: {heartbeat.active_strategies}")
                print(f"  Feed Type: {heartbeat.feed_type}")
                print(f"  Tick Count: {heartbeat.tick_count}")
                print(f"  Error Count: {heartbeat.error_count}")
                print()
            else:
                print("Heartbeat: No data")
                print()
            
            # Strategies
            registry = get_strategy_registry()
            strategies = registry.get_all_strategies()
            
            print(f"Active Strategies: {len(strategies)}")
            print()
            
            # Per-strategy metrics
            scorer = get_shadow_scorer()
            promotion_evaluator = get_promotion_evaluator()
            
            print("Strategy Metrics:")
            print("-" * 80)
            print(f"{'Strategy':<30} {'Return':<12} {'Sharpe':<10} {'Drawdown':<12} {'Trades':<10} {'State':<15}")
            print("-" * 80)
            
            for strategy_id in strategies.keys():
                metrics = scorer.get_latest_metrics(strategy_id)
                if metrics:
                    state = promotion_evaluator.get_current_state(strategy_id)
                    print(
                        f"{strategy_id[:28]:<30} "
                        f"{metrics.total_return*100:>10.2f}% "
                        f"{metrics.sharpe_ratio:>9.2f} "
                        f"{metrics.max_drawdown*100:>10.2f}% "
                        f"{metrics.total_trades:>9} "
                        f"{state.value:<15}"
                    )
            
            print()
            
            # Regime
            regime_analyzer = get_regime_analyzer()
            current_regime = regime_analyzer.get_current_regime()
            
            if current_regime:
                print(f"Current Regime: {current_regime.regime}")
                print(f"  Volatility: {current_regime.volatility:.4f}")
                print(f"  Trend: {current_regime.trend:.4f}")
                print()
            
            # Replay progress (if applicable)
            trainer = get_shadow_trainer()
            if trainer.market_feed and hasattr(trainer.market_feed, 'get_progress'):
                progress = trainer.market_feed.get_progress()
                if progress:
                    print(f"Replay Progress: {progress.get('progress_pct', 0):.1f}%")
                    print()
            
            print("=" * 80)
            print(f"Last Update: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
            print("Press Ctrl+C to exit")
        
        except Exception as e:
            logger.error(f"Error rendering dashboard: {e}", exc_info=True)


if HAS_TEXTUAL:
    class ShadowDashboardApp(App):
        """Textual-based shadow dashboard app."""
        
        CSS = """
        Container {
            padding: 1;
        }
        Label {
            padding: 1;
        }
        """
        
        def compose(self) -> ComposeResult:
            """Compose dashboard layout."""
            yield Header()
            yield Container(
                Vertical(
                    Label("Shadow Training Dashboard (Read-Only)", id="title"),
                    Label("", id="heartbeat"),
                    Label("", id="strategies"),
                    Label("", id="metrics"),
                    Label("", id="regime"),
                    Label("", id="replay"),
                )
            )
            yield Footer()
        
        def on_mount(self) -> None:
            """Start refresh timer."""
            self.set_interval(1.0, self.refresh_data)
            self.refresh_data()
        
        def refresh_data(self) -> None:
            """Refresh dashboard data."""
            try:
                # Heartbeat
                heartbeat_monitor = get_shadow_heartbeat_monitor()
                heartbeat = heartbeat_monitor.get_heartbeat()
                
                heartbeat_text = "No heartbeat data"
                if heartbeat:
                    heartbeat_text = (
                        f"Heartbeat: {heartbeat.timestamp.strftime('%H:%M:%S')} | "
                        f"Alive: {heartbeat.trainer_alive} | "
                        f"Strategies: {heartbeat.active_strategies} | "
                        f"Feed: {heartbeat.feed_type} | "
                        f"Ticks: {heartbeat.tick_count}"
                    )
                
                self.query_one("#heartbeat", Label).update(heartbeat_text)
                
                # Strategies
                registry = get_strategy_registry()
                strategies = registry.get_all_strategies()
                strategies_text = f"Active Strategies: {len(strategies)}"
                self.query_one("#strategies", Label).update(strategies_text)
                
                # Metrics summary
                scorer = get_shadow_scorer()
                metrics_text = "Metrics: Loading..."
                if strategies:
                    metrics_list = []
                    for strategy_id in list(strategies.keys())[:5]:  # Show top 5
                        metrics = scorer.get_latest_metrics(strategy_id)
                        if metrics:
                            metrics_list.append(
                                f"{strategy_id[:20]}: "
                                f"Return={metrics.total_return*100:.1f}% "
                                f"Sharpe={metrics.sharpe_ratio:.2f}"
                            )
                    if metrics_list:
                        metrics_text = " | ".join(metrics_list)
                
                self.query_one("#metrics", Label).update(metrics_text)
                
                # Regime
                regime_analyzer = get_regime_analyzer()
                current_regime = regime_analyzer.get_current_regime()
                regime_text = "Regime: Unknown"
                if current_regime:
                    regime_text = (
                        f"Regime: {current_regime.regime} | "
                        f"Vol: {current_regime.volatility:.4f} | "
                        f"Trend: {current_regime.trend:.4f}"
                    )
                self.query_one("#regime", Label).update(regime_text)
                
                # Replay progress
                trainer = get_shadow_trainer()
                replay_text = ""
                if trainer.market_feed and hasattr(trainer.market_feed, 'get_progress'):
                    progress = trainer.market_feed.get_progress()
                    if progress:
                        replay_text = f"Replay: {progress.get('progress_pct', 0):.1f}%"
                self.query_one("#replay", Label).update(replay_text)
            
            except Exception as e:
                logger.error(f"Error refreshing dashboard: {e}", exc_info=True)


def run_dashboard(refresh_interval: float = 1.0) -> None:
    """
    Run shadow dashboard.
    
    Args:
        refresh_interval: Refresh interval in seconds
    """
    dashboard = ShadowDashboard(refresh_interval=refresh_interval)
    dashboard.start()


if __name__ == "__main__":
    run_dashboard()
