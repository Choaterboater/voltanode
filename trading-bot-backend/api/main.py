"""FastAPI application with CORS and router registration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.config import BotConfig
from bot.engine import PaperTradingEngine, LiveTradingEngine
from data.cache import DataCache
from data.fetcher import MarketData

# Import routers
from api.routes import portfolio, strategies, trades, backtest, market, advisor, settings, orders


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    import os
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

        # Use LiveTradingEngine if live mode is enabled and broker is configured
        if config.live_mode.enabled and config.live_mode.default_broker != "mock":
            from brokers.registry import get_broker
            try:
                broker = get_broker(config.live_mode.default_broker)
                broker_cfg = config.brokers.get(config.live_mode.default_broker)
                if broker_cfg and broker_cfg.api_key_encrypted and broker_cfg.api_secret_encrypted:
                    from security.encryption import ApiKeyStore
                    key_store = ApiKeyStore.from_env()
                    api_key = key_store.decrypt(broker_cfg.api_key_encrypted)
                    api_secret = key_store.decrypt(broker_cfg.api_secret_encrypted)
                    broker.connect(
                        api_key, api_secret,
                        testnet=getattr(broker_cfg, "testnet", True),
                        paper=getattr(broker_cfg, "paper", True),
                    )
                engine = LiveTradingEngine(config=config, broker=broker)
            except Exception as exc:
                logger = logging.getLogger("volta.api")
                logger.warning(f"Failed to initialize live engine: {exc}. Falling back to paper.")
                engine = PaperTradingEngine(config=config, market_data=market_data)
        else:
            engine = PaperTradingEngine(config=config, market_data=market_data)
        
        # Set engine on routers
        portfolio.set_engine(engine)
        strategies.set_engine(engine)
        trades.set_engine(engine)
        orders.set_engine(engine)
        
        app.state.engine = engine
        app.state.config = config
        
        yield
        
        # Shutdown
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
