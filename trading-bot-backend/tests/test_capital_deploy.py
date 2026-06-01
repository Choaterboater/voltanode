"""Capital deployment allocator API tests."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import strategies
from api.routes.strategies import (
    _has_real_position,
    _held_share_class_roots,
    _merge_deploy_candidates,
)
from bot.config import BotConfig, PositionSide
from bot.engine import PaperTradingEngine
from bot.orders import OrderStatus


def _client(engine: PaperTradingEngine) -> TestClient:
    strategies.set_engine(engine)
    app = FastAPI()
    app.state.engine = engine
    app.state.config = engine.config
    app.include_router(strategies.router, prefix="/strategies")
    return TestClient(app)


def _mock_deploy_sources(monkeypatch, scanner_rows, long_term_rows=None) -> None:
    lt_rows = long_term_rows if long_term_rows is not None else scanner_rows

    async def fake_scanner(**kwargs):
        return {"elapsed_ms": 1, "results": scanner_rows}

    async def fake_long_term(**kwargs):
        return {"elapsed_ms": 1, "results": lt_rows}

    async def fake_squeeze(**kwargs):
        return {"elapsed_ms": 1, "results": []}

    monkeypatch.setattr("api.routes.advisor.market_scanner", fake_scanner)
    monkeypatch.setattr("api.routes.advisor.long_term_screener", fake_long_term)
    monkeypatch.setattr("api.routes.advisor.squeeze_screener", fake_squeeze)


def test_capital_deploy_dry_run_skips_held_symbol(monkeypatch) -> None:
    engine = PaperTradingEngine(BotConfig())
    portfolio = engine.get_portfolio("default")
    portfolio.open_position("BTCUSD", PositionSide.LONG, 0.1, 50_000.0)

    _mock_deploy_sources(
        monkeypatch,
        [
            {"symbol": "BTC", "score": 80.0, "direction": "long", "current_price": 50_000.0},
            {"symbol": "DOGE", "score": 70.0, "direction": "long", "current_price": 0.15},
        ],
    )
    resp = _client(engine).post("/strategies/capital-deploy?dry_run=true&asset_class=crypto")

    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["deployed"][0]["symbol"] == "DOGE"
    assert any(s["symbol"] == "BTC" and s["reason"] == "already_held" for s in body["skipped"])


def test_capital_deploy_places_buy_order(monkeypatch) -> None:
    engine = PaperTradingEngine(BotConfig())

    _mock_deploy_sources(
        monkeypatch,
        [{"symbol": "DOGE", "score": 70.0, "direction": "long", "current_price": 0.15}],
    )
    resp = _client(engine).post("/strategies/capital-deploy?max_new_positions=1&asset_class=crypto")

    assert resp.status_code == 200
    body = resp.json()
    assert body["deployed"][0]["symbol"] == "DOGE"
    assert body["deployed"][0]["status"] == "filled"
    position = engine.get_portfolio("default").get_position("DOGE")
    assert position is not None
    assert position.size > 0
    assert position.stop_loss is not None
    assert position.take_profit is not None


def test_capital_deploy_skips_rejected_and_tries_next(monkeypatch) -> None:
    engine = PaperTradingEngine(BotConfig())
    original_execute = engine.execute_order

    def execute_with_first_reject(order, current_price):
        if order.symbol == "BAD":
            order.status = OrderStatus.REJECTED
            return None
        return original_execute(order, current_price)

    engine.execute_order = execute_with_first_reject  # type: ignore[method-assign]

    _mock_deploy_sources(
        monkeypatch,
        [
            {"symbol": "BAD", "score": 80.0, "direction": "long", "current_price": 10.0},
            {"symbol": "DOGE", "score": 70.0, "direction": "long", "current_price": 0.15},
        ],
    )
    resp = _client(engine).post("/strategies/capital-deploy?max_new_positions=1&asset_class=crypto")

    assert resp.status_code == 200
    body = resp.json()
    assert body["deployed"][0]["symbol"] == "DOGE"
    assert any(s["symbol"] == "BAD" and s["reason"] == "broker_rejected" for s in body["skipped"])


def test_capital_deploy_counts_pending_as_deployed(monkeypatch) -> None:
    engine = PaperTradingEngine(BotConfig())

    def execute_pending(order, current_price):
        order.status = OrderStatus.PENDING
        engine.submit_order(order)
        return None

    engine.execute_order = execute_pending  # type: ignore[method-assign]

    _mock_deploy_sources(
        monkeypatch,
        [{"symbol": "DOGE", "score": 70.0, "direction": "long", "current_price": 0.15}],
    )
    resp = _client(engine).post("/strategies/capital-deploy?max_new_positions=1&asset_class=crypto")

    assert resp.status_code == 200
    body = resp.json()
    assert body["deployed"][0]["symbol"] == "DOGE"
    assert body["deployed"][0]["status"] == "pending"
    assert not body["skipped"]


def test_capital_deploy_skips_single_source_candidates(monkeypatch) -> None:
    engine = PaperTradingEngine(BotConfig())

    _mock_deploy_sources(
        monkeypatch,
        [{"symbol": "DOGE", "score": 70.0, "direction": "long", "current_price": 0.15}],
        long_term_rows=[],
    )
    resp = _client(engine).post("/strategies/capital-deploy?max_new_positions=1&asset_class=crypto")

    assert resp.status_code == 200
    body = resp.json()
    assert body["deployed"] == []
    assert any(
        s.get("symbol") == "DOGE" and s.get("reason") == "insufficient_sources"
        for s in body["skipped"]
    )


def test_has_real_position_checks_live_broker_symbols() -> None:
    engine = PaperTradingEngine(BotConfig())

    assert _has_real_position(
        engine.get_portfolio("default"),
        "MOD",
        broker_positions=[{"symbol": "MOD", "size": 16.5}],
    )


def test_share_class_roots_detect_goog_googl() -> None:
    engine = PaperTradingEngine(BotConfig())
    portfolio = engine.get_portfolio("default")
    portfolio.open_position("GOOGL", PositionSide.LONG, 1.0, 100.0)

    roots = _held_share_class_roots(portfolio, None)
    assert "GOOG" in roots


def test_merge_deploy_candidates_rewards_multi_source_confirmation() -> None:
    ranked = _merge_deploy_candidates([
        {
            "source": "scanner",
            "weight": 1.0,
            "rows": [
                {"symbol": "AAA", "score": 40, "current_price": 10},
                {"symbol": "BBB", "score": 42, "current_price": 20},
            ],
        },
        {
            "source": "long_term",
            "weight": 0.5,
            "rows": [
                {"symbol": "AAA", "score": 50, "current_price": 10},
            ],
        },
    ])

    assert ranked[0]["symbol"] == "AAA"
    assert set(ranked[0]["sources"]) == {"long_term", "scanner"}
    assert ranked[0]["score"] > ranked[1]["score"]
