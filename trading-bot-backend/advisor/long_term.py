"""Long-term (year+) holding-candidate scorer.

Composite of three signals weighted for buy-and-hold quality:

  - Fundamentals (50%): score_fundamentals() — P/E, growth, margins, debt
  - Trend (30%):       close above 200dma + positive 1-year return
  - Low volatility (20%): inverse of annualized stddev of daily returns

Crypto returns a neutral fundamentals component (50/100) per the existing
``score_fundamentals`` convention, so the trend + vol signal still
differentiates names within an asset class.

Powers GET /advisor/long-term. Indicator-pure (no I/O) — callers pass
fundamentals + an OHLCV DataFrame; this module ranks them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import math
import numpy as np
import pandas as pd

from advisor.fundamentals import FundamentalSnapshot, score_fundamentals


# Composite weights — must sum to 1.0. Operator can override per-call.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "fundamentals": 0.50,
    "trend": 0.30,
    "low_volatility": 0.20,
}

# Minimum bars required for the trend + vol components. SMA-200 needs 200;
# the 1-year return needs 252 trading days; vol stddev wants the same window
# so its dispersion estimate isn't sampled from a single regime.
MIN_BARS_LONG_TERM = 252

# Annualized-vol band used by the low-volatility scorer. Below LOW_VOL is
# "boring blue-chip", above HIGH_VOL is "too jumpy to hold a year".
LOW_VOL = 0.20   # ~20% — typical S&P leader
HIGH_VOL = 0.60  # 60%+ → memes, small caps, leveraged tickers


@dataclass
class ComponentScore:
    name: str
    score: float        # 0.0 – 1.0
    value: Optional[float] = None  # raw underlying value (vol, 1y return, etc.)
    signal: str = ""


@dataclass
class LongTermScore:
    """Composite long-term holding score for one symbol."""
    symbol: str
    score: float                          # 0–100, weighted composite
    current_price: float
    name: str = ""
    sector: str = ""
    components: Dict[str, ComponentScore] = field(default_factory=dict)
    bars: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "score": round(self.score, 2),
            "current_price": round(self.current_price, 4) if self.current_price else 0.0,
            "bars": self.bars,
            "components": {
                k: {
                    "score": round(v.score, 3),
                    "value": (
                        round(v.value, 4)
                        if isinstance(v.value, (int, float)) and v.value is not None
                        else v.value
                    ),
                    "signal": v.signal,
                }
                for k, v in self.components.items()
            },
            "error": self.error,
        }


# ── Component scorers ──

def _fundamentals_component(snap: FundamentalSnapshot) -> ComponentScore:
    """Map score_fundamentals (0-100) onto a 0-1 component score."""
    raw, rationale = score_fundamentals(snap)
    return ComponentScore(
        name="fundamentals",
        score=max(0.0, min(1.0, raw / 100.0)),
        value=float(raw),
        signal=rationale or "neutral",
    )


def _trend_component(df: pd.DataFrame) -> ComponentScore:
    """Above-200dma + positive 1-year return = strong long-term trend.

    Each sub-signal contributes 0.5: bing close>200dma alone = 0.5, +30%
    1y alone = 0.5, both maxed = 1.0. 1y return saturates at 30% gain
    so a doubled name doesn't drown out a steady compounder.
    """
    if len(df) < MIN_BARS_LONG_TERM:
        return ComponentScore(
            name="trend", score=0.0, value=None, signal="insufficient_history"
        )

    close = df["close"].astype(float)
    current = float(close.iloc[-1])
    sma200 = float(close.rolling(window=200).mean().iloc[-1])
    year_ago = float(close.iloc[-252])

    above_dma = current > sma200
    one_year_return = (current - year_ago) / year_ago if year_ago > 0 else 0.0

    dma_part = 0.5 if above_dma else 0.0
    # Saturate at +30% gain → full credit. Negative return → zero.
    return_part = max(0.0, min(0.5, one_year_return / 0.30 * 0.5))
    total = dma_part + return_part

    if above_dma and one_year_return > 0.20:
        signal = "strong_uptrend"
    elif above_dma and one_year_return > 0:
        signal = "moderate_uptrend"
    elif above_dma:
        signal = "above_dma_but_flat"
    elif one_year_return > 0:
        signal = "below_dma_but_positive_year"
    else:
        signal = "downtrend"

    return ComponentScore(
        name="trend",
        score=total,
        value=one_year_return,
        signal=signal,
    )


def _low_volatility_component(df: pd.DataFrame) -> ComponentScore:
    """Lower annualized vol = higher score. Inverse-linear between
    LOW_VOL (full credit) and HIGH_VOL (zero credit)."""
    if len(df) < MIN_BARS_LONG_TERM:
        return ComponentScore(
            name="low_volatility", score=0.0, value=None, signal="insufficient_history"
        )
    rets = df["close"].astype(float).pct_change().dropna().tail(252)
    if len(rets) < 30 or rets.std() == 0:
        return ComponentScore(
            name="low_volatility", score=0.0, value=None, signal="insufficient_returns"
        )
    annual_vol = float(rets.std() * math.sqrt(252))
    if annual_vol <= LOW_VOL:
        score = 1.0
        signal = "low_vol_compounder"
    elif annual_vol >= HIGH_VOL:
        score = 0.0
        signal = "too_volatile"
    else:
        score = (HIGH_VOL - annual_vol) / (HIGH_VOL - LOW_VOL)
        signal = "moderate_vol"
    return ComponentScore(
        name="low_volatility", score=score, value=annual_vol, signal=signal,
    )


# ── Public scoring entry point ──

def score_long_term(
    symbol: str,
    df: pd.DataFrame,
    snap: FundamentalSnapshot,
    weights: Optional[Dict[str, float]] = None,
) -> LongTermScore:
    """Compute long-term holding score for one symbol.

    Args:
        symbol: Display symbol (kept verbatim in the return value).
        df: OHLCV DataFrame with lower-case columns. Needs >= 252 bars
            (1 year of daily data) for trend + vol components.
        snap: Pre-fetched fundamentals (FundamentalSnapshot).
        weights: Optional override for composite weights. Missing keys
            fall back to DEFAULT_WEIGHTS.

    Returns:
        LongTermScore. ``error`` is set when input data is unusable; the
        composite is still computed best-effort from whatever components
        could be evaluated.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    # Normalize to handle operator passing un-normalized inputs (e.g. 5/3/2).
    total_w = sum(w.values()) or 1.0
    w = {k: v / total_w for k, v in w.items()}

    if df is None or df.empty:
        return LongTermScore(
            symbol=symbol, score=0.0, current_price=0.0, bars=0,
            error="empty_ohlcv",
        )

    fund = _fundamentals_component(snap)
    trend = _trend_component(df)
    vol = _low_volatility_component(df)

    composite = (
        w.get("fundamentals", 0.0) * fund.score
        + w.get("trend", 0.0) * trend.score
        + w.get("low_volatility", 0.0) * vol.score
    ) * 100.0

    current_price = float(df["close"].iloc[-1])
    bars = len(df)
    # Tag the response if either of the technical components couldn't run —
    # operator should know they're looking at a fundamentals-only score.
    err = None
    if trend.signal == "insufficient_history" or vol.signal == "insufficient_history":
        err = "insufficient_history_for_trend_or_vol"

    return LongTermScore(
        symbol=symbol,
        score=composite,
        current_price=current_price,
        name=snap.name,
        sector=snap.sector,
        bars=bars,
        components={"fundamentals": fund, "trend": trend, "low_volatility": vol},
        error=err,
    )


def rank_long_term(
    scores: list[LongTermScore],
    top: Optional[int] = None,
    min_score: float = 0.0,
) -> list[LongTermScore]:
    """Filter + sort descending by composite. Mirrors scanner.rank_scores."""
    valid = [s for s in scores if s.error in (None, "insufficient_history_for_trend_or_vol")
             and s.score >= min_score]
    valid.sort(key=lambda s: s.score, reverse=True)
    if top is not None:
        valid = valid[:top]
    return valid
