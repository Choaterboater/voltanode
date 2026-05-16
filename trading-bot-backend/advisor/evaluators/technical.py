"""Technical evaluators — wrap scanner.py's component scorers as Evaluators.

The math here is identical to ``advisor/scanner.py``'s ``_rsi_score`` etc.
We don't reimplement — we call those existing functions and translate their
``ComponentScore`` output into the ``EvaluatorVerdict`` shape. Changes to
RSI/breakout/volume math should land in scanner.py and flow through here
automatically.
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
from advisor.indicators import compute_rsi
from advisor.scanner import _breakout_score, _rel_volume_score, _rsi_score


def _signal_to_direction(signal: str, fallback: str = DIR_NEUTRAL) -> str:
    """Map scanner.py's signal strings to a direction.

    Mapping mirrors scanner._infer_direction's per-component logic; the
    chain's aggregate_direction does the final cross-component vote.
    """
    if "oversold" in signal:
        return DIR_LONG
    if "overbought" in signal:
        return DIR_SHORT
    if signal == "breakout_up":
        return DIR_LONG
    if signal == "breakout_down":
        return DIR_SHORT
    if signal == "near_support":
        return DIR_LONG
    if signal == "near_resistance":
        return DIR_SHORT
    return fallback


class RsiExtremeEvaluator(Evaluator):
    """Score how oversold/overbought RSI is (scanner.py:_rsi_score)."""
    name = "rsi"

    def __init__(self, rsi_period: int = 14) -> None:
        self.rsi_period = rsi_period
        # +2 to match scanner.score_symbol's min_bars formula
        self.min_bars = rsi_period + 2

    def evaluate(self, df: pd.DataFrame, context: EvaluatorContext) -> EvaluatorVerdict:
        rsi_series = compute_rsi(df, period=self.rsi_period)
        rsi_val = float(rsi_series.iloc[-1])
        comp = _rsi_score(rsi_val)
        return EvaluatorVerdict(
            name=self.name,
            score=comp.score,
            direction=_signal_to_direction(comp.signal),
            signal=comp.signal,
            raw_value=comp.value,
        )


class BreakoutEvaluator(Evaluator):
    """Score breakout / range-edge proximity (scanner.py:_breakout_score)."""
    name = "breakout"

    def __init__(self, lookback: int = 20) -> None:
        self.lookback = lookback
        self.min_bars = lookback + 2

    def evaluate(self, df: pd.DataFrame, context: EvaluatorContext) -> EvaluatorVerdict:
        comp = _breakout_score(df, lookback=self.lookback)
        return EvaluatorVerdict(
            name=self.name,
            score=comp.score,
            direction=_signal_to_direction(comp.signal),
            signal=comp.signal,
            raw_value=comp.value,
        )


class RelativeVolumeEvaluator(Evaluator):
    """Score current-bar volume vs trailing average (scanner.py:_rel_volume_score).

    Volume by itself has no direction (high volume can mean a rip or a dump).
    We always return ``direction="neutral"`` — the chain's aggregator should
    use this evaluator's *score* as a confirmation weight on the directional
    evaluators, not as a directional vote.
    """
    name = "rel_volume"

    def __init__(self, lookback: int = 20) -> None:
        self.lookback = lookback
        self.min_bars = lookback + 1

    def evaluate(self, df: pd.DataFrame, context: EvaluatorContext) -> EvaluatorVerdict:
        comp = _rel_volume_score(df, lookback=self.lookback)
        return EvaluatorVerdict(
            name=self.name,
            score=comp.score,
            direction=DIR_NEUTRAL,  # see docstring
            signal=comp.signal,
            raw_value=comp.value,
        )
