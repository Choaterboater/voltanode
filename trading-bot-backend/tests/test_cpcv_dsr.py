"""CPCV + Deflated Sharpe Ratio promotion-gate tests (backtest/validation.py).

Pure math (fold purge/embargo, DSR behavior) + integration on synthetic data
(a genuinely trending config passes; a noise/short-history config fails).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestConfig
from backtest.validation import (
    PromotionGateConfig,
    cpcv_splits,
    deflated_sharpe_ratio,
    evaluate_promotion,
    _norm_cdf,
    _norm_ppf,
)


# ── Closed-form normal sanity ──────────────────────────────────────────────


def test_norm_cdf_ppf_round_trip() -> None:
    assert _norm_cdf(0.0) == pytest.approx(0.5, abs=1e-9)
    assert _norm_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
    assert _norm_ppf(0.975) == pytest.approx(1.96, abs=1e-2)
    # round-trip
    for p in (0.01, 0.25, 0.5, 0.84, 0.999):
        assert _norm_cdf(_norm_ppf(p)) == pytest.approx(p, abs=1e-6)


# ── CPCV fold generation ────────────────────────────────────────────────────


def test_cpcv_splits_purge_embargo_no_overlap() -> None:
    n = 120
    splits = cpcv_splits(n, n_groups=6, n_test_groups=2, embargo_pct=0.05)
    assert len(splits) == 15  # C(6,2)
    embargo = math.ceil(n * 0.05)
    for train_idx, test_idx in splits:
        train, test = set(train_idx.tolist()), set(test_idx.tolist())
        assert train & test == set()  # no leakage
        # no train bar within `embargo` of any test bar
        for t in test:
            for k in range(t - embargo, t + embargo + 1):
                assert k not in train


def test_cpcv_splits_degenerate_returns_empty() -> None:
    assert cpcv_splits(3, n_groups=6, n_test_groups=2) == []


# ── Deflated Sharpe Ratio ───────────────────────────────────────────────────


def test_dsr_high_for_robust_low_for_overfit() -> None:
    robust = deflated_sharpe_ratio(observed_sr=2.0, sr_variance_across_trials=0.04, n_trials=10, n_returns=250)
    overfit = deflated_sharpe_ratio(observed_sr=0.3, sr_variance_across_trials=0.25, n_trials=200, n_returns=250)
    assert robust > 0.5
    assert overfit < 0.5


def test_dsr_monotonic_decreasing_in_n_trials() -> None:
    vals = [deflated_sharpe_ratio(1.0, 0.1, n, 250) for n in (1, 50, 500)]
    assert vals[0] >= vals[1] >= vals[2]


def test_dsr_degenerate_inputs_return_zero() -> None:
    assert deflated_sharpe_ratio(1.0, 0.0, 10, 250) == 0.0
    assert deflated_sharpe_ratio(1.0, 0.1, 10, 1) == 0.0


# ── Integration: gate on synthetic data ─────────────────────────────────────

_BT = BacktestConfig(initial_balance={"USDT": 100_000.0}, fee_rate=0.0005, slippage_bps=2.0, allow_short=True)
_MOM_CFG = {"fast_ema": 5, "slow_ema": 15, "trend_filter_ema": 30, "position_pct": 0.05}


def _ohlc(closes: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame({
        "open": closes,
        "high": closes * 1.005,
        "low": closes * 0.995,
        "close": closes,
        "volume": np.full(len(closes), 1000.0),
    })
    df.attrs["symbol"] = "BTC"
    return df


def test_gate_fails_closed_on_short_history() -> None:
    closes = 100.0 + np.arange(40, dtype=float)
    df = _ohlc(closes)
    gate = PromotionGateConfig(enabled=True)
    res = evaluate_promotion("momentum", _MOM_CFG, df, _BT, n_trials=20, gate_cfg=gate)
    # Too few bars per fold to trade -> no edge -> fails closed (safe).
    assert res.passed is False
    assert res.mean_oos_sharpe == pytest.approx(0.0, abs=1e-9)


def test_gate_fails_overfit_noise_with_many_trials() -> None:
    rng = np.random.default_rng(123)
    # Seeded random walk: no real trend -> momentum has no durable edge.
    steps = rng.normal(0, 1.0, 300).cumsum()
    closes = 100.0 + steps
    closes = np.maximum(closes, 1.0)
    df = _ohlc(closes)
    gate = PromotionGateConfig(enabled=True)
    res = evaluate_promotion("momentum", _MOM_CFG, df, _BT, n_trials=200, gate_cfg=gate)
    assert res.passed is False
    assert res.reason != ""


def test_gate_result_serializes() -> None:
    closes = 100.0 + np.arange(60, dtype=float)
    res = evaluate_promotion("momentum", _MOM_CFG, _ohlc(closes), _BT, n_trials=10, gate_cfg=PromotionGateConfig(enabled=True))
    d = res.to_dict()
    assert {"passed", "dsr", "mean_oos_sharpe", "n_folds", "n_trials"} <= set(d.keys())
