"""Federal Reserve Economic Data (FRED) macro signals.

Free API. Single env var ``FRED_API_KEY``. We pull a small set of
high-signal series — VIX, Fed funds rate, 10-year Treasury, CPI,
unemployment — and cache them for 6 hours since they update at most
daily (most are weekly/monthly).

Strategies can read these via ``signal_context`` to gate entries
("no buys when VIX > 30", "skip the FOMC week", etc.).

Source: Federal Reserve Bank of St. Louis

Robustness: FRED's API returns intermittent 500s (we've seen this on
T10Y2Y, CPIAUCSL, UNRATE, DGS2 across separate boots). The fetch path
retries up to 3 times with exponential backoff on 5xx + connection
errors. Per-series failures are logged at DEBUG (not WARN) for the
expected-transient cases so the backend startup log isn't full of red
the first time FRED hiccups.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("volta.signals.fred")

_BASE_URL = "https://api.stlouisfed.org/fred"
_TTL_SECONDS = 6 * 3600.0
_CACHE: Dict[str, Any] = {}

# Retry budget per series. Three attempts with 1s/2s/4s backoff is enough
# to ride out FRED's transient 500s without dragging out startup.
_MAX_RETRIES = 3
_RETRY_STATUS_CODES = {500, 502, 503, 504}
_BASE_BACKOFF_SEC = 1.0


# Curated series — id, friendly name, and a short interpretation hint.
SERIES: Dict[str, Dict[str, str]] = {
    "VIXCLS": {
        "name": "VIX (Volatility Index)",
        "hint": "Fear gauge. <15 complacent, 15-25 normal, >30 panic.",
        "frequency": "daily",
    },
    "DFF": {
        "name": "Federal Funds Effective Rate",
        "hint": "Short-term policy rate. Direction matters more than level.",
        "frequency": "daily",
    },
    "DGS10": {
        "name": "10-Year Treasury Yield",
        "hint": "Long-term risk-free rate. Rising yields = headwind for tech / growth.",
        "frequency": "daily",
    },
    "T10Y2Y": {
        "name": "10Y - 2Y Treasury Spread",
        "hint": "Yield curve. Negative = inverted = recession signal.",
        "frequency": "daily",
    },
    "CPIAUCSL": {
        "name": "CPI (All Items)",
        "hint": "Headline inflation. Watch month-over-month change.",
        "frequency": "monthly",
    },
    "PPIFIS": {
        "name": "PPI: Final Demand",
        "hint": "Producer inflation. Leads CPI by 1-3 months — early warning for consumer prices.",
        "frequency": "monthly",
    },
    "PCEPILFE": {
        "name": "Core PCE Price Index",
        "hint": "The Fed's actual target inflation measure. Strips food/energy. More important than CPI for rate-path expectations.",
        "frequency": "monthly",
    },
    "UNRATE": {
        "name": "Unemployment Rate",
        "hint": "Labor market. Rising rate often precedes Fed cuts.",
        "frequency": "monthly",
    },
    # ─── Bond yields & credit spreads — corp-debt refi pressure ───
    "DGS2": {
        "name": "2-Year Treasury Yield",
        "hint": "Short end of curve. Most sensitive to Fed expectations; sets short-term corp borrow costs.",
        "frequency": "daily",
    },
    "BAA10Y": {
        "name": "BAA - 10Y Spread",
        "hint": "Investment-grade credit spread (Moody's BAA over 10Y Treasury). Widens when corp credit stress rises — hurts levered names refinancing.",
        "frequency": "daily",
    },
    "BAMLH0A0HYM2": {
        "name": "HY Option-Adjusted Spread",
        "hint": "High-yield (junk) bond spread over Treasuries. Best real-time gauge of corporate distress. >5% = stress, >8% = crisis.",
        "frequency": "daily",
    },
    # ISM PMIs are no longer on FRED post-2019 (licensing). For an
    # equivalent growth-leading-indicator track the Chicago PMI / CFNAI
    # via FRED or pull ISM directly from forexfactory's free calendar.
}


@dataclass
class FredObservation:
    series_id: str
    name: str
    hint: str
    frequency: str
    value: Optional[float]
    date: str  # ISO date of the observation
    previous_value: Optional[float] = None
    change: Optional[float] = None  # value - previous_value
    change_pct: Optional[float] = None


@dataclass
class MacroSnapshot:
    """Full macro context for the strategy / dashboard."""

    fetched_at: str
    series: Dict[str, FredObservation] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "series": {sid: asdict(obs) for sid, obs in self.series.items()},
        }


def _api_key() -> str:
    return os.environ.get("FRED_API_KEY", "").strip()


def is_configured() -> bool:
    return bool(_api_key())


def _fetch_series(series_id: str, api_key: str) -> Optional[FredObservation]:
    """Pull last 2 observations of a series so we can compute change.

    Retries up to ``_MAX_RETRIES`` times on 5xx and connection errors,
    sleeping 1s/2s/4s between attempts. 4xx errors (bad series id, bad
    key, etc.) are NOT retried — they fail fast since retrying won't
    change the outcome.
    """
    meta = SERIES.get(series_id, {"name": series_id, "hint": "", "frequency": "unknown"})

    body: Optional[Dict[str, Any]] = None
    last_err: Optional[str] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            r = requests.get(
                f"{_BASE_URL}/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 2,
                },
                timeout=10,
            )
            # Don't retry on 4xx — that's a request problem, not a server hiccup
            if 400 <= r.status_code < 500:
                logger.warning(
                    f"FRED 4xx for {series_id}: {r.status_code} (no retry)"
                )
                return None
            r.raise_for_status()
            body = r.json()
            break  # success
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            last_err = f"HTTP {code}"
            if code not in _RETRY_STATUS_CODES or attempt == _MAX_RETRIES:
                # Give up — final failure gets a single quiet log line
                logger.debug(
                    f"FRED {series_id}: gave up after {attempt}/{_MAX_RETRIES} attempts ({last_err})"
                )
                return None
        except (requests.ConnectionError, requests.Timeout, ValueError) as exc:
            last_err = type(exc).__name__
            if attempt == _MAX_RETRIES:
                logger.debug(
                    f"FRED {series_id}: gave up after {attempt}/{_MAX_RETRIES} attempts ({last_err})"
                )
                return None
        # Exponential backoff: 1s, 2s, 4s
        time.sleep(_BASE_BACKOFF_SEC * (2 ** (attempt - 1)))

    if body is None:
        return None

    obs_list = body.get("observations") or []
    if not obs_list:
        return None

    head = obs_list[0]
    prev = obs_list[1] if len(obs_list) > 1 else {}
    value = _safe_float(head.get("value"))
    previous_value = _safe_float(prev.get("value"))
    change = None
    change_pct = None
    if value is not None and previous_value is not None:
        change = value - previous_value
        if previous_value != 0:
            change_pct = (change / abs(previous_value)) * 100

    return FredObservation(
        series_id=series_id,
        name=meta["name"],
        hint=meta["hint"],
        frequency=meta["frequency"],
        value=value,
        date=str(head.get("date", "")),
        previous_value=previous_value,
        change=change,
        change_pct=change_pct,
    )


def fetch_macro_snapshot(force: bool = False) -> Optional[MacroSnapshot]:
    """Pull the curated FRED bundle, with caching."""
    if not is_configured():
        return None

    now = time.monotonic()
    cached = _CACHE.get("snapshot")
    cached_ts = _CACHE.get("ts", 0.0)
    if not force and cached is not None and now - cached_ts < _TTL_SECONDS:
        return cached

    api_key = _api_key()
    snap = MacroSnapshot(fetched_at=datetime.now(timezone.utc).isoformat())
    failed_series: List[str] = []
    for series_id in SERIES.keys():
        obs = _fetch_series(series_id, api_key)
        if obs is not None:
            snap.series[series_id] = obs
        else:
            failed_series.append(series_id)

    # One summary line per fetch instead of one WARNING per failed series.
    # Partial success is normal (FRED frequently 500s on a subset for a
    # few minutes at a time); ALL-failure is what actually deserves alarm.
    fetched_n = len(snap.series)
    if fetched_n and failed_series:
        logger.info(
            f"FRED: fetched {fetched_n}/{len(SERIES)} series; "
            f"missing after retries: {','.join(failed_series)}"
        )
    elif failed_series:
        logger.warning(
            f"FRED: ALL series failed after retries ({len(failed_series)}). "
            "Check FRED_API_KEY and rate limits."
        )

    if not snap.series:
        # Don't cache an empty result — likely transient
        return None

    _CACHE["snapshot"] = snap
    _CACHE["ts"] = now
    return snap


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "" or v == ".":
            return None
        f = float(v)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None
