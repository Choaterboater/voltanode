"""Tests for advisor.news_impact — calibration backtest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import numpy as np
import pandas as pd
import pytest

from advisor.news_impact import (
    BucketStat,
    DEFAULT_HORIZONS_DAYS,
    DEFAULT_SCORE_BUCKETS,
    ImpactReport,
    _bucketize,
    _price_n_trading_days_later,
    _price_on_or_after,
    compute_impact,
)


@dataclass
class _FakeScore:
    compound_score: float
    analyzed_at: datetime
    article_id: str = "fake"
    symbol: str = "FAKE"


class _FakeStorage:
    def __init__(self, scores_by_symbol):
        self._by_sym = scores_by_symbol

    def get_sentiment_for_symbol(self, symbol, hours=24, model=None):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [s for s in self._by_sym.get(symbol, []) if s.analyzed_at >= cutoff]


def _make_hist(start: datetime, prices: list) -> pd.DataFrame:
    """Build a yfinance-shaped daily history with explicit closes."""
    n = len(prices)
    ts = [start + timedelta(days=i) for i in range(n)]
    df = pd.DataFrame({
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": [1000] * n,
    })
    df["ts_utc"] = pd.to_datetime(ts, utc=True)
    return df


class TestBucketize:
    def test_score_lands_in_bucket(self):
        assert _bucketize(-0.7, DEFAULT_SCORE_BUCKETS) == (-1.01, -0.50)
        assert _bucketize(-0.3, DEFAULT_SCORE_BUCKETS) == (-0.50, -0.10)
        assert _bucketize(0.0,  DEFAULT_SCORE_BUCKETS) == (-0.10, 0.10)
        assert _bucketize(0.3,  DEFAULT_SCORE_BUCKETS) == (0.10, 0.50)
        assert _bucketize(0.8,  DEFAULT_SCORE_BUCKETS) == (0.50, 1.01)

    def test_boundary_goes_to_higher_bucket(self):
        # Buckets are half-open [low, high)
        assert _bucketize(0.10, DEFAULT_SCORE_BUCKETS) == (0.10, 0.50)


class TestPriceLookups:
    def test_price_on_or_after_matches_same_day(self):
        start = datetime(2026, 5, 1, tzinfo=timezone.utc)
        hist = _make_hist(start, [100.0, 101.0, 102.0, 103.0, 104.0])
        # Article at start → matches first row
        result = _price_on_or_after(hist, start)
        assert result is not None
        price, bar_ts = result
        assert price == 100.0

    def test_price_on_or_after_jumps_weekend(self):
        # Hist has gaps — article timestamp lands on a gap day
        start = datetime(2026, 5, 1, tzinfo=timezone.utc)
        hist = _make_hist(start, [100.0, 101.0, 102.0])
        # Article 1 day after the last bar → no future close → None
        result = _price_on_or_after(hist, start + timedelta(days=10))
        assert result is None

    def test_price_n_trading_days_later(self):
        start = datetime(2026, 5, 1, tzinfo=timezone.utc)
        hist = _make_hist(start, [100.0, 101.0, 102.0, 103.0, 104.0])
        # 2 trading days after the first bar → 102.0
        result = _price_n_trading_days_later(hist, start, 2)
        assert result == 102.0

    def test_price_n_days_off_end(self):
        start = datetime(2026, 5, 1, tzinfo=timezone.utc)
        hist = _make_hist(start, [100.0, 101.0])
        # Asking for 5 days later when we only have 2 → None
        result = _price_n_trading_days_later(hist, start, 5)
        assert result is None


class TestComputeImpactWithInjectedHist:
    """Drive compute_impact with monkeypatched yfinance fetch + canned articles."""

    def _setup(self, monkeypatch, articles_for_symbol, hist_for_symbol):
        """Patch _fetch_history_for_symbol so we don't hit yfinance."""
        from advisor import news_impact

        def _fake_fetch(symbol, days_back):
            return hist_for_symbol.get(symbol)

        monkeypatch.setattr(news_impact, "_fetch_history_for_symbol", _fake_fetch)
        return _FakeStorage(articles_for_symbol)

    def test_positive_score_aligned_with_positive_return(self, monkeypatch):
        # Construct a perfectly-aligned dataset: positive articles → price up
        now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
        # 5 trading days starting 5 days ago, then up-trend
        start = now - timedelta(days=10)
        # Up-trend: each day +1%
        prices = [100.0 * (1.01 ** i) for i in range(15)]
        hist = _make_hist(start, prices)
        # Three positive-score articles at days 0, 1, 2
        articles = [
            _FakeScore(compound_score=0.8, analyzed_at=start + timedelta(days=0)),
            _FakeScore(compound_score=0.7, analyzed_at=start + timedelta(days=1)),
            _FakeScore(compound_score=0.6, analyzed_at=start + timedelta(days=2)),
        ]
        storage = self._setup(monkeypatch, {"NVDA": articles}, {"NVDA": hist})

        report = compute_impact(["NVDA"], lookback_days=20, horizons_days=(1, 3),
                                 storage=storage)
        assert report.error is None
        assert report.article_count == 3
        # Find the (+0.50, +1.01) bucket at horizon=1: 3 articles, all positive returns
        cells = {(b.score_low, b.score_high, b.horizon_days): b for b in report.buckets}
        # bucket (0.5, 1.01) horizon 1
        high_pos = cells.get((0.50, 1.01, 1))
        assert high_pos is not None
        assert high_pos.n == 3
        assert high_pos.mean_return_pct > 0
        assert high_pos.hit_rate == 1.0  # all 3 had positive return

    def test_negative_score_misaligned_with_uptrend(self, monkeypatch):
        # Negative articles into an uptrend → hit_rate near zero
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=10)
        prices = [100.0 * (1.01 ** i) for i in range(15)]
        hist = _make_hist(start, prices)
        articles = [
            _FakeScore(compound_score=-0.8, analyzed_at=start + timedelta(days=i))
            for i in range(3)
        ]
        storage = self._setup(monkeypatch, {"NVDA": articles}, {"NVDA": hist})

        report = compute_impact(["NVDA"], lookback_days=20, horizons_days=(1,),
                                 storage=storage)
        cells = {(b.score_low, b.score_high, b.horizon_days): b for b in report.buckets}
        high_neg = cells.get((-1.01, -0.50, 1))
        assert high_neg is not None
        assert high_neg.n == 3
        # Negative-bucket hit = return < 0; we engineered all-positive returns
        assert high_neg.hit_rate == 0.0
        assert high_neg.mean_return_pct > 0  # actual return was up

    def test_missing_history_skips_symbol(self, monkeypatch):
        storage = self._setup(monkeypatch, {"NVDA": [_FakeScore(0.5, datetime.now(timezone.utc))]},
                              {})  # no NVDA history
        report = compute_impact(["NVDA"], lookback_days=10, storage=storage)
        assert report.article_count == 0
        assert report.skipped_count >= 1
        assert report.by_symbol["NVDA"]["skipped"] is True

    def test_middle_bucket_hit_rate_is_half(self, monkeypatch):
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=10)
        prices = [100.0 + i * 2.0 for i in range(15)]
        hist = _make_hist(start, prices)
        # Neutral-score articles (-0.05) → land in middle bucket
        articles = [_FakeScore(0.0, start + timedelta(days=i)) for i in range(3)]
        storage = self._setup(monkeypatch, {"NVDA": articles}, {"NVDA": hist})
        report = compute_impact(["NVDA"], lookback_days=20, horizons_days=(1,),
                                 storage=storage)
        cells = {(b.score_low, b.score_high, b.horizon_days): b for b in report.buckets}
        middle = cells.get((-0.10, 0.10, 1))
        assert middle is not None and middle.n == 3
        # Middle bucket straddles zero — directional hit-rate undefined → 0.5
        assert middle.hit_rate == 0.5

    def test_to_dict_serializable(self, monkeypatch):
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=5)
        hist = _make_hist(start, [100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        articles = [_FakeScore(0.5, start + timedelta(days=0))]
        storage = self._setup(monkeypatch, {"NVDA": articles}, {"NVDA": hist})
        report = compute_impact(["NVDA"], lookback_days=10, storage=storage)
        import json
        s = json.dumps(report.to_dict())
        round_tripped = json.loads(s)
        assert round_tripped["article_count"] == 1
        assert "buckets" in round_tripped


class TestDefaults:
    def test_score_buckets_span_full_range(self):
        # First bucket starts <= -1, last bucket ends > 1
        lows = [b[0] for b in DEFAULT_SCORE_BUCKETS]
        highs = [b[1] for b in DEFAULT_SCORE_BUCKETS]
        assert min(lows) <= -1.0
        assert max(highs) >= 1.0

    def test_score_buckets_non_overlapping(self):
        # Each bucket's high should equal the next bucket's low (no gaps,
        # no overlaps — half-open [low, high) means boundary belongs higher)
        for i in range(len(DEFAULT_SCORE_BUCKETS) - 1):
            assert DEFAULT_SCORE_BUCKETS[i][1] == DEFAULT_SCORE_BUCKETS[i + 1][0]

    def test_horizons_positive_and_ordered(self):
        assert DEFAULT_HORIZONS_DAYS == tuple(sorted(DEFAULT_HORIZONS_DAYS))
        assert all(h > 0 for h in DEFAULT_HORIZONS_DAYS)
