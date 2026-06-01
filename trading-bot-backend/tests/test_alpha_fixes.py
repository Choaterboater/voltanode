"""Regression tests for the Tier-1 alpha/safety fixes:

1. Daily-loss circuit breaker compares a percent-of-equity (not dollars-vs-%).
2. Strategy SELL signals close the FULL held position (agentic exit), not a
   fresh equity-% notional.
3. The news -> trade bridge: aggregated sentiment from storage populates the
   live NewsSentimentStrategy cache and actually produces a tradeable signal.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bot.config import OrderSide, SignalType
from bot.orders import Order, ExecutionSimulator
from bot.portfolio import Portfolio, PositionSide
from safety.limits import SafetyConfig, SafetyValidationError, SafetyValidator
from strategies.base import BaseStrategy, Signal, TickData
from strategies.news_sentiment import NewsSentimentStrategy
from news.models import NewsArticle, SentimentResult
from news.storage import NewsStorage


# ── 1. Daily-loss unit conversion ──────────────────────────────────────────


def _funded_portfolio(cash: float = 100_000.0) -> Portfolio:
    return Portfolio("default", {"USD": cash})


def test_daily_loss_breaker_trips_on_percent_not_dollars() -> None:
    """A $6k loss on a $100k book is 6% > 5% cap -> reject."""
    portfolio = _funded_portfolio(100_000.0)
    validator = SafetyValidator(SafetyConfig(max_daily_loss_pct=5.0))
    order = Order.limit("ETH", OrderSide.BUY, 0.001, price=3_000.0)
    with pytest.raises(SafetyValidationError, match="Daily loss"):
        validator.validate_order(order, portfolio, daily_pnl=-6_000.0, current_price=3_000.0)


def test_small_dollar_loss_does_not_trip_breaker() -> None:
    """The old code tripped at a $5 loss; $3k on $100k is 3% < 5% -> allowed."""
    portfolio = _funded_portfolio(100_000.0)
    validator = SafetyValidator(SafetyConfig(max_daily_loss_pct=5.0))
    order = Order.limit("ETH", OrderSide.BUY, 0.001, price=3_000.0)
    # Should NOT raise — this is well under the 5% cap.
    validator.validate_order(order, portfolio, daily_pnl=-3_000.0, current_price=3_000.0)


# ── 2. Agentic full-quantity exit ──────────────────────────────────────────


class _ExitStrategy(BaseStrategy):
    """Minimal strategy that emits a SELL sized far smaller than the position."""

    name = "exit_test"

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=data.attrs.get("symbol", "BTC"),
            signal_type=SignalType.SELL,
            confidence=0.9,
            timestamp=pd.Timestamp.now(),
            suggested_size=0.01,  # tiny equity-% notional, NOT the held qty
        )


def _ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [10.0, 11.0, 12.0],
        }
    )


def test_exit_sell_closes_full_position() -> None:
    portfolio = Portfolio("default", {"USD": 10_000.0})
    portfolio.open_position("BTC", PositionSide.LONG, 5.0, 50_000.0)
    portfolio.get_position("BTC").update_price(50_000.0)

    strat = _ExitStrategy("exit1", {})
    tick = TickData(symbol="BTC", price=50_000.0)
    out = strat.on_tick(tick, portfolio, ohlcv_data=_ohlcv())

    assert out is not None
    assert out.signal_type == SignalType.SELL
    # Full close: sized to the held 5.0, not the 0.01 the strategy proposed.
    assert out.suggested_size == pytest.approx(5.0)


def test_explicit_partial_sell_is_not_upsized() -> None:
    portfolio = Portfolio("default", {"USD": 10_000.0})
    portfolio.open_position("BTC", PositionSide.LONG, 5.0, 50_000.0)
    portfolio.get_position("BTC").update_price(50_000.0)

    class _PartialStrategy(_ExitStrategy):
        def generate_signal(self, data, current_price):
            sig = super().generate_signal(data, current_price)
            sig.suggested_size = 1.0
            sig.metadata = {"partial": True}
            return sig

    strat = _PartialStrategy("partial1", {})
    out = strat.on_tick(TickData(symbol="BTC", price=50_000.0), portfolio, ohlcv_data=_ohlcv())
    assert out.signal_type == SignalType.SELL
    assert out.suggested_size == pytest.approx(1.0)  # left as the partial intent


# ── 3. News -> trade bridge ─────────────────────────────────────────────────


def test_news_bridge_populates_cache_and_signals(tmp_path) -> None:
    storage = NewsStorage(db_path=str(tmp_path / "news.db"))
    storage.save_article(
        NewsArticle(
            id="a1",
            headline="AAPL soars on blowout earnings",
            summary="Record quarter beats estimates",
            source="test",
            symbols=["AAPL"],
        )
    )
    storage.save_sentiment(
        SentimentResult(
            article_id="a1",
            symbol="AAPL",
            compound_score=0.6,
            positive_score=0.7,
            negative_score=0.0,
            neutral_score=0.3,
            confidence=0.8,
            model="vader",
        )
    )

    agg = storage.get_trading_sentiment(hours=6, min_articles=1)
    assert "AAPL" in agg, "fresh sentiment must survive the time-window filter"
    assert agg["AAPL"]["compound"] == pytest.approx(0.6, abs=1e-6)
    assert agg["AAPL"]["confidence"] == pytest.approx(0.8, abs=1e-6)

    NewsSentimentStrategy.set_sentiment_bulk(agg)
    strat = NewsSentimentStrategy("news1", {})
    strat._equity = 100_000.0

    df = _ohlcv()
    df.attrs["symbol"] = "AAPL"
    sig = strat.generate_signal(df, current_price=102.0)
    assert sig.signal_type == SignalType.BUY
    assert sig.suggested_size and sig.suggested_size > 0


def test_news_cache_decays_when_empty() -> None:
    NewsSentimentStrategy.set_sentiment_bulk({})  # nothing in the window
    strat = NewsSentimentStrategy("news2", {})
    df = _ohlcv()
    df.attrs["symbol"] = "AAPL"
    sig = strat.generate_signal(df, current_price=102.0)
    assert sig.signal_type == SignalType.HOLD


def test_update_sentiment_uppercases_key() -> None:
    NewsSentimentStrategy.set_sentiment_bulk({})
    NewsSentimentStrategy.update_sentiment("tsla", 0.5, 0.9)
    assert "TSLA" in NewsSentimentStrategy._symbol_sentiment


# ── 4. Equity snapshot anti-double-count (the ~5x spike / 80.9% drawdown bug) ──


def test_equity_ignores_overlapping_broker_ledgers() -> None:
    """Alpaca returns USD + EQUITY + BUYING_POWER; summing them all (plus
    position MV) wrote ~5x equity spikes. compute_portfolio_equity must take
    the EQUITY key alone, never the sum."""
    from safety.limits import compute_portfolio_equity

    portfolio = Portfolio(
        "default", {"EQUITY": 100_000.0, "USD": 33_000.0, "BUYING_POWER": 200_000.0}
    )
    portfolio.open_position("BTC", PositionSide.LONG, 1.0, 50_000.0)
    portfolio.get_position("BTC").update_price(50_000.0)

    eq = compute_portfolio_equity(portfolio)
    assert eq == pytest.approx(100_000.0)  # not 333k+ and not +50k MV on top


# ── 5. Volatility-targeted sizing (opt-in overlay) ─────────────────────────


class _BuyStrategy(BaseStrategy):
    name = "buy_test"

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=data.attrs.get("symbol", "BTC"),
            signal_type=SignalType.BUY,
            confidence=0.9,
            timestamp=pd.Timestamp.now(),
            suggested_size=1.0,
        )


def _ohlcv_from_closes(closes: list[float]) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": [10.0] * len(closes),
        }
    )
    df.attrs["symbol"] = "BTC"
    return df


_VT_CONFIG = {
    "volatility_target": {
        "enabled": True,
        "daily_vol": 0.03,
        "lookback": 20,
        "scale_min": 0.3,
        "scale_max": 2.5,
    }
}


def test_vol_target_upsizes_calm_asset() -> None:
    """Very low realized vol -> scale hits the max clamp -> size up."""
    portfolio = Portfolio("default", {"USD": 100_000.0})
    strat = _BuyStrategy("vt1", _VT_CONFIG)
    calm = [100.0 + i * 0.01 for i in range(25)]  # ~0 volatility
    out = strat.on_tick(TickData(symbol="BTC", price=calm[-1]), portfolio, ohlcv_data=_ohlcv_from_closes(calm))
    assert out.signal_type == SignalType.BUY
    assert out.suggested_size == pytest.approx(2.5)  # clamped at scale_max


def test_vol_target_downsizes_choppy_asset() -> None:
    """High realized vol -> scale hits the min clamp -> size down."""
    portfolio = Portfolio("default", {"USD": 100_000.0})
    strat = _BuyStrategy("vt2", _VT_CONFIG)
    choppy = [100, 112, 90, 118, 86, 120, 84, 122, 88, 116] * 2  # huge swings
    out = strat.on_tick(TickData(symbol="BTC", price=float(choppy[-1])), portfolio, ohlcv_data=_ohlcv_from_closes([float(c) for c in choppy]))
    assert out.signal_type == SignalType.BUY
    assert out.suggested_size == pytest.approx(0.3)  # clamped at scale_min


def test_vol_target_disabled_leaves_size_unchanged() -> None:
    """No volatility_target block -> behaves exactly as before."""
    portfolio = Portfolio("default", {"USD": 100_000.0})
    strat = _BuyStrategy("vt3", {})
    calm = [100.0 + i * 0.01 for i in range(25)]
    out = strat.on_tick(TickData(symbol="BTC", price=calm[-1]), portfolio, ohlcv_data=_ohlcv_from_closes(calm))
    assert out.suggested_size == pytest.approx(1.0)


# ── 6. Funding-rate regime classifier ──────────────────────────────────────


def test_funding_classifier_regimes() -> None:
    from data.funding import classify_funding_regime, _to_binance_perp

    crowded_long = classify_funding_regime(0.001, symbol="BTC")
    assert crowded_long.regime == "crowded_long"
    assert crowded_long.bias == "bearish"
    assert crowded_long.blocks_new_long is True

    crowded_short = classify_funding_regime(-0.001, symbol="BTC")
    assert crowded_short.regime == "crowded_short"
    assert crowded_short.bias == "bullish"
    assert crowded_short.blocks_new_long is False

    neutral = classify_funding_regime(0.0001, symbol="BTC")
    assert neutral.regime == "neutral"

    assert _to_binance_perp("BTC") == "BTCUSDT"
    assert _to_binance_perp("bitcoin") == "BTCUSDT"
    assert _to_binance_perp("BTC-USD") == "BTCUSDT"
    assert _to_binance_perp("ETHUSDT") == "ETHUSDT"


# ── 7. Cost-aware entry gate (opt-in) ──────────────────────────────────────


class _BuyWithTPStrategy(BaseStrategy):
    name = "buy_tp_test"

    def __init__(self, sid, cfg, tp_mult):
        super().__init__(sid, cfg)
        self._tp_mult = tp_mult

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=data.attrs.get("symbol", "BTC"),
            signal_type=SignalType.BUY,
            confidence=0.9,
            timestamp=pd.Timestamp.now(),
            suggested_size=1.0,
            take_profit=current_price * self._tp_mult,
        )


_CG_CONFIG = {"cost_gate": {"enabled": True, "round_trip_bps": 30.0, "margin": 1.5}}


def test_cost_gate_rejects_buy_with_tight_target() -> None:
    """TP only 0.2% (20 bps) away < 45 bps required -> HOLD."""
    portfolio = Portfolio("default", {"USD": 100_000.0})
    strat = _BuyWithTPStrategy("cg1", _CG_CONFIG, tp_mult=1.002)
    out = strat.on_tick(TickData(symbol="BTC", price=100.0), portfolio, ohlcv_data=_ohlcv_from_closes([100.0] * 10))
    assert out.signal_type == SignalType.HOLD
    assert (out.metadata or {}).get("trigger") == "cost_gate"


def test_cost_gate_allows_buy_with_wide_target() -> None:
    """TP 10% (1000 bps) away >> required -> BUY passes."""
    portfolio = Portfolio("default", {"USD": 100_000.0})
    strat = _BuyWithTPStrategy("cg2", _CG_CONFIG, tp_mult=1.10)
    out = strat.on_tick(TickData(symbol="BTC", price=100.0), portfolio, ohlcv_data=_ohlcv_from_closes([100.0] * 10))
    assert out.signal_type == SignalType.BUY


def test_cost_gate_disabled_leaves_buy() -> None:
    portfolio = Portfolio("default", {"USD": 100_000.0})
    strat = _BuyWithTPStrategy("cg3", {}, tp_mult=1.002)
    out = strat.on_tick(TickData(symbol="BTC", price=100.0), portfolio, ohlcv_data=_ohlcv_from_closes([100.0] * 10))
    assert out.signal_type == SignalType.BUY


# ── 8. Honest fees/slippage: reproducibility + size-aware impact ───────────


def test_proportional_slippage_is_reproducible_with_seed() -> None:
    """Same seed -> identical fills (was unseeded global np.random)."""
    a = ExecutionSimulator(slippage_model="proportional", slippage_bps=10.0, seed=7)
    b = ExecutionSimulator(slippage_model="proportional", slippage_bps=10.0, seed=7)
    pa = [a.apply_slippage(100.0, OrderSide.BUY) for _ in range(5)]
    pb = [b.apply_slippage(100.0, OrderSide.BUY) for _ in range(5)]
    assert pa == pb


def test_sqrt_impact_penalizes_larger_orders() -> None:
    """With impact on, a bigger order fills at a worse price."""
    sim = ExecutionSimulator(
        fee_rate=0.0, slippage_model="fixed", slippage_bps=0.0,
        impact_coeff_bps=20.0, impact_ref_notional=10_000.0,
    )
    small = sim.execute(Order.market("BTC", OrderSide.BUY, 1.0), current_price=100.0)
    big = sim.execute(Order.market("BTC", OrderSide.BUY, 1000.0), current_price=100.0)
    assert small is not None and big is not None
    assert big.filled_price > small.filled_price > 100.0


def test_impact_off_by_default_no_price_change() -> None:
    """Default (coeff 0) + zero base slippage/fee -> fills at mark, unchanged."""
    sim = ExecutionSimulator(fee_rate=0.0, slippage_model="fixed", slippage_bps=0.0)
    f = sim.execute(Order.market("BTC", OrderSide.BUY, 1000.0), current_price=100.0)
    assert f is not None
    assert f.filled_price == pytest.approx(100.0)
