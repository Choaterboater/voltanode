"""In-memory TTL cache for expensive scan endpoint responses."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Tuple

_SCAN_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

# Five minutes — long enough to make back-navigation instant, short enough
# that a manual refresh still picks up fresh market data.
DEFAULT_TTL_S = 300.0


def make_key(prefix: str, **params: Any) -> str:
    """Stable cache key from endpoint prefix + query parameters."""
    return f"{prefix}:" + json.dumps(params, sort_keys=True, default=str)


def cache_get(
    key: str,
    *,
    ttl_s: float = DEFAULT_TTL_S,
    nocache: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return a cached payload with cache metadata, or None on miss."""
    if nocache:
        return None
    entry = _SCAN_CACHE.get(key)
    if not entry:
        return None
    ts, payload = entry
    if time.time() - ts > ttl_s:
        _SCAN_CACHE.pop(key, None)
        return None
    out = dict(payload)
    out["cached"] = True
    out["cache_age_ms"] = int((time.time() - ts) * 1000)
    return out


def cache_set(key: str, payload: Dict[str, Any]) -> None:
    """Store a scan response. Strips prior cache metadata before storing."""
    clean = {k: v for k, v in payload.items() if k not in ("cached", "cache_age_ms")}
    _SCAN_CACHE[key] = (time.time(), clean)


def cache_clear(prefix: str | None = None) -> int:
    """Clear all entries, or entries whose key starts with ``prefix``."""
    if prefix is None:
        n = len(_SCAN_CACHE)
        _SCAN_CACHE.clear()
        return n
    keys = [k for k in _SCAN_CACHE if k.startswith(prefix)]
    for k in keys:
        del _SCAN_CACHE[k]
    return len(keys)
