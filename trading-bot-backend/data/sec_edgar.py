"""SEC EDGAR client for recent 13D / 13G filings.

What it does
------------
Pulls SC 13D / 13D-A / 13G / 13G-A filings filed in the last N days from EDGAR's
free public full-text-search JSON endpoint, parses the ticker out of each hit's
``display_names`` (falls back to the CIK→ticker map when the inline ticker is
missing), and returns a deduped list of ``Filing`` records.

Why
---
13D / 13G filings (>5% holder declarations) are the catalyst layer of the
squeeze screener: when a known activist or fund crosses the 5% threshold, it's
often the precursor to a short squeeze setup (CAR / GME pattern).

SEC compliance
--------------
Per https://www.sec.gov/os/accessing-edgar-data, every request must include a
User-Agent that identifies the requester. Override the default with the
``SEC_USER_AGENT`` env var (recommended: ``YourApp/1.0 (you@example.com)``).
Rate limit is 10 req/sec; we stay well under that.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("volta.sec_edgar")


_EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"

# Filing types we care about — 5%+ holder declarations and amendments.
_FORMS = ["SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"]


def _user_agent() -> str:
    return os.environ.get(
        "SEC_USER_AGENT",
        "VoltaNode-Bot/1.0 (operator@voltanode.local)",
    )


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
    }


@dataclass
class Filing:
    """A single 13D/13G filing parsed from EDGAR."""

    ticker: str
    cik: str
    form: str             # "SC 13D", "SC 13D/A", etc.
    filed_at: str         # ISO date "YYYY-MM-DD"
    filer_name: str       # e.g. "ProKidney Corp"
    accession: str        # "0001193125-26-104287"

    @property
    def edgar_url(self) -> str:
        """Direct link to the filing index on SEC.gov."""
        a = self.accession.replace("-", "")
        return (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={self.cik}&type={self.form.replace(' ', '+')}"
            f"&dateb=&owner=include&count=40"
        )


# ── CIK ↔ ticker map (cached once per process, refreshed daily) ──

_TICKER_CACHE: Dict[str, Dict[str, Any]] = {}


async def _get_cik_ticker_map() -> Dict[str, str]:
    """Return a CIK→ticker dict (CIKs zero-padded to 10 digits).

    Cached for 24h after first fetch.
    """
    cached = _TICKER_CACHE.get("map")
    if cached and time.time() - cached["fetched_at"] < 86400:
        return cached["data"]
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=_headers()) as client:
            r = await client.get(_TICKER_MAP_URL)
            r.raise_for_status()
            raw = r.json()
        # Schema: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "APPLE INC"}, ...}
        out: Dict[str, str] = {}
        for entry in raw.values():
            cik = str(entry["cik_str"]).zfill(10)
            ticker = str(entry["ticker"]).upper()
            out[cik] = ticker
        _TICKER_CACHE["map"] = {"fetched_at": time.time(), "data": out}
        logger.info("sec_edgar: CIK-ticker map loaded (%d entries)", len(out))
        return out
    except Exception as exc:
        logger.warning("sec_edgar: CIK-ticker fetch failed: %s", exc)
        return _TICKER_CACHE.get("map", {}).get("data", {})


# ── Filing fetch ──

# Pattern for parsing tickers out of display_names like
# "ProKidney Corp. (PROK) (Subject)"
_TICKER_RX = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,5})\)")


def _parse_tickers(display_names: List[str]) -> List[str]:
    """Extract ticker codes from EDGAR ``display_names`` strings.

    Each filing has multiple display_names — usually one for the issuer (Subject)
    and one per filer/reporting person. We want the issuer's ticker, which
    typically appears in the first 'Subject' entry.
    """
    out: List[str] = []
    for name in display_names:
        if "(Subject)" not in name and "(Issuer)" not in name and len(out) > 0:
            continue  # only fall through to non-Subject names if we have nothing yet
        for m in _TICKER_RX.finditer(name):
            sym = m.group(1).strip().upper().replace(".", "-")
            if sym and len(sym) <= 6:
                out.append(sym)
    # Dedup preserving order
    seen: set = set()
    return [s for s in out if not (s in seen or seen.add(s))]


async def fetch_recent_filings(
    days_back: int = 7,
    max_results: int = 200,
) -> List[Filing]:
    """Fetch SC 13D / 13G filings filed within the last ``days_back`` days.

    Returns deduped Filings (one per ticker — most recent filing wins).
    Returns ``[]`` on error rather than raising; the screener still works
    against the rest of the universe.

    Note: EDGAR's full-text search returns the ``form`` field (singular). We
    intentionally don't pass a date range to the API — instead we fetch the
    latest ~200 filings and filter by ``file_date`` here. This works whether
    the host clock is ahead/behind SEC's, and avoids the API's quirk of
    returning zero hits when the requested range straddles "no data yet".
    """
    # EDGAR's search-index returns 500 when ``forms`` carries more than one
    # form — request each variant separately and merge.
    hits: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=_headers()) as client:
            tasks = [
                client.get(_EDGAR_SEARCH, params={"q": "", "forms": form})
                for form in _FORMS
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
        for form, resp in zip(_FORMS, responses):
            if isinstance(resp, Exception):
                logger.warning("sec_edgar: %s fetch failed: %s", form, resp)
                continue
            try:
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("sec_edgar: %s parse failed: %s", form, exc)
                continue
            form_hits = (data.get("hits") or {}).get("hits") or []
            hits.extend(form_hits)
    except Exception as exc:
        logger.warning("sec_edgar: search failed: %s", exc)
        return []

    if not hits:
        return []

    # Sort hits by file_date desc so dedup keeps the freshest filing per ticker.
    hits.sort(
        key=lambda h: (h.get("_source") or {}).get("file_date", ""),
        reverse=True,
    )

    # Determine the "latest" date in the result set, then keep filings within
    # ``days_back`` of it. This sidesteps any host-clock mismatch.
    all_dates = [
        (h.get("_source") or {}).get("file_date", "") for h in hits
    ]
    valid_dates = [d for d in all_dates if d]
    if not valid_dates:
        return []
    latest_str = max(valid_dates)
    try:
        latest_dt = datetime.strptime(latest_str[:10], "%Y-%m-%d").date()
    except ValueError:
        latest_dt = datetime.now(timezone.utc).date()
    cutoff = latest_dt - timedelta(days=max(1, days_back))

    cik_map = await _get_cik_ticker_map()
    seen_tickers: set = set()
    out: List[Filing] = []

    for hit in hits:
        src = hit.get("_source") or {}
        # EDGAR uses ``form`` (singular) in this response.
        raw_form = src.get("form") or src.get("forms")
        if isinstance(raw_form, list):
            form = str(raw_form[0]).strip() if raw_form else ""
        else:
            form = str(raw_form or "").strip()
        if form not in _FORMS:
            continue

        display_names = src.get("display_names") or []
        ciks = src.get("ciks") or []
        accession = (
            (src.get("adsh") or hit.get("_id") or "").strip()
        )
        filed_at = (src.get("file_date") or "")[:10]
        # Apply the days_back filter relative to the freshest data SEC has.
        if filed_at:
            try:
                fd = datetime.strptime(filed_at, "%Y-%m-%d").date()
                if fd < cutoff:
                    continue
            except ValueError:
                pass

        # Try to parse ticker from display_names first (preferred — has issuer ticker
        # explicitly), fall back to first CIK lookup.
        tickers = _parse_tickers(display_names)
        if not tickers and ciks:
            cik = str(ciks[0]).zfill(10)
            mapped = cik_map.get(cik)
            if mapped:
                tickers = [mapped]
        if not tickers:
            continue

        ticker = tickers[0]
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)

        # Filer name: drop the parenthetical role tags
        filer_raw = display_names[0] if display_names else ""
        filer_name = re.sub(r"\s*\([^)]*\)\s*", " ", filer_raw).strip()

        cik_str = str(ciks[0]).zfill(10) if ciks else ""

        out.append(
            Filing(
                ticker=ticker,
                cik=cik_str,
                form=form,
                filed_at=filed_at,
                filer_name=filer_name,
                accession=accession,
            )
        )
        if len(out) >= max_results:
            break

    logger.info(
        "sec_edgar: fetched %d filings (%d unique tickers) over %dd",
        len(hits),
        len(out),
        days_back,
    )
    return out
