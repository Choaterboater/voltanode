"""6-factor squeeze score — ranks GME/CAR-shape setups, not intraday squeezes.

Why GME/CAR — not Ortex
-----------------------
Operator's stated horizon is swing/position (days→weeks), not intraday. That
makes Yahoo's bi-monthly FINRA-derived short interest acceptable: the lag
matters when you're trying to catch a squeeze in progress, but a 2-week-old
SI reading is fine when you're identifying setups *before* they trigger.

The six factors
---------------
1. **Short Interest %** (0–2.0)
   Higher SI = more fuel. 25%+ scores max; <5% scores 0.

2. **Float size** (0–2.0)
   Smaller float = sharper squeeze geometry. ≤50M float scores max.

3. **Days to Cover** (0–1.5)
   How long it would take shorts to cover at average daily volume. ≥10
   days scores max — long DTC means a wave of buying can't dissipate.

4. **Earnings trend** (–0.5 to 1.5)
   The RXT insight: rising EPS while shorts pile in = setup. QoQ growth
   above 30% with YoY positive scores max; declining earnings deducts.

5. **Recent 13D / 13G filing** (0–1.0)
   Catalyst signal — a >5% holder declaration in the last week.

6. **Technical breakout** (0–2.0)
   Existing scanner composite — RSI extreme + breakout + relative
   volume — normalised to a 0–2 contribution.

Total: 0–10. Mirrors the tier-system in your friend's CAR/GME postmortem
screener (BASE / WATCHLIST / ADD).

What this doesn't see
---------------------
- Cash-settled swaps (disclosed only in 13D footnotes for activists; the
  ``recent_13d_filing`` factor flags the filing but you have to read the
  document to see swap structure).
- Intraday short-borrow rate spikes — Ortex/S3 territory, paid feeds.
- Form 4 open-market buys vs option exercises — not distinguished here.
- Float changes from secondaries between yfinance refreshes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from data.fundamentals import Fundamentals


# ── Tier thresholds (matched to screenshot's BASE / WATCHLIST scale) ──
# Max possible total = 11.5 with all seven factors firing.

TIER_ADD = 8.0
TIER_WATCHLIST = 5.0
TIER_BASE = 2.5


@dataclass
class SqueezeFactors:
    """Per-factor breakdown — surfaced in the API response so the operator
    can see *why* a name scored where it did."""

    short_interest: float = 0.0          # 0–2.0
    float_size: float = 0.0              # 0–2.0
    days_to_cover: float = 0.0           # 0–1.5
    earnings_trend: float = 0.0          # -0.5 to 1.5
    recent_13d: float = 0.0              # 0–1.0
    technical: float = 0.0               # 0–2.0
    off_exchange_short: float = 0.0      # 0–1.5  (FINRA TRF dark-pool short %)

    # Human-readable signal flags per factor.
    notes: Dict[str, str] = field(default_factory=dict)

    def total(self) -> float:
        return (
            self.short_interest
            + self.float_size
            + self.days_to_cover
            + self.earnings_trend
            + self.recent_13d
            + self.technical
            + self.off_exchange_short
        )


@dataclass
class SqueezeScore:
    """Composite squeeze score for one ticker, with breakdown."""

    ticker: str
    score: float
    tier: str               # "ADD" | "WATCHLIST" | "BASE" | "DISMISS"
    factors: SqueezeFactors
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "score": round(self.score, 2),
            "tier": self.tier,
            "factors": {
                "short_interest": round(self.factors.short_interest, 2),
                "float_size": round(self.factors.float_size, 2),
                "days_to_cover": round(self.factors.days_to_cover, 2),
                "earnings_trend": round(self.factors.earnings_trend, 2),
                "recent_13d": round(self.factors.recent_13d, 2),
                "technical": round(self.factors.technical, 2),
                "off_exchange_short": round(self.factors.off_exchange_short, 2),
            },
            "factor_notes": self.factors.notes,
            "warnings": self.warnings,
        }


# ── Per-factor scorers ──

def _score_short_interest(si_pct: Optional[float]) -> tuple[float, str]:
    """``si_pct`` is a fraction (0.20 = 20%)."""
    if si_pct is None:
        return 0.0, "no_data"
    pct = si_pct * 100.0
    if pct >= 25:
        return 2.0, f"very_high ({pct:.1f}%)"
    if pct >= 15:
        return 1.5, f"high ({pct:.1f}%)"
    if pct >= 10:
        return 1.0, f"elevated ({pct:.1f}%)"
    if pct >= 5:
        return 0.5, f"normal ({pct:.1f}%)"
    return 0.0, f"low ({pct:.1f}%)"


def _score_float(float_shares: Optional[float]) -> tuple[float, str]:
    if float_shares is None or float_shares <= 0:
        return 0.0, "no_data"
    m = float_shares / 1_000_000
    if m <= 50:
        return 2.0, f"very_small ({m:.0f}M)"
    if m <= 100:
        return 1.5, f"small ({m:.0f}M)"
    if m <= 200:
        return 1.0, f"medium ({m:.0f}M)"
    if m <= 500:
        return 0.5, f"large ({m:.0f}M)"
    return 0.0, f"very_large ({m:.0f}M)"


def _score_days_to_cover(dtc: Optional[float]) -> tuple[float, str]:
    if dtc is None:
        return 0.0, "no_data"
    if dtc >= 10:
        return 1.5, f"very_high ({dtc:.1f}d)"
    if dtc >= 5:
        return 1.0, f"high ({dtc:.1f}d)"
    if dtc >= 3:
        return 0.5, f"moderate ({dtc:.1f}d)"
    return 0.0, f"low ({dtc:.1f}d)"


def _score_earnings_trend(
    qoq: Optional[float],
    yoy: Optional[float],
) -> tuple[float, str]:
    """The RXT factor: rising EPS while shorts pile in = setup."""
    if qoq is None and yoy is None:
        return 0.0, "no_data"
    qoq_v = qoq if qoq is not None else 0.0
    yoy_v = yoy if yoy is not None else 0.0
    if qoq_v >= 0.30 and yoy_v > 0:
        return 1.5, f"strong_uptrend (QoQ +{qoq_v*100:.0f}%, YoY +{yoy_v*100:.0f}%)"
    if qoq_v >= 0.10:
        return 1.0, f"uptrend (QoQ +{qoq_v*100:.0f}%)"
    if qoq_v > 0:
        return 0.5, f"mild_uptrend (QoQ +{qoq_v*100:.0f}%)"
    if qoq_v <= -0.20:
        return -0.5, f"declining (QoQ {qoq_v*100:.0f}%)"
    return 0.0, f"flat (QoQ {qoq_v*100:.0f}%)"


def _score_technical(scanner_score: Optional[float]) -> tuple[float, str]:
    """Map 0–100 scanner score to 0–2.0 contribution."""
    if scanner_score is None:
        return 0.0, "no_data"
    contribution = (scanner_score / 100.0) * 2.0
    if scanner_score >= 60:
        sig = f"strong ({scanner_score:.0f})"
    elif scanner_score >= 40:
        sig = f"moderate ({scanner_score:.0f})"
    else:
        sig = f"weak ({scanner_score:.0f})"
    return contribution, sig


def _score_off_exchange_short(off_ex_pct: Optional[float]) -> tuple[float, str]:
    """FINRA TRF dark-pool short volume as % of off-exchange volume.

    50%+ = institutional shorting heavily through dark pools, often a
    bullish setup signal (CAR/GME pattern). 30%+ = elevated.
    """
    if off_ex_pct is None:
        return 0.0, "no_data"
    if off_ex_pct >= 50:
        return 1.5, f"very_high ({off_ex_pct:.1f}%)"
    if off_ex_pct >= 40:
        return 1.0, f"elevated ({off_ex_pct:.1f}%)"
    if off_ex_pct >= 30:
        return 0.5, f"moderate ({off_ex_pct:.1f}%)"
    return 0.0, f"low ({off_ex_pct:.1f}%)"


def _tier_for_score(score: float) -> str:
    if score >= TIER_ADD:
        return "ADD"
    if score >= TIER_WATCHLIST:
        return "WATCHLIST"
    if score >= TIER_BASE:
        return "BASE"
    return "DISMISS"


# ── Public scorer ──

def score_squeeze(
    ticker: str,
    fundamentals: Fundamentals,
    *,
    has_recent_13d_filing: bool = False,
    scanner_score: Optional[float] = None,
    off_exchange_short_pct: Optional[float] = None,
) -> SqueezeScore:
    """Compute the 7-factor squeeze score for one ticker."""
    factors = SqueezeFactors()
    warnings: List[str] = []

    # 1. Short interest
    factors.short_interest, factors.notes["short_interest"] = _score_short_interest(
        fundamentals.short_pct_of_float
    )
    if not fundamentals.has_short_interest_data:
        warnings.append("short_interest_unavailable")

    # 2. Float
    factors.float_size, factors.notes["float_size"] = _score_float(
        fundamentals.float_shares
    )

    # 3. Days to cover
    factors.days_to_cover, factors.notes["days_to_cover"] = _score_days_to_cover(
        fundamentals.short_ratio_days_to_cover
    )

    # 4. Earnings trend (the RXT factor)
    factors.earnings_trend, factors.notes["earnings_trend"] = _score_earnings_trend(
        fundamentals.earnings_qoq_growth,
        fundamentals.earnings_growth_yoy,
    )
    if not fundamentals.has_earnings_growth_data:
        warnings.append("earnings_trend_unavailable")

    # 5. Recent 13D/13G filing (catalyst)
    if has_recent_13d_filing:
        factors.recent_13d = 1.0
        factors.notes["recent_13d"] = "filed_in_window"
    else:
        factors.notes["recent_13d"] = "none"

    # 6. Technical breakout (from existing scanner)
    factors.technical, factors.notes["technical"] = _score_technical(scanner_score)

    # 7. Off-exchange short volume (FINRA TRF, free)
    (
        factors.off_exchange_short,
        factors.notes["off_exchange_short"],
    ) = _score_off_exchange_short(off_exchange_short_pct)
    if off_exchange_short_pct is None:
        warnings.append("off_exchange_short_unavailable")

    total = factors.total()
    return SqueezeScore(
        ticker=ticker.upper(),
        score=total,
        tier=_tier_for_score(total),
        factors=factors,
        warnings=warnings,
    )


def passes_structural_filters(
    fundamentals: Fundamentals,
    *,
    min_market_cap: float = 100_000_000,      # $100M
    max_market_cap: float = 5_000_000_000,    # $5B
    max_float_shares: float = 500_000_000,    # 500M
    min_price: float = 1.0,                   # $1 (penny-stock floor)
    max_price: Optional[float] = 20.0,        # $20 ceiling — most squeeze setups are sub-$20
    min_avg_daily_volume: float = 100_000,    # 100k shares
    sector_blocklist: Optional[List[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Apply the screenshot's structural filters. Returns (passes, reject_reason).

    ``max_price`` defaults to $20 since high-priced names rarely exhibit the
    squeeze geometry — retail can't pile in efficiently and the float math
    doesn't compound the same way. Set to ``None`` to disable the ceiling
    (e.g. CVNA-shape rallies).
    """
    blocklist = [s.lower() for s in (sector_blocklist or ["utilities"])]

    if fundamentals.market_cap is None:
        return False, "no_market_cap"
    if fundamentals.market_cap < min_market_cap:
        return False, "market_cap_too_small"
    if fundamentals.market_cap > max_market_cap:
        return False, "market_cap_too_large"

    if fundamentals.float_shares is not None and fundamentals.float_shares > max_float_shares:
        return False, "float_too_large"

    if fundamentals.current_price is not None:
        if fundamentals.current_price < min_price:
            return False, "price_below_min"
        if max_price is not None and fundamentals.current_price > max_price:
            return False, "price_above_max"

    adv = fundamentals.avg_daily_volume_10d or fundamentals.avg_daily_volume_3m
    if adv is not None and adv < min_avg_daily_volume:
        return False, "volume_too_thin"

    sector_l = (fundamentals.sector or "").lower()
    if any(b in sector_l for b in blocklist):
        return False, f"sector_blocked ({fundamentals.sector})"
    # REITs: industry will contain "REIT"
    if "reit" in (fundamentals.industry or "").lower() and "reit" in blocklist:
        return False, "industry_blocked (REIT)"

    return True, None
