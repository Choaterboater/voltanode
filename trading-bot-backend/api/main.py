"""FastAPI application with CORS and router registration."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import logging
from pathlib import Path

from fastapi import FastAPI

from utils.logging_config import setup_logging
from fastapi.middleware.cors import CORSMiddleware

from bot.config import BotConfig, AssetClass
from bot.engine import PaperTradingEngine, LiveTradingEngine, TickData
from data.cache import DataCache
from data.fetcher import MarketData
from strategies.base import BaseStrategy

# Import routers
from api.routes import portfolio, strategies, trades, backtest, market, advisor, settings, orders, news

logger = logging.getLogger("volta.api")


async def _run_tick_loop(app: FastAPI) -> None:
    """Background task that fetches prices and drives the engine tick loop."""
    engine: PaperTradingEngine | None = None
    # Wait until the engine is attached to app.state
    for _ in range(30):
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            break
        await asyncio.sleep(1)

    if engine is None:
        logger.error("Tick loop could not find engine on app.state")
        return

    config: BotConfig = getattr(app.state, "config", BotConfig())
    interval = config.engine.tick_interval_seconds if config else 5.0

    while True:
        try:
            if not engine.is_running:
                await asyncio.sleep(max(1.0, interval))
                continue

            if engine.market_data is None:
                await asyncio.sleep(interval)
                continue

            # Gather unique symbols and whether any strategy needs OHLCV
            symbol_specs: dict[str, tuple[str, AssetClass, bool]] = {}
            for account_id, strat_list in engine._strategies.items():
                for strategy in strat_list:
                    if not getattr(strategy, "is_active", True):
                        continue

                    symbol = strategy.config.get("symbol", "BTC")
                    asset_class_str = strategy.config.get("asset_class", "crypto").upper()
                    try:
                        asset_class = AssetClass[asset_class_str]
                    except KeyError:
                        asset_class = AssetClass.CRYPTO

                    cache_key = f"{symbol}_{asset_class.value}"
                    needs_ohlcv = strategy.on_tick.__func__ is BaseStrategy.on_tick
                    if cache_key in symbol_specs:
                        _, _, existing_needs = symbol_specs[cache_key]
                        symbol_specs[cache_key] = (symbol, asset_class, existing_needs or needs_ohlcv)
                    else:
                        symbol_specs[cache_key] = (symbol, asset_class, needs_ohlcv)

            for cache_key, (symbol, asset_class, needs_ohlcv) in symbol_specs.items():
                try:
                    price = await asyncio.wait_for(
                        engine.market_data.get_price(symbol, asset_class), timeout=10.0
                    )
                    tick = TickData(symbol=symbol, price=price)

                    ohlcv_data = None
                    if needs_ohlcv:
                        ohlcv_data = await asyncio.wait_for(
                            engine.market_data.get_ohlcv(
                                symbol, asset_class, timeframe="1d", limit=300
                            ),
                            timeout=15.0,
                        )

                    engine.on_tick(tick, ohlcv_data=ohlcv_data)
                except asyncio.TimeoutError:
                    logger.warning(f"Tick timeout for {cache_key}")
                except Exception as exc:
                    logger.warning(f"Tick error for {cache_key}: {exc}")

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception(f"Unexpected error in tick loop: {exc}")
            await asyncio.sleep(interval)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    import os

    # Setup structured logging early
    log_level = os.environ.get("BOT_APP__LOG_LEVEL", "INFO")
    json_logs = os.environ.get("BOT_APP__JSON_LOGS", "true").lower() == "true"
    setup_logging(level=log_level, json_format=json_logs)

    config_path = os.environ.get("BOT_CONFIG", "config.yaml")
    if os.path.exists(config_path):
        config = BotConfig.from_yaml(config_path)
    else:
        config = BotConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        """Application lifespan context manager."""
        # Startup
        cache = DataCache(cache_dir=str(Path(config.app.data_dir) / "cache"))
        market_data = MarketData(cache=cache, config=config)

        # Always create LiveTradingEngine with mock broker as default.
        # This allows seamless live mode toggling without engine swapping.
        from brokers.registry import get_broker
        broker = get_broker("mock")
        broker.connect("mock_key", "mock_secret")
        engine = LiveTradingEngine(config=config, broker=broker)
        engine.market_data = market_data

        # Set engine on routers
        portfolio.set_engine(engine)
        strategies.set_engine(engine)
        trades.set_engine(engine)
        orders.set_engine(engine)

        app.state.engine = engine
        app.state.config = config

        # Start background tick loop
        tick_task = asyncio.create_task(_run_tick_loop(app))

        yield

        # Shutdown
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass
        engine.stop()

    app = FastAPI(
        title="Paper Trading Bot API",
        version="1.0.0",
        description="REST API for paper trading bot management",
        lifespan=lifespan,
    )

    # CORS — permissive for local dev, strict for production
    origins = ["http://localhost:3000", "http://localhost:3001", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://127.0.0.1:5173"]
    if config.api and config.api.cors_origins:
        for o in config.api.cors_origins:
            if o not in origins:
                origins.append(o)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(portfolio.router, prefix="/portfolio", tags=["Portfolio"])
    app.include_router(strategies.router, prefix="/strategies", tags=["Strategies"])
    app.include_router(trades.router, prefix="/trades", tags=["Trades"])
    app.include_router(orders.router, prefix="/orders", tags=["Orders"])
    app.include_router(backtest.router, prefix="/backtest", tags=["Backtest"])
    app.include_router(market.router, prefix="/market", tags=["Market Data"])
    app.include_router(advisor.router, prefix="/advisor", tags=["Advisor"])
    app.include_router(settings.router, prefix="/settings", tags=["Settings"])
    app.include_router(news.router, prefix="/news", tags=["News"])

    # Initialize news module with config from environment
    try:
        from api.routes.news import init_news
        provider = os.environ.get("LLM_PROVIDER", "")
        init_news(
            api_key=os.environ.get("ALPACA_API_KEY", ""),
            api_secret=os.environ.get("ALPACA_SECRET_KEY", ""),
            llm_provider=provider,
            llm_api_key=os.environ.get("LLM_API_KEY", "") if provider.lower() != "ollama" else "",
            llm_model=os.environ.get("LLM_MODEL", ""),
        )
    except Exception:
        pass  # News is optional

    @app.get("/health")
    async def health_check() -> dict:
        """Health check endpoint."""
        return {"status": "ok", "version": "1.0.0"}

    @app.get("/engine/status")
    async def engine_status() -> dict:
        """Get engine status."""
        engine = getattr(app.state, "engine", None)
        if engine:
            return {
                "running": engine.is_running,
                "account_count": len(engine.get_all_portfolios()),
            }
        return {"running": False, "account_count": 0}

    @app.post("/engine/start")
    async def engine_start() -> dict:
        """Start the engine."""
        engine = getattr(app.state, "engine", None)
        if engine:
            engine.start()
            return {"status": "started"}
        return {"status": "error", "message": "Engine not initialized"}

    @app.post("/engine/stop")
    async def engine_stop() -> dict:
        """Stop the engine."""
        engine = getattr(app.state, "engine", None)
        if engine:
            engine.stop()
            return {"status": "stopped"}
        return {"status": "error", "message": "Engine not initialized"}

    return app


app = create_app()
