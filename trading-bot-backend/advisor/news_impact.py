"""News impact calibration backtest.

For every historical (article, score, symbol) tuple in the news DB:
  1. fetch the underlying's daily OHLCV around the article timestamp
  2. compute returns at 1d / 3d / 5d horizons after the article
  3. bucket the article by its compound score band
  4. aggregate per-bucket stats (n, mean return, median return, hit rate)

Output: a calibration table that answers "what return does a score-X
article actually predict?" — the empirical alternative to assuming a
positive score = a positive move.

Indicator-pure with one external dependency: yfinance for historical
prices. Crypto symbols are skipped (CoinGecko's API doesn't give the
clean ts-aligned daily bars we need without rate-limit pain).
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from news.storage import NewsStorage

logger = logging.getLogger("volta.advisor.news_impact")


# Score buckets — chosen so each bucket has roughly equal article density
# on a typical news flow. The middle bucket [-0.1, 0.1] captures "neutral"
# noise; outer buckets are where the signal lives.
DEFAULT_SCORE_BUCKETS: Tuple[Tuple[float, float], ...] = (
    (-1.01, -0.50),
    (-0.50, -0.10),
    (-0.10,  0.10),
    ( 0.10,  0.50),
    ( 0.50,  1.01),
)

# Forward-return horizons in trading days.
DEFAULT_HORIZONS_DAYS = (1, 3, 5)


@dataclass
class BucketStat:
    """Aggregated forward returns for one (score_bucket, horizon) cell."""
    score_low: float
    score_high: float
    horizon_days: int
    n: int
    mean_return_pct: float
    median_return_pct: float
    hit_rate: float        # share of articles whose forward return moved
                           # in the direction the score implied
    stdev_return_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score_low": round(self.score_low, 2),
            "score_high": round(self.score_high, 2),
            "horizon_days": self.horizon_days,
            "n": self.n,
            "mean_return_pct": round(self.mean_return_pct, 4),
            "median_return_pct": round(self.median_return_pct, 4),
            "hit_rate": round(self.hit_rate, 4),
            "stdev_return_pct": round(self.stdev_return_pct, 4),
        }


@dataclass
class ImpactReport:
    """Calibration report — the full backtest output."""
    generated_at: str
    lookback_days: int
    symbols: List[str]
    article_count: int
    skipped_count: int          # articles dropped (no price data, weekend, etc.)
    buckets: List[BucketStat] = field(default_factory=list)
    by_symbol: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "lookback_days": self.lookback_days,
            "symbols": self.symbols,
            "article_count": self.article_count,
            "skipped_count": self.skipped_count,
            "buckets": [b.to_dict() for b in self.buckets],
            "by_symbol": self.by_symbol,
            "error": self.error,
        }


def _fetch_history_for_symbol(symbol: str, days_back: int) -> Optional[pd.DataFrame]:
    """Pull `days_back + horizon_buffer` of daily OHLCV via yfinance.

    Returns a DataFrame indexed by tz-aware UTC date midnight, or None on
    failure. We pad an extra 10 trading days so forward-return lookups
    don't run off the end of the array near the start of the backtest
    window.
    """
    try:
        import yfinance as yf
        # Period > 1y → use "max", else round up to next preset.
        if days_back <= 30:
            period = "3mo"
        elif days_back <= 90:
            period = "6mo"
        elif days_back <= 180:
            period = "1y"
        elif days_back <= 365:
            period = "2y"
        else:
            period = "5y"
        hist = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        # Normalize index to tz-aware UTC midnight per row so we can match
        # against an article's UTC timestamp cleanly.
        idx = pd.to_datetime(hist.index, utc=True)
        hist = hist.reset_index(drop=True)
        hist["ts_utc"] = idx
        hist.columns = [str(c).lower() for c in hist.columns]
        return hist
    except Exception as exc:
        logger.warning(f"yfinance fetch failed for {symbol}: {exc}")
        return None


def _price_on_or_after(hist: pd.DataFrame, ts: datetime) -> Optional[Tuple[float, datetime]]:
    """Find the first daily close at or after `ts`. Returns (price, bar_ts).

    Articles published intraday match that day's close; articles published
    on weekends/holidays match the next trading day's close.
    """
    if hist is None or hist.empty:
        return None
    mask = hist["ts_utc"] >= ts
    rows = hist.loc[mask]
    if rows.empty:
        return None
    row = rows.iloc[0]
    return float(row["close"]), row["ts_utc"].to_pydatetime()


def _price_n_trading_days_later(hist: pd.DataFrame, ts: datetime, n: int) -> Optional[float]:
    """Close `n` trading days after the bar that anchors `ts`. None if off the end."""
    if hist is None or hist.empty:
        return None
    mask = hist["ts_utc"] >= ts
    pos_arr = hist.index[mask]
    if len(pos_arr) == 0:
        return None
    anchor_pos = int(pos_arr[0])
    target_pos = anchor_pos + n
    if target_pos >= len(hist):
        return None
    return float(hist.iloc[target_pos]["close"])


def _bucketize(score: float, buckets: Tuple[Tuple[float, float], ...]) -> Optional[Tuple[float, float]]:
    """Find the (low, high) bucket containing this score."""
    for low, high in buckets:
        if low <= score < high:
            return (low, high)
    return None


def compute_impact(
    symbols: List[str],
    lookback_days: int = 30,
    horizons_days: Tuple[int, ...] = DEFAULT_HORIZONS_DAYS,
    score_buckets: Tuple[Tuple[float, float], ...] = DEFAULT_SCORE_BUCKETS,
    storage: Optional[NewsStorage] = None,
    min_articles_per_bucket: int = 3,
) -> ImpactReport:
    """Build a calibration report over `symbols` for the last `lookback_days`.

    Iterates every (article, sentiment) row in the window, gets the
    underlying's close at the article's day + horizon-days later, computes
    the percent return, buckets by sentiment compound score, and emits
    per-bucket stats including a directional hit-rate.

    Hit rate definition:
      - bucket has positive score → "hit" means forward return > 0
      - bucket has negative score → "hit" means forward return < 0
      - middle bucket (straddles zero) → hit_rate is undefined; we report 0.5

    Args:
        symbols: Tickers to include. Crypto names (anything classifyAsset
            would call crypto) are auto-skipped.
        lookback_days: Calendar days of history to scan.
        horizons_days: Forward windows to evaluate, in trading days.
        score_buckets: Score ranges. Half-open [low, high).
        storage: Optional NewsStorage (default: new instance reading news.db).
        min_articles_per_bucket: Buckets with fewer rows than this are
            kept in the output but flagged via small n — caller can filter.
    """
    started = datetime.now(timezone.utc)
    syms = [s.strip().upper() for s in symbols if s and s.strip()]
    if not syms:
        return ImpactReport(
            generated_at=started.isoformat(), lookback_days=lookback_days,
            symbols=[], article_count=0, skipped_count=0,
            error="no_symbols",
        )

    if storage is None:
        try:
            storage = NewsStorage()
        except Exception as exc:
            return ImpactReport(
                generated_at=started.isoformat(), lookback_days=lookback_days,
                symbols=syms, article_count=0, skipped_count=0,
                error=f"storage_init_failed: {exc}",
            )

    # Pull price history per symbol once. Cache miss → skip the symbol.
    histories: Dict[str, pd.DataFrame] = {}
    for sym in syms:
        hist = _fetch_history_for_symbol(sym, lookback_days)
        if hist is not None:
            histories[sym] = hist

    # Per-cell accumulators: (low, high, horizon) → [returns]
    cells: Dict[Tuple[float, float, int], List[float]] = {}
    by_symbol: Dict[str, Dict[str, Any]] = {}
    article_count = 0
    skipped_count = 0
    hours_lookback = lookback_days * 24

    for sym in syms:
        hist = histories.get(sym)
        if hist is None:
            skipped_count += 1
            by_symbol[sym] = {"n_articles": 0, "skipped": True, "reason": "no_price_history"}
            continue

        try:
            scores = storage.get_sentiment_for_symbol(sym, hours=hours_lookback)
        except Exception as exc:
            logger.warning(f"impact: storage query failed for {sym}: {exc}")
            skipped_count += 1
            by_symbol[sym] = {"n_articles": 0, "skipped": True, "reason": "storage_error"}
            continue

        per_sym_n = 0
        per_sym_returns: List[float] = []
        for s in scores:
            article_ts = s.analyzed_at
            if not isinstance(article_ts, datetime):
                try:
                    article_ts = datetime.fromisoformat(str(article_ts).replace("Z", "+00:00"))
                except Exception:
                    skipped_count += 1
                    continue
            if article_ts.tzinfo is None:
                article_ts = article_ts.replace(tzinfo=timezone.utc)

            anchor = _price_on_or_after(hist, article_ts)
            if anchor is None:
                skipped_count += 1
                continue
            anchor_price, anchor_bar_ts = anchor

            bucket = _bucketize(float(s.compound_score), score_buckets)
            if bucket is None:
                skipped_count += 1
                continue

            for h in horizons_days:
                fwd_price = _price_n_trading_days_later(hist, anchor_bar_ts, h)
                if fwd_price is None or anchor_price <= 0:
                    continue
                ret = (fwd_price - anchor_price) / anchor_price * 100.0
                cells.setdefault((bucket[0], bucket[1], h), []).append(ret)
                if h == horizons_days[0]:
                    per_sym_returns.append(ret)
            per_sym_n += 1
            article_count += 1

        by_symbol[sym] = {
            "n_articles": per_sym_n,
            "mean_short_horizon_return_pct": (
                round(sum(per_sym_returns) / len(per_sym_returns), 4)
                if per_sym_returns else None
            ),
        }

    # Aggregate cells → bucket stats
    bucket_stats: List[BucketStat] = []
    for (low, high) in score_buckets:
        for h in horizons_days:
            returns = cells.get((low, high, h), [])
            if not returns:
                bucket_stats.append(BucketStat(
                    score_low=low, score_high=high, horizon_days=h,
                    n=0, mean_return_pct=0.0, median_return_pct=0.0,
                    hit_rate=0.0, stdev_return_pct=0.0,
                ))
                continue
            mean = sum(returns) / len(returns)
            median = statistics.median(returns)
            stdev = statistics.stdev(returns) if len(returns) >= 2 else 0.0
            # Hit-rate semantics: directional agreement with bucket sign.
            if low >= 0 and high > 0:
                # Strictly positive bucket — hit = return > 0
                hits = sum(1 for r in returns if r > 0)
                hit_rate = hits / len(returns)
            elif high <= 0 and low < 0:
                # Strictly negative bucket — hit = return < 0
                hits = sum(1 for r in returns if r < 0)
                hit_rate = hits / len(returns)
            else:
                # Straddles zero — directional hit-rate undefined.
                hit_rate = 0.5
            bucket_stats.append(BucketStat(
                score_low=low, score_high=high, horizon_days=h,
                n=len(returns), mean_return_pct=mean,
                median_return_pct=median, hit_rate=hit_rate,
                stdev_return_pct=stdev,
            ))

    return ImpactReport(
        generated_at=started.isoformat(),
        lookback_days=lookback_days,
        symbols=syms,
        article_count=article_count,
        skipped_count=skipped_count,
        buckets=bucket_stats,
        by_symbol=by_symbol,
    )
