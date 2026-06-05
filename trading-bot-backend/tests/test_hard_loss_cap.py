"""Hard per-position loss cap: force-close a position past the cap even when
its own strategy stop is wider. Backstops the tail that sank realized P&L."""
from __future__ import annotations

import pytest

from bot.config import BotConfig, PositionSide
from bot.engine import PaperTradingEngine, TickData


def _engine_with_position(stop_loss: float) -> PaperTradingEngine:
    engine = PaperTradingEngine(BotConfig())
    engine._max_position_loss_pct = 0.10  # 10% hard cap, regardless of config
    portfolio = engine.get_portfolio("default")
    # Wide strategy stop (-20%) so ONLY the hard cap can fire in these tests.
    portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0,
                            stop_loss=stop_loss, take_profit=200.0)
    return engine


def test_force_closes_past_cap() -> None:
    engine = _engine_with_position(stop_loss=80.0)  # -20% strategy stop
    engine.on_tick(TickData(symbol="TEST", price=88.0))  # -12%: past 10% cap, not the 80 stop
    pos = engine.get_portfolio("default").get_position("TEST")
    assert pos is None or pos.status != "open" or pos.size == pytest.approx(0.0)


def test_holds_within_cap() -> None:
    engine = _engine_with_position(stop_loss=80.0)
    engine.on_tick(TickData(symbol="TEST", price=95.0))  # -5%: within cap and stop
    pos = engine.get_portfolio("default").get_position("TEST")
    assert pos is not None and pos.status == "open"
