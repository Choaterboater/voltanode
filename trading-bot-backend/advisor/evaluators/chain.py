"""Evaluator chain — runs evaluators and aggregates verdicts."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from advisor.evaluators.base import (
    ChainResult,
    DIR_NEUTRAL,
    Evaluator,
    EvaluatorContext,
    EvaluatorVerdict,
    aggregate_direction,
)


class EvaluatorChain:
    """Run a sequence of evaluators on a symbol's OHLCV, aggregate verdicts.

    Weights are normalized at construction (sum to 1.0) so the composite
    score is comparable across chains with different weight configurations.
    """

    def __init__(
        self,
        evaluators: List[Tuple[Evaluator, float]],
    ) -> None:
        if not evaluators:
            raise ValueError("EvaluatorChain requires at least one evaluator")
        names = [e.name for e, _ in evaluators]
        if len(set(names)) != len(names):
            raise ValueError(
                f"Evaluator names must be unique within a chain; got {names}"
            )
        weight_sum = sum(w for _, w in evaluators)
        if weight_sum <= 0:
            raise ValueError("Evaluator weights must sum to a positive number")
        # Normalize weights to sum to 1.0 — operator can pass anything (0.4/0.3/0.3
        # or 4/3/3) and get a consistent 0–100 composite.
        self._items: List[Tuple[Evaluator, float]] = [
            (ev, float(w) / weight_sum) for ev, w in evaluators
        ]

    @property
    def weights(self) -> Dict[str, float]:
        return {ev.name: w for ev, w in self._items}

    def evaluate(
        self,
        symbol: str,
        df: pd.DataFrame,
        context: Optional[EvaluatorContext] = None,
    ) -> ChainResult:
        """Run the chain on one symbol. Returns ``ChainResult`` with verdicts."""
        if df is None or df.empty:
            return ChainResult(
                symbol=symbol,
                composite_score=0.0,
                direction=DIR_NEUTRAL,
                weights=self.weights,
                error="empty_ohlcv",
            )

        ctx = context or EvaluatorContext(symbol=symbol)
        verdicts: List[EvaluatorVerdict] = []
        for ev, _ in self._items:
            if ev.min_bars and len(df) < ev.min_bars:
                verdicts.append(EvaluatorVerdict(
                    name=ev.name, score=0.0, direction=DIR_NEUTRAL,
                    signal="insufficient_data",
                    metadata={"required_bars": ev.min_bars, "have_bars": len(df)},
                ))
                continue
            try:
                v = ev.evaluate(df, ctx)
            except Exception as exc:
                v = EvaluatorVerdict(
                    name=ev.name, score=0.0, direction=DIR_NEUTRAL,
                    signal="error", metadata={"error": str(exc)[:200]},
                )
            verdicts.append(v)

        # Composite = sum(weight * score) * 100  (weights already normalized)
        composite = sum(w * v.score for (_, w), v in zip(self._items, verdicts)) * 100.0
        direction = aggregate_direction(verdicts, weights=self.weights)

        return ChainResult(
            symbol=symbol,
            composite_score=composite,
            direction=direction,
            verdicts=verdicts,
            weights=self.weights,
        )


def build_default_chain(
    weights: Optional[Dict[str, float]] = None,
    rsi_period: int = 14,
    breakout_lookback: int = 20,
    volume_lookback: int = 20,
    include_news: bool = True,
    news_hours: int = 24,
) -> EvaluatorChain:
    """Build the canonical scanner chain.

    Default chain: RSI extremes + breakout + rel volume (mirrors
    advisor/scanner.py's DEFAULT_WEIGHTS) PLUS a news_sentiment voter
    when ``include_news`` is True. News gets 20% weight by default,
    proportionally shrinking the TA weights so they still sum to 1.0
    after normalization. Set include_news=False for legacy
    /scanner-compatible output.
    """
    from advisor.evaluators.news import NewsSentimentEvaluator
    from advisor.evaluators.technical import (
        BreakoutEvaluator,
        RelativeVolumeEvaluator,
        RsiExtremeEvaluator,
    )
    from advisor.scanner import DEFAULT_WEIGHTS

    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    items: list = [
        (RsiExtremeEvaluator(rsi_period=rsi_period),       w.get("rsi", 0.0)),
        (BreakoutEvaluator(lookback=breakout_lookback),    w.get("breakout", 0.0)),
        (RelativeVolumeEvaluator(lookback=volume_lookback), w.get("rel_volume", 0.0)),
    ]
    if include_news:
        # 20% default — empirically the negative-news bucket showed 79-100%
        # 1-3d hit rate (advisor/news_impact backtest). Operator can
        # override via the weights dict using key "news_sentiment".
        items.append((NewsSentimentEvaluator(hours=news_hours),
                      w.get("news_sentiment", 0.20)))
    return EvaluatorChain(items)
