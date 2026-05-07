"""Fundamentals snapshot helper for the squeeze screener.

Pulls the structural metrics the screener needs (market cap, float, short
interest %, sector, ADV, current price, earnings trend) from a single
``yfinance.Ticker.info`` call. Cached for 24h per symbol so a 100-ticker
screener pass doesn't re-hit Yahoo on every scan.

**Data freshness caveats** — surfaced in the screener response so operators
can judge:

* ``short_pct_of_float`` is FINRA bi-monthly data with ~2-week lag. For
  intraday squeeze tracking you'd need Ortex/S3 (paid). For swing/position
  setups (CAR / GME pattern), the lag is acceptable.
* ``earnings_qoq_growth`` is from yfinance's pre-computed field; on rare
  symbols it can be stale by a quarter. Cross-check with the next earnings date
  before sizing.
* Float can change after secondaries; treat as approximate.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import yfinance as yf

logger = logging.getLogger("volta.fundamentals")


@dataclass
class QuarterlyEPS:
    """One quarter's reported EPS (or net income proxy if EPS unavailable)."""

    period_end: str    # ISO YYYY-MM-DD
    eps: Optional[float] = None
    estimate: Optional[float] = None
    surprise_pct: Optional[float] = None  # (actual - estimate) / |estimate|


@dataclass
class Fundamentals:
    """Structural snapshot for one ticker."""

    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""

    market_cap: Optional[float] = None       # USD
    float_shares: Optional[float] = None     # shares
    shares_outstanding: Optional[float] = None
    shares_short: Optional[float] = None
    short_pct_of_float: Optional[float] = None  # 0–1 fraction; multiply by 100 for %
    short_ratio_days_to_cover: Optional[float] = None

    current_price: Optional[float] = None
    avg_daily_volume_10d: Optional[float] = None
    avg_daily_volume_3m: Optional[float] = None

    # Earnings-trend signal (the RXT insight): rising EPS + high SI + low
    # float = squeeze precursor.
    earnings_growth_yoy: Optional[float] = None        # info["earningsGrowth"]
    earnings_qoq_growth: Optional[float] = None        # info["earningsQuarterlyGrowth"]
    revenue_growth_yoy: Optional[float] = None         # info["revenueGrowth"]
    profit_margins: Optional[float] = None
    forward_pe: Optional[float] = None
    next_earnings_date: Optional[str] = None           # ISO YYYY-MM-DD if known

    # Last N quarters of reported EPS — drives the inline bar chart in the
    # squeeze screener UI. Oldest first.
    quarterly_eps: list = None  # type: List[QuarterlyEPS]

    # Source tracking — useful for the response's "warnings" section.
    has_short_interest_data: bool = False
    has_earnings_growth_data: bool = False
    fetch_error: Optional[str] = None

    def __post_init__(self) -> None:
        if self.quarterly_eps is None:
            self.quarterly_eps = []


# 24h in-memory cache. Squeeze setups don't move on minute timescale.
_CACHE: Dict[str, Dict[str, Any]] = {}
_DEFAULT_TTL_S = 24 * 3600


def _cache_get(ticker: str, ttl_s: float) -> Optional[Fundamentals]:
    entry = _CACHE.get(ticker.upper())
    if entry is None:
        return None
    if time.time() - entry["fetched_at"] > ttl_s:
        return None
    return entry["data"]


def _cache_set(ticker: str, data: Fundamentals) -> None:
    _CACHE[ticker.upper()] = {"fetched_at": time.time(), "data": data}


def _coerce_float(v: Any) -> Optional[float]:
    """Best-effort float conversion. None / empty / non-numeric → None."""
    if v is None or v == "" or v == "Infinity":
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _fetch_sync(ticker: str) -> Fundamentals:
    """Synchronous yfinance fetch — wrap in ``asyncio.to_thread``."""
    fund = Fundamentals(ticker=ticker.upper())
    try:
        t = yf.Ticker(ticker)
        info = getattr(t, "info", None) or getattr(t, "fast_info", None) or {}

        # info is a dict-like for recent yfinance; older versions use object attrs.
        def g(*keys: str) -> Any:
            for k in keys:
                if isinstance(info, dict):
                    if k in info and info[k] is not None:
                        return info[k]
                else:
                    v = getattr(info, k, None)
                    if v is not None:
                        return v
            return None

        fund.name = str(g("longName", "shortName") or "")
        fund.sector = str(g("sector") or "")
        fund.industry = str(g("industry") or "")

        fund.market_cap = _coerce_float(g("marketCap"))
        fund.float_shares = _coerce_float(g("floatShares", "impliedSharesOutstanding"))
        fund.shares_outstanding = _coerce_float(g("sharesOutstanding"))
        fund.shares_short = _coerce_float(g("sharesShort"))
        fund.short_pct_of_float = _coerce_float(g("shortPercentOfFloat"))
        fund.short_ratio_days_to_cover = _coerce_float(g("shortRatio"))

        fund.current_price = _coerce_float(
            g("regularMarketPrice", "currentPrice", "lastPrice", "previousClose")
        )
        fund.avg_daily_volume_10d = _coerce_float(g("averageDailyVolume10Day"))
        fund.avg_daily_volume_3m = _coerce_float(g("averageDailyVolume3Month"))

        fund.earnings_growth_yoy = _coerce_float(g("earningsGrowth"))
        fund.earnings_qoq_growth = _coerce_float(g("earningsQuarterlyGrowth"))
        fund.revenue_growth_yoy = _coerce_float(g("revenueGrowth"))
        fund.profit_margins = _coerce_float(g("profitMargins"))
        fund.forward_pe = _coerce_float(g("forwardPE"))

        # Next earnings date — yfinance exposes via either info or earnings_dates.
        ne = g("earningsDate")
        if ne:
            try:
                # earningsDate is sometimes a list of [start, end] timestamps.
                if isinstance(ne, (list, tuple)) and ne:
                    ne = ne[0]
                # Convert pandas Timestamp / datetime / string to ISO date
                fund.next_earnings_date = str(ne)[:10]
            except Exception:
                pass

        # Pull last N quarters of reported EPS for the inline chart.
        # ``earnings_history`` is the most reliable yfinance source; falls
        # back to quarterly_income_stmt if the history endpoint errors.
        try:
            hist = getattr(t, "earnings_history", None)
            if hist is not None and not hist.empty:
                # earnings_history columns: epsActual, epsEstimate, epsDifference, surprisePercent
                hist_sorted = hist.sort_index().tail(8)  # last 8 quarters
                for idx, row in hist_sorted.iterrows():
                    eps = _coerce_float(row.get("epsActual"))
                    est = _coerce_float(row.get("epsEstimate"))
                    sp = _coerce_float(row.get("surprisePercent"))
                    if eps is None and est is None:
                        continue
                    fund.quarterly_eps.append(
                        QuarterlyEPS(
                            period_end=str(idx)[:10],
                            eps=eps,
                            estimate=est,
                            surprise_pct=sp,
                        )
                    )
        except Exception as exc:
            logger.debug("fundamentals: %s earnings_history failed: %s", ticker, exc)

        # Fallback: derive from quarterly_income_stmt if no EPS history.
        if not fund.quarterly_eps:
            try:
                qis = getattr(t, "quarterly_income_stmt", None)
                if qis is not None and not qis.empty:
                    for col_name in ("Basic EPS", "Diluted EPS", "BasicEPS", "DilutedEPS"):
                        if col_name in qis.index:
                            row = qis.loc[col_name].dropna()
                            for period_idx, eps_v in row.items():
                                eps = _coerce_float(eps_v)
                                if eps is None:
                                    continue
                                fund.quarterly_eps.append(
                                    QuarterlyEPS(
                                        period_end=str(period_idx)[:10],
                                        eps=eps,
                                    )
                                )
                            fund.quarterly_eps.sort(key=lambda q: q.period_end)
                            fund.quarterly_eps = fund.quarterly_eps[-8:]
                            break
            except Exception as exc:
                logger.debug("fundamentals: %s quarterly_income_stmt failed: %s", ticker, exc)

        fund.has_short_interest_data = fund.short_pct_of_float is not None
        fund.has_earnings_growth_data = (
            fund.earnings_qoq_growth is not None
            or fund.earnings_growth_yoy is not None
            or len(fund.quarterly_eps) >= 2
        )
    except Exception as exc:
        fund.fetch_error = str(exc)[:200]
        logger.debug("fundamentals: %s fetch failed: %s", ticker, exc)
    return fund


async def fetch_fundamentals(
    ticker: str,
    ttl_s: float = _DEFAULT_TTL_S,
) -> Fundamentals:
    """Async-safe wrapper around the sync yfinance fetch with 24h caching."""
    cached = _cache_get(ticker, ttl_s)
    if cached is not None:
        return cached
    data = await asyncio.to_thread(_fetch_sync, ticker)
    _cache_set(ticker, data)
    return data
