"""Tests for the NewsSentimentEvaluator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import pytest

from advisor.evaluators import (
    EvaluatorContext,
    NewsSentimentEvaluator,
    build_default_chain,
)
from advisor.evaluators.base import DIR_LONG, DIR_NEUTRAL, DIR_SHORT


@dataclass
class _FakeSummary:
    symbol: str
    article_count: int
    avg_compound: float
    sentiment_label: str = "mixed"
    trending: bool = False


class _FakeStorage:
    """Minimal NewsStorage substitute returning canned summaries."""
    def __init__(self, summary: Optional[_FakeSummary] = None, raise_on_query: bool = False):
        self._summary = summary
        self._raise = raise_on_query

    def get_symbol_sentiment_summary(self, symbol, hours=24):
        if self._raise:
            raise RuntimeError("synthetic db failure")
        return self._summary


def _ctx(symbol: str = "NVDA") -> EvaluatorContext:
    return EvaluatorContext(symbol=symbol)


class TestVerdicts:
    def test_bullish_summary_returns_long(self):
        summary = _FakeSummary(symbol="NVDA", article_count=10,
                                avg_compound=0.35, sentiment_label="bullish")
        ev = NewsSentimentEvaluator(storage=_FakeStorage(summary))
        v = ev.evaluate(pd.DataFrame(), _ctx())
        assert v.name == "news_sentiment"
        assert v.direction == DIR_LONG
        assert v.score > 0.5
        assert v.signal == "bullish"
        assert v.metadata["article_count"] == 10

    def test_bearish_summary_returns_short(self):
        summary = _FakeSummary(symbol="NVDA", article_count=8,
                                avg_compound=-0.35, sentiment_label="bearish")
        ev = NewsSentimentEvaluator(storage=_FakeStorage(summary))
        v = ev.evaluate(pd.DataFrame(), _ctx())
        assert v.direction == DIR_SHORT
        assert v.score > 0.5

    def test_inside_neutral_band_returns_neutral(self):
        # avg_compound=0.03 → inside ±0.05 neutral band
        summary = _FakeSummary(symbol="NVDA", article_count=15,
                                avg_compound=0.03, sentiment_label="neutral")
        ev = NewsSentimentEvaluator(storage=_FakeStorage(summary))
        v = ev.evaluate(pd.DataFrame(), _ctx())
        assert v.direction == DIR_NEUTRAL
        assert v.score == 0.0

    def test_score_saturates_at_conviction_band(self):
        # avg=0.30 is well above the 0.15 conviction band → score should be 1.0
        summary = _FakeSummary(symbol="NVDA", article_count=20,
                                avg_compound=0.30, sentiment_label="bullish")
        ev = NewsSentimentEvaluator(storage=_FakeStorage(summary))
        v = ev.evaluate(pd.DataFrame(), _ctx())
        assert v.score == 1.0


class TestEdgeCases:
    def test_no_summary_returns_no_news(self):
        ev = NewsSentimentEvaluator(storage=_FakeStorage(None))
        v = ev.evaluate(pd.DataFrame(), _ctx())
        assert v.signal == "no_news"
        assert v.score == 0.0
        assert v.direction == DIR_NEUTRAL

    def test_empty_symbol_handled(self):
        ev = NewsSentimentEvaluator(storage=_FakeStorage(_FakeSummary("", 5, 0.4)))
        v = ev.evaluate(pd.DataFrame(), EvaluatorContext(symbol=""))
        assert v.signal == "empty_symbol"
        assert v.score == 0.0

    def test_low_article_count_neutralized(self):
        # 2 articles below the default min_articles=3
        summary = _FakeSummary(symbol="NVDA", article_count=2, avg_compound=0.5)
        ev = NewsSentimentEvaluator(storage=_FakeStorage(summary))
        v = ev.evaluate(pd.DataFrame(), _ctx())
        assert v.signal == "low_article_count"
        assert v.score == 0.0
        assert v.direction == DIR_NEUTRAL
        # Still surfaces the raw average for diagnostics
        assert v.raw_value == 0.5

    def test_storage_error_returns_safely(self):
        ev = NewsSentimentEvaluator(storage=_FakeStorage(raise_on_query=True))
        v = ev.evaluate(pd.DataFrame(), _ctx())
        assert v.signal == "storage_error"
        assert v.score == 0.0
        assert "synthetic db failure" in v.metadata["error"]

    def test_volume_boosts_confidence(self):
        # Same avg, different volume → higher volume gets higher confidence
        low_vol = _FakeSummary("NVDA", article_count=3, avg_compound=0.3)
        high_vol = _FakeSummary("NVDA", article_count=20, avg_compound=0.3)
        v_low = NewsSentimentEvaluator(storage=_FakeStorage(low_vol)).evaluate(pd.DataFrame(), _ctx())
        v_high = NewsSentimentEvaluator(storage=_FakeStorage(high_vol)).evaluate(pd.DataFrame(), _ctx())
        # Score is the same (saturated); confidence should differ
        assert v_high.confidence > v_low.confidence


class TestChainIntegration:
    def test_default_chain_includes_news(self):
        chain = build_default_chain()
        names = [ev.name for ev, _ in chain._items]
        assert "news_sentiment" in names

    def test_chain_without_news_when_disabled(self):
        chain = build_default_chain(include_news=False)
        names = [ev.name for ev, _ in chain._items]
        assert "news_sentiment" not in names

    def test_news_weight_overridable(self):
        chain = build_default_chain(weights={"news_sentiment": 0.5})
        # Weights are normalized; ratio should hold
        w = chain.weights
        assert w.get("news_sentiment", 0) > 0.3  # was 0.5 raw, normalized down

    def test_chain_runs_with_news_evaluator_swallowing_storage_failure(self):
        """The news evaluator must NEVER blow up the chain — it returns
        a safe 'storage_error' verdict instead so technical evaluators
        still contribute."""
        from advisor.evaluators import EvaluatorChain
        from advisor.evaluators.technical import RsiExtremeEvaluator

        # Build a one-element chain with a broken-storage news evaluator
        bad_storage = _FakeStorage(raise_on_query=True)
        chain = EvaluatorChain([
            (NewsSentimentEvaluator(storage=bad_storage), 1.0),
        ])
        # Need at least RSI-min-bars worth of df for safety; use trivial
        df = pd.DataFrame({
            "open": [100]*30, "high": [101]*30, "low": [99]*30,
            "close": [100]*30, "volume": [1000]*30,
        })
        result = chain.evaluate("NVDA", df)
        assert result.error is None  # chain itself doesn't error
        assert result.verdicts[0].signal == "storage_error"
