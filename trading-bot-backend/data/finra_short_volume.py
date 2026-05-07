"""FINRA daily short-sale volume — free CDN, no API key.

Pulls FINRA's published daily reg-SHO short-sale volume files and exposes
per-ticker stats for the squeeze screener.

The two files we care about
---------------------------
* ``CNMSshvol{YYYYMMDD}.txt`` — Consolidated NMS feed, all venues.
  Used to compute total daily short-volume %.

* ``FNSQshvol{YYYYMMDD}.txt`` — FINRA/NASDAQ TRF (off-exchange / dark pool
  trades reported through the NASDAQ TRF).
* ``FNYXshvol{YYYYMMDD}.txt`` — FINRA/NYSE TRF.

Together the two TRF files = the "Off-Exchange Short Volume" that Fintel
surfaces. High off-exchange short volume + high SI% = institutional
shorting hiding from public order books — historically a bullish signal
for squeeze setups.

File format (pipe-delimited)
----------------------------
``Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market``

Caveats
-------
- FINRA posts T+1 (yesterday's data is available the morning after).
- Files don't exist for weekends/holidays — we walk back up to 5 days
  to find the most recent.
- Only covers reg-SHO-eligible NMS securities.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("volta.finra_short_volume")


_CDN_BASE = "https://cdn.finra.org/equity/regsho/daily"

# Type aliases for clarity
Symbol = str
SymbolStats = Dict[Symbol, Dict[str, float]]


@dataclass
class ShortVolumeSnapshot:
    """Per-ticker short-volume stats for a given trade date."""

    ticker: str
    trade_date: str                      # ISO YYYY-MM-DD

    # Total NMS (all venues)
    short_volume_total: float = 0.0      # shares
    total_volume: float = 0.0
    short_pct_total: float = 0.0         # 0–100

    # FINRA TRF (off-exchange / dark pool only)
    off_exchange_short_volume: float = 0.0
    off_exchange_total_volume: float = 0.0
    off_exchange_short_pct: float = 0.0  # 0–100, mirrors Fintel's "Off-Exchange Short Volume Ratio"

    # Source flags
    has_cnms: bool = False
    has_trf: bool = False


# ── Cache: results keyed by trade_date ──

_CACHE: Dict[str, Dict[str, Any]] = {}
_DEFAULT_TTL_S = 6 * 3600  # FINRA refreshes once daily; 6h is plenty


def _cache_key(trade_date: str) -> str:
    return f"finra_{trade_date}"


# ── HTTP fetch + parse ──

_HEADERS = {
    "User-Agent": "VoltaNode-Bot/1.0 (operator@voltanode.local)",
    "Accept": "text/plain, */*",
}


async def _fetch_file(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """Fetch one FINRA file. Returns text body, or None on 404/error."""
    try:
        r = await client.get(url, timeout=20.0)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text
    except Exception as exc:
        logger.debug("finra: fetch %s failed: %s", url, exc)
        return None


def _parse(text: str) -> SymbolStats:
    """Parse a pipe-delimited FINRA short-volume file.

    Returns ``{symbol: {'short': x, 'total': y, 'short_exempt': z}}``.
    Skips header line and the trailing sentinel ``File ... |`` row.
    """
    out: SymbolStats = {}
    for line in text.splitlines():
        if not line or line.startswith("Date|") or line.startswith("File "):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        try:
            sym = parts[1].strip().upper()
            short_vol = float(parts[2] or 0)
            short_exempt = float(parts[3] or 0)
            total_vol = float(parts[4] or 0)
        except (ValueError, IndexError):
            continue
        if not sym:
            continue
        # Some symbols appear once per market in CNMS; aggregate.
        if sym in out:
            out[sym]["short"] += short_vol
            out[sym]["short_exempt"] += short_exempt
            out[sym]["total"] += total_vol
        else:
            out[sym] = {
                "short": short_vol,
                "short_exempt": short_exempt,
                "total": total_vol,
            }
    return out


async def _load_for_date(yyyymmdd: str) -> Tuple[SymbolStats, SymbolStats]:
    """Fetch CNMS + TRF files for one trade date. Returns (cnms_stats, trf_stats)."""
    urls_cnms = f"{_CDN_BASE}/CNMSshvol{yyyymmdd}.txt"
    urls_trf_q = f"{_CDN_BASE}/FNSQshvol{yyyymmdd}.txt"
    urls_trf_n = f"{_CDN_BASE}/FNYXshvol{yyyymmdd}.txt"

    async with httpx.AsyncClient(headers=_HEADERS, timeout=25.0) as client:
        cnms_text, trf_q_text, trf_n_text = await asyncio.gather(
            _fetch_file(client, urls_cnms),
            _fetch_file(client, urls_trf_q),
            _fetch_file(client, urls_trf_n),
        )

    cnms = _parse(cnms_text) if cnms_text else {}

    # Merge the two TRF files.
    trf: SymbolStats = {}
    for text in (trf_q_text, trf_n_text):
        if not text:
            continue
        partial = _parse(text)
        for sym, stats in partial.items():
            if sym in trf:
                trf[sym]["short"] += stats["short"]
                trf[sym]["short_exempt"] += stats["short_exempt"]
                trf[sym]["total"] += stats["total"]
            else:
                trf[sym] = dict(stats)

    return cnms, trf


def _candidate_dates(now: Optional[datetime] = None, lookback_days: int = 5) -> List[str]:
    """Walk back from today looking for an available trade date.

    FINRA posts T+1 in the morning; on a Monday morning the most recent
    available file is Friday's. Skip weekends.
    """
    base = (now or datetime.now(timezone.utc)).date()
    out: List[str] = []
    for i in range(lookback_days):
        d = base - timedelta(days=i)
        # Skip Saturday=5, Sunday=6
        if d.weekday() >= 5:
            continue
        out.append(d.strftime("%Y%m%d"))
    return out


async def latest_short_volume_snapshot(
    ttl_s: float = _DEFAULT_TTL_S,
    lookback_days: int = 5,
) -> Optional[Dict[Symbol, ShortVolumeSnapshot]]:
    """Return ``{ticker: ShortVolumeSnapshot}`` for the freshest available trade date.

    Cached per trade-date so a screener pass that scores 200 tickers only
    fetches FINRA once.
    """
    for yyyymmdd in _candidate_dates(lookback_days=lookback_days):
        cache_key = _cache_key(yyyymmdd)
        cached = _CACHE.get(cache_key)
        if cached and time.time() - cached["fetched_at"] < ttl_s:
            return cached["data"]

        cnms, trf = await _load_for_date(yyyymmdd)
        if not cnms and not trf:
            continue  # No file for this date — try the previous one.

        trade_date = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
        out: Dict[str, ShortVolumeSnapshot] = {}
        all_syms = set(cnms.keys()) | set(trf.keys())
        for sym in all_syms:
            snap = ShortVolumeSnapshot(ticker=sym, trade_date=trade_date)
            cs = cnms.get(sym)
            if cs and cs["total"] > 0:
                snap.short_volume_total = cs["short"]
                snap.total_volume = cs["total"]
                snap.short_pct_total = (cs["short"] / cs["total"]) * 100.0
                snap.has_cnms = True
            ts = trf.get(sym)
            if ts and ts["total"] > 0:
                snap.off_exchange_short_volume = ts["short"]
                snap.off_exchange_total_volume = ts["total"]
                snap.off_exchange_short_pct = (ts["short"] / ts["total"]) * 100.0
                snap.has_trf = True
            out[sym] = snap

        _CACHE[cache_key] = {"fetched_at": time.time(), "data": out}
        logger.info(
            "finra: loaded %s — %d symbols (cnms=%d, trf=%d)",
            trade_date,
            len(out),
            len(cnms),
            len(trf),
        )
        return out

    logger.warning("finra: no recent file found in last %dd lookback", lookback_days)
    return None


async def short_volume_for(ticker: str) -> Optional[ShortVolumeSnapshot]:
    """Convenience: fetch (or reuse cached) freshest snapshot for one ticker."""
    snap_map = await latest_short_volume_snapshot()
    if snap_map is None:
        return None
    return snap_map.get(ticker.upper())
