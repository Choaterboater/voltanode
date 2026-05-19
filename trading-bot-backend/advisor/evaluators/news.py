"""News sentiment evaluator — drops news into the evaluator-chain pattern.

Reads aggregated sentiment from news.storage.NewsStorage (the same source
the news_sentiment bots and /advisor/research use). Maps avg compound
score → 0-1 strength + a directional vote.

Today's calibration backtest (see advisor/news_impact.py) showed that
strongly-negative news at 1-3d gives 79-100% hit rate, while strongly-
positive news fades at 1d but pays at 5d (93%). For the chain's purposes
we just emit the directional read; the chain's caller decides horizon.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from advisor.evaluators.base import (
    DIR_LONG,
    DIR_NEUTRAL,
    DIR_SHORT,
    Evaluator,
    EvaluatorContext,
    EvaluatorVerdict,
)
from news.storage import NewsStorage


# Score thresholds — same band the existing SymbolSentiment.label uses
# so chain output is consistent with the news endpoints. Anything inside
# ±0.05 is "neutral noise"; ±0.15 splits drift from conviction.
_NEUTRAL_BAND = 0.05
_CONVICTION_BAND = 0.15


class NewsSentimentEvaluator(Evaluator):
    """24h aggregated news sentiment for a symbol.

    Constructor takes an optional NewsStorage so tests can inject a fake;
    production callers can omit it and the evaluator builds one on first
    use (cheap — same SQLite handle the news endpoints use).
    """
    name = "news_sentiment"
    # No OHLCV requirement — news evaluator looks at the news DB, not bars.
    # min_bars=0 means the chain will never skip it for "insufficient data."
    min_bars = 0

    def __init__(
        self,
        hours: int = 24,
        min_articles: int = 3,
        storage: Optional[NewsStorage] = None,
    ) -> None:
        self.hours = hours
        self.min_articles = min_articles
        self._storage = storage

    def _get_storage(self) -> NewsStorage:
        if self._storage is None:
            self._storage = NewsStorage()
        return self._storage

    def evaluate(self, df: pd.DataFrame, context: EvaluatorContext) -> EvaluatorVerdict:
        # Crypto symbols → CoinGecko-id or ticker; news storage keys by
        # ticker. The context already normalises to upper-case symbol via
        # the chain, so just use it directly. Sym mapping for crypto
        # coingecko-ids (bitcoin → BTC) lives in advisor.llm_advisor;
        # we accept the caller's symbol verbatim and miss gracefully
        # when no rows match.
        symbol = (context.symbol or "").upper().strip()
        if not symbol:
            return EvaluatorVerdict(
                name=self.name, score=0.0, direction=DIR_NEUTRAL,
                signal="empty_symbol",
            )

        try:
            storage = self._get_storage()
            summary = storage.get_symbol_sentiment_summary(
                symbol=symbol, hours=self.hours,
            )
        except Exception as exc:
            return EvaluatorVerdict(
                name=self.name, score=0.0, direction=DIR_NEUTRAL,
                signal="storage_error",
                metadata={"error": str(exc)[:200]},
            )

        if summary is None or summary.article_count == 0:
            return EvaluatorVerdict(
                name=self.name, score=0.0, direction=DIR_NEUTRAL,
                signal="no_news",
                metadata={"hours": self.hours},
            )

        avg = float(summary.avg_compound)
        n = int(summary.article_count)

        # Need enough articles to trust the average. Below the floor,
        # neutralize the verdict but still report the underlying value
        # for diagnostic surface.
        if n < self.min_articles:
            return EvaluatorVerdict(
                name=self.name, score=0.0, direction=DIR_NEUTRAL,
                signal="low_article_count",
                raw_value=avg,
                metadata={"article_count": n, "min_required": self.min_articles},
            )

        # Direction — strict band so chain aggregation can rely on a
        # confident vote. Inside ±_NEUTRAL_BAND we return neutral so we
        # don't push the composite around on noise.
        if avg > _NEUTRAL_BAND:
            direction = DIR_LONG
        elif avg < -_NEUTRAL_BAND:
            direction = DIR_SHORT
        else:
            direction = DIR_NEUTRAL

        # Strength — scales |avg| to [0,1] saturating at the conviction
        # band. avg=±0.15 → score 1.0; avg=±0.05 → ~0.0.
        magnitude = max(0.0, abs(avg) - _NEUTRAL_BAND)
        score = min(1.0, magnitude / max(1e-9, _CONVICTION_BAND - _NEUTRAL_BAND))

        # Article-volume confidence — confidence should reflect "we have
        # a lot of agreeing data" not just "the average is extreme."
        # Cap n at 10 for the multiplier so 100 articles doesn't trump
        # the directional read of a single strongly-worded story.
        vol_conf = min(1.0, n / 10.0)
        confidence = score * (0.5 + 0.5 * vol_conf)

        signal = summary.sentiment_label or "mixed"

        return EvaluatorVerdict(
            name=self.name,
            score=score,
            direction=direction,
            signal=signal,
            raw_value=avg,
            confidence=confidence,
            metadata={
                "article_count": n,
                "hours": self.hours,
                "trending": bool(summary.trending),
            },
        )
