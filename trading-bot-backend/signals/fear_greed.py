"""Crypto Fear & Greed Index from alternative.me.

Free, no API key, no rate limit worth mentioning. Returns a single 0-100
score where 0 = Extreme Fear, 100 = Extreme Greed. Classic "buy fear,
sell greed" contrarian signal — very useful for crypto strategies.

Cached for 1 hour because the underlying index updates daily.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("volta.signals.fear_greed")

_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_TTL_SECONDS = 3600.0


@dataclass
class FearGreedSignal:
    """Snapshot of the alternative.me crypto F&G index."""

    value: int  # 0-100
    label: str  # "Extreme Fear" / "Fear" / "Neutral" / "Greed" / "Extreme Greed"
    timestamp: str  # ISO8601 from the source
    history: List[Dict[str, Any]]  # last 7 days of (value, label, timestamp)

    @property
    def is_extreme_fear(self) -> bool:
        return self.value <= 24

    @property
    def is_fear(self) -> bool:
        return 25 <= self.value <= 44

    @property
    def is_neutral(self) -> bool:
        return 45 <= self.value <= 54

    @property
    def is_greed(self) -> bool:
        return 55 <= self.value <= 74

    @property
    def is_extreme_greed(self) -> bool:
        return self.value >= 75

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["is_extreme_fear"] = self.is_extreme_fear
        d["is_extreme_greed"] = self.is_extreme_greed
        return d


def fetch_fear_greed(force: bool = False) -> Optional[FearGreedSignal]:
    """Pull the current Fear & Greed index, with caching.

    ``force=True`` bypasses the cache (use sparingly).
    """
    now = time.monotonic()
    if not force and _CACHE["data"] is not None and now - _CACHE["ts"] < _TTL_SECONDS:
        return _CACHE["data"]

    try:
        # limit=8 → today + 7-day history, enough for trend computation
        r = requests.get("https://api.alternative.me/fng/?limit=8", timeout=10)
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(f"Fear & Greed fetch failed: {exc}")
        return None

    points = body.get("data") or []
    if not points:
        return None

    head = points[0]
    try:
        value = int(head.get("value", 0))
    except (TypeError, ValueError):
        return None
    label = str(head.get("value_classification", "")) or _label_from_value(value)
    ts_unix = head.get("timestamp")
    timestamp = ""
    if ts_unix:
        try:
            from datetime import datetime, timezone
            timestamp = datetime.fromtimestamp(int(ts_unix), tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass

    history: List[Dict[str, Any]] = []
    for p in points[1:]:
        try:
            history.append({
                "value": int(p.get("value", 0)),
                "label": str(p.get("value_classification", "")),
                "timestamp": p.get("timestamp"),
            })
        except (TypeError, ValueError):
            continue

    sig = FearGreedSignal(value=value, label=label, timestamp=timestamp, history=history)
    _CACHE["data"] = sig
    _CACHE["ts"] = now
    return sig


def _label_from_value(v: int) -> str:
    if v <= 24:
        return "Extreme Fear"
    if v <= 44:
        return "Fear"
    if v <= 54:
        return "Neutral"
    if v <= 74:
        return "Greed"
    return "Extreme Greed"
