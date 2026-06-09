"""Tests for the 2026-06-09 feature-edge overhaul.

Covers the six build items:
1. Drawdown halt lets position-REDUCING exits through (side-checked).
2. auto_discovery mid-band reset no longer wipes the 'entered' latch.
3. regime_gate default-on for macd / news_sentiment (config-merge semantics).
4. ATR-aware exits: per-position atr_stop_pct, hard-cap widening,
   breakeven/trail scaling, Position serialization.
5. Honest scoreboard: origin_strategy_id stamping + persistence + the
   trade-memory phantom-lot FIFO guard.
6. Auto-disable supervisor: bench rules, exclusions, re-bench watermark.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from bot.config import BotConfig, OrderSide, PositionSide
from bot.engine import PaperTradingEngine, TickData
from bot.orders import FillResult, Order
from bot.portfolio import Portfolio
from bot.risk import RiskManager


# ── helpers ──────────────────────────────────────────────────────────────────


def _mk_engine() -> PaperTradingEngine:
    engine = PaperTradingEngine(BotConfig())
    portfolio = engine.get_portfolio("default")
    portfolio.deposit("USD", 1_000_000.0)
    portfolio.deposit("USDT", 1_000_000.0)
    return engine


def _mk_fill(order: Order, qty: float, price: float) -> FillResult:
    return FillResult(
        order_id=order.id,
        symbol=order.symbol,
        filled_qty=qty,
        filled_price=price,
        fee=0.0,
        slippage=0.0,
        timestamp=datetime.now(timezone.utc),
        side=order.side,
    )


def _ohlcv(n: int = 40, price: float = 100.0, day_range: float = 4.0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [price] * n,
            "high": [price + day_range / 2] * n,
            "low": [price - day_range / 2] * n,
            "close": [price] * n,
            "volume": [1_000.0] * n,
        },
        index=idx,
    )


# ── 1. drawdown halt exit bypass ─────────────────────────────────────────────


class TestDrawdownHaltExitBypass:
    def _breached_rm(self) -> RiskManager:
        rm = RiskManager(BotConfig().risk)
        rm.drawdown_monitor.update(100_000.0)
        rm.drawdown_monitor.update(80_000.0)  # -20% > 10% cap
        assert rm.drawdown_monitor.is_breached()
        return rm

    def test_sell_against_long_allowed_and_clamped(self) -> None:
        rm = self._breached_rm()
        portfolio = Portfolio("default", {"USD": 10_000.0})
        portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0)
        order = Order.market("TEST", OrderSide.SELL, 15.0, account_id="default",
                             strategy_id="sltp_manager")
        result = rm.check_order(order, portfolio, current_price=90.0)
        assert result.allowed
        assert result.order.quantity == pytest.approx(10.0)  # clamped to held

    def test_buy_rejected_while_breached(self) -> None:
        rm = self._breached_rm()
        portfolio = Portfolio("default", {"USD": 10_000.0})
        order = Order.market("TEST", OrderSide.BUY, 1.0, account_id="default",
                             strategy_id="momentum_x")
        result = rm.check_order(order, portfolio, current_price=100.0)
        assert not result.allowed

    def test_sell_with_no_position_rejected(self) -> None:
        # A SELL that would OPEN a naked short is not an exit — same
        # side-blind defect family as bugs #13/#15; must stay halted.
        rm = self._breached_rm()
        portfolio = Portfolio("default", {"USD": 10_000.0})
        order = Order.market("TEST", OrderSide.SELL, 5.0, account_id="default",
                             strategy_id="momentum_x")
        result = rm.check_order(order, portfolio, current_price=100.0)
        assert not result.allowed

    def test_buy_closing_short_allowed(self) -> None:
        rm = self._breached_rm()
        portfolio = Portfolio("default", {"USD": 10_000.0})
        portfolio.open_position("TEST", PositionSide.SHORT, 8.0, 100.0)
        order = Order.market("TEST", OrderSide.BUY, 8.0, account_id="default",
                             strategy_id="sltp_manager")
        result = rm.check_order(order, portfolio, current_price=110.0)
        assert result.allowed

    def test_unbreached_behavior_unchanged(self) -> None:
        rm = RiskManager(BotConfig().risk)
        portfolio = Portfolio("default", {"USD": 10_000.0})
        order = Order.market("TEST", OrderSide.BUY, 1.0, account_id="default")
        assert rm.check_order(order, portfolio, current_price=100.0).allowed


# ── 2. auto_discovery exit latch ─────────────────────────────────────────────


class TestAutoDiscoveryExitLatch:
    def _strategy(self):
        from strategies.auto_discovery import AutoDiscoveryStrategy

        return AutoDiscoveryStrategy(
            "auto_discovery_test",
            {
                "symbols": ["TEST"],
                "entry_score": 40.0,
                "exit_score": 30.0,
                "min_hold_minutes": 0,
                "enable_llm_gate": False,
                "use_watchlist": False,
                # regime gate would need >=100 bars; not under test here
                "regime_gate": {"enabled": False},
            },
        )

    def _signal_at(self, strategy, monkeypatch, score: float, bars: int):
        import strategies.auto_discovery as ad

        stub = SimpleNamespace(score=score, direction="long", error=None, components={})
        monkeypatch.setattr(ad, "score_symbol", lambda *a, **k: stub)
        df = _ohlcv(n=bars)
        df.attrs["symbol"] = "TEST"
        return strategy.generate_signal(df, 100.0)

    def test_decay_through_midband_still_exits(self, monkeypatch) -> None:
        strategy = self._strategy()
        entered = self._signal_at(strategy, monkeypatch, 50.0, bars=20)
        assert entered.signal_type.value == "buy"
        assert strategy._last_side["TEST"] == "entered"

        # Mid-band (40 > 35 > 30): the latch must SURVIVE — pre-fix this
        # reset it to 'neutral' and disarmed the exit leg forever.
        mid = self._signal_at(strategy, monkeypatch, 35.0, bars=21)
        assert mid.signal_type.value == "hold"
        assert strategy._last_side["TEST"] == "entered"

        decayed = self._signal_at(strategy, monkeypatch, 25.0, bars=22)
        assert decayed.signal_type.value == "sell"
        assert decayed.metadata.get("trigger") == "score_decayed"

    def test_midband_reset_still_clears_exited_latch(self, monkeypatch) -> None:
        # Anti-churn intent preserved: after an exit, the mid-band pass
        # resets 'exited' -> 'neutral' so re-entry needs a fresh cross.
        strategy = self._strategy()
        self._signal_at(strategy, monkeypatch, 50.0, bars=20)
        self._signal_at(strategy, monkeypatch, 25.0, bars=21)
        assert strategy._last_side["TEST"] == "exited"
        self._signal_at(strategy, monkeypatch, 35.0, bars=22)
        assert strategy._last_side["TEST"] == "neutral"


# ── 3. regime_gate default-on for macd / news_sentiment ─────────────────────


class TestRegimeGateDefaults:
    def test_macd_default_config_has_gate(self) -> None:
        from strategies.macd import MACDStrategy

        s = MACDStrategy("macd_x", {"symbol": "TEST"})
        assert s.config["regime_gate"]["enabled"] is True

    def test_news_sentiment_default_config_has_gate(self) -> None:
        from strategies.news_sentiment import NewsSentimentStrategy

        s = NewsSentimentStrategy("news_x", {"symbol": "TEST"})
        assert s.config["regime_gate"]["enabled"] is True

    def test_explicit_disable_wins_merge(self) -> None:
        from strategies.macd import MACDStrategy

        s = MACDStrategy("macd_x", {"symbol": "TEST", "regime_gate": {"enabled": False}})
        assert s.config["regime_gate"]["enabled"] is False

    def test_gate_blocks_buy_in_downtrend(self) -> None:
        from bot.config import SignalType
        from strategies.macd import MACDStrategy
        from strategies.base import Signal

        s = MACDStrategy("macd_x", {"symbol": "TEST", "regime_gate": {"enabled": True, "trend_ema": 100}})
        # 120 bars trending down hard: latest close far below EMA-100.
        n = 120
        closes = [200.0 - i for i in range(n)]
        df = pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes,
             "volume": [1.0] * n},
            index=pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC"),
        )
        buy = Signal(
            strategy_id="macd_x", symbol="TEST", signal_type=SignalType.BUY,
            confidence=0.9, timestamp=datetime.now(timezone.utc),
        )
        gated = s._apply_regime_gate(buy, df)
        assert gated.signal_type == SignalType.HOLD
        assert gated.metadata["trigger"] == "regime_gate"

        sell = Signal(
            strategy_id="macd_x", symbol="TEST", signal_type=SignalType.SELL,
            confidence=0.9, timestamp=datetime.now(timezone.utc),
        )
        assert s._apply_regime_gate(sell, df).signal_type == SignalType.SELL


# ── 4. ATR-aware exits ───────────────────────────────────────────────────────


class TestAtrAwareExits:
    def test_floor_records_atr_stop_pct(self) -> None:
        engine = _mk_engine()
        portfolio = engine.get_portfolio("default")
        pos = portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0)
        engine._apply_atr_stop_floor(pos, _ohlcv(day_range=4.0))
        # ATR ~4 -> 2.5*4/100 = 10%
        assert pos.atr_stop_pct == pytest.approx(0.10, abs=0.02)
        assert pos.stop_loss is not None

    def test_hard_cap_honors_wider_atr_stop(self) -> None:
        engine = _mk_engine()
        engine._max_position_loss_pct = 0.06
        portfolio = engine.get_portfolio("default")
        # Wide explicit stop so only the cap path can close it.
        pos = portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0,
                                      stop_loss=50.0, take_profit=200.0)
        pos.atr_stop_pct = 0.10

        engine.on_tick(TickData(symbol="TEST", price=92.0))  # -8%: inside ATR band
        pos = portfolio.get_position("TEST")
        assert pos is not None and pos.status == "open"

        engine.on_tick(TickData(symbol="TEST", price=89.0))  # -11%: past 10% ATR cap
        pos = portfolio.get_position("TEST")
        assert pos is None or pos.status != "open" or pos.size == pytest.approx(0.0)

    def test_hard_cap_backstop_without_atr(self) -> None:
        engine = _mk_engine()
        engine._max_position_loss_pct = 0.06
        portfolio = engine.get_portfolio("default")
        portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0,
                                stop_loss=50.0, take_profit=200.0)
        engine.on_tick(TickData(symbol="TEST", price=93.0))  # -7% > 6% cap
        pos = portfolio.get_position("TEST")
        assert pos is None or pos.status != "open" or pos.size == pytest.approx(0.0)

    def test_narrow_atr_never_shrinks_cap(self) -> None:
        engine = _mk_engine()
        engine._max_position_loss_pct = 0.06
        portfolio = engine.get_portfolio("default")
        pos = portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0,
                                      stop_loss=50.0, take_profit=200.0)
        pos.atr_stop_pct = 0.03  # narrower than the cap
        engine.on_tick(TickData(symbol="TEST", price=95.0))  # -5%: within 6% cap
        pos = portfolio.get_position("TEST")
        assert pos is not None and pos.status == "open"

    def test_breakeven_scales_with_atr(self) -> None:
        engine = _mk_engine()
        portfolio = engine.get_portfolio("default")
        pos = portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0,
                                      stop_loss=90.0, take_profit=200.0)
        pos.atr_stop_pct = 0.07  # breakeven arms at 1.25*7% = 8.75%

        engine._profit_manager_order(pos, TickData(symbol="TEST", price=105.0), "default")
        assert pos.stop_loss == pytest.approx(90.0)  # +5% < 8.75%: untouched

        engine._profit_manager_order(pos, TickData(symbol="TEST", price=109.0), "default")
        assert pos.stop_loss >= 100.0  # +9% > 8.75%: at least breakeven

    def test_breakeven_default_without_atr(self) -> None:
        engine = _mk_engine()
        portfolio = engine.get_portfolio("default")
        pos = portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0,
                                      stop_loss=90.0, take_profit=200.0)
        engine._profit_manager_order(pos, TickData(symbol="TEST", price=104.5), "default")
        assert pos.stop_loss == pytest.approx(100.2)  # +4.5% arms default +4% breakeven

    def test_position_serialization_roundtrip(self) -> None:
        portfolio = Portfolio("default", {"USD": 1_000.0})
        pos = portfolio.open_position("TEST", PositionSide.LONG, 1.0, 100.0)
        pos.atr_stop_pct = 0.08
        pos.opened_by_strategy_id = "mean_reversion_1"
        d = pos.to_dict()
        assert d["atr_stop_pct"] == pytest.approx(0.08)
        assert d["opened_by_strategy_id"] == "mean_reversion_1"

    def test_pm_knobs_read_from_config(self) -> None:
        config = BotConfig()
        config.risk.pm_breakeven_pct = 0.05
        config.risk.pm_trail_giveback_pct = 0.11
        engine = PaperTradingEngine(config)
        assert engine._pm_breakeven_pct == pytest.approx(0.05)
        assert engine._pm_trail_giveback_pct == pytest.approx(0.11)
        assert engine._pm_partial_enabled is False


# ── 5. honest scoreboard ─────────────────────────────────────────────────────


class TestOriginAttribution:
    def test_exit_fill_inherits_opener(self) -> None:
        engine = _mk_engine()
        portfolio = engine.get_portfolio("default")

        buy = Order.market("TEST", OrderSide.BUY, 10.0, account_id="default",
                           strategy_id="mean_reversion_1")
        engine._update_portfolio_on_fill(buy, _mk_fill(buy, 10.0, 100.0), portfolio)
        pos = portfolio.get_position("TEST")
        assert pos.opened_by_strategy_id == "mean_reversion_1"

        sell = Order.market("TEST", OrderSide.SELL, 10.0, account_id="default",
                            strategy_id="sltp_manager")
        fill = _mk_fill(sell, 10.0, 95.0)
        engine._update_portfolio_on_fill(sell, fill, portfolio)

        assert fill.origin_strategy_id == "mean_reversion_1"
        trade = engine._trades[-1]
        assert trade.strategy_id == "sltp_manager"          # who placed the exit
        assert trade.origin_strategy_id == "mean_reversion_1"  # who owns the P&L

    def test_average_up_keeps_first_opener(self) -> None:
        engine = _mk_engine()
        portfolio = engine.get_portfolio("default")
        b1 = Order.market("TEST", OrderSide.BUY, 5.0, account_id="default",
                          strategy_id="bot_a")
        engine._update_portfolio_on_fill(b1, _mk_fill(b1, 5.0, 100.0), portfolio)
        b2 = Order.market("TEST", OrderSide.BUY, 5.0, account_id="default",
                          strategy_id="bot_b")
        engine._update_portfolio_on_fill(b2, _mk_fill(b2, 5.0, 102.0), portfolio)
        assert portfolio.get_position("TEST").opened_by_strategy_id == "bot_a"

    def test_origin_survives_fills_persistence(self, tmp_path) -> None:
        engine = _mk_engine()
        engine.set_fills_persistence(tmp_path / "fills.jsonl")
        portfolio = engine.get_portfolio("default")

        buy = Order.market("TEST", OrderSide.BUY, 10.0, account_id="default",
                           strategy_id="mean_reversion_1")
        fill = _mk_fill(buy, 10.0, 100.0)
        engine._update_portfolio_on_fill(buy, fill, portfolio)
        engine._persist_fill(fill, strategy_id="mean_reversion_1")

        engine2 = _mk_engine()
        engine2.set_fills_persistence(tmp_path / "fills.jsonl")
        assert engine2._trades[-1].origin_strategy_id == "mean_reversion_1"
        assert engine2._fills[-1].origin_strategy_id == "mean_reversion_1"


class TestPhantomLotGuard:
    def test_recorded_pnl_reanchors_fifo(self, tmp_path) -> None:
        from learning.trade_memory import TradeMemory

        fills_path = tmp_path / "fills.jsonl"
        rows = [
            # Phantom lot the broker never held (TARA 5/27 incident shape).
            {"order_id": "o1", "symbol": "TARA", "filled_qty": 1034.69,
             "filled_price": 4.81, "fee": 0.0, "slippage": 0.0,
             "timestamp": "2026-05-27T18:52:06+00:00", "side": "buy",
             "realized_pnl": None, "broker_order_id": "b1",
             "strategy_id": "capital_allocator"},
            # The real lot.
            {"order_id": "o2", "symbol": "TARA", "filled_qty": 874.866286,
             "filled_price": 4.34, "fee": 0.0, "slippage": 0.0,
             "timestamp": "2026-06-03T13:30:23+00:00", "side": "buy",
             "realized_pnl": None, "broker_order_id": "b2",
             "strategy_id": "capital_allocator"},
            # Exit carrying the engine's broker-true realized P&L (-$306.20,
            # computed off the 4.34 basis at execution time).
            {"order_id": "o3", "symbol": "TARA", "filled_qty": 874.866286,
             "filled_price": 3.99, "fee": 0.0, "slippage": 0.0,
             "timestamp": "2026-06-09T14:50:59+00:00", "side": "sell",
             "realized_pnl": -306.20, "broker_order_id": "b3",
             "strategy_id": "sltp_manager"},
        ]
        fills_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                              encoding="utf-8")

        tm = TradeMemory(memory_path=str(tmp_path / "memory.jsonl"),
                         vault_dir=str(tmp_path / "vault"))
        n = tm.backfill_from_fills(fills_path=str(fills_path))
        assert n >= 1
        recs = tm.all()
        tara = [r for r in recs if r["symbol"] == "TARA"]
        assert len(tara) == 1
        # Blind FIFO would book (3.99-4.81)*874.87 = -$717 off the phantom
        # 4.81 lot; the guard re-anchors to the 4.34 lot -> ~-$306.
        assert tara[0]["entry_price"] == pytest.approx(4.34)
        assert tara[0]["pnl"] == pytest.approx(-306.2, abs=1.0)

    def test_plain_fifo_when_no_recorded_pnl(self, tmp_path) -> None:
        from learning.trade_memory import TradeMemory

        fills_path = tmp_path / "fills.jsonl"
        rows = [
            {"order_id": "o1", "symbol": "AAA", "filled_qty": 10.0,
             "filled_price": 100.0, "fee": 0.0, "slippage": 0.0,
             "timestamp": "2026-06-01T00:00:00+00:00", "side": "buy",
             "realized_pnl": None, "broker_order_id": "", "strategy_id": "bot_a"},
            {"order_id": "o2", "symbol": "AAA", "filled_qty": 10.0,
             "filled_price": 110.0, "fee": 0.0, "slippage": 0.0,
             "timestamp": "2026-06-02T00:00:00+00:00", "side": "buy",
             "realized_pnl": None, "broker_order_id": "", "strategy_id": "bot_a"},
            {"order_id": "o3", "symbol": "AAA", "filled_qty": 10.0,
             "filled_price": 105.0, "fee": 0.0, "slippage": 0.0,
             "timestamp": "2026-06-03T00:00:00+00:00", "side": "sell",
             "realized_pnl": None, "broker_order_id": "", "strategy_id": "bot_a"},
        ]
        fills_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                              encoding="utf-8")
        tm = TradeMemory(memory_path=str(tmp_path / "memory.jsonl"),
                         vault_dir=str(tmp_path / "vault"))
        tm.backfill_from_fills(fills_path=str(fills_path))
        recs = tm.all()
        # Oldest lot first, unchanged legacy semantics.
        assert recs[0]["entry_price"] == pytest.approx(100.0)


# ── 6. auto-disable supervisor ───────────────────────────────────────────────


def _round_trips(strategy: str, wins: int, losses: int,
                 win_pnl: float = 10.0, loss_pnl: float = -40.0) -> list:
    out = []
    for i in range(wins):
        out.append({"strategy": strategy, "pnl": win_pnl, "symbol": "T"})
    for i in range(losses):
        out.append({"strategy": strategy, "pnl": loss_pnl, "symbol": "T"})
    return out


class TestSupervisor:
    def _supervisor(self, tmp_path):
        from learning.supervisor import StrategySupervisor

        return StrategySupervisor(state_path=tmp_path / "state.json")

    def test_benches_proven_loser(self, tmp_path) -> None:
        sup = self._supervisor(tmp_path)
        records = _round_trips("bot_a", wins=4, losses=8)  # PF = 40/320 = 0.125
        bot = SimpleNamespace(is_active=True)
        persisted = []
        actions = sup.run(records, {"bot_a": bot},
                          persist=lambda: persisted.append(1))
        assert bot.is_active is False
        assert len(actions) == 1 and actions[0]["strategy_id"] == "bot_a"
        assert persisted  # registry persisted
        assert (tmp_path / "state.json").exists()

    def test_too_few_trades_untouched(self, tmp_path) -> None:
        sup = self._supervisor(tmp_path)
        records = _round_trips("bot_a", wins=1, losses=8)  # only 9 trades
        bot = SimpleNamespace(is_active=True)
        actions = sup.run(records, {"bot_a": bot}, persist=lambda: None)
        assert bot.is_active is True and not actions

    def test_protective_ids_never_evaluated(self, tmp_path) -> None:
        sup = self._supervisor(tmp_path)
        records = _round_trips("sltp_manager", wins=0, losses=30)
        bot = SimpleNamespace(is_active=True)
        actions = sup.run(records, {"sltp_manager": bot}, persist=lambda: None)
        assert bot.is_active is True and not actions

    def test_positive_edge_untouched(self, tmp_path) -> None:
        sup = self._supervisor(tmp_path)
        records = _round_trips("bot_a", wins=8, losses=4,
                               win_pnl=50.0, loss_pnl=-10.0)  # PF = 10
        bot = SimpleNamespace(is_active=True)
        actions = sup.run(records, {"bot_a": bot}, persist=lambda: None)
        assert bot.is_active is True and not actions

    def test_manual_reenable_needs_fresh_evidence(self, tmp_path) -> None:
        sup = self._supervisor(tmp_path)
        records = _round_trips("bot_a", wins=4, losses=8)
        bot = SimpleNamespace(is_active=True)
        sup.run(records, {"bot_a": bot}, persist=lambda: None)
        assert bot.is_active is False

        bot.is_active = True  # operator re-enables
        actions = sup.run(records, {"bot_a": bot}, persist=lambda: None)
        assert bot.is_active is True and not actions  # same stale evidence

        # 5 fresh losing round trips later: bench again.
        fresh = records + _round_trips("bot_a", wins=0, losses=5)
        actions = sup.run(fresh, {"bot_a": bot}, persist=lambda: None)
        assert bot.is_active is False and len(actions) == 1

    def test_watermark_survives_restart(self, tmp_path) -> None:
        from learning.supervisor import StrategySupervisor

        records = _round_trips("bot_a", wins=4, losses=8)
        bot = SimpleNamespace(is_active=True)
        sup1 = StrategySupervisor(state_path=tmp_path / "state.json")
        sup1.run(records, {"bot_a": bot}, persist=lambda: None)
        bot.is_active = True  # operator re-enables, then backend restarts

        sup2 = StrategySupervisor(state_path=tmp_path / "state.json")
        actions = sup2.run(records, {"bot_a": bot}, persist=lambda: None)
        assert bot.is_active is True and not actions

    def test_stats_reports_unbenched_and_no_evidence(self, tmp_path) -> None:
        sup = self._supervisor(tmp_path)
        records = _round_trips("bot_a", wins=4, losses=8)
        bot_a = SimpleNamespace(is_active=True)
        bot_b = SimpleNamespace(is_active=True)  # no closed trades yet
        rows = sup.stats(records, {"bot_a": bot_a, "bot_b": bot_b})
        by_id = {r["strategy_id"]: r for r in rows}
        assert by_id["bot_a"]["n"] == 12
        assert by_id["bot_b"]["n"] == 0 and by_id["bot_b"]["profit_factor"] is None
