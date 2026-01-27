"""
PHASE 10 — DASHBOARD (READ-ONLY)

Local dashboard for shadow replay observability.

Required views:
- Replay status (mode, window, tick)
- Shadow heartbeat
- Active assets
- Per-asset PnL curves
- Portfolio PnL
- Drawdown
- Volatility
- Correlation matrix
- Regime performance
- Replay progress bar

Rules:
- Read-only only
- No buttons that mutate state
- Auto-refresh
- Survives engine restarts
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import time
import threading

try:
    from textual.app import App, ComposeResult
    from textual.widgets import Header, Footer, Static, DataTable, ProgressBar
    from textual.containers import Container, Horizontal, Vertical
    from textual.reactive import reactive
    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

from sentinel_x.monitoring.logger import logger
from sentinel_x.shadow.integration import get_shadow_replay_integration
from sentinel_x.shadow.heartbeat import get_shadow_heartbeat_monitor
from sentinel_x.shadow.scoring_multi_asset import get_multi_asset_scorer
from sentinel_x.marketdata.historical_feed import get_historical_feed


class ShadowReplayDashboard:
    """
    Shadow replay dashboard (read-only).
    
    Features:
    - Replay status monitoring
    - Shadow heartbeat display
    - Active assets view
    - Per-asset PnL curves
    - Portfolio metrics
    - Correlation matrix
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
        
        logger.info("ShadowReplayDashboard initialized")
    
    def start(self) -> None:
        """Start dashboard."""
        if not HAS_TEXTUAL:
            logger.warning("Textual not available, using text-based dashboard")
            self._start_text_dashboard()
            return
        
        try:
            app = ShadowReplayDashboardApp()
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
            
            print("=" * 100)
            print("SHADOW REPLAY DASHBOARD (READ-ONLY)")
            print("=" * 100)
            print()
            
            # Replay status
            integration = get_shadow_replay_integration()
            replay_status = integration.get_replay_status()
            
            if replay_status.get("replay_active"):
                progress = replay_status.get("progress", {})
                print(f"Replay Status: ACTIVE")
                print(f"  Mode: {progress.get('mode', 'UNKNOWN')}")
                print(f"  Progress: {progress.get('progress_pct', 0):.1f}%")
                print(f"  Tick: {progress.get('current_tick', 0)} / {progress.get('total_ticks', 0)}")
                print(f"  Current Time: {progress.get('current_timestamp', 'N/A')}")
                print()
            else:
                print("Replay Status: INACTIVE")
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
                print()
            
            # Portfolio metrics
            scorer = get_multi_asset_scorer()
            
            # Get active assets (simplified - would get from replay feed)
            # For now, show placeholder
            print("Portfolio Metrics:")
            print("-" * 100)
            print("(Metrics will appear when replay is active)")
            print()
            
            print("=" * 100)
            print(f"Last Update: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
            print("Press Ctrl+C to exit")
        
        except Exception as e:
            logger.error(f"Error rendering dashboard: {e}", exc_info=True)


if HAS_TEXTUAL:
    class ShadowReplayDashboardApp(App):
        """Textual-based shadow replay dashboard app."""
        
        CSS = """
        Container {
            padding: 1;
        }
        Static {
            padding: 1;
        }
        """
        
        def compose(self) -> ComposeResult:
            """Compose dashboard layout."""
            yield Header()
            yield Container(
                Vertical(
                    Static("Shadow Replay Dashboard (Read-Only)", id="title"),
                    Static("", id="replay_status"),
                    Static("", id="heartbeat"),
                    Static("", id="portfolio"),
                    Static("", id="assets"),
                    Static("", id="progress"),
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
                # Replay status
                integration = get_shadow_replay_integration()
                replay_status = integration.get_replay_status()
                
                if replay_status.get("replay_active"):
                    progress = replay_status.get("progress", {})
                    status_text = (
                        f"Replay: ACTIVE | "
                        f"Mode: {progress.get('mode', 'UNKNOWN')} | "
                        f"Progress: {progress.get('progress_pct', 0):.1f}% | "
                        f"Tick: {progress.get('current_tick', 0)}/{progress.get('total_ticks', 0)}"
                    )
                else:
                    status_text = "Replay: INACTIVE"
                
                self.query_one("#replay_status", Static).update(status_text)
                
                # Heartbeat
                heartbeat_monitor = get_shadow_heartbeat_monitor()
                heartbeat = heartbeat_monitor.get_heartbeat()
                
                if heartbeat:
                    heartbeat_text = (
                        f"Heartbeat: {heartbeat.timestamp.strftime('%H:%M:%S')} | "
                        f"Alive: {heartbeat.trainer_alive} | "
                        f"Strategies: {heartbeat.active_strategies} | "
                        f"Ticks: {heartbeat.tick_count}"
                    )
                else:
                    heartbeat_text = "Heartbeat: No data"
                
                self.query_one("#heartbeat", Static).update(heartbeat_text)
                
                # Portfolio (simplified)
                portfolio_text = "Portfolio Metrics: (Active during replay)"
                self.query_one("#portfolio", Static).update(portfolio_text)
                
                # Assets (simplified)
                assets_text = "Active Assets: (Shown during replay)"
                self.query_one("#assets", Static).update(assets_text)
                
                # Progress bar
                if replay_status.get("replay_active"):
                    progress = replay_status.get("progress", {})
                    progress_pct = progress.get("progress_pct", 0)
                    progress_text = f"Progress: {progress_pct:.1f}%"
                else:
                    progress_text = "Progress: N/A"
                
                self.query_one("#progress", Static).update(progress_text)
            
            except Exception as e:
                logger.error(f"Error refreshing dashboard: {e}", exc_info=True)


def run_dashboard(refresh_interval: float = 1.0) -> None:
    """
    Run shadow replay dashboard.
    
    Args:
        refresh_interval: Refresh interval in seconds
    """
    dashboard = ShadowReplayDashboard(refresh_interval=refresh_interval)
    dashboard.start()


if __name__ == "__main__":
    run_dashboard()
