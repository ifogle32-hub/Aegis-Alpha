"""Main entry point for Sentinel X trading system."""
import sys
import signal
import threading
import uvicorn
from sentinel_x.monitoring.logger import logger
from sentinel_x.core.config import get_config
from sentinel_x.core.engine import TradingEngine
from sentinel_x.core.state import BotState, EngineMode, set_state
from sentinel_x.data.market_data import get_market_data
from sentinel_x.data.storage import get_storage
from sentinel_x.intelligence.strategy_manager import get_strategy_manager
from sentinel_x.strategies.momentum import MomentumStrategy
from sentinel_x.strategies.mean_reversion import MeanReversionStrategy
from sentinel_x.strategies.breakout import BreakoutStrategy
from sentinel_x.strategies.test_strategy import TestStrategy
from sentinel_x.execution.router import OrderRouter
from sentinel_x.api.rork_server import app, set_engine, set_strategy_manager, set_storage, set_executor, set_order_router
from sentinel_x.execution.wire_brokers import wire_brokers

def main():
    """Main entry point."""
    try:
        logger.info("=" * 60)
        logger.info("Sentinel X Trading System - Starting")
        logger.info("=" * 60)
        
        # Load configuration
        logger.info("Loading configuration...")
        config = get_config()
        logger.info(f"Configuration loaded: {len(config.symbols)} symbols, {len(config.timeframes)} timeframes")
        logger.info(f"Trade mode: {config.trade_mode}")
        logger.info(f"Initial capital: ${config.initial_capital:,.2f}")
        
        # Initialize market data
        logger.info("Initializing market data provider...")
        market_data = get_market_data(config.symbols, seed=42)
        
        # PHASE 4: Initialize strategies via StrategyFactory (ONLY instantiation path)
        logger.info("Initializing strategies via StrategyFactory...")
        strategies = []
        
        # PHASE 4: Use StrategyFactory to create strategies (hard boundary)
        from sentinel_x.intelligence.strategy_factory import get_strategy_factory
        from sentinel_x.intelligence.models import StrategyConfig
        
        factory = get_strategy_factory()
        
        # PHASE 4: Create strategies via factory with default configs (backward compatibility)
        # Strategy type -> default config mapping
        default_strategy_configs = [
            ("momentum", {
                "strategy_type": "momentum",
                "timeframe": 15,
                "lookback": 50,
                "entry_params": {"fast_ema": 12, "slow_ema": 26}
            }),
            ("mean_reversion", {
                "strategy_type": "mean_reversion",
                "timeframe": 15,
                "lookback": 20,
                "entry_params": {"entry_z": 2.0},
                "exit_params": {"exit_z": 0.5}
            }),
            ("breakout", {
                "strategy_type": "breakout",
                "timeframe": 15,
                "lookback": 20,
                "entry_params": {"channel_period": 20, "breakout_threshold": 0.01}
            }),
            ("test", {
                "strategy_type": "test",
                "timeframe": 15,
                "lookback": 10,
                "entry_params": {}
            })
        ]
        
        # Safe strategy instantiation via factory - never crash boot
        import inspect
        for strategy_type, config_dict in default_strategy_configs:
            try:
                # PHASE 4: Create StrategyConfig from default config
                try:
                    config = StrategyConfig(**config_dict)
                except Exception as e:
                    logger.error(f"Failed to create StrategyConfig for {strategy_type}: {e}", exc_info=True)
                    continue
                
                # PHASE 4: Create strategy via factory (ONLY instantiation path)
                # Use default name (strategy class name)
                strategy_name_map = {
                    "momentum": "MomentumStrategy",
                    "mean_reversion": "MeanReversionStrategy",
                    "breakout": "BreakoutStrategy",
                    "test": "TestStrategy"
                }
                default_name = strategy_name_map.get(strategy_type, f"{strategy_type}Strategy")
                
                try:
                    strategy = factory.create(config, name=default_name)
                    if strategy is None:
                        logger.error(f"Factory returned None for {strategy_type}")
                        continue
                    
                    strategies.append(strategy)
                    logger.debug(f"Initialized {default_name} via factory")
                except (RuntimeError, ValueError) as e:
                    logger.error(f"Failed to create {strategy_type} via factory: {e}", exc_info=True)
                    # Continue boot even if strategy fails
                    
            except Exception as e:
                logger.error(f"Failed to initialize {strategy_type}: {e}", exc_info=True)
                # Continue boot even if strategy fails
        
        logger.info(f"Initialized {len(strategies)} strategies via StrategyFactory")
        
        # Initialize storage and strategy manager
        logger.info("Initializing storage and strategy manager...")
        storage = get_storage()
        strategy_manager = get_strategy_manager(storage)
        
        # Register strategies - safe registration, skip broken ones
        for strategy in strategies:
            try:
                strategy_manager.register(strategy)
            except Exception as e:
                logger.error(f"Failed to register {strategy.__class__.__name__}: {e}", exc_info=True)
                # Continue boot even if registration fails
        
        # PHASE 1: Initialize order router first (starts with zero executors)
        logger.info("Initializing order router...")
        order_router = OrderRouter(config)
        logger.info("Order router initialized (no executors registered yet)")
        
        # Initialize broker manager (for health monitoring)
        logger.info("Initializing broker manager...")
        from sentinel_x.execution.broker_manager import get_broker_manager
        broker_manager = get_broker_manager()
        if order_router.paper_executor:
            broker_manager.register_broker(order_router.paper_executor)
        if order_router.alpaca_executor and order_router.alpaca_executor.connected:
            broker_manager.register_broker(order_router.alpaca_executor)
        
        # Initialize engine (with strategies, market_data, order_router)
        logger.info("Initializing trading engine...")
        engine = TradingEngine(
            config=config,
            strategies=strategies,
            market_data=market_data,
            order_router=order_router
        )
        
        # Register components with API server
        logger.info("Registering components with API server...")
        set_engine(engine)
        set_strategy_manager(strategy_manager)
        set_storage(storage)
        # Keep paper_executor for backwards compatibility (use router's executor)
        paper_executor = order_router.paper_executor
        if paper_executor:
            set_executor(paper_executor)
        set_order_router(order_router)
        
        # Start FastAPI server in background thread
        logger.info("Starting FastAPI control plane (Rork API)...")
        api_thread = threading.Thread(
            target=lambda: uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning"),
            daemon=True,
            name="FastAPI-Server"
        )
        api_thread.start()
        logger.info("FastAPI control plane started on http://0.0.0.0:8000")
        logger.info("API docs available at http://0.0.0.0:8000/docs")
        
        # PHASE 1: Engine boot defaults to PAPER mode (changed from RESEARCH)
        # The engine loop will run forever, starting in PAPER mode by default
        from sentinel_x.core.engine_mode import get_engine_mode, EngineMode
        current_mode = get_engine_mode()
        logger.info(f"Engine initialized: Starting in {current_mode.value} mode")
        if current_mode == EngineMode.PAPER:
            logger.info("PAPER trading mode active - orders will execute via Alpaca paper broker")
        
        # PHASE 3: Start the always-on loop ONCE at process boot
        # The loop runs until engine.killed == True
        # The loop is never restarted
        logger.info("=" * 60)
        logger.info("Starting always-on engine loop...")
        logger.info("=" * 60)
        
        # Run forever (loop starts here and never restarts)
        engine.run_forever()
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        try:
            from sentinel_x.core.state import set_state, BotState
            set_state(BotState.STOPPED)
        except:
            pass
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        try:
            from sentinel_x.core.state import set_state, BotState
            set_state(BotState.STOPPED)
        except:
            pass
        sys.exit(1)
    finally:
        logger.info("=" * 60)
        logger.info("Sentinel X Trading System - Stopped")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()

