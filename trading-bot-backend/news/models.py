"""News and sentiment data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class NewsArticle:
    """A news article from Alpaca or other source."""

    id: str
    headline: str
    summary: str
    source: str
    symbols: List[str]
    url: str = ""
    author: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    content: str = ""  # Full article text if available

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "headline": self.headline,
            "summary": self.summary,
            "source": self.source,
            "symbols": self.symbols,
            "url": self.url,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class SentimentResult:
    """Sentiment analysis result for a news article or text."""

    article_id: str
    symbol: str  # Primary symbol this sentiment applies to
    compound_score: float  # -1.0 (very negative) to +1.0 (very positive)
    positive_score: float
    negative_score: float
    neutral_score: float
    confidence: float  # 0.0 to 1.0
    model: str  # "vader", "kimi", "claude", etc.
    impact_assessment: str = ""  # LLM-generated: "high", "medium", "low"
    key_themes: List[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "article_id": self.article_id,
            "symbol": self.symbol,
            "compound_score": round(self.compound_score, 4),
            "positive_score": round(self.positive_score, 4),
            "negative_score": round(self.negative_score, 4),
            "neutral_score": round(self.neutral_score, 4),
            "confidence": round(self.confidence, 4),
            "model": self.model,
            "impact_assessment": self.impact_assessment,
            "key_themes": self.key_themes,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class SymbolSentiment:
    """Aggregated sentiment for a symbol across multiple articles."""

    symbol: str
    article_count: int
    avg_compound: float
    sentiment_label: str  # "bullish", "bearish", "neutral", "mixed"
    latest_headlines: List[str]
    trending: bool = False
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "article_count": self.article_count,
            "avg_compound": round(self.avg_compound, 4),
            "sentiment_label": self.sentiment_label,
            "latest_headlines": self.latest_headlines,
            "trending": self.trending,
            "updated_at": self.updated_at.isoformat(),
        }
