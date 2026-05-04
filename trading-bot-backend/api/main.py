"""FastAPI application with CORS and router registration."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import logging
from pathlib import Path

# Load .env (e.g. VOLTANODE_SECRET_KEY) before anything else reads os.environ.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI

from utils.logging_config import setup_logging
from fastapi.middleware.cors import CORSMiddleware

from bot.config import BotConfig, AssetClass
from bot.engine import PaperTradingEngine, LiveTradingEngine, TickData
from data.cache import DataCache
from data.equity_history import EquityHistoryStore
from data.fetcher import MarketData
from strategies.base import BaseStrategy

# Import routers
from api.routes import portfolio, strategies, trades, backtest, market, advisor, settings, orders, news, signals

logger = logging.getLogger("volta.api")


async def _run_news_loop(app: FastAPI) -> None:
    """Background task: periodically fetch Alpaca news + score sentiment.

    Runs every 5 min. Skips silently if news module isn't initialized
    (e.g. no Alpaca keys). Scoring uses VADER if no LLM is configured.
    """
    # Wait for lifespan to finish wiring app.state.engine
    for _ in range(30):
        if hasattr(app.state, "engine"):
            break
        await asyncio.sleep(1)

    while True:
        try:
            try:
                from api.routes import news as news_routes
                fetcher = news_routes._get_fetcher()
                storage = news_routes._get_storage()
                engine_n = news_routes._get_engine()
                if fetcher is None or not (fetcher.api_key and fetcher.api_secret):
                    pass
                else:
                    articles = await asyncio.to_thread(
                        fetcher.fetch, None, 50, 24
                    )
                    new_count = 0
                    analyzed_count = 0
                    for article in articles:
                        # Only score newly-saved articles. Articles already in
                        # storage have already been scored — re-running burns
                        # GPU cycles and creates duplicate sentiment rows.
                        is_new = storage.save_article(article)
                        if not is_new:
                            continue
                        new_count += 1
                        try:
                            results = engine_n.analyze(article)
                            for r in results:
                                storage.save_sentiment(r)
                                analyzed_count += 1
                        except Exception as exc:
                            logger.warning(f"Sentiment analysis failed for article {article.id}: {exc}")
                    if articles:
                        logger.info(
                            f"News loop: fetched={len(articles)} new={new_count} "
                            f"analyzed={analyzed_count}"
                        )
            except Exception as exc:
                logger.warning(f"News loop iteration failed: {exc}")

            await asyncio.sleep(300)  # 5 min
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception(f"Unexpected error in news loop: {exc}")
            await asyncio.sleep(300)


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

            # Gather unique (symbol, asset_class) pairs across all active
            # strategies. Each strategy may declare multiple symbols via
            # config.symbols (list) or a single config.symbol.
            symbol_specs: dict[str, tuple[str, AssetClass, bool]] = {}
            for account_id, strat_list in engine._strategies.items():
                for strategy in strat_list:
                    if not getattr(strategy, "is_active", True):
                        continue

                    asset_class_str = strategy.config.get("asset_class", "crypto").upper()
                    try:
                        asset_class = AssetClass[asset_class_str]
                    except KeyError:
                        asset_class = AssetClass.CRYPTO

                    # Resolve the strategy's configured symbol list.
                    if hasattr(strategy, "configured_symbols"):
                        scoped = strategy.configured_symbols()
                    else:
                        scoped = []
                    if not scoped:
                        scoped = [strategy.config.get("symbol", "BTC")]

                    needs_ohlcv = strategy.on_tick.__func__ is BaseStrategy.on_tick
                    for symbol in scoped:
                        cache_key = f"{symbol}_{asset_class.value}"
                        if cache_key in symbol_specs:
                            _, _, existing_needs = symbol_specs[cache_key]
                            symbol_specs[cache_key] = (symbol, asset_class, existing_needs or needs_ohlcv)
                        else:
                            symbol_specs[cache_key] = (symbol, asset_class, needs_ohlcv)

            # Build SignalContext once per tick cycle so per-strategy gates
            # (VIX panic, earnings imminent, insider tone) share the same data
            # rather than each strategy hitting external APIs independently.
            try:
                from signals import build_signal_context
                signal_context = build_signal_context()
            except Exception as exc:
                logger.debug(f"signal context build failed: {exc}")
                signal_context = None

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

                    engine.on_tick(tick, ohlcv_data=ohlcv_data, signal_context=signal_context)
                except asyncio.TimeoutError:
                    logger.warning(f"Tick timeout for {cache_key}")
                except Exception as exc:
                    logger.warning(f"Tick error for {cache_key}: {exc}")

            # Record an equity snapshot for each account (throttled to once
            # per minute per account regardless of tick frequency).
            history = getattr(app.state, "equity_history", None)
            if history is not None:
                for account_id, portfolio in engine.get_all_portfolios().items():
                    try:
                        balances = portfolio.get_all_balances()
                        positions = portfolio.get_all_positions()
                        equity = sum(balances.values()) + sum(p.market_value for p in positions)
                        # If broker is live, prefer broker-reported equity
                        if getattr(engine, "live_mode", False) and getattr(engine, "broker", None) and engine.broker.is_connected() and engine.broker.name != "mock":
                            try:
                                broker_bal = engine.get_broker_balance()
                                if broker_bal and "EQUITY" in broker_bal:
                                    equity = float(broker_bal["EQUITY"])
                            except Exception:
                                pass
                        history.append_throttled(account_id, equity)
                    except Exception as exc:
                        logger.warning(f"Equity snapshot failed for {account_id}: {exc}")

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

        # Restore the broker the user last had configured. If live_mode is
        # enabled in config and a real broker has stored encrypted keys, connect
        # to it on startup. Otherwise fall back to the mock broker (which
        # supports seamless live-mode toggling without engine swapping).
        from brokers.registry import get_broker

        broker = None
        if (
            config.live_mode.enabled
            and config.live_mode.default_broker
            and config.live_mode.default_broker != "mock"
        ):
            broker_name = config.live_mode.default_broker
            broker_cfg = config.brokers.get(broker_name)
            if broker_cfg and broker_cfg.api_key_encrypted and broker_cfg.api_secret_encrypted:
                try:
                    from security.encryption import ApiKeyStore
                    key_store = ApiKeyStore.from_env()
                    real_broker = get_broker(broker_name)
                    api_key = key_store.decrypt(broker_cfg.api_key_encrypted)
                    api_secret = key_store.decrypt(broker_cfg.api_secret_encrypted)
                    real_broker.connect(
                        api_key, api_secret,
                        testnet=getattr(broker_cfg, "testnet", True),
                        paper=getattr(broker_cfg, "paper", True),
                    )
                    broker = real_broker
                    logger.info(f"Restored live broker on startup: {broker_name}")
                except Exception as exc:
                    logger.warning(
                        f"Could not restore live broker '{broker_name}' on startup: {exc}. "
                        "Falling back to mock."
                    )

        if broker is None:
            broker = get_broker("mock")
            broker.connect("mock_key", "mock_secret")

        engine = LiveTradingEngine(config=config, broker=broker)
        engine.market_data = market_data

        # Set engine on routers
        portfolio.set_engine(engine)
        strategies.set_engine(engine)
        trades.set_engine(engine)
        orders.set_engine(engine)

        # Persistent equity-curve store, one append-only file per account.
        history_dir = Path(config.app.data_dir) / "equity_history"
        equity_history = EquityHistoryStore(history_dir)
        app.state.equity_history = equity_history
        portfolio.set_equity_history(equity_history)

        app.state.engine = engine
        app.state.config = config

        # Start engine so the tick loop actually drives strategies.
        # Without this, _running stays False and on_tick is never called.
        engine.start()

        # Restore persisted bots so they survive restarts.
        try:
            restored = strategies.restore_strategies(engine)
            if restored:
                logger.info(f"Restored {restored} bot(s) from disk")
        except Exception as exc:
            logger.warning(f"Could not restore bots from disk: {exc}")

        # Start background tick loop
        tick_task = asyncio.create_task(_run_tick_loop(app))
        # Start background news fetcher (Alpaca + sentiment)
        news_task = asyncio.create_task(_run_news_loop(app))

        yield

        # Shutdown
        tick_task.cancel()
        news_task.cancel()
        for task in (tick_task, news_task):
            try:
                await task
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
    app.include_router(signals.router, prefix="/signals", tags=["Signals"])

    # Initialize news module — prefer encrypted Alpaca keys from config.yaml
    # (the same set the user entered in Settings); fall back to env vars.
    try:
        from api.routes.news import init_news
        provider = os.environ.get("LLM_PROVIDER", "")

        alpaca_key = os.environ.get("ALPACA_API_KEY", "")
        alpaca_sec = os.environ.get("ALPACA_SECRET_KEY", "")
        if not (alpaca_key and alpaca_sec):
            try:
                from security.encryption import ApiKeyStore
                broker_cfg = config.brokers.get("alpaca")
                if broker_cfg and broker_cfg.api_key_encrypted and broker_cfg.api_secret_encrypted:
                    key_store = ApiKeyStore.from_env()
                    alpaca_key = key_store.decrypt(broker_cfg.api_key_encrypted)
                    alpaca_sec = key_store.decrypt(broker_cfg.api_secret_encrypted)
                    logger.info("News: using Alpaca keys decrypted from config")
            except Exception as exc:
                logger.warning(f"News: could not decrypt Alpaca keys from config: {exc}")

        init_news(
            api_key=alpaca_key,
            api_secret=alpaca_sec,
            llm_provider=provider,
            llm_api_key=os.environ.get("LLM_API_KEY", "") if provider.lower() != "ollama" else "",
            llm_model=os.environ.get("LLM_MODEL", ""),
        )
    except Exception as exc:
        logger.warning(f"News init failed: {exc}")

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
