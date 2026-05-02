"""FastAPI application with CORS and router registration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import logging
from pathlib import Path

from fastapi import FastAPI

from utils.logging_config import setup_logging
from fastapi.middleware.cors import CORSMiddleware

from bot.config import BotConfig
from bot.engine import PaperTradingEngine, LiveTradingEngine
from data.cache import DataCache
from data.fetcher import MarketData

# Import routers
from api.routes import portfolio, strategies, trades, backtest, market, advisor, settings, orders, news


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
