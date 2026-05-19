"""Evaluator protocol + verdict types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd


# Direction codes — kept as string literals to match the rest of the codebase
# (scanner.py, strategies, broker shims all speak this).
DIR_LONG = "long"
DIR_SHORT = "short"
DIR_NEUTRAL = "neutral"
VALID_DIRECTIONS = (DIR_LONG, DIR_SHORT, DIR_NEUTRAL)


@dataclass
class EvaluatorContext:
    """Cross-evaluator context passed into every ``evaluate`` call.

    Holds knobs an individual evaluator may need without bloating the call
    signature. Most evaluators ignore most fields. Add new fields here when
    a new evaluator needs cross-cutting state — don't thread them through
    constructor params.
    """
    symbol: str
    asset_class: str = "crypto"
    timeframe: str = "1h"
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluatorVerdict:
    """One evaluator's opinion on one symbol.

    Attributes:
        name: Evaluator's stable identifier (used as a dict key in chain output).
        score: Strength of the signal, 0.0–1.0. 0 means "no signal".
        direction: ``"long"`` | ``"short"`` | ``"neutral"``.
        signal: Short human-readable tag (e.g. ``"oversold"``, ``"breakout_up"``).
        raw_value: Underlying indicator value (e.g. RSI=24.3). Optional, for diagnostics.
        confidence: 0.0–1.0 self-reported reliability. Defaults to score.
        metadata: Free-form extra detail (band positions, breakout magnitudes, etc.).
    """
    name: str
    score: float
    direction: str
    signal: str = ""
    raw_value: Optional[float] = None
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in VALID_DIRECTIONS:
            raise ValueError(
                f"EvaluatorVerdict.direction must be one of {VALID_DIRECTIONS}, "
                f"got {self.direction!r}"
            )
        # Clamp score into [0,1] — defensive against bad evaluator math
        self.score = max(0.0, min(1.0, float(self.score)))
        if self.confidence is None:
            self.confidence = self.score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "direction": self.direction,
            "signal": self.signal,
            "raw_value": (
                round(self.raw_value, 4)
                if isinstance(self.raw_value, (int, float)) and self.raw_value is not None
                else self.raw_value
            ),
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "metadata": self.metadata,
        }


@dataclass
class ChainResult:
    """Output of running a chain on one symbol."""
    symbol: str
    composite_score: float                  # 0–100, weighted sum * 100
    direction: str                          # aggregated long/short/neutral
    verdicts: List[EvaluatorVerdict] = field(default_factory=list)
    weights: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "composite_score": round(self.composite_score, 2),
            "direction": self.direction,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "weights": {k: round(v, 3) for k, v in self.weights.items()},
            "error": self.error,
        }


class Evaluator(ABC):
    """Subclass and implement ``evaluate``. Stateless across calls.

    ``name`` doubles as the key the chain uses to look up weights, so make
    it stable and unique. Convention: lower_snake_case, no spaces.
    """
    name: str = "base"

    #: Minimum OHLCV bars required. Chain skips this evaluator when len(df) is below.
    min_bars: int = 0

    @abstractmethod
    def evaluate(self, df: pd.DataFrame, context: EvaluatorContext) -> EvaluatorVerdict:
        """Return a verdict on the symbol given OHLCV history.

        Implementations should NOT raise on indicator errors — return a
        ``score=0, direction="neutral", signal="error"`` verdict instead so
        the chain can still aggregate other evaluators.
        """
        ...


def aggregate_direction(
    verdicts: List[EvaluatorVerdict],
    weights: Optional[Dict[str, float]] = None,
) -> str:
    """Weighted-vote aggregation of evaluator directions.

    Each verdict contributes ``weight * verdict.score`` to its direction's
    tally. The dominant direction wins. Ties or zero-signal sets → neutral.
    Volume-override semantics (scanner.py's logic where loud volume + clean
    breakout overrides RSI) is NOT replicated here — that's a cross-evaluator
    coupling we deliberately don't bake into the base aggregator. A caller
    that wants it can post-process the verdicts list.
    """
    w = weights or {}
    tallies: Counter[str] = Counter()
    for v in verdicts:
        weight = w.get(v.name, 1.0)
        tallies[v.direction] += weight * v.score
    # Strip neutral from the contest unless it's the only one with mass
    tallies.pop(DIR_NEUTRAL, None)
    if not tallies:
        return DIR_NEUTRAL
    top, top_val = tallies.most_common(1)[0]
    # If every meaningful direction has zero mass, neutral
    if top_val <= 0:
        return DIR_NEUTRAL
    # If two non-neutral directions tie exactly, neutral (genuine conflict)
    if len(tallies) >= 2:
        second_val = tallies.most_common(2)[1][1]
        if abs(top_val - second_val) < 1e-9:
            return DIR_NEUTRAL
    return top
