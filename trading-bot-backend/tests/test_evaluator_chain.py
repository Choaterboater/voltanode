"""Tests for the evaluator-chain pattern (Phase 5 architecture)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from advisor.evaluators import (
    BreakoutEvaluator,
    ChainResult,
    EvaluatorChain,
    EvaluatorContext,
    EvaluatorVerdict,
    RelativeVolumeEvaluator,
    RsiExtremeEvaluator,
    aggregate_direction,
    build_default_chain,
)
from advisor.evaluators.base import DIR_LONG, DIR_NEUTRAL, DIR_SHORT


@pytest.fixture
def oversold_ohlcv() -> pd.DataFrame:
    """OHLCV with a clear downtrend so RSI ends deeply oversold and close is
    below the prior 20-bar low (i.e. breakout_down)."""
    np.random.seed(3)
    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    # Strong downtrend
    close = 200 - np.arange(n) * 2.0 + np.random.randn(n) * 0.5
    df = pd.DataFrame({
        "timestamp": dates,
        "open": close * 1.001,
        "high": close * 1.005,
        "low": close * 0.995,
        "close": close,
        "volume": np.random.randint(1000, 5000, n),
    })
    df.attrs["symbol"] = "DOWN"
    return df


@pytest.fixture
def overbought_ohlcv() -> pd.DataFrame:
    """Uptrend with noisy pullbacks ending in a parabolic surge → RSI > 70.

    Pure linear uptrend yields zero down-bars, which makes compute_rsi's
    Wilder formula divide by zero → NaN → fillna(50). We need real
    pullbacks so avg_loss > 0, then a final surge to push RSI past 70.
    """
    np.random.seed(5)
    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    # Drifty trend with enough noise to produce occasional down-bars
    base = 100 + np.arange(n) * 1.5 + np.random.randn(n) * 3.0
    # Last 8 bars: parabolic surge on top of the trend
    surge = np.concatenate([
        np.zeros(n - 8),
        np.array([2, 4, 7, 11, 16, 22, 30, 40]),
    ])
    close = base + surge
    df = pd.DataFrame({
        "timestamp": dates,
        "open": close * 0.999,
        "high": close * 1.005,
        "low": close * 0.995,
        "close": close,
        # last bar has a huge volume spike to trigger rel_volume too
        "volume": list(np.random.randint(1000, 5000, n - 1)) + [50000],
    })
    df.attrs["symbol"] = "UP"
    return df


class TestEvaluatorVerdict:
    def test_clamps_score_to_unit_range(self) -> None:
        v = EvaluatorVerdict(name="x", score=1.5, direction=DIR_LONG)
        assert v.score == 1.0
        v = EvaluatorVerdict(name="x", score=-0.5, direction=DIR_LONG)
        assert v.score == 0.0

    def test_rejects_invalid_direction(self) -> None:
        with pytest.raises(ValueError):
            EvaluatorVerdict(name="x", score=0.5, direction="sideways")

    def test_confidence_defaults_to_score(self) -> None:
        v = EvaluatorVerdict(name="x", score=0.7, direction=DIR_LONG)
        assert v.confidence == 0.7

    def test_to_dict_roundtrip_shape(self) -> None:
        v = EvaluatorVerdict(
            name="rsi", score=0.8, direction=DIR_LONG,
            signal="oversold", raw_value=22.3, metadata={"period": 14},
        )
        d = v.to_dict()
        assert d["name"] == "rsi"
        assert d["direction"] == DIR_LONG
        assert d["signal"] == "oversold"
        assert d["raw_value"] == 22.3
        assert d["metadata"] == {"period": 14}


class TestIndividualEvaluators:
    def test_rsi_evaluator_long_on_oversold(self, oversold_ohlcv: pd.DataFrame) -> None:
        ev = RsiExtremeEvaluator(rsi_period=14)
        v = ev.evaluate(oversold_ohlcv, EvaluatorContext(symbol="DOWN"))
        assert v.name == "rsi"
        assert v.direction == DIR_LONG  # oversold → mean-reversion long
        assert v.score > 0.0
        assert "oversold" in v.signal

    def test_rsi_evaluator_short_on_overbought(self, overbought_ohlcv: pd.DataFrame) -> None:
        ev = RsiExtremeEvaluator(rsi_period=14)
        v = ev.evaluate(overbought_ohlcv, EvaluatorContext(symbol="UP"))
        assert v.direction == DIR_SHORT
        assert "overbought" in v.signal

    def test_breakout_evaluator_long_on_uptrend(self, overbought_ohlcv: pd.DataFrame) -> None:
        ev = BreakoutEvaluator(lookback=20)
        v = ev.evaluate(overbought_ohlcv, EvaluatorContext(symbol="UP"))
        assert v.direction == DIR_LONG
        assert v.signal in ("breakout_up", "near_resistance")

    def test_rel_volume_is_directionless(self, overbought_ohlcv: pd.DataFrame) -> None:
        # rel_volume should never vote a direction — caller uses score as a
        # confirmation weight, not a vote.
        ev = RelativeVolumeEvaluator(lookback=20)
        v = ev.evaluate(overbought_ohlcv, EvaluatorContext(symbol="UP"))
        assert v.direction == DIR_NEUTRAL
        assert v.score > 0.0  # last bar had 50000 vol vs avg ~3000

    def test_evaluator_below_min_bars_handled_by_chain(self) -> None:
        # Chain should short-circuit with insufficient_data; the evaluator
        # itself is allowed to be picky.
        short_df = pd.DataFrame({
            "open": [100]*5, "high": [101]*5, "low": [99]*5,
            "close": [100]*5, "volume": [1000]*5,
        })
        chain = EvaluatorChain([(BreakoutEvaluator(lookback=20), 1.0)])
        result = chain.evaluate("SHORT", short_df)
        assert len(result.verdicts) == 1
        assert result.verdicts[0].signal == "insufficient_data"


class TestChainAggregation:
    def test_constructor_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            EvaluatorChain([])

    def test_constructor_rejects_duplicate_names(self) -> None:
        with pytest.raises(ValueError):
            EvaluatorChain([
                (BreakoutEvaluator(), 0.5),
                (BreakoutEvaluator(), 0.5),
            ])

    def test_weights_normalize_to_one(self) -> None:
        chain = EvaluatorChain([
            (RsiExtremeEvaluator(), 4.0),
            (BreakoutEvaluator(), 3.0),
            (RelativeVolumeEvaluator(), 3.0),
        ])
        total = sum(chain.weights.values())
        assert abs(total - 1.0) < 1e-9
        assert chain.weights["rsi"] == pytest.approx(0.4)

    def test_default_chain_matches_scanner_weights(self) -> None:
        from advisor.scanner import DEFAULT_WEIGHTS
        chain = build_default_chain()
        for k, v in DEFAULT_WEIGHTS.items():
            assert chain.weights[k] == pytest.approx(v)

    def test_aggregate_direction_weighted_vote(self) -> None:
        v1 = EvaluatorVerdict(name="a", score=0.8, direction=DIR_LONG)
        v2 = EvaluatorVerdict(name="b", score=0.4, direction=DIR_SHORT)
        # Equal weights → long wins (0.8 vs 0.4)
        d = aggregate_direction([v1, v2], weights={"a": 0.5, "b": 0.5})
        assert d == DIR_LONG

    def test_aggregate_direction_tie_is_neutral(self) -> None:
        v1 = EvaluatorVerdict(name="a", score=0.5, direction=DIR_LONG)
        v2 = EvaluatorVerdict(name="b", score=0.5, direction=DIR_SHORT)
        d = aggregate_direction([v1, v2], weights={"a": 1.0, "b": 1.0})
        assert d == DIR_NEUTRAL

    def test_aggregate_direction_all_neutral(self) -> None:
        v1 = EvaluatorVerdict(name="a", score=0.7, direction=DIR_NEUTRAL)
        v2 = EvaluatorVerdict(name="b", score=0.5, direction=DIR_NEUTRAL)
        d = aggregate_direction([v1, v2])
        assert d == DIR_NEUTRAL

    def test_aggregate_direction_weight_override_flips_winner(self) -> None:
        # Verdict scores favor long; flipping weights heavy-toward-short flips outcome
        v1 = EvaluatorVerdict(name="a", score=0.6, direction=DIR_LONG)
        v2 = EvaluatorVerdict(name="b", score=0.5, direction=DIR_SHORT)
        d_eq = aggregate_direction([v1, v2], weights={"a": 1.0, "b": 1.0})
        assert d_eq == DIR_LONG
        d_w = aggregate_direction([v1, v2], weights={"a": 0.1, "b": 5.0})
        assert d_w == DIR_SHORT


class TestChainEndToEnd:
    def test_chain_emits_one_verdict_per_evaluator(self, oversold_ohlcv: pd.DataFrame) -> None:
        chain = build_default_chain()
        result = chain.evaluate("DOWN", oversold_ohlcv)
        names = [v.name for v in result.verdicts]
        assert names == ["rsi", "breakout", "rel_volume"]
        assert result.error is None

    def test_composite_score_matches_scanner_on_same_df(
        self, oversold_ohlcv: pd.DataFrame
    ) -> None:
        """Compatibility check: same math, same composite, modulo rounding."""
        from advisor.scanner import score_symbol
        chain_result = build_default_chain().evaluate("DOWN", oversold_ohlcv)
        scanner_result = score_symbol("DOWN", oversold_ohlcv)
        # Both should be within 0.01 (rounding of intermediate verdict scores)
        assert chain_result.composite_score == pytest.approx(scanner_result.score, abs=0.01)

    def test_chain_handles_empty_df(self) -> None:
        chain = build_default_chain()
        result = chain.evaluate("NULL", pd.DataFrame())
        assert result.error == "empty_ohlcv"
        assert result.composite_score == 0.0
        assert result.direction == DIR_NEUTRAL

    def test_chain_handles_evaluator_exceptions(self) -> None:
        class BoomEvaluator:
            name = "boom"
            min_bars = 0
            def evaluate(self, df, context):
                raise RuntimeError("synthetic explosion")

        from advisor.evaluators.base import Evaluator
        # Need an Evaluator instance — register via the protocol
        boom = BoomEvaluator()
        chain = EvaluatorChain([(boom, 1.0)])
        df = pd.DataFrame({
            "open": [100]*30, "high": [101]*30, "low": [99]*30,
            "close": [100]*30, "volume": [1000]*30,
        })
        result = chain.evaluate("X", df)
        assert result.verdicts[0].signal == "error"
        assert "synthetic explosion" in result.verdicts[0].metadata["error"]
        # Chain still produces a result — doesn't propagate the exception
        assert result.composite_score == 0.0

    def test_chain_result_to_dict_serializable(self, oversold_ohlcv: pd.DataFrame) -> None:
        import json
        chain = build_default_chain()
        result = chain.evaluate("DOWN", oversold_ohlcv)
        # Must be JSON-serializable for the API endpoint to return it
        s = json.dumps(result.to_dict())
        round_tripped = json.loads(s)
        assert round_tripped["symbol"] == "DOWN"
        assert "verdicts" in round_tripped
        assert "weights" in round_tripped
