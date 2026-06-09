"""P0 risk-overhaul fixes (audit 2026-06-09).

Covers the four money-relevant fixes shipped together:
1. Crypto taker fee is recorded on fills (was hardcoded 0.0 -> inflated P&L).
2. The kill switch exempts protective EXITS but still blocks entries.
3. The daily-loss tracker seeds a SELL's cost basis from open positions, so it
   isn't blind to losers held overnight / across a restart.
4. The profit manager no longer trims winners to 40% by default (it inverted
   the win/loss payoff); the full winner runs.
Plus a guard that the momentum bots inherit the regime gate from DEFAULT_CONFIG.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot.config import BotConfig, OrderSide, PositionSide
from bot.engine import LiveTradingEngine, PaperTradingEngine, TickData
from bot.orders import FillResult, Order
from brokers.alpaca import AlpacaBroker
from brokers.registry import get_broker
from safety.daily_tracker import DailyPnlTracker
from safety.kill_switch import KillSwitchError
from strategies.momentum import MomentumStrategy


@pytest.fixture
def config() -> BotConfig:
    return BotConfig()


def _fake_filled(qty: float, price: float) -> dict:
    return {
        "status": "filled",
        "filled_qty": str(qty),
        "filled_avg_price": str(price),
        "id": "broker-test-1",
    }


# ── 1. Crypto fee ────────────────────────────────────────────────────────────

class TestCryptoFee:
    def test_crypto_fill_charges_taker_fee(self, monkeypatch) -> None:
        broker = AlpacaBroker(paper=True, crypto_fee_rate=0.0025)
        broker._api_key = "k"
        broker._api_secret = "s"
        monkeypatch.setattr(broker, "_request", lambda *a, **k: _fake_filled(0.1, 50000.0))

        fill = broker.place_order(Order.market("BTC", OrderSide.BUY, 0.1, account_id="default"))

        # 0.1 * 50000 * 0.0025 = 12.5 — no longer silently 0.
        assert fill.fee == pytest.approx(0.1 * 50000.0 * 0.0025)
        assert fill.fee > 0

    def test_equity_fill_is_commission_free(self, monkeypatch) -> None:
        broker = AlpacaBroker(paper=True, crypto_fee_rate=0.0025)
        broker._api_key = "k"
        broker._api_secret = "s"
        monkeypatch.setattr(broker, "_request", lambda *a, **k: _fake_filled(10, 150.0))

        fill = broker.place_order(Order.market("AAPL", OrderSide.BUY, 10, account_id="default"))

        assert fill.fee == 0.0

    def test_engine_pushes_configured_rate_onto_broker(self, config: BotConfig) -> None:
        config.risk.crypto_fee_rate = 0.0015
        broker = get_broker("mock")
        broker.connect("k", "s")
        # MockBroker has no crypto_fee_rate attr -> the push is a no-op; use a
        # real adapter to assert the wiring.
        alpaca = AlpacaBroker(paper=True)
        eng = LiveTradingEngine(config=config, broker=alpaca)
        assert eng.broker.crypto_fee_rate == pytest.approx(0.0015)


# ── 2. Kill-switch exempts protective exits ──────────────────────────────────

class TestKillSwitchExemptsExits:
    def _engine(self, config: BotConfig) -> LiveTradingEngine:
        broker = get_broker("mock")
        broker.connect("test_key", "test_secret")
        return LiveTradingEngine(config=config, broker=broker)

    def test_entry_is_blocked_when_halted(self, config: BotConfig) -> None:
        eng = self._engine(config)
        eng.kill_switch.activate("daily loss limit")
        entry = Order.market("BTC", OrderSide.BUY, 0.01, account_id="default")
        with pytest.raises(KillSwitchError):
            eng.execute_order(entry, 50000.0)

    def test_protective_exit_not_blocked_when_halted(self, config: BotConfig) -> None:
        eng = self._engine(config)
        eng.kill_switch.activate("daily loss limit")
        # A protective close must NOT raise KillSwitchError — the daily-loss
        # halt exists to cap the loss, not to freeze the stops that do it.
        exit_order = Order.market(
            "BTC", OrderSide.SELL, 0.01, account_id="default", strategy_id="sltp_manager"
        )
        fill = eng.execute_order(exit_order, 50000.0)  # must not raise
        assert isinstance(fill, FillResult)


# ── 3. Daily-tracker cost-basis seeding ──────────────────────────────────────

def _sell(symbol: str, qty: float, price: float) -> FillResult:
    return FillResult(
        order_id="o1",
        symbol=symbol,
        filled_qty=qty,
        filled_price=price,
        fee=0.0,
        slippage=0.0,
        timestamp=datetime.now(timezone.utc),
        side=OrderSide.SELL,
        realized_pnl=None,
        broker_order_id="b1",
    )


class TestDailyTrackerSeeding:
    def test_seeds_basis_from_open_position(self) -> None:
        # Position opened before today / before restart: entry 100, now sold at 90.
        tracker = DailyPnlTracker(position_provider=lambda: {"BTC": (100.0, 1.0)})
        pnl = tracker.record(_sell("BTC", 1.0, 90.0))
        assert pnl == pytest.approx(-10.0)  # real loss, not masked to 0
        assert tracker.daily_pnl == pytest.approx(-10.0)

    def test_without_provider_falls_back_to_zero(self) -> None:
        tracker = DailyPnlTracker()  # no provider -> legacy fallback
        pnl = tracker.record(_sell("BTC", 1.0, 90.0))
        assert pnl == 0.0

    def test_today_basis_takes_priority_over_provider(self) -> None:
        # If we bought today, the tracked basis wins over the provider snapshot.
        from bot.orders import FillResult as FR

        tracker = DailyPnlTracker(position_provider=lambda: {"BTC": (100.0, 1.0)})
        buy = FR(
            order_id="b", symbol="BTC", filled_qty=1.0, filled_price=80.0,
            fee=0.0, slippage=0.0, timestamp=datetime.now(timezone.utc),
            side=OrderSide.BUY, realized_pnl=None, broker_order_id="x",
        )
        tracker.record(buy)
        pnl = tracker.record(_sell("BTC", 1.0, 90.0))
        assert pnl == pytest.approx(10.0)  # (90-80), today's basis, not provider's 100


# ── 4. Exit-sizing: full winner runs by default ──────────────────────────────

class TestExitSizing:
    def test_no_partial_trim_by_default(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        portfolio = engine.get_portfolio("default")
        portfolio.open_position("TEST", PositionSide.LONG, 100.0, 100.0, stop_loss=92.0, take_profit=108.0)

        engine.on_tick(TickData(symbol="TEST", price=108.0))  # +8%

        pos = portfolio.get_position("TEST")
        assert pos is not None
        assert pos.size == pytest.approx(100.0)  # full position retained
        assert not [o for o in engine.get_orders() if o.strategy_id == "partial_take_profit"]

    def test_trail_is_wider_than_loss_stop(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        portfolio = engine.get_portfolio("default")
        portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0, stop_loss=95.0)
        engine.on_tick(TickData(symbol="TEST", price=120.0))  # +20%, trail armed
        pos = portfolio.get_position("TEST")
        # Trail gives back 8% of the 120 high = 110.4, well above the 95 (5%)
        # loss stop — winners get more room than losers.
        assert pos.stop_loss == pytest.approx(120.0 * 0.92)


# ── 5. Regime gate inherited by the trend bots ───────────────────────────────

def test_momentum_inherits_regime_gate_from_default_config() -> None:
    # Registered-style config (no explicit regime_gate); inheritance via
    # {**DEFAULT_CONFIG, **config} must still leave the gate enabled.
    strat = MomentumStrategy("m1", {"symbols": ["BTC", "ETH"], "fast_ema": 12, "slow_ema": 26})
    rg = strat.config.get("regime_gate")
    assert rg and rg.get("enabled") is True
