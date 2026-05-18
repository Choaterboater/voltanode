"""News sentiment velocity — change in sentiment over time, not just level.

A static "+0.3 avg compound over 24h" tells you a stock has positive news.
A "+0.3 over 24h but +0.6 over the last 1h" tells you the news has just
*accelerated* positive — that's where the alpha lives. Velocity =
short-window mean minus long-window mean. Acceleration = velocity change
between two short windows.

Pure aggregation on top of news.storage.NewsStorage. No external I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from news.storage import NewsStorage


# Time windows used by every velocity computation. Tuned for swing-trading
# decision cadence: 1h catches breaking-news, 6h smooths intra-session
# noise, 24h gives the longer trend baseline.
DEFAULT_WINDOWS_HOURS = (1, 6, 24)


@dataclass
class WindowStat:
    """Stats over one rolling window."""
    hours: int
    article_count: int
    avg_compound: float
    max_compound: float
    min_compound: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hours": self.hours,
            "article_count": self.article_count,
            "avg_compound": round(self.avg_compound, 4),
            "max_compound": round(self.max_compound, 4),
            "min_compound": round(self.min_compound, 4),
        }


@dataclass
class VelocitySnapshot:
    """Velocity + acceleration for one symbol."""
    symbol: str
    computed_at: str
    windows: List[WindowStat] = field(default_factory=list)
    velocity: float = 0.0              # short_window_avg - long_window_avg
    velocity_label: str = "flat"       # accelerating_bull|accelerating_bear|flat
    acceleration: float = 0.0          # 2nd-derivative-ish; change in velocity
    fresh_article_pct: float = 0.0     # share of 24h articles that landed in last 1h
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "computed_at": self.computed_at,
            "windows": [w.to_dict() for w in self.windows],
            "velocity": round(self.velocity, 4),
            "velocity_label": self.velocity_label,
            "acceleration": round(self.acceleration, 4),
            "fresh_article_pct": round(self.fresh_article_pct, 4),
            "error": self.error,
        }


def _window_stats(scores: List, hours: int) -> WindowStat:
    """Aggregate sentiment scores filtered to the last `hours`.

    ``scores`` is a list of SentimentResult-like objects ordered newest
    first (matches NewsStorage.get_sentiment_for_symbol output). Each
    must have ``compound_score`` and ``analyzed_at`` attributes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    in_window: List[float] = []
    for s in scores:
        ts = s.analyzed_at
        if not isinstance(ts, datetime):
            # SQLite might give us strings
            try:
                ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < cutoff:
            continue
        in_window.append(float(s.compound_score))
    if not in_window:
        return WindowStat(hours=hours, article_count=0, avg_compound=0.0,
                          max_compound=0.0, min_compound=0.0)
    return WindowStat(
        hours=hours,
        article_count=len(in_window),
        avg_compound=sum(in_window) / len(in_window),
        max_compound=max(in_window),
        min_compound=min(in_window),
    )


def _classify_velocity(velocity: float) -> str:
    """Map a numeric velocity to a directional tag.

    Thresholds chosen so noise (small avg-compound differences across
    windows) maps to ``flat``. ±0.15 is the same band the existing
    SymbolSentiment summary uses to call something bullish/bearish.
    """
    if velocity > 0.15:
        return "accelerating_bull"
    if velocity < -0.15:
        return "accelerating_bear"
    if velocity > 0.05:
        return "drifting_bull"
    if velocity < -0.05:
        return "drifting_bear"
    return "flat"


def compute_velocity(
    symbol: str,
    storage: Optional[NewsStorage] = None,
    windows: tuple[int, ...] = DEFAULT_WINDOWS_HOURS,
) -> VelocitySnapshot:
    """Build a VelocitySnapshot for one symbol.

    Args:
        symbol: Ticker (case-preserved in output, upper-cased for DB lookup).
        storage: Optional NewsStorage. Defaults to a fresh instance which
            reads news.db at the configured path.
        windows: Hour-window tuple, ordered shortest first. The first
            element is the "short" window for velocity comparison; the
            last is the "long" baseline.

    Velocity = (avg compound in shortest window) – (avg compound in
    longest window). Positive = news is becoming MORE positive recently;
    negative = MORE negative.

    Acceleration = change in velocity between the two shortest windows
    (e.g. 1h-vs-6h minus 6h-vs-24h). Sniffs a regime change.

    Fresh-article % = share of 24h articles that came in the shortest
    window. Helps the operator weight velocity by news *volume*.
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        return VelocitySnapshot(
            symbol=symbol, computed_at=datetime.now(timezone.utc).isoformat(),
            error="empty_symbol",
        )

    if storage is None:
        try:
            storage = NewsStorage()
        except Exception as exc:
            return VelocitySnapshot(
                symbol=sym, computed_at=datetime.now(timezone.utc).isoformat(),
                error=f"storage_init_failed: {exc}",
            )

    # Pull the longest window once; slice down for each shorter window.
    long_hours = max(windows)
    try:
        scores = storage.get_sentiment_for_symbol(sym, hours=long_hours)
    except Exception as exc:
        return VelocitySnapshot(
            symbol=sym, computed_at=datetime.now(timezone.utc).isoformat(),
            error=f"storage_query_failed: {exc}",
        )

    sorted_windows = sorted(windows)
    stats = [_window_stats(scores, h) for h in sorted_windows]

    short_stat = stats[0]
    long_stat = stats[-1]
    velocity = short_stat.avg_compound - long_stat.avg_compound

    # Acceleration: difference between two consecutive deltas, if we
    # have at least 3 windows. Two-window inputs return 0.0.
    accel = 0.0
    if len(stats) >= 3:
        d1 = stats[0].avg_compound - stats[1].avg_compound
        d2 = stats[1].avg_compound - stats[-1].avg_compound
        accel = d1 - d2

    fresh_pct = 0.0
    if long_stat.article_count > 0:
        fresh_pct = short_stat.article_count / long_stat.article_count

    return VelocitySnapshot(
        symbol=sym,
        computed_at=datetime.now(timezone.utc).isoformat(),
        windows=stats,
        velocity=velocity,
        velocity_label=_classify_velocity(velocity),
        acceleration=accel,
        fresh_article_pct=fresh_pct,
    )
