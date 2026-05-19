"""Tests for advisor.news_velocity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from advisor.news_velocity import (
    DEFAULT_WINDOWS_HOURS,
    VelocitySnapshot,
    WindowStat,
    _classify_velocity,
    _window_stats,
    compute_velocity,
)


@dataclass
class _FakeScore:
    compound_score: float
    analyzed_at: datetime


class _FakeStorage:
    """Minimal NewsStorage substitute that returns canned scores."""
    def __init__(self, scores):
        self._scores = scores

    def get_sentiment_for_symbol(self, symbol, hours=24, model=None):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [s for s in self._scores if s.analyzed_at >= cutoff]


def _at(minutes_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


class TestWindowStats:
    def test_empty_returns_zero(self):
        ws = _window_stats([], hours=1)
        assert ws.article_count == 0
        assert ws.avg_compound == 0.0

    def test_filters_outside_window(self):
        scores = [
            _FakeScore(0.5, _at(10)),    # 10 min ago — in 1h window
            _FakeScore(0.7, _at(30)),    # 30 min ago — in 1h window
            _FakeScore(-0.4, _at(120)),  # 2h ago — outside 1h
        ]
        ws = _window_stats(scores, hours=1)
        assert ws.article_count == 2
        assert ws.avg_compound == pytest.approx(0.6)
        assert ws.max_compound == 0.7
        assert ws.min_compound == 0.5

    def test_includes_all_when_window_large(self):
        scores = [_FakeScore(0.5, _at(10)), _FakeScore(-0.3, _at(60))]
        ws = _window_stats(scores, hours=24)
        assert ws.article_count == 2
        assert ws.avg_compound == pytest.approx(0.1)


class TestClassifyVelocity:
    @pytest.mark.parametrize("v,expected", [
        (0.30, "accelerating_bull"),
        (0.10, "drifting_bull"),
        (0.0,  "flat"),
        (-0.10, "drifting_bear"),
        (-0.30, "accelerating_bear"),
    ])
    def test_thresholds(self, v, expected):
        assert _classify_velocity(v) == expected


class TestComputeVelocity:
    def test_accelerating_bull_when_short_avg_higher(self):
        # 1h avg = 0.6 (positive), 24h avg = 0.1 (much lower) → strong bull velocity
        scores = [
            _FakeScore(0.7, _at(10)),
            _FakeScore(0.5, _at(30)),       # 1h window: avg 0.6
            _FakeScore(0.0, _at(60 * 8)),   # 8h ago — out of 6h, in 24h
            _FakeScore(-0.3, _at(60 * 20)), # 20h ago — in 24h
        ]
        snap = compute_velocity("NVDA", storage=_FakeStorage(scores))
        assert snap.error is None
        assert snap.velocity > 0.3
        assert snap.velocity_label == "accelerating_bull"
        assert snap.windows[0].hours == 1
        assert snap.windows[-1].hours == 24

    def test_accelerating_bear_when_short_avg_lower(self):
        # 1h avg = -0.7, 24h avg = -0.3 → velocity -0.4 (still > threshold for bear)
        scores = [
            _FakeScore(-0.8, _at(10)),
            _FakeScore(-0.6, _at(40)),     # 1h: avg -0.7
            _FakeScore(0.5, _at(60 * 12)), # 12h ago: pulls 24h avg up to -0.3
        ]
        snap = compute_velocity("NVDA", storage=_FakeStorage(scores))
        assert snap.velocity < -0.30
        assert snap.velocity_label == "accelerating_bear"

    def test_flat_when_windows_match(self):
        # Same avg across windows → velocity ~0
        scores = [
            _FakeScore(0.2, _at(10)),
            _FakeScore(0.2, _at(60 * 4)),
            _FakeScore(0.2, _at(60 * 20)),
        ]
        snap = compute_velocity("NVDA", storage=_FakeStorage(scores))
        assert abs(snap.velocity) < 0.05
        assert snap.velocity_label == "flat"

    def test_fresh_pct_reflects_recency(self):
        # 1 article in 1h, 4 total in 24h → fresh_pct = 0.25
        scores = [
            _FakeScore(0.3, _at(10)),
            _FakeScore(0.3, _at(60 * 2)),
            _FakeScore(0.3, _at(60 * 6)),
            _FakeScore(0.3, _at(60 * 18)),
        ]
        snap = compute_velocity("NVDA", storage=_FakeStorage(scores))
        assert snap.fresh_article_pct == pytest.approx(0.25)

    def test_acceleration_present_with_three_windows(self):
        # 1h: 0.6, 6h: 0.3, 24h: 0.1 → velocity 0.5, accel = (0.6-0.3) - (0.3-0.1) = 0.1
        scores = [
            _FakeScore(0.6, _at(15)),
            _FakeScore(0.2, _at(60 * 3)),  # in 6h window, not 1h
            _FakeScore(0.05, _at(60 * 12)),
        ]
        snap = compute_velocity("NVDA", storage=_FakeStorage(scores))
        assert snap.acceleration != 0.0

    def test_empty_symbol_returns_error(self):
        snap = compute_velocity("", storage=_FakeStorage([]))
        assert snap.error == "empty_symbol"

    def test_no_articles_returns_flat(self):
        snap = compute_velocity("NVDA", storage=_FakeStorage([]))
        # No data → all zeros → velocity 0 → flat (NOT an error)
        assert snap.error is None
        assert snap.velocity == 0.0
        assert snap.velocity_label == "flat"
        assert all(w.article_count == 0 for w in snap.windows)

    def test_to_dict_serializable(self):
        import json
        scores = [_FakeScore(0.5, _at(5))]
        snap = compute_velocity("NVDA", storage=_FakeStorage(scores))
        s = json.dumps(snap.to_dict())
        round_tripped = json.loads(s)
        assert round_tripped["symbol"] == "NVDA"
        assert "windows" in round_tripped
        assert "velocity" in round_tripped


class TestDefaults:
    def test_default_windows_ordered_short_to_long(self):
        assert DEFAULT_WINDOWS_HOURS == tuple(sorted(DEFAULT_WINDOWS_HOURS))

    def test_default_windows_include_short_and_long(self):
        assert min(DEFAULT_WINDOWS_HOURS) <= 1
        assert max(DEFAULT_WINDOWS_HOURS) >= 24
