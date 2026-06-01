"""User watchlist — JSON-file-backed persistent store.

Single-tenant (one watchlist per backend instance). Stored at
``data/watchlist.json`` so it survives backend restarts. Each entry has:

* ``symbol`` — uppercased ticker
* ``asset_type`` — "stock" or "crypto"
* ``note`` — optional free-text annotation
* ``source`` — where the entry came from ("manual", "squeeze", "scanner",
  etc.) so the UI can show provenance
* ``added_at`` — ISO timestamp

The Squeeze and Scanner pages POST here when an operator promotes a ranked
candidate to their watchlist. The Watchlist page GETs the full list.
Removal is by symbol+asset_type.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("volta.watchlist")

router = APIRouter()

_STORE_PATH = Path("data") / "watchlist.json"


def _load_all() -> List[Dict[str, Any]]:
    """Load the full watchlist from disk. Empty list on missing/corrupt."""
    if not _STORE_PATH.exists():
        return []
    try:
        data = json.loads(_STORE_PATH.read_text())
        if isinstance(data, list):
            return data
    except Exception as exc:
        logger.warning("watchlist: read failed: %s", exc)
    return []


def _save_all(items: List[Dict[str, Any]]) -> None:
    """Atomically write the watchlist to disk."""
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, indent=2))
    tmp.replace(_STORE_PATH)


def _key(symbol: str, asset_type: str) -> tuple[str, str]:
    """Canonical dedup key — uppercase symbol + lowercase asset_type."""
    return (symbol.strip().upper(), asset_type.strip().lower())


# ── Request models ──

class WatchlistAddRequest(BaseModel):
    symbol: str
    asset_type: str = Field(default="stock", description="'stock' or 'crypto'")
    note: Optional[str] = None
    source: str = Field(default="manual", description="manual | squeeze | scanner | advisor")


# ── Endpoints ──

@router.get("/")
async def list_watchlist(asset_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return the full watchlist, newest first. Optionally filter by asset_type."""
    items = _load_all()
    if asset_type:
        items = [it for it in items if str(it.get("asset_type", "")).lower() == asset_type.lower()]
    items.sort(key=lambda x: str(x.get("added_at", "")), reverse=True)
    return items


_ENRICHED_CACHE: Dict[str, Any] = {}  # key: asset_type filter, value: (ts, payload)
_ENRICHED_TTL_SECONDS = 300.0


@router.get("/enriched")
async def list_watchlist_enriched(
    asset_type: Optional[str] = None,
    concurrency: int = 12,
    nocache: bool = False,
) -> Dict[str, Any]:
    """Return watchlist with live market data appended per row.

    Fetches recent OHLCV for each symbol in parallel, then attaches:
      * ``current_price``
      * ``day_pct_change`` (latest close vs prior close)
      * ``week_pct_change`` (latest close vs 5 trading days ago)
      * ``sparkline`` — last 20 daily closes for the inline chart
      * ``relative_volume`` — current bar volume vs trailing-20 mean

    Same shape the Squeeze page renders, so the Watchlist UI can reuse
    the same Sparkline + sortable-table pattern.
    """
    import asyncio
    import time
    from data.cache import DataCache
    from data.fetcher import MarketData
    from bot.config import BotConfig

    base = await list_watchlist(asset_type=asset_type)
    if not base:
        return {"items": [], "errors": []}

    # Serve from in-memory cache if it's fresh (<60s). Avoids re-running
    # the 40-symbol enrichment on every dashboard navigation. Pass
    # ``nocache=true`` to force a refetch (used by the Refresh button).
    cache_key = asset_type or "_all_"
    now = time.time()
    if not nocache:
        cached = _ENRICHED_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _ENRICHED_TTL_SECONDS:
            return cached[1]

    market_data = MarketData(cache=DataCache(cache_dir="./data/cache"), config=BotConfig())
    sem = asyncio.Semaphore(max(1, min(20, concurrency)))

    async def _enrich_one(item: Dict[str, Any]) -> Dict[str, Any]:
        sym = str(item.get("symbol", "")).strip().upper()
        atype = str(item.get("asset_type", "stock")).lower()
        out: Dict[str, Any] = dict(item)
        out["current_price"] = None
        out["day_pct_change"] = None
        out["week_pct_change"] = None
        out["sparkline"] = None
        out["relative_volume"] = None
        out["fetch_error"] = None
        async with sem:
            try:
                if atype == "crypto":
                    df = await market_data.get_crypto_ohlcv(
                        sym, vs_currency="usd", days=30, interval="daily"
                    )
                else:
                    df = await asyncio.to_thread(
                        market_data.get_stock_ohlcv, sym, "3mo", "1d"
                    )
                if df is None or df.empty:
                    out["fetch_error"] = "no_data"
                    return out
                df = df.copy()
                df.columns = [str(c).lower() for c in df.columns]
                if len(df) >= 1:
                    out["current_price"] = float(df["close"].iloc[-1])
                if len(df) >= 2 and df["close"].iloc[-2] > 0:
                    out["day_pct_change"] = float(
                        (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2]
                    )
                if len(df) >= 6 and df["close"].iloc[-6] > 0:
                    out["week_pct_change"] = float(
                        (df["close"].iloc[-1] - df["close"].iloc[-6]) / df["close"].iloc[-6]
                    )
                if len(df) >= 20:
                    out["sparkline"] = [
                        float(x) for x in df["close"].tail(20).tolist()
                        if x is not None and x == x
                    ]
                if "volume" in df.columns and len(df) >= 21:
                    cur_v = float(df["volume"].iloc[-1])
                    avg_v = float(df["volume"].iloc[-21:-1].mean())
                    if avg_v > 0:
                        out["relative_volume"] = cur_v / avg_v
            except Exception as exc:
                out["fetch_error"] = str(exc)[:140]
                logger.debug("watchlist enriched: %s failed: %s", sym, exc)
        return out

    enriched = await asyncio.gather(*(_enrich_one(it) for it in base))
    errors = [
        {"symbol": e.get("symbol"), "error": e["fetch_error"]}
        for e in enriched
        if e.get("fetch_error")
    ]
    payload = {"items": enriched, "errors": errors}
    _ENRICHED_CACHE[cache_key] = (now, payload)
    return payload


@router.post("/")
async def add_to_watchlist(req: WatchlistAddRequest) -> Dict[str, Any]:
    """Add a ticker to the watchlist. Idempotent — re-adding refreshes the
    note + source + added_at without duplicating."""
    sym = req.symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol required")
    asset = req.asset_type.strip().lower()
    if asset not in ("stock", "crypto"):
        raise HTTPException(status_code=400, detail="asset_type must be 'stock' or 'crypto'")

    items = _load_all()
    target_key = _key(sym, asset)
    # Strip any existing entry with the same symbol+asset_type (idempotent overwrite)
    items = [it for it in items if _key(it.get("symbol", ""), it.get("asset_type", "")) != target_key]

    new_item = {
        "symbol": sym,
        "asset_type": asset,
        "note": req.note,
        "source": req.source,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    items.append(new_item)
    _save_all(items)
    return {"status": "added", "item": new_item, "total": len(items)}


@router.post("/bulk")
async def bulk_add_to_watchlist(items: List[WatchlistAddRequest]) -> Dict[str, Any]:
    """Add many tickers in one call. Each item is the same shape as POST /.

    Convenience endpoint for external apps (e.g. another scanner / alerts
    pipeline) that want to push a batch of picks at once. Idempotent —
    re-posting the same symbol+asset_type refreshes the entry's note +
    source rather than duplicating.
    """
    if not items:
        return {"status": "noop", "added": 0, "total": len(_load_all())}
    existing = _load_all()
    for req in items:
        sym = req.symbol.strip().upper()
        if not sym:
            continue
        asset = req.asset_type.strip().lower()
        if asset not in ("stock", "crypto"):
            continue
        target_key = _key(sym, asset)
        existing = [
            it for it in existing
            if _key(it.get("symbol", ""), it.get("asset_type", "")) != target_key
        ]
        existing.append({
            "symbol": sym,
            "asset_type": asset,
            "note": req.note,
            "source": req.source,
            "added_at": datetime.now(timezone.utc).isoformat(),
        })
    _save_all(existing)
    return {"status": "ok", "added": len(items), "total": len(existing)}


@router.delete("/{symbol}")
async def remove_from_watchlist(symbol: str, asset_type: str = "stock") -> Dict[str, Any]:
    """Remove a ticker from the watchlist by symbol + asset_type."""
    sym = symbol.strip().upper()
    asset = asset_type.strip().lower()
    items = _load_all()
    target_key = _key(sym, asset)
    before = len(items)
    items = [it for it in items if _key(it.get("symbol", ""), it.get("asset_type", "")) != target_key]
    removed = before - len(items)
    if removed == 0:
        raise HTTPException(status_code=404, detail=f"{sym} ({asset}) not in watchlist")
    _save_all(items)
    return {"status": "removed", "symbol": sym, "asset_type": asset, "remaining": len(items)}


@router.get("/contains/{symbol}")
async def contains(symbol: str, asset_type: str = "stock") -> Dict[str, Any]:
    """Quick check used by buttons to render 'On Watchlist' vs 'Add'."""
    sym = symbol.strip().upper()
    asset = asset_type.strip().lower()
    target_key = _key(sym, asset)
    for it in _load_all():
        if _key(it.get("symbol", ""), it.get("asset_type", "")) == target_key:
            return {"symbol": sym, "asset_type": asset, "in_watchlist": True, "item": it}
    return {"symbol": sym, "asset_type": asset, "in_watchlist": False}
