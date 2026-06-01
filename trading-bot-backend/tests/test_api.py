"""HTTP API regression tests (trades order, flatten ledger, safety propagation)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import portfolio, settings, trades
from bot.config import BotConfig, OrderSide
from bot.engine import LiveTradingEngine, PaperTradingEngine, TickData, Trade
from bot.orders import Order
from brokers.registry import get_broker


@pytest.fixture
def bot_config_path(tmp_path, monkeypatch):
    """Isolate safety POST persistence from the repo config.yaml."""
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("BOT_CONFIG", str(path))
    return path


@pytest.fixture
def paper_api(bot_config_path) -> tuple[TestClient, PaperTradingEngine, BotConfig]:
    config = BotConfig()
    engine = PaperTradingEngine(config)
    engine.start()
    portfolio.set_engine(engine)
    trades.set_engine(engine)

    app = FastAPI()
    app.state.engine = engine
    app.state.config = config
    app.include_router(portfolio.router, prefix="/portfolio")
    app.include_router(trades.router, prefix="/trades")
    return TestClient(app), engine, config


@pytest.fixture
def live_api(bot_config_path) -> tuple[TestClient, LiveTradingEngine, BotConfig]:
    config = BotConfig()
    config.safety.max_exposure_pct = 50.0
    config.safety.max_orders_per_minute = 10
    broker = get_broker("mock")
    broker.connect("test_key", "test_secret")
    engine = LiveTradingEngine(config=config, broker=broker)
    engine.start()
    portfolio.set_engine(engine)
    trades.set_engine(engine)

    app = FastAPI()
    app.state.engine = engine
    app.state.config = config
    app.include_router(portfolio.router, prefix="/portfolio")
    app.include_router(trades.router, prefix="/trades")
    app.include_router(settings.router, prefix="/settings")
    return TestClient(app), engine, config


class TestTradesApi:
    def test_trades_newest_first(self, paper_api: tuple) -> None:
        client, engine, _config = paper_api
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(3):
            engine._trades.append(
                Trade(
                    id=str(uuid.uuid4()),
                    order_id=f"order-{i}",
                    strategy_id="test",
                    symbol="BTC",
                    side="buy",
                    quantity=0.01,
                    price=100.0 + i,
                    fee=0.0,
                    realized_pnl=None,
                    timestamp=base + timedelta(minutes=i),
                )
            )

        resp = client.get("/trades/?limit=3")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 3
        assert rows[0]["price"] == 102.0
        assert rows[2]["price"] == 100.0


class TestFlattenApi:
    def test_flatten_records_trade_in_ledger(self, paper_api: tuple) -> None:
        client, engine, _config = paper_api
        engine._current_prices["BTC"] = 65000.0
        buy = Order.market("BTC", OrderSide.BUY, 0.1, strategy_id="seed_buy")
        engine.submit_order(buy)
        engine.on_tick(TickData(symbol="BTC", price=65000.0))

        resp = client.post("/portfolio/default/flatten?symbols=BTC")
        assert resp.status_code == 200
        body = resp.json()
        assert body["closed"], f"expected closed symbols, got {body}"

        trades_resp = client.get("/trades/?limit=50")
        assert trades_resp.status_code == 200
        ledger = trades_resp.json()
        assert any(t.get("strategy_id") == "manual_flatten" for t in ledger)


class TestSafetyApi:
    def test_safety_post_propagates_to_validator(self, live_api: tuple) -> None:
        client, engine, config = live_api
        assert engine.safety_validator.config.max_exposure_pct == 50.0

        resp = client.post(
            "/settings/safety",
            json={"max_exposure_pct": 175.0, "max_orders_per_minute": 60},
        )
        assert resp.status_code == 200
        assert resp.json()["max_exposure_pct"] == 175.0

        assert engine.safety_validator.config.max_exposure_pct == 175.0
        assert engine.safety_validator.rate_limiter.max_per_minute == 60
        assert config.safety.max_exposure_pct == 175.0

        status = client.get("/settings/safety-status")
        assert status.status_code == 200
        limits = status.json()["safety_limits"]
        assert limits["max_exposure_pct"] == 175.0
        assert limits["max_orders_per_minute"] == 60
