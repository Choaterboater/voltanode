"""External universe + movers feeds for /advisor/scanner.

Two pieces:

* ``sp500_universe()`` — full S&P 500 ticker list, scraped from Wikipedia on
  first use and cached for 24h. Lets the scanner rank a much wider stock
  universe than the curated default.

* ``day_gainers()`` / ``most_actives()`` — Yahoo Finance predefined-screener
  feeds. Returns the top-N tickers currently moving by % gain or absolute
  volume. This is what catches RXT-shape outliers that aren't on any
  hand-maintained watchlist.

Both feeds cache results with TTLs so the scanner doesn't hammer external
hosts on every call. Failures fall back to small built-in defaults so the
scanner stays useful even if Wikipedia/Yahoo error out.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("volta.universes")


# ── Caching primitives ──

_CACHE: Dict[str, Dict[str, Any]] = {}


def _cache_get(key: str, ttl_seconds: float) -> Optional[List[str]]:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    if time.time() - entry["fetched_at"] > ttl_seconds:
        return None
    return list(entry["value"])


def _cache_set(key: str, value: List[str]) -> None:
    _CACHE[key] = {"fetched_at": time.time(), "value": list(value)}


# ── S&P 500 (Wikipedia scrape) ──

# Curated fallback if Wikipedia is unreachable. Mega-caps + sector representatives —
# enough that the scanner still has signal even when the scrape fails.
_SP500_FALLBACK = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "BRK.B", "JPM",
    "LLY", "V", "MA", "UNH", "XOM", "WMT", "PG", "JNJ", "HD", "ORCL",
    "COST", "ABBV", "BAC", "MRK", "NFLX", "CVX", "KO", "PEP", "ADBE", "CRM",
    "TMO", "AMD", "MCD", "ACN", "LIN", "CSCO", "ABT", "DIS", "WFC", "CAT",
    "GE", "MS", "DHR", "PM", "INTU", "GS", "AXP", "VZ", "TXN", "IBM",
]


_SP500_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "main/data/constituents.csv"
)


async def _fetch_sp500_from_csv() -> List[str]:
    """Fetch the S&P 500 list from the public DataHub CSV. No HTML parser needed.

    The CSV has a stable 'Symbol' column. yfinance/Alpaca both expect '-' for
    class-B shares (BRK.B → BRK-B), so we normalize.
    """
    async with httpx.AsyncClient(timeout=15.0, headers=_DEFAULT_HEADERS) as client:
        r = await client.get(_SP500_CSV_URL)
        r.raise_for_status()
        text = r.text

    lines = text.splitlines()
    if len(lines) < 100:
        raise RuntimeError(f"csv too short: {len(lines)} lines")
    header = lines[0].split(",")
    try:
        sym_idx = next(
            i for i, h in enumerate(header) if h.strip().lower() == "symbol"
        )
    except StopIteration:
        raise RuntimeError(f"no Symbol column in header: {header}")

    syms: List[str] = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) <= sym_idx:
            continue
        sym = parts[sym_idx].strip().strip('"').upper().replace(".", "-")
        if sym and len(sym) <= 6:
            syms.append(sym)
    return syms


async def sp500_universe(ttl_hours: float = 24.0) -> List[str]:
    """Return the S&P 500 ticker list. Cached for ``ttl_hours``.

    Tries DataHub CSV first (no parser dependency); falls back to
    ``_SP500_FALLBACK`` (~50 mega-cap names) if the fetch errors.
    """
    cached = _cache_get("sp500", ttl_hours * 3600.0)
    if cached is not None:
        return cached
    try:
        syms = await _fetch_sp500_from_csv()
        if len(syms) < 100:
            raise RuntimeError(f"suspiciously short ({len(syms)})")
        _cache_set("sp500", syms)
        logger.info("sp500_universe: fetched %d tickers from DataHub CSV", len(syms))
        return syms
    except Exception as exc:
        logger.warning("sp500_universe: fetch failed (%s); using fallback", exc)
        _cache_set("sp500", _SP500_FALLBACK)
        return list(_SP500_FALLBACK)


# ── Yahoo Finance movers (predefined screeners) ──

# Yahoo's predefined screeners. ``day_gainers`` = top % gainers today;
# ``most_actives`` = highest absolute volume. Both return JSON with a
# ``finance.result[0].quotes`` array.
_YF_SCREENER_URL = (
    "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
)

# yfinance includes its own crumb-cookie dance; we hit the public predefined
# endpoint directly which doesn't require auth, just a real User-Agent.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


async def _yahoo_screener(scr_id: str, count: int = 50) -> List[str]:
    """Fetch a Yahoo predefined screener and return ticker symbols."""
    params = {"count": str(min(count, 100)), "scrIds": scr_id}
    async with httpx.AsyncClient(timeout=15.0, headers=_DEFAULT_HEADERS) as client:
        r = await client.get(_YF_SCREENER_URL, params=params)
        r.raise_for_status()
        data = r.json()
    quotes = (
        (data.get("finance") or {}).get("result", [{}])[0].get("quotes")
        or []
    )
    out: List[str] = []
    for q in quotes:
        sym = (q.get("symbol") or "").strip().upper()
        if not sym:
            continue
        # Skip futures / options / weird types — keep equities + ETFs.
        qtype = (q.get("quoteType") or "").upper()
        if qtype not in ("EQUITY", "ETF", ""):
            continue
        out.append(sym)
    return out


async def day_gainers(limit: int = 25, ttl_minutes: float = 5.0) -> List[str]:
    """Top % gainers today (US equities). Cached for ``ttl_minutes``."""
    cached = _cache_get(f"day_gainers_{limit}", ttl_minutes * 60.0)
    if cached is not None:
        return cached
    try:
        syms = await _yahoo_screener("day_gainers", count=limit)
        _cache_set(f"day_gainers_{limit}", syms)
        logger.info("day_gainers: fetched %d tickers", len(syms))
        return syms
    except Exception as exc:
        logger.warning("day_gainers: fetch failed (%s)", exc)
        _cache_set(f"day_gainers_{limit}", [])
        return []


async def most_actives(limit: int = 25, ttl_minutes: float = 5.0) -> List[str]:
    """Highest-volume names today (US equities). Cached for ``ttl_minutes``."""
    cached = _cache_get(f"most_actives_{limit}", ttl_minutes * 60.0)
    if cached is not None:
        return cached
    try:
        syms = await _yahoo_screener("most_actives", count=limit)
        _cache_set(f"most_actives_{limit}", syms)
        logger.info("most_actives: fetched %d tickers", len(syms))
        return syms
    except Exception as exc:
        logger.warning("most_actives: fetch failed (%s)", exc)
        _cache_set(f"most_actives_{limit}", [])
        return []


async def movers(limit_per_feed: int = 25) -> List[str]:
    """Combined day_gainers + most_actives, deduped, preserving order."""
    g, a = await asyncio.gather(
        day_gainers(limit=limit_per_feed),
        most_actives(limit=limit_per_feed),
    )
    seen: set = set()
    out: List[str] = []
    for sym in (g + a):
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out
