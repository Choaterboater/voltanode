"""Evaluator-chain pattern for composite signal scoring.

Inspired by OctoBot's evaluator architecture: each Evaluator emits a
weighted opinion (score 0–1 + direction + tag) on a symbol, a chain
aggregates them, and the operator tunes weights instead of editing the
aggregation logic in one place. This makes adding new signals (TA, social,
fundamental, on-chain) additive — register an Evaluator subclass, give it
a weight, done.

The existing ``advisor/scanner.py`` composite scorer is the "before"
shape: three components hardcoded into ``score_symbol`` with a fixed
weighted sum. This module is the "after": same math, decomposed.

``GET /advisor/scanner`` is unchanged. The new pattern is exposed via
``POST /advisor/scanner/chain``.
"""

from advisor.evaluators.base import (
    ChainResult,
    Evaluator,
    EvaluatorContext,
    EvaluatorVerdict,
    aggregate_direction,
)
from advisor.evaluators.chain import EvaluatorChain, build_default_chain
from advisor.evaluators.news import NewsSentimentEvaluator
from advisor.evaluators.technical import (
    BreakoutEvaluator,
    RelativeVolumeEvaluator,
    RsiExtremeEvaluator,
)

__all__ = [
    "Evaluator",
    "EvaluatorContext",
    "EvaluatorVerdict",
    "ChainResult",
    "EvaluatorChain",
    "build_default_chain",
    "RsiExtremeEvaluator",
    "BreakoutEvaluator",
    "RelativeVolumeEvaluator",
    "NewsSentimentEvaluator",
    "aggregate_direction",
]
