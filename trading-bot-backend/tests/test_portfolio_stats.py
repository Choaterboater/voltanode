"""Portfolio stats API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import portfolio
from bot.config import BotConfig
from bot.engine import PaperTradingEngine
from data.equity_history import EquityHistoryStore


def _client(engine: PaperTradingEngine, history: EquityHistoryStore) -> TestClient:
    portfolio.set_engine(engine)
    portfolio.set_equity_history(history)
    app = FastAPI()
    app.include_router(portfolio.router, prefix="/portfolio")
    return TestClient(app)


def test_portfolio_stats_returns_curve_and_metrics(tmp_path: Path) -> None:
    engine = PaperTradingEngine(BotConfig())
    history = EquityHistoryStore(tmp_path)
    history.append("default", 100_000.0, datetime(2026, 5, 1, tzinfo=timezone.utc))
    history.append("default", 101_000.0, datetime(2026, 5, 2, tzinfo=timezone.utc))
    history.append("default", 100_500.0, datetime(2026, 5, 3, tzinfo=timezone.utc))

    resp = _client(engine, history).get("/portfolio/default/stats?range=ALL")

    assert resp.status_code == 200
    body = resp.json()
    assert body["account_id"] == "default"
    assert len(body["equity_curve"]) == 3
    assert "sharpe_ratio" in body
    assert "max_drawdown_pct" in body
    assert "win_rate" in body


def test_portfolio_response_includes_broker_metadata() -> None:
    engine = PaperTradingEngine(BotConfig())
    resp = _client(engine, EquityHistoryStore(Path("data/equity_history"))).get("/portfolio/default")

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "paper"
    assert body["broker_connected"] is False
