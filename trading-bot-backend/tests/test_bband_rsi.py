"""Tests for the BbandRsi strategy port."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestConfig, BacktestRunner
from bot.config import SignalType
from strategies import STRATEGY_REGISTRY, StrategyFactory
from strategies.bband_rsi import BbandRsiStrategy


@pytest.fixture
def oscillating_ohlcv() -> pd.DataFrame:
    """Synthetic OHLCV that swings hard enough to drive RSI past 30/70 and
    push close below/above the Bollinger bands."""
    np.random.seed(11)
    n = 250
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    t = np.arange(n)
    base = 100 + 15 * np.sin(t / 8) + 0.04 * t
    noise = np.random.randn(n) * 1.5
    close = base + noise
    df = pd.DataFrame({
        "timestamp": dates,
        "open": close * 0.998,
        "high": close * 1.012,
        "low": close * 0.988,
        "close": close,
        "volume": np.random.randint(1000, 10000, n),
    })
    df.attrs["symbol"] = "TEST"
    return df


class TestRegistry:
    def test_registered_as_bband_rsi(self) -> None:
        assert "bband_rsi" in STRATEGY_REGISTRY
        assert STRATEGY_REGISTRY["bband_rsi"] is BbandRsiStrategy

    def test_factory_pascalcase_resolution(self) -> None:
        strat = StrategyFactory("BbandRsi", config={"symbols": ["TEST"]})
        assert isinstance(strat, BbandRsiStrategy)

    def test_factory_snakecase_resolution(self) -> None:
        strat = StrategyFactory("bband_rsi", config={"symbols": ["TEST"]})
        assert isinstance(strat, BbandRsiStrategy)


class TestParamSpace:
    def test_param_space_non_empty_and_well_formed(self) -> None:
        space = BbandRsiStrategy.param_space()
        assert space
        required = {"rsi_period", "rsi_oversold", "rsi_overbought",
                    "bb_period", "bb_std", "take_profit_pct", "stop_loss_pct"}
        assert required.issubset(space.keys())
        for name, spec in space.items():
            assert spec["type"] in ("int", "float", "categorical"), name

    def test_param_space_aligns_with_default_config(self) -> None:
        cls = BbandRsiStrategy
        space = cls.param_space()
        for name in space:
            assert name in cls.DEFAULT_CONFIG, (
                f"{name} is in param_space but not in DEFAULT_CONFIG; "
                f"hyperopt-tuned params won't persist back to the bot"
            )


class TestSignalSemantics:
    """Faithful-port checks: textbook 30/70, strict band breach, typical-price BBs."""

    def test_insufficient_history_holds(self) -> None:
        strat = BbandRsiStrategy("t", {})
        short_df = pd.DataFrame({
            "open": [100], "high": [101], "low": [99], "close": [100], "volume": [1000],
        })
        short_df.attrs["symbol"] = "TEST"
        sig = strat.generate_signal(short_df, 100.0)
        assert sig.signal_type == SignalType.HOLD
        assert sig.metadata.get("trigger") == "insufficient_history"

    def test_oversold_below_band_fires_buy(self, oscillating_ohlcv: pd.DataFrame) -> None:
        # Walk the oscillating series until we hit a bar where RSI<30 and
        # close<lower band. Strategy must emit BUY there.
        strat = BbandRsiStrategy("t", {})
        saw_buy = False
        for i in range(60, len(oscillating_ohlcv)):
            window = oscillating_ohlcv.iloc[: i + 1].copy()
            window.attrs["symbol"] = "TEST"
            sig = strat.generate_signal(window, float(window["close"].iloc[-1]))
            if sig.signal_type == SignalType.BUY:
                saw_buy = True
                assert sig.metadata.get("trigger") == "rsi_oversold_below_lower_band"
                assert sig.stop_loss is not None and sig.stop_loss < float(window["close"].iloc[-1])
                assert sig.take_profit is not None and sig.take_profit > float(window["close"].iloc[-1])
                break
        assert saw_buy, "oscillating fixture should produce at least one BUY"

    def test_overbought_fires_sell(self, oscillating_ohlcv: pd.DataFrame) -> None:
        strat = BbandRsiStrategy("t", {})
        saw_sell = False
        for i in range(60, len(oscillating_ohlcv)):
            window = oscillating_ohlcv.iloc[: i + 1].copy()
            window.attrs["symbol"] = "TEST"
            sig = strat.generate_signal(window, float(window["close"].iloc[-1]))
            if sig.signal_type == SignalType.SELL:
                saw_sell = True
                assert sig.metadata.get("trigger") == "rsi_overbought"
                break
        assert saw_sell, "oscillating fixture should produce at least one SELL"

    def test_per_bar_latch_holds_repeats(self, oscillating_ohlcv: pd.DataFrame) -> None:
        # Once a bar fires non-HOLD, the next call on the same bar must HOLD.
        strat = BbandRsiStrategy("t", {})
        # Use the dataframe's index for stable bar keys
        df = oscillating_ohlcv.copy().set_index("timestamp")
        df.attrs["symbol"] = "TEST"
        for i in range(60, len(df)):
            window = df.iloc[: i + 1].copy()
            window.attrs["symbol"] = "TEST"
            sig = strat.generate_signal(window, float(window["close"].iloc[-1]))
            if sig.signal_type in (SignalType.BUY, SignalType.SELL):
                repeat = strat.generate_signal(window, float(window["close"].iloc[-1]))
                assert repeat.signal_type == SignalType.HOLD
                assert repeat.metadata.get("trigger") == "already_fired_this_bar"
                return
        pytest.fail("no non-HOLD signal in fixture")


class TestBacktestIntegration:
    """The whole point of this strategy is to be runnable through the same
    backtest path as the other strategies. Smoke that."""

    def test_runs_in_backtest_runner(self, oscillating_ohlcv: pd.DataFrame) -> None:
        strat = StrategyFactory("bband_rsi", config={"symbols": ["TEST"]})
        cfg = BacktestConfig(initial_balance={"USDT": 10_000.0}, fee_rate=0.001)
        runner = BacktestRunner(strat, oscillating_ohlcv, cfg)
        result = runner.run()
        # Must run end-to-end without raising; trades may or may not fire
        # depending on whether the synthetic series hit the strict thresholds.
        assert result.equity_curve is not None and not result.equity_curve.empty
        assert result.metrics is not None


class TestHyperoptCompat:
    """Make sure the hyperopt module can pick this strategy up."""

    def test_hyperopt_smoke_5_trials(self, oscillating_ohlcv: pd.DataFrame) -> None:
        from hyperopt import run_hyperopt

        result = run_hyperopt(
            strategy_type="bband_rsi",
            symbol="TEST",
            asset_class="crypto",
            n_trials=5,
            objective="sharpe",
            fixed_config={"symbols": ["TEST"]},
            df=oscillating_ohlcv,
        )
        assert result.strategy_type == "bband_rsi"
        # best_params may be empty if every trial fell under MIN_TRADES_FOR_VALID_TRIAL;
        # the load-bearing assertion is that the engine accepted bband_rsi at all.
        if result.best_params:
            assert set(result.best_params).issubset(
                set(BbandRsiStrategy.param_space().keys())
            )
