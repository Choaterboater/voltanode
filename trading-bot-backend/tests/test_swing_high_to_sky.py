"""Tests for the SwingHighToSky strategy port."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestConfig, BacktestRunner
from bot.config import SignalType
from strategies import STRATEGY_REGISTRY, StrategyFactory
from strategies.swing_high_to_sky import SwingHighToSkyStrategy, _cci, _rsi


@pytest.fixture
def oscillating_ohlcv() -> pd.DataFrame:
    """Synthetic OHLCV with sharp swings — drives CCI past +/- thresholds."""
    np.random.seed(13)
    n = 350
    dates = pd.date_range("2024-01-01", periods=n, freq="15min")
    t = np.arange(n)
    base = 100 + 20 * np.sin(t / 6) + 0.03 * t
    noise = np.random.randn(n) * 2.0
    close = base + noise
    df = pd.DataFrame({
        "timestamp": dates,
        "open": close * 0.998,
        "high": close * 1.015,
        "low": close * 0.985,
        "close": close,
        "volume": np.random.randint(1000, 10000, n),
    })
    df.attrs["symbol"] = "TEST"
    return df


class TestRegistry:
    def test_registered_as_swing_high_to_sky(self) -> None:
        assert "swing_high_to_sky" in STRATEGY_REGISTRY
        assert STRATEGY_REGISTRY["swing_high_to_sky"] is SwingHighToSkyStrategy

    def test_factory_pascalcase_resolution(self) -> None:
        strat = StrategyFactory("SwingHighToSky", config={"symbols": ["TEST"]})
        assert isinstance(strat, SwingHighToSkyStrategy)


class TestIndicatorMath:
    """CCI math sanity — basic shape + flat-price div-zero handling."""

    def test_cci_returns_finite_on_real_data(self, oscillating_ohlcv: pd.DataFrame) -> None:
        cci = _cci(
            oscillating_ohlcv["high"],
            oscillating_ohlcv["low"],
            oscillating_ohlcv["close"],
            20,
        )
        assert len(cci) == len(oscillating_ohlcv)
        tail = cci.iloc[-50:]
        assert np.isfinite(tail).any(), "tail CCI should have finite values"

    def test_cci_handles_flat_prices_without_raising(self) -> None:
        # Perfectly flat prices → MAD == 0 → div by zero. The implementation
        # replaces 0 with NaN before dividing; result is NaN, not exception.
        flat = pd.Series([100.0] * 30)
        cci = _cci(flat, flat, flat, 10)
        assert cci.iloc[-1] != cci.iloc[-1] or cci.iloc[-1] == 0  # NaN or 0
        assert not np.isinf(cci).any()

    def test_rsi_basic_range(self, oscillating_ohlcv: pd.DataFrame) -> None:
        rsi = _rsi(oscillating_ohlcv["close"], 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()


class TestParamSpace:
    def test_param_space_non_empty_and_well_formed(self) -> None:
        space = SwingHighToSkyStrategy.param_space()
        assert space
        required = {"buy_cci_period", "buy_cci_threshold", "buy_rsi_period",
                    "buy_rsi_threshold", "sell_cci_period", "sell_cci_threshold",
                    "sell_rsi_period", "sell_rsi_threshold",
                    "take_profit_pct", "stop_loss_pct"}
        assert required.issubset(space.keys())
        for name, spec in space.items():
            assert spec["type"] in ("int", "float", "categorical")

    def test_param_space_aligns_with_default_config(self) -> None:
        cls = SwingHighToSkyStrategy
        for name in cls.param_space():
            assert name in cls.DEFAULT_CONFIG, (
                f"{name} in param_space but not DEFAULT_CONFIG; "
                f"apply-hyperopt won't be able to merge it back"
            )


class TestSignalSemantics:
    def test_insufficient_history_holds(self) -> None:
        strat = SwingHighToSkyStrategy("t", {})
        short_df = pd.DataFrame({
            "open": [100]*10, "high": [101]*10, "low": [99]*10,
            "close": [100]*10, "volume": [1000]*10,
        })
        short_df.attrs["symbol"] = "TEST"
        sig = strat.generate_signal(short_df, 100.0)
        assert sig.signal_type == SignalType.HOLD
        assert sig.metadata.get("trigger") == "insufficient_history"

    def test_strategy_fires_at_least_once_on_oscillating(
        self, oscillating_ohlcv: pd.DataFrame
    ) -> None:
        # Mechanics check: with loosened thresholds the strategy must emit
        # at least one BUY or SELL on this fixture. The upstream defaults
        # (CCI < -175, RSI < 90) only fire on extreme swings and aren't the
        # subject of this unit test — they're validated by live hyperopt.
        strat = SwingHighToSkyStrategy("t", {
            "buy_cci_threshold": -80,   # less extreme than upstream's -175
            "buy_rsi_threshold": 90,
            "sell_cci_threshold": 0,
            "sell_rsi_threshold": 60,
        })
        signals = []
        for i in range(100, len(oscillating_ohlcv)):
            window = oscillating_ohlcv.iloc[: i + 1].copy()
            window.attrs["symbol"] = "TEST"
            sig = strat.generate_signal(window, float(window["close"].iloc[-1]))
            if sig.signal_type in (SignalType.BUY, SignalType.SELL):
                signals.append((i, sig.signal_type, sig.metadata.get("trigger")))
        assert signals, "loosened-threshold strategy should produce signals"

    def test_per_bar_latch_holds_repeats(self, oscillating_ohlcv: pd.DataFrame) -> None:
        strat = SwingHighToSkyStrategy("t", {
            "buy_cci_threshold": -80,
            "buy_rsi_threshold": 90,
            "sell_cci_threshold": 0,
            "sell_rsi_threshold": 60,
        })
        df = oscillating_ohlcv.copy().set_index("timestamp")
        df.attrs["symbol"] = "TEST"
        for i in range(100, len(df)):
            window = df.iloc[: i + 1].copy()
            window.attrs["symbol"] = "TEST"
            sig = strat.generate_signal(window, float(window["close"].iloc[-1]))
            if sig.signal_type in (SignalType.BUY, SignalType.SELL):
                repeat = strat.generate_signal(window, float(window["close"].iloc[-1]))
                assert repeat.signal_type == SignalType.HOLD
                assert repeat.metadata.get("trigger") == "already_fired_this_bar"
                return
        pytest.fail("no non-HOLD signal in fixture — can't test latch")


class TestBacktestIntegration:
    def test_runs_in_backtest_runner(self, oscillating_ohlcv: pd.DataFrame) -> None:
        strat = StrategyFactory("swing_high_to_sky", config={"symbols": ["TEST"]})
        cfg = BacktestConfig(initial_balance={"USDT": 10_000.0}, fee_rate=0.001)
        runner = BacktestRunner(strat, oscillating_ohlcv, cfg)
        result = runner.run()
        assert not result.equity_curve.empty
        assert result.metrics is not None


class TestHyperoptCompat:
    def test_hyperopt_smoke_5_trials(self, oscillating_ohlcv: pd.DataFrame) -> None:
        from hyperopt import run_hyperopt

        result = run_hyperopt(
            strategy_type="swing_high_to_sky",
            symbol="TEST",
            asset_class="crypto",
            n_trials=5,
            objective="sharpe",
            fixed_config={"symbols": ["TEST"]},
            df=oscillating_ohlcv,
        )
        assert result.strategy_type == "swing_high_to_sky"
        if result.best_params:
            assert set(result.best_params).issubset(
                set(SwingHighToSkyStrategy.param_space().keys())
            )
