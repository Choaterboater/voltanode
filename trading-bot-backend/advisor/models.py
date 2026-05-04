"""Shared data classes for the AI Advisor module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class IndicatorReading:
    """Single indicator reading with signal interpretation."""

    name: str
    value: float
    signal: str  # "bullish", "bearish", "neutral"
    strength: float  # 0.0 to 1.0
    description: str


@dataclass
class PriceTarget:
    """Predicted price target with rationale."""

    label: str
    price: float
    probability: float  # 0.0 to 1.0
    rationale: str


@dataclass
class LLMCommentary:
    """Optional LLM-generated commentary blended with the deterministic TA verdict."""

    rationale: str  # Human-readable narrative tying indicators + news together
    agreement: str  # "agrees", "disagrees", "mixed" — how the LLM views the TA verdict
    adjusted_confidence: float  # 0–100, LLM's blended confidence after considering news
    key_factors: List[str] = field(default_factory=list)  # Top 3-5 drivers
    news_impact: str = "none"  # "high" | "medium" | "low" | "none"
    article_count: int = 0
    model: str = ""  # Which LLM produced this (e.g. "llama3.1:8b")
    # When the LLM disagrees with the TA verdict, this is the action it
    # would prefer. Empty string when it agrees or has no strong alternative.
    alternative_verdict: str = ""  # "" | "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL"


@dataclass
class AnalysisResult:
    """Complete analysis result for a symbol."""

    symbol: str
    current_price: float
    asset_type: str
    verdict: str  # "BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL"
    confidence: float  # 0.0 to 100.0
    summary: str
    indicators: List[IndicatorReading]
    price_targets: List[PriceTarget]
    risk_level: str  # "low", "moderate", "high", "extreme"
    suggested_position_size: float  # % of portfolio
    entry_zone: tuple  # (low, high)
    stop_loss: float
    take_profit: float
    time_horizon: str  # "short_term", "medium_term", "long_term"
    chart_data: Dict[str, Any] = field(default_factory=dict)
    llm_commentary: "LLMCommentary | None" = None
