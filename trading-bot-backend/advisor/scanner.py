"""Composite signal-strength scanner.

Ranks tradable assets by a weighted blend of:
  * RSI extreme — distance from 50, scaled toward 0 (oversold) or 100 (overbought)
  * Breakout proximity — close vs prior-N-bar high/low (excluding current bar)
  * Relative volume — current bar volume vs N-bar mean

Used by ``GET /advisor/scanner`` (manual-review tool) and by
``AutoDiscoveryStrategy`` (live universe-scanning bot).

The scoring is intentionally indicator-pure — no market_data or async I/O.
Callers pass an OHLCV DataFrame (lower-case columns:
``timestamp, open, high, low, close, volume``) and get back a score that
can be ranked across symbols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from advisor.indicators import compute_rsi


# Component weights — must sum to 1.0
DEFAULT_WEIGHTS: Dict[str, float] = {
    "rsi": 0.40,
    "breakout": 0.30,
    "rel_volume": 0.30,
}


@dataclass
class ComponentScore:
    """One scoring component (RSI / breakout / volume)."""

    value: float        # raw indicator value (e.g. RSI=24.3, rel_vol=2.1)
    score: float        # normalised 0–1
    signal: str         # human-readable tag


@dataclass
class ScannerScore:
    """Composite score for one symbol."""

    symbol: str
    score: float                                            # 0–100
    direction: str                                          # "long" | "short" | "neutral"
    current_price: float
    components: Dict[str, ComponentScore] = field(default_factory=dict)
    bars: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": round(self.score, 2),
            "direction": self.direction,
            "current_price": self.current_price,
            "bars": self.bars,
            "components": {
                k: {
                    "value": round(v.value, 4),
                    "score": round(v.score, 3),
                    "signal": v.signal,
                }
                for k, v in self.components.items()
            },
            "error": self.error,
        }


# ── Component scorers ──

def _rsi_score(rsi_val: float) -> ComponentScore:
    """Score RSI extremeness. 50 → 0, 0 or 100 → 1."""
    if rsi_val <= 30:
        score = (30.0 - rsi_val) / 30.0
        signal = "oversold" if rsi_val <= 25 else "approaching_oversold"
    elif rsi_val >= 70:
        score = (rsi_val - 70.0) / 30.0
        signal = "overbought" if rsi_val >= 75 else "approaching_overbought"
    else:
        score = 0.0
        signal = "neutral"
    return ComponentScore(
        value=rsi_val,
        score=max(0.0, min(1.0, score)),
        signal=signal,
    )


def _breakout_score(df: pd.DataFrame, lookback: int = 20) -> ComponentScore:
    """Score breakout / range-extreme proximity using prior N bars (excludes current).

    A clean break of the prior range scores 0.7+ ; sitting near either edge of an
    intact range scores up to 0.5; mid-range scores ~0.
    """
    if len(df) < lookback + 2:
        return ComponentScore(value=0.0, score=0.0, signal="insufficient_data")
    close = float(df["close"].iloc[-1])
    prior_high = float(df["high"].iloc[-lookback - 1 : -1].max())
    prior_low = float(df["low"].iloc[-lookback - 1 : -1].min())
    rng = prior_high - prior_low
    if rng <= 0:
        return ComponentScore(value=0.0, score=0.0, signal="flat_range")

    if close > prior_high:
        magnitude = (close - prior_high) / rng
        score = min(1.0, 0.7 + magnitude * 2.0)
        return ComponentScore(value=magnitude, score=score, signal="breakout_up")
    if close < prior_low:
        magnitude = (prior_low - close) / rng
        score = min(1.0, 0.7 + magnitude * 2.0)
        return ComponentScore(value=magnitude, score=score, signal="breakout_down")

    pos_in_range = (close - prior_low) / rng  # 0 = at low, 1 = at high
    edge_proximity = abs(pos_in_range - 0.5) * 2.0  # 0 mid, 1 at edges
    score = edge_proximity * 0.5  # cap inside-range scores at 0.5
    if pos_in_range > 0.85:
        signal = "near_resistance"
    elif pos_in_range < 0.15:
        signal = "near_support"
    else:
        signal = "mid_range"
    return ComponentScore(value=pos_in_range, score=score, signal=signal)


def _rel_volume_score(df: pd.DataFrame, lookback: int = 20) -> ComponentScore:
    """Current-bar volume vs trailing N-bar mean. 1× → 0, 3×+ → 1."""
    if len(df) < lookback + 1:
        return ComponentScore(value=1.0, score=0.0, signal="insufficient_data")
    cur_vol = float(df["volume"].iloc[-1])
    avg_vol = float(df["volume"].iloc[-lookback - 1 : -1].mean())
    if avg_vol <= 0:
        return ComponentScore(value=0.0, score=0.0, signal="no_volume_history")
    rv = cur_vol / avg_vol
    score = max(0.0, min(1.0, (rv - 1.0) / 2.0))
    if rv >= 2.5:
        signal = "very_elevated"
    elif rv >= 1.5:
        signal = "elevated"
    elif rv >= 0.8:
        signal = "normal"
    else:
        signal = "below_average"
    return ComponentScore(value=rv, score=score, signal=signal)


def _infer_direction(
    rsi: ComponentScore,
    breakout: ComponentScore,
    rel_volume: Optional[ComponentScore] = None,
) -> str:
    """Combine RSI + breakout (+ optional volume) into a long/short/neutral tag.

    Volume-override rule: when a clean breakout coincides with very-elevated
    volume (2.6×+ trailing average, i.e. ``rel_volume.score >= 0.8``), trust
    the breakout direction even if RSI is overstretched the other way. This
    captures parabolic-on-real-volume moves like RXT (RSI overbought + 14×
    volume + breakout_up) that earlier returned "neutral" and got skipped.
    """
    if "oversold" in rsi.signal:
        rsi_dir = "long"
    elif "overbought" in rsi.signal:
        rsi_dir = "short"
    else:
        rsi_dir = "neutral"

    if breakout.signal in ("breakout_up", "near_support"):
        bo_dir = "long"
    elif breakout.signal in ("breakout_down", "near_resistance"):
        bo_dir = "short"
    else:
        bo_dir = "neutral"

    # Volume override before resolving conflicts.
    if (
        rel_volume is not None
        and rel_volume.score >= 0.8
        and breakout.signal in ("breakout_up", "breakout_down")
    ):
        return "long" if breakout.signal == "breakout_up" else "short"

    if rsi_dir == bo_dir:
        return rsi_dir
    if rsi_dir == "neutral":
        return bo_dir
    if bo_dir == "neutral":
        return rsi_dir
    return "neutral"  # genuine conflict, no volume override available


# ── Public scoring entry-point ──

def score_symbol(
    symbol: str,
    df: pd.DataFrame,
    weights: Optional[Dict[str, float]] = None,
    rsi_period: int = 14,
    breakout_lookback: int = 20,
    volume_lookback: int = 20,
) -> ScannerScore:
    """Compute composite signal score for one symbol from its OHLCV DataFrame.

    Args:
        symbol: Display symbol (kept verbatim in the return value).
        df: OHLCV DataFrame with lower-case columns. Must contain at least
            ``max(periods) + 2`` rows or scoring is skipped.
        weights: Component-weight overrides; missing keys fall back to DEFAULT_WEIGHTS.
        rsi_period: RSI look-back.
        breakout_lookback: Prior-bar window for the breakout component.
        volume_lookback: Prior-bar window for the relative-volume component.

    Returns:
        ScannerScore. ``error`` is set (and ``score=0``) when input data is unusable.
    """
    min_bars = max(rsi_period, breakout_lookback, volume_lookback) + 2
    if df is None or df.empty or len(df) < min_bars:
        return ScannerScore(
            symbol=symbol,
            score=0.0,
            direction="neutral",
            current_price=0.0 if df is None or df.empty else float(df["close"].iloc[-1]),
            bars=0 if df is None else len(df),
            error="insufficient_data",
        )

    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    rsi_series = compute_rsi(df, period=rsi_period)
    rsi_c = _rsi_score(float(rsi_series.iloc[-1]))
    bo_c = _breakout_score(df, lookback=breakout_lookback)
    rv_c = _rel_volume_score(df, lookback=volume_lookback)

    composite = (
        w.get("rsi", 0.0) * rsi_c.score
        + w.get("breakout", 0.0) * bo_c.score
        + w.get("rel_volume", 0.0) * rv_c.score
    ) * 100.0

    return ScannerScore(
        symbol=symbol,
        score=composite,
        direction=_infer_direction(rsi_c, bo_c, rv_c),
        current_price=float(df["close"].iloc[-1]),
        bars=len(df),
        components={"rsi": rsi_c, "breakout": bo_c, "rel_volume": rv_c},
    )


def rank_scores(
    scores: List[ScannerScore],
    top: Optional[int] = None,
    min_score: float = 0.0,
) -> List[ScannerScore]:
    """Filter out errored / low-score entries and sort descending by composite score."""
    valid = [s for s in scores if s.error is None and s.score >= min_score]
    valid.sort(key=lambda s: s.score, reverse=True)
    if top is not None:
        valid = valid[:top]
    return valid
