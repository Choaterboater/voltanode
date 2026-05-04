"""Federal Reserve Economic Data (FRED) macro signals.

Free API. Single env var ``FRED_API_KEY``. We pull a small set of
high-signal series — VIX, Fed funds rate, 10-year Treasury, CPI,
unemployment — and cache them for 6 hours since they update at most
daily (most are weekly/monthly).

Strategies can read these via ``signal_context`` to gate entries
("no buys when VIX > 30", "skip the FOMC week", etc.).

Source: Federal Reserve Bank of St. Louis
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
    "UNRATE": {
        "name": "Unemployment Rate",
        "hint": "Labor market. Rising rate often precedes Fed cuts.",
        "frequency": "monthly",
    },
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
    """Pull last 2 observations of a series so we can compute change."""
    meta = SERIES.get(series_id, {"name": series_id, "hint": "", "frequency": "unknown"})
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
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(f"FRED fetch failed for {series_id}: {exc}")
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
    for series_id in SERIES.keys():
        obs = _fetch_series(series_id, api_key)
        if obs is not None:
            snap.series[series_id] = obs

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
