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

import pandas as pd
import pytest

from backtest.engine import BacktestConfig, BacktestRunner
from backtest.metrics import BacktestMetrics
from bot.config import BotConfig, OrderSide, PositionSide
from bot.engine import LiveTradingEngine, PaperTradingEngine, TickData
from bot.orders import FillResult, Order
from bot.portfolio import Portfolio, Position
from brokers.alpaca import AlpacaBroker
from brokers.registry import get_broker
from safety.daily_tracker import DailyPnlTracker
from safety.kill_switch import KillSwitchError
from strategies.base import Signal, SignalType
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


# ── 6. ATR-adaptive stop floor (timeframe-mismatch fix) ──────────────────────

def _flat_ohlcv(half_range: float, n: int = 20, close: float = 100.0) -> pd.DataFrame:
    """OHLCV with a flat close and a fixed high/low band, so the true range is
    a constant 2*half_range -> ATR == 2*half_range (deterministic for tests)."""
    return pd.DataFrame(
        {
            "high": [close + half_range] * n,
            "low": [close - half_range] * n,
            "close": [close] * n,
        }
    )


class TestAtrAdaptiveStops:
    def _pos(self, stop: float | None) -> Position:
        return Position(
            symbol="BTC", side=PositionSide.LONG, size=1.0,
            entry_price=100.0, current_price=100.0, stop_loss=stop,
        )

    def test_widens_a_tight_stop_to_the_atr_floor(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        pos = self._pos(98.0)  # 2% stop — tighter than the ~5% ATR floor
        engine._apply_atr_stop_floor(pos, _flat_ohlcv(1.0))  # ATR=2 -> 2.5*2/100 = 5%
        assert pos.stop_loss == pytest.approx(95.0)

    def test_never_tightens_a_wider_stop(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        pos = self._pos(90.0)  # 10% — already wider than the ATR floor
        engine._apply_atr_stop_floor(pos, _flat_ohlcv(1.0))
        assert pos.stop_loss == pytest.approx(90.0)

    def test_clamped_to_max_pct(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        pos = self._pos(99.0)
        engine._apply_atr_stop_floor(pos, _flat_ohlcv(10.0))  # ATR=20 -> 50%, clamp to 12%
        assert pos.stop_loss == pytest.approx(88.0)

    def test_clamped_to_min_pct(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        pos = self._pos(99.5)
        engine._apply_atr_stop_floor(pos, _flat_ohlcv(0.05))  # ATR=0.1 -> 0.25%, clamp to 3%
        assert pos.stop_loss == pytest.approx(97.0)

    def test_noop_without_ohlcv(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        pos = self._pos(98.0)
        engine._apply_atr_stop_floor(pos, None)  # no data -> legacy fixed stop kept
        assert pos.stop_loss == pytest.approx(98.0)

    def test_disabled_is_noop(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        engine._atr_stop_enabled = False
        pos = self._pos(98.0)
        engine._apply_atr_stop_floor(pos, _flat_ohlcv(1.0))
        assert pos.stop_loss == pytest.approx(98.0)


# ── 7. Backtest fidelity — match the live fee + ATR-stop model ───────────────

class TestBacktestFidelity:
    def test_backtest_uses_crypto_fee_for_crypto_asset_class(self) -> None:
        strat = MomentumStrategy("bt-crypto", {"asset_class": "crypto", "fast_ema": 5, "slow_ema": 10})
        runner = BacktestRunner(strat, _flat_ohlcv(1.0, n=30), BacktestConfig(initial_balance={"USDT": 10000.0}))
        assert runner._is_crypto is True
        assert runner.execution.fee_rate == pytest.approx(0.0025)

    def test_backtest_uses_equity_fee_for_non_crypto(self) -> None:
        strat = MomentumStrategy("bt-stock", {"asset_class": "stock", "fast_ema": 5, "slow_ema": 10})
        runner = BacktestRunner(strat, _flat_ohlcv(1.0, n=30), BacktestConfig(initial_balance={"USDT": 10000.0}))
        assert runner._is_crypto is False
        assert runner.execution.fee_rate == pytest.approx(0.001)

    def test_backtest_widens_a_tight_stop_via_atr(self) -> None:
        strat = MomentumStrategy("bt-atr", {"fast_ema": 5, "slow_ema": 10})
        data = _flat_ohlcv(1.0, n=30)  # ATR=2 at ~100 -> ~5% floor
        runner = BacktestRunner(strat, data, BacktestConfig(initial_balance={"USDT": 100000.0}))
        portfolio = Portfolio("backtest", {"USDT": 100000.0})
        positions: dict = {}
        sig = Signal(
            strategy_id="bt-atr", symbol="BTC", signal_type=SignalType.BUY,
            confidence=0.8, timestamp=pd.Timestamp.now(),
            suggested_size=1.0, stop_loss=98.0, take_profit=130.0,  # tight 2% stop
        )
        runner._execute_signal(sig, 100.0, portfolio, positions, "USDT", ohlcv=data)
        pos = positions.get("BTC")
        assert pos is not None
        # The 2% strategy stop is widened toward the ~5% ATR floor (~95).
        assert pos["stop_loss"] < 97.0
        assert pos["stop_loss"] > 93.0


# ── 8. Phantom-short fix on unmatched SELLs (audit bug #6) ────────────────────

class TestPhantomShortFix:
    def _live_engine(self, config: BotConfig) -> LiveTradingEngine:
        broker = get_broker("mock")
        broker.connect("k", "s")
        return LiveTradingEngine(config=config, broker=broker)

    def _sell_fill(self) -> FillResult:
        return FillResult(
            order_id="o", symbol="BTC", filled_qty=1.0, filled_price=90.0,
            fee=0.0, slippage=0.0, timestamp=datetime.now(timezone.utc),
            side=OrderSide.SELL, realized_pnl=None, broker_order_id="b",
        )

    def test_unmatched_sell_realizes_pnl_from_broker_basis(self, config: BotConfig) -> None:
        eng = self._live_engine(config)
        portfolio = eng.get_portfolio("default")
        eng._pending_close_basis["BTC"] = 100.0  # captured by the SELL-guard
        order = Order.market("BTC", OrderSide.SELL, 1.0, account_id="default")
        fill = self._sell_fill()
        eng._update_portfolio_on_fill(order, fill, portfolio)
        # Real loss recorded (90-100)*1, not None -> counts in win-rate/PF.
        assert fill.realized_pnl == pytest.approx(-10.0)
        pos = portfolio.get_position("BTC")
        assert pos is None or pos.side.value != "short"  # no phantom short

    def test_unmatched_sell_records_zero_not_none_when_basis_unknown(self, config: BotConfig) -> None:
        eng = self._live_engine(config)
        portfolio = eng.get_portfolio("default")
        order = Order.market("BTC", OrderSide.SELL, 1.0, account_id="default")
        fill = self._sell_fill()
        eng._update_portfolio_on_fill(order, fill, portfolio)
        assert fill.realized_pnl == 0.0  # not None -> still counted, just 0
        pos = portfolio.get_position("BTC")
        assert pos is None or pos.side.value != "short"


# ── 9. Backtest Sharpe annualization inferred from bar spacing (audit bug #8) ─

def _equity_df(step_seconds: float, n: int = 50) -> pd.DataFrame:
    base = pd.Timestamp("2024-01-01")
    return pd.DataFrame(
        {
            "timestamp": [base + pd.Timedelta(seconds=step_seconds * i) for i in range(n)],
            "equity": [100.0 + 0.1 * i for i in range(n)],
        }
    )


class TestBacktestAnnualization:
    def test_periods_per_year_hourly(self) -> None:
        m = BacktestMetrics(_equity_df(3600.0), [])
        assert m._periods_per_year() == pytest.approx(8760.0, rel=0.02)

    def test_periods_per_year_daily(self) -> None:
        m = BacktestMetrics(_equity_df(86400.0), [])
        assert m._periods_per_year() == pytest.approx(365.0, rel=0.02)

    def test_defaults_to_252_without_timestamps(self) -> None:
        df = pd.DataFrame({"equity": [100.0 + 0.1 * i for i in range(50)]})
        assert BacktestMetrics(df, [])._periods_per_year() == pytest.approx(252.0)

    def test_sharpe_scales_with_bar_frequency(self) -> None:
        # Identical returns, finer bars -> higher annualized Sharpe (the bug was
        # treating 1h bars as daily, understating it ~6x).
        hourly = BacktestMetrics(_equity_df(3600.0), []).sharpe_ratio
        daily = BacktestMetrics(_equity_df(86400.0), []).sharpe_ratio
        assert hourly > daily > 0


# ── 10. Momentum symmetric exit (audit bug #4) ───────────────────────────────

def _cross_down_data() -> pd.DataFrame:
    # Rise 100->129 over 30 bars, then drop to 100 on the last bar so the fast
    # EMA crosses below the slow EMA exactly on the final bar (a cross-down).
    closes = [100.0 + i for i in range(30)] + [100.0]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        }
    )
    df.attrs["symbol"] = "BTC"
    return df


class TestMomentumSymmetricExit:
    _CFG = {"fast_ema": 5, "slow_ema": 10, "trend_filter_ema": 20}

    def test_legacy_exits_on_any_cross_down(self) -> None:
        # exit_requires_trend_break=False reproduces the old behaviour AND
        # confirms the fixture actually produces a cross-down on the last bar.
        strat = MomentumStrategy("m", {**self._CFG, "exit_requires_trend_break": False})
        sig = strat.generate_signal(_cross_down_data(), current_price=140.0)  # above trend
        assert sig.signal_type == SignalType.SELL

    def test_cross_down_in_uptrend_holds(self) -> None:
        # Default (require trend break): a cross-down while price is still above
        # the trend EMA is a pullback -> HOLD, not a churning full exit.
        strat = MomentumStrategy("m", self._CFG)
        sig = strat.generate_signal(_cross_down_data(), current_price=140.0)  # above trend
        assert sig.signal_type == SignalType.HOLD

    def test_cross_down_below_trend_sells(self) -> None:
        # Confirmed trend break (price below the trend EMA) still exits.
        strat = MomentumStrategy("m", self._CFG)
        sig = strat.generate_signal(_cross_down_data(), current_price=90.0)  # below trend
        assert sig.signal_type == SignalType.SELL

    def test_gradual_breakdown_still_exits(self) -> None:
        # The cross-down happened bars ago (last bar is bearish but NOT a fresh
        # cross edge); price is now below the trend EMA. The fix must still emit
        # a SELL here — the original edge-only logic would silently HOLD forever.
        closes = [100.0 + i for i in range(30)] + [130.0 - 3.0 * i for i in range(1, 13)]
        df = pd.DataFrame({
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        })
        df.attrs["symbol"] = "BTC"
        strat = MomentumStrategy("m", self._CFG)
        sig = strat.generate_signal(df, current_price=closes[-1])  # ~94, below trend EMA
        assert sig.signal_type == SignalType.SELL


# ── 11. CPCV/DSR promotion gate default-on (audit feature) ───────────────────

def test_promotion_gate_enabled_by_default() -> None:
    # The Sharpe-annualization fix (#8) makes the gate trustworthy, so it now
    # defaults ON — apply-hyperopt must clear CPCV/DSR (force=true overrides).
    assert BotConfig().promotion_gate.enabled is True
