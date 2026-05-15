"""Tests for the hyperopt module."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict

import numpy as np
import optuna
import pandas as pd
import pytest

from backtest.engine import BacktestConfig
from hyperopt import (
    HyperoptResult,
    append_history,
    latest_for_strategy,
    read_all,
    run_hyperopt,
)
from hyperopt.objective import baseline_value, make_objective
from strategies import STRATEGY_REGISTRY, StrategyFactory


@pytest.fixture
def oscillating_ohlcv() -> pd.DataFrame:
    """Synthetic OHLCV that oscillates enough for RSI/MACD strategies to trade.

    Pure trending data (test_backtest.py's fixture) starves mean-reversion of
    overbought/oversold conditions, so a few hyperopt tests below need
    something choppier.
    """
    np.random.seed(7)
    n = 300
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    t = np.arange(n)
    # Sine wave + drift + noise — gives both crossovers and band touches
    base = 100 + 8 * np.sin(t / 12) + 0.05 * t
    noise = np.random.randn(n) * 1.2
    prices = base + noise
    df = pd.DataFrame({
        "timestamp": dates,
        "open": prices * 0.998,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": np.random.randint(1000, 10000, n),
    })
    df.attrs["symbol"] = "TEST"
    return df


@pytest.fixture
def bt_config() -> BacktestConfig:
    return BacktestConfig(
        initial_balance={"USDT": 10_000.0},
        fee_rate=0.001,
        slippage_bps=5.0,
        allow_short=True,
    )


class TestParamSpace:
    """All three target strategies must expose param_space()."""

    @pytest.mark.parametrize("strategy_type", ["mean_reversion", "macd", "momentum"])
    def test_param_space_is_non_empty(self, strategy_type: str) -> None:
        cls = STRATEGY_REGISTRY[strategy_type]
        space = cls.param_space()
        assert space, f"{strategy_type} must define a non-empty param_space"
        for name, spec in space.items():
            assert "type" in spec, f"{strategy_type}.{name} missing type"
            assert spec["type"] in ("int", "float", "categorical")

    def test_base_strategy_param_space_default_empty(self) -> None:
        from strategies.base import BaseStrategy
        assert BaseStrategy.param_space() == {}


class TestRunHyperopt:
    """Smoke tests for run_hyperopt() using a pre-built DataFrame."""

    def test_macd_smoke_5_trials(
        self, oscillating_ohlcv: pd.DataFrame, bt_config: BacktestConfig
    ) -> None:
        result = run_hyperopt(
            strategy_type="macd",
            symbol="TEST",
            asset_class="crypto",
            n_trials=5,
            objective="sharpe",
            fixed_config={"symbols": ["TEST"]},
            df=oscillating_ohlcv,
        )
        assert isinstance(result, HyperoptResult)
        assert result.strategy_type == "macd"
        assert result.n_trials == 5
        if result.best_params:
            # If at least one valid trial, best_params must align with the space.
            assert set(result.best_params).issubset(set(STRATEGY_REGISTRY["macd"].param_space()))
            assert math.isfinite(result.best_value)

    def test_mean_reversion_smoke(
        self, oscillating_ohlcv: pd.DataFrame, bt_config: BacktestConfig
    ) -> None:
        result = run_hyperopt(
            strategy_type="mean_reversion",
            symbol="TEST",
            asset_class="crypto",
            n_trials=5,
            objective="sharpe",
            fixed_config={"symbols": ["TEST"]},
            df=oscillating_ohlcv,
        )
        assert result.strategy_type == "mean_reversion"
        # Don't require best_params to be non-empty — synthetic data may not
        # produce >= MIN_TRADES_FOR_VALID_TRIAL trades for every random params.

    def test_unknown_strategy_raises(self, oscillating_ohlcv: pd.DataFrame) -> None:
        with pytest.raises(ValueError):
            run_hyperopt(
                strategy_type="not_a_real_strategy",
                symbol="TEST",
                asset_class="crypto",
                n_trials=2,
                df=oscillating_ohlcv,
            )

    def test_strategy_without_param_space_raises(self, oscillating_ohlcv: pd.DataFrame) -> None:
        # GridStrategy doesn't define param_space — should reject the run.
        with pytest.raises(ValueError, match="opts out"):
            run_hyperopt(
                strategy_type="grid",
                symbol="TEST",
                asset_class="crypto",
                n_trials=2,
                df=oscillating_ohlcv,
            )


class TestConstraintViolation:
    """MACD fast>=slow and Momentum fast_ema>=slow_ema must be rejected."""

    def test_macd_fast_ge_slow_returns_neg_inf(
        self, oscillating_ohlcv: pd.DataFrame, bt_config: BacktestConfig
    ) -> None:
        obj_fn = make_objective(
            "macd", oscillating_ohlcv, bt_config, "sharpe",
            fixed_config={"symbols": ["TEST"]},
        )

        # Bypass Optuna sampler — drive the objective directly with a
        # violating combo. Optuna's TPESampler can also produce these
        # naturally; the objective must short-circuit either way.
        class _FakeTrial:
            def __init__(self, params):
                self._params = params
                self.user_attrs: Dict[str, Any] = {}

            def suggest_int(self, name, low, high, step=1):
                return self._params[name]

            def suggest_float(self, name, low, high, step=None, log=False):
                return self._params[name]

            def suggest_categorical(self, name, choices):
                return self._params[name]

            def set_user_attr(self, k, v):
                self.user_attrs[k] = v

        result = obj_fn(_FakeTrial({"fast": 25, "slow": 20, "signal": 9}))
        assert result == float("-inf")

    def test_momentum_fast_ge_slow_returns_neg_inf(
        self, oscillating_ohlcv: pd.DataFrame, bt_config: BacktestConfig
    ) -> None:
        obj_fn = make_objective(
            "momentum", oscillating_ohlcv, bt_config, "sharpe",
            fixed_config={"symbols": ["TEST"]},
        )

        class _FakeTrial:
            def __init__(self, params):
                self._params = params
                self.user_attrs: Dict[str, Any] = {}

            def suggest_int(self, name, low, high, step=1):
                return self._params[name]

            def suggest_float(self, name, low, high, step=None, log=False):
                return self._params[name]

            def suggest_categorical(self, name, choices):
                return self._params[name]

            def set_user_attr(self, k, v):
                self.user_attrs[k] = v

        bad_params = {
            "fast_ema": 30,
            "slow_ema": 25,
            "signal_ema": 9,
            "trend_filter_ema": 200,
        }
        assert obj_fn(_FakeTrial(bad_params)) == float("-inf")


class TestHistoryStore:
    """Append-only JSONL store roundtrip."""

    def test_append_and_latest(self, tmp_path: Path) -> None:
        hist_path = tmp_path / "hyperopt_history.jsonl"

        result1 = HyperoptResult(
            strategy_type="macd",
            symbol="BTC/USD",
            objective="sharpe",
            n_trials=10,
            best_params={"fast": 8, "slow": 30, "signal": 9},
            best_value=1.23,
            baseline_value=0.45,
            duration_sec=12.0,
        )
        result2 = HyperoptResult(
            strategy_type="macd",
            symbol="BTC/USD",
            objective="sharpe",
            n_trials=10,
            best_params={"fast": 10, "slow": 30, "signal": 9},
            best_value=1.50,
            baseline_value=0.45,
            duration_sec=15.0,
        )
        append_history(result1, strategy_id="macd_btc", path=hist_path)
        append_history(result2, strategy_id="macd_btc", path=hist_path)
        append_history(result1, strategy_id="other_bot", path=hist_path)

        all_rows = read_all(path=hist_path)
        assert len(all_rows) == 3

        latest = latest_for_strategy("macd_btc", path=hist_path)
        assert latest is not None
        assert latest["best_value"] == 1.50  # most-recent macd_btc row, not the first
        assert latest["best_params"] == {"fast": 10, "slow": 30, "signal": 9}

    def test_latest_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert latest_for_strategy("nonexistent", path=tmp_path / "nope.jsonl") is None


class TestBaselineValue:
    """baseline_value should match a manual BacktestRunner pass with DEFAULTS."""

    def test_baseline_matches_default_config_backtest(
        self, oscillating_ohlcv: pd.DataFrame, bt_config: BacktestConfig
    ) -> None:
        from backtest.engine import BacktestRunner

        bv = baseline_value(
            "macd", oscillating_ohlcv, bt_config, "sharpe",
            fixed_config={"symbols": ["TEST"]},
        )

        strategy = StrategyFactory("macd", config={"symbols": ["TEST"]})
        result = BacktestRunner(strategy, oscillating_ohlcv, bt_config).run()
        manual = float(result.metrics.to_dict()["sharpe_ratio"])

        if math.isfinite(manual):
            assert bv == pytest.approx(manual, rel=1e-6)
        else:
            assert not math.isfinite(bv)
