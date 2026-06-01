"""Backtest realism fixes:

1. SELL while flat (shorting off) must NOT inject phantom cash / inflate equity.
2. win-rate / avg_trade_return denominate over CLOSED round-trips, not entries.
3. long-only (allow_short=False) never opens a short position.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bot.config import SignalType
from backtest.engine import BacktestConfig, BacktestRunner
from backtest.metrics import BacktestMetrics, TradeRecord
from strategies.base import BaseStrategy, Signal


def _flat_ohlcv(n: int = 30) -> pd.DataFrame:
    closes = np.full(n, 100.0)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="D"),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": np.full(n, 1000.0),
    })


class _AlwaysSell(BaseStrategy):
    """Emits SELL every bar — used to probe the flat-SELL path."""
    name = "always_sell"

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=data.attrs.get("symbol", "BTC"),
            signal_type=SignalType.SELL,
            confidence=1.0,
            timestamp=pd.Timestamp.now(),
            suggested_size=1.0,
        )


def test_flat_sell_long_only_does_not_inflate_equity():
    """Long-only: SELL while flat is a no-op — equity stays at the start balance."""
    cfg = BacktestConfig(initial_balance={"USDT": 10_000.0}, fee_rate=0.0, slippage_bps=0.0, allow_short=False)
    result = BacktestRunner(_AlwaysSell("s1", {}), _flat_ohlcv(), cfg).run()
    final_equity = result.equity_curve["equity"].iloc[-1]
    assert final_equity == pytest.approx(10_000.0, abs=1e-6)  # no phantom cash
    # No long ever opened, and shorting off -> no positions, no closed trades.
    assert result.metrics.to_dict()["closed_trades"] == 0


def test_long_only_opens_no_short():
    """allow_short=False -> the SELL path never creates a short position."""
    cfg = BacktestConfig(initial_balance={"USDT": 10_000.0}, fee_rate=0.0, slippage_bps=0.0, allow_short=False)
    result = BacktestRunner(_AlwaysSell("s2", {}), _flat_ohlcv(), cfg).run()
    assert result.metrics.total_return_pct == pytest.approx(0.0, abs=1e-6)


def test_win_rate_denominates_over_closes_not_entries():
    """3 entries (0 P&L) + 2 closes (1 win, 1 loss) -> 50%, not 1/5=20%."""
    eq = pd.DataFrame({"timestamp": pd.date_range("2025-01-01", periods=3), "equity": [10000.0, 10100.0, 10050.0], "drawdown": [0.0, 0.0, 0.5]})
    trades = [
        TradeRecord(pd.Timestamp.now(), 0.0, "buy", 1.0, 100.0, is_entry=True),
        TradeRecord(pd.Timestamp.now(), 0.0, "buy", 1.0, 100.0, is_entry=True),
        TradeRecord(pd.Timestamp.now(), 0.0, "buy", 1.0, 100.0, is_entry=True),
        TradeRecord(pd.Timestamp.now(), 200.0, "sell", 1.0, 120.0),   # win
        TradeRecord(pd.Timestamp.now(), -80.0, "sell", 1.0, 95.0),    # loss
    ]
    m = BacktestMetrics(eq, trades)
    assert m.win_rate == pytest.approx(50.0)          # 1 of 2 closes, NOT 1 of 5
    assert m.to_dict()["closed_trades"] == 2
    assert m.to_dict()["total_trades"] == 5           # all orders still counted


class _AlwaysBuyHuge(BaseStrategy):
    """Tries to BUY an absurd size every bar — probes the buying-power cap."""
    name = "always_buy_huge"

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=data.attrs.get("symbol", "BTC"),
            signal_type=SignalType.BUY,
            confidence=1.0,
            timestamp=pd.Timestamp.now(),
            suggested_size=1e9,  # way more than cash affords
        )


def test_buy_capped_to_cash_bounds_drawdown_under_100pct():
    """A leveraged dip-buyer is the bug that produced >100% drawdowns. With the
    buying-power cap, a price that halves can lose at most ~its long exposure —
    drawdown stays well under 100%."""
    closes = np.linspace(100.0, 50.0, 40)  # price halves over the window
    df = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=40, freq="D"),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": np.full(40, 1000.0),
    })
    cfg = BacktestConfig(initial_balance={"USDT": 10_000.0}, fee_rate=0.0, slippage_bps=0.0, allow_short=False)
    result = BacktestRunner(_AlwaysBuyHuge("b1", {}), df, cfg).run()
    assert result.metrics.max_drawdown_pct < 100.0   # no leverage blowup
    assert result.metrics.max_drawdown_pct <= 60.0   # ~50% (fully invested, price halves)


class _BuyTightTP(BaseStrategy):
    """BUYs every bar with a tight (20 bps) take-profit — probes the cost gate."""
    name = "buy_tight_tp"

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=data.attrs.get("symbol", "BTC"),
            signal_type=SignalType.BUY,
            confidence=1.0,
            timestamp=pd.Timestamp.now(),
            suggested_size=0.5,
            take_profit=current_price * 1.002,  # 20 bps — below a 45 bps cost bar
        )


def test_cost_gate_applies_in_backtest_when_enabled():
    """Paper-to-live fidelity: the on_tick cost gate now runs in the backtest.
    Off -> trades happen; on (tight TP can't clear round-trip cost) -> blocked."""
    closes = np.linspace(100.0, 110.0, 30)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=30, freq="D"),
        "open": closes, "high": closes * 1.001, "low": closes * 0.999,
        "close": closes, "volume": np.full(30, 1000.0),
    })
    cfg = BacktestConfig(initial_balance={"USDT": 10_000.0}, fee_rate=0.001, slippage_bps=5.0, allow_short=False)

    off = BacktestRunner(_BuyTightTP("off", {}), df.copy(), cfg).run().metrics.to_dict()
    on = BacktestRunner(
        _BuyTightTP("on", {"cost_gate": {"enabled": True, "round_trip_bps": 30.0, "margin": 1.5}}),
        df.copy(), cfg,
    ).run().metrics.to_dict()

    assert off["total_trades"] > 0    # without the gate it trades
    assert on["total_trades"] == 0    # gate blocks every BUY (TP 20bps < 45bps bar)


def test_position_aware_rebuy_suppressed_in_backtest():
    """Mirror live on_tick: while already long, repeated BUYs are suppressed
    (one entry, no adds) — instead of the old add-on-every-bar that inflated
    trade counts and returns."""
    closes = np.linspace(100.0, 110.0, 20)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=20, freq="D"),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": np.full(20, 1000.0),
    })
    cfg = BacktestConfig(initial_balance={"USDT": 10_000.0}, fee_rate=0.0, slippage_bps=0.0, allow_short=False)
    r = BacktestRunner(_AlwaysBuyHuge("rb", {}), df, cfg).run().metrics.to_dict()
    assert r["total_trades"] == 1    # one entry; further BUYs suppressed while long
    assert r["closed_trades"] == 0   # never sold


class _BuyOnceWithRisk(BaseStrategy):
    """BUYs once on bar 1 with a 5% stop + 10% take-profit, then holds."""
    name = "buy_once_risk"

    def __init__(self, sid, cfg):
        super().__init__(sid, cfg)
        self._done = False

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        sym = data.attrs.get("symbol", "AAPL")
        if self._done:
            return Signal(strategy_id=self.strategy_id, symbol=sym, signal_type=SignalType.HOLD, confidence=0.0, timestamp=pd.Timestamp.now())
        self._done = True
        return Signal(
            strategy_id=self.strategy_id, symbol=sym, signal_type=SignalType.BUY,
            confidence=1.0, timestamp=pd.Timestamp.now(), suggested_size=1.0,
            stop_loss=current_price * 0.95, take_profit=current_price * 1.10,
        )


def _bars(rows):
    df = pd.DataFrame(rows)
    df.attrs["symbol"] = "AAPL"
    return df


def test_backtest_enforces_stop_loss():
    # bar1 buy @100 (stop=95); bar2 dips to low 94 -> stop fires ~95.
    df = _bars([
        {"timestamp": pd.Timestamp("2025-01-01"), "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1e3},
        {"timestamp": pd.Timestamp("2025-01-02"), "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1e3},
        {"timestamp": pd.Timestamp("2025-01-03"), "open": 99, "high": 100, "low": 94, "close": 96, "volume": 1e3},
    ])
    cfg = BacktestConfig(initial_balance={"USDT": 10_000.0}, fee_rate=0.0, slippage_bps=0.0, allow_short=False)
    r = BacktestRunner(_BuyOnceWithRisk("s", {}), df, cfg).run().metrics.to_dict()
    assert r["closed_trades"] == 1               # the stop closed the position
    assert -5.5 < r["avg_trade_return"] < -4.5   # ~ -$5 realized (stop 95 from entry 100, 1 unit)


def test_backtest_enforces_take_profit():
    df = _bars([
        {"timestamp": pd.Timestamp("2025-01-01"), "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1e3},
        {"timestamp": pd.Timestamp("2025-01-02"), "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1e3},
        {"timestamp": pd.Timestamp("2025-01-03"), "open": 105, "high": 112, "low": 104, "close": 111, "volume": 1e3},
    ])
    cfg = BacktestConfig(initial_balance={"USDT": 10_000.0}, fee_rate=0.0, slippage_bps=0.0, allow_short=False)
    r = BacktestRunner(_BuyOnceWithRisk("s", {}), df, cfg).run().metrics.to_dict()
    assert r["closed_trades"] == 1
    assert 9.5 < r["avg_trade_return"] < 10.5   # ~ +$10 realized (TP 110 from entry 100, 1 unit)


def test_win_rate_empty_and_all_entries_is_zero():
    eq = pd.DataFrame({"timestamp": pd.date_range("2025-01-01", periods=2), "equity": [10000.0, 10000.0], "drawdown": [0.0, 0.0]})
    assert BacktestMetrics(eq, []).win_rate == 0.0
    only_entries = [TradeRecord(pd.Timestamp.now(), 0.0, "buy", 1.0, 100.0, is_entry=True)]
    assert BacktestMetrics(eq, only_entries).win_rate == 0.0
