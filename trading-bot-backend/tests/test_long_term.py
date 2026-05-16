"""Tests for the long-term (year+) holding screener."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from advisor.fundamentals import FundamentalSnapshot
from advisor.long_term import (
    DEFAULT_WEIGHTS,
    HIGH_VOL,
    LOW_VOL,
    LongTermScore,
    MIN_BARS_LONG_TERM,
    _fundamentals_component,
    _low_volatility_component,
    _trend_component,
    rank_long_term,
    score_long_term,
)


@pytest.fixture
def two_year_uptrend() -> pd.DataFrame:
    """500 bars of low-vol uptrend → trend high + vol low."""
    np.random.seed(11)
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 + np.arange(n) * 0.15 + np.random.randn(n) * 0.5
    return pd.DataFrame({
        "timestamp": dates,
        "open": close * 0.999, "high": close * 1.005,
        "low": close * 0.995, "close": close,
        "volume": np.random.randint(1000, 5000, n),
    })


@pytest.fixture
def two_year_downtrend() -> pd.DataFrame:
    """500 bars of steady downtrend → trend zero, current < 200dma."""
    np.random.seed(13)
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 200 - np.arange(n) * 0.15 + np.random.randn(n) * 0.5
    return pd.DataFrame({
        "timestamp": dates,
        "open": close * 0.999, "high": close * 1.005,
        "low": close * 0.995, "close": close,
        "volume": np.random.randint(1000, 5000, n),
    })


@pytest.fixture
def two_year_high_vol() -> pd.DataFrame:
    """Sideways but very jumpy — vol component should score near zero."""
    np.random.seed(17)
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    # Daily ~5% noise → annualized vol ≈ 80%
    close = 100 + np.cumsum(np.random.randn(n) * 5)
    close = np.maximum(close, 1)  # don't go negative
    return pd.DataFrame({
        "timestamp": dates,
        "open": close * 0.99, "high": close * 1.03,
        "low": close * 0.97, "close": close,
        "volume": np.random.randint(1000, 5000, n),
    })


@pytest.fixture
def strong_fund_snap() -> FundamentalSnapshot:
    """Excellent fundamentals → score_fundamentals returns near 100."""
    return FundamentalSnapshot(
        symbol="GREAT", asset_type="stock", name="Great Co",
        sector="Technology",
        trailing_pe=14.0, peg_ratio=0.8,
        return_on_equity=0.30, profit_margin=0.25,
        revenue_growth=0.25, debt_to_equity=20.0,
        recommendation_mean=1.5,
    )


@pytest.fixture
def weak_fund_snap() -> FundamentalSnapshot:
    """Poor fundamentals → score near 0."""
    return FundamentalSnapshot(
        symbol="WEAK", asset_type="stock", name="Weak Co",
        sector="Energy",
        trailing_pe=80.0, peg_ratio=4.0,
        return_on_equity=0.02, profit_margin=-0.05,
        revenue_growth=-0.10, debt_to_equity=400.0,
        recommendation_mean=4.2,
    )


class TestFundamentalsComponent:
    def test_strong_fundamentals_high_score(self, strong_fund_snap) -> None:
        c = _fundamentals_component(strong_fund_snap)
        assert c.name == "fundamentals"
        assert c.score > 0.85
        assert c.value is not None and c.value > 85

    def test_weak_fundamentals_low_score(self, weak_fund_snap) -> None:
        c = _fundamentals_component(weak_fund_snap)
        assert c.score < 0.20

    def test_crypto_returns_neutral(self) -> None:
        snap = FundamentalSnapshot(symbol="BTC", asset_type="crypto")
        c = _fundamentals_component(snap)
        assert c.score == pytest.approx(0.5)


class TestTrendComponent:
    def test_uptrend_high_score(self, two_year_uptrend: pd.DataFrame) -> None:
        c = _trend_component(two_year_uptrend)
        # Above 200dma AND positive 1y return = full credit (1.0)
        assert c.score >= 0.95
        assert c.signal == "strong_uptrend"
        assert c.value > 0  # 1y return is positive

    def test_downtrend_zero_score(self, two_year_downtrend: pd.DataFrame) -> None:
        c = _trend_component(two_year_downtrend)
        # Below 200dma AND negative 1y return = zero
        assert c.score == 0.0
        assert c.signal == "downtrend"

    def test_insufficient_history_zero(self) -> None:
        short = pd.DataFrame({"close": [100] * 50, "open": [100]*50, "high": [101]*50, "low": [99]*50, "volume": [1000]*50})
        c = _trend_component(short)
        assert c.score == 0.0
        assert c.signal == "insufficient_history"


class TestLowVolatilityComponent:
    def test_low_vol_uptrend_high_score(self, two_year_uptrend: pd.DataFrame) -> None:
        # The uptrend fixture has tiny noise — should sit in the low-vol band
        c = _low_volatility_component(two_year_uptrend)
        assert c.score > 0.5  # well below HIGH_VOL=0.6
        assert c.value is not None and c.value < HIGH_VOL

    def test_high_vol_low_score(self, two_year_high_vol: pd.DataFrame) -> None:
        c = _low_volatility_component(two_year_high_vol)
        assert c.score < 0.20
        assert c.value is not None and c.value > LOW_VOL

    def test_insufficient_history(self) -> None:
        short = pd.DataFrame({"close": [100] * 50, "open": [100]*50, "high": [101]*50, "low": [99]*50, "volume": [1000]*50})
        c = _low_volatility_component(short)
        assert c.score == 0.0
        assert c.signal == "insufficient_history"


class TestComposite:
    def test_great_company_uptrend_scores_high(self, two_year_uptrend, strong_fund_snap) -> None:
        s = score_long_term("GREAT", two_year_uptrend, strong_fund_snap)
        assert s.symbol == "GREAT"
        assert s.score > 80  # composite of high fund + high trend + low vol
        assert s.error is None
        # Components surfaced for the API consumer
        assert set(s.components.keys()) == {"fundamentals", "trend", "low_volatility"}

    def test_weak_company_downtrend_scores_low(self, two_year_downtrend, weak_fund_snap) -> None:
        s = score_long_term("WEAK", two_year_downtrend, weak_fund_snap)
        # Weak fundamentals (0) + downtrend (0) + low-vol (full credit, since
        # the synthetic downtrend is straight-line smooth) = 20% weight on
        # low-vol max = 20.0. Anything <=20 is correct.
        assert s.score <= 20.0
        assert s.components["fundamentals"].score == pytest.approx(0.0)
        assert s.components["trend"].score == 0.0

    def test_empty_df_returns_error(self, strong_fund_snap) -> None:
        s = score_long_term("X", pd.DataFrame(), strong_fund_snap)
        assert s.error == "empty_ohlcv"
        assert s.score == 0.0

    def test_short_df_returns_fundamentals_only(self, strong_fund_snap) -> None:
        short = pd.DataFrame({
            "open": [100]*50, "high": [101]*50, "low": [99]*50,
            "close": [100]*50, "volume": [1000]*50,
        })
        s = score_long_term("GREAT", short, strong_fund_snap)
        # Trend + vol components zero; fundamentals still scored.
        assert s.error == "insufficient_history_for_trend_or_vol"
        # Composite = 0.5 * fund_score * 100, so a high-fund stock comes out around 45-50
        assert 30 < s.score < 55

    def test_weights_normalize(self, two_year_uptrend, strong_fund_snap) -> None:
        # Caller passes unnormalized 5/3/2 — should produce same composite
        # as the default 0.5/0.3/0.2 normalization.
        s_default = score_long_term("GREAT", two_year_uptrend, strong_fund_snap)
        s_un = score_long_term(
            "GREAT", two_year_uptrend, strong_fund_snap,
            weights={"fundamentals": 5, "trend": 3, "low_volatility": 2},
        )
        assert s_default.score == pytest.approx(s_un.score, abs=0.01)

    def test_weight_override_changes_ranking(self, two_year_uptrend, two_year_downtrend,
                                              strong_fund_snap, weak_fund_snap) -> None:
        # GREAT-uptrend vs WEAK-uptrend (same OHLCV, different fundamentals).
        # Under default weights GREAT wins; under fundamentals=0/trend=1 they tie.
        s_great = score_long_term("GREAT", two_year_uptrend, strong_fund_snap)
        s_weak_up = score_long_term("WEAK", two_year_uptrend, weak_fund_snap)
        assert s_great.score > s_weak_up.score
        # Strip fundamentals entirely
        s_great_no_f = score_long_term(
            "GREAT", two_year_uptrend, strong_fund_snap,
            weights={"fundamentals": 0, "trend": 1, "low_volatility": 0},
        )
        s_weak_no_f = score_long_term(
            "WEAK", two_year_uptrend, weak_fund_snap,
            weights={"fundamentals": 0, "trend": 1, "low_volatility": 0},
        )
        assert s_great_no_f.score == pytest.approx(s_weak_no_f.score, abs=0.01)


class TestRanking:
    def test_rank_sorts_descending(self, two_year_uptrend, two_year_downtrend,
                                    strong_fund_snap, weak_fund_snap) -> None:
        a = score_long_term("A", two_year_uptrend, strong_fund_snap)
        b = score_long_term("B", two_year_downtrend, weak_fund_snap)
        ranked = rank_long_term([b, a])
        assert ranked[0].symbol == "A"
        assert ranked[1].symbol == "B"

    def test_rank_filters_below_min_score(self, two_year_uptrend, two_year_downtrend,
                                           strong_fund_snap, weak_fund_snap) -> None:
        a = score_long_term("A", two_year_uptrend, strong_fund_snap)
        b = score_long_term("B", two_year_downtrend, weak_fund_snap)
        ranked = rank_long_term([a, b], min_score=50.0)
        # b's composite is far below 50; should be dropped
        assert all(r.score >= 50.0 for r in ranked)
        assert "A" in [r.symbol for r in ranked]

    def test_rank_top_n_cap(self, two_year_uptrend, strong_fund_snap) -> None:
        scores = [
            score_long_term(f"S{i}", two_year_uptrend, strong_fund_snap)
            for i in range(10)
        ]
        ranked = rank_long_term(scores, top=3)
        assert len(ranked) == 3

    def test_rank_keeps_insufficient_history_as_partial(self, strong_fund_snap) -> None:
        # Symbols with only fundamentals (no trend/vol) should still rank.
        short = pd.DataFrame({
            "open": [100]*50, "high": [101]*50, "low": [99]*50,
            "close": [100]*50, "volume": [1000]*50,
        })
        partial = score_long_term("PARTIAL", short, strong_fund_snap)
        assert partial.error == "insufficient_history_for_trend_or_vol"
        ranked = rank_long_term([partial])
        assert len(ranked) == 1


class TestDefaultWeights:
    def test_default_weights_sum_to_one(self) -> None:
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_default_weights_have_fundamentals_majority(self) -> None:
        # Fundamentals should dominate the composite for a "buy and hold"
        # signal — if this changes, update the endpoint docstring.
        assert DEFAULT_WEIGHTS["fundamentals"] >= 0.50
