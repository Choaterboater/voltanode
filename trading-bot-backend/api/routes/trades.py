"""Trades API routes."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from bot.engine import PaperTradingEngine

logger = logging.getLogger("volta.trades")

router = APIRouter()

engine: PaperTradingEngine | None = None


def set_engine(e: PaperTradingEngine) -> None:
    global engine
    engine = e


# ─── External trade ingest (D:\Trade -> VoltaNode learning loop) ───
#
# Sibling bots (currently the `tradingbot` project at D:\Trade) POST their
# realized round-trips here so VoltaNode's advisor can calibrate against
# real outcomes from another execution venue.
#
# Storage: append-only JSONL at data/external_trades.jsonl.
# Idempotency: (source, symbol, entry_ts) hash. Replays return 200 with
# already_seen=true so the caller's cursor advances cleanly.

_EXTERNAL_TRADES_PATH = Path("data") / "external_trades.jsonl"
_dedup_lock = Lock()
_seen_keys: set[str] | None = None  # populated lazily on first POST


class ExternalTradeIn(BaseModel):
    """Inbound payload from a sibling bot reporting a closed round-trip."""

    source: str = Field(..., min_length=1, max_length=40, description="Caller identifier, e.g. 'tradingbot'")
    symbol: str = Field(..., min_length=1, max_length=20)
    side: str = Field(..., description="BUY or SELL — entry direction")
    qty: float = Field(..., gt=0)
    entry_price: float = Field(..., ge=0)
    exit_price: float = Field(..., ge=0)
    entry_ts: str = Field(..., description="ISO-8601 timestamp")
    exit_ts: str = Field(..., description="ISO-8601 timestamp")
    realized_pnl: float = Field(..., description="Signed; positive = win")
    strategy_tag: str = Field("", max_length=120)
    conviction_score: float | None = Field(None, description="Optional 0-100")

    @field_validator("side")
    @classmethod
    def _normalize_side(cls, v: str) -> str:
        u = v.strip().upper()
        if u not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        return u

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        return v.strip().upper()


def _trade_key(source: str, symbol: str, entry_ts: str) -> str:
    raw = f"{source.lower()}|{symbol.upper()}|{entry_ts}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _load_dedup_set() -> set[str]:
    """Scan existing JSONL once to rebuild the dedup set on first call."""
    seen: set[str] = set()
    if not _EXTERNAL_TRADES_PATH.exists():
        return seen
    try:
        with _EXTERNAL_TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                k = row.get("_key") or _trade_key(
                    row.get("source", ""),
                    row.get("symbol", ""),
                    row.get("entry_ts", ""),
                )
                seen.add(k)
    except Exception as exc:
        logger.warning("external_trades: dedup scan failed: %s", exc)
    return seen


def _ensure_dedup_loaded() -> set[str]:
    global _seen_keys
    if _seen_keys is None:
        _seen_keys = _load_dedup_set()
        logger.info("external_trades: loaded %d existing keys", len(_seen_keys))
    return _seen_keys


@router.post("/external/ingest")
async def ingest_external_trade(payload: ExternalTradeIn) -> Dict[str, Any]:
    """Accept a realized round-trip from a sibling bot.

    Idempotent on (source, symbol, entry_ts). On replay returns 200 with
    ``already_seen=true`` so the caller's cursor can advance without retry
    loops or duplicate writes.
    """
    key = _trade_key(payload.source, payload.symbol, payload.entry_ts)

    with _dedup_lock:
        seen = _ensure_dedup_loaded()
        if key in seen:
            return {"accepted": True, "already_seen": True, "key": key}

        row = payload.model_dump()
        row["_key"] = key
        row["ingested_at"] = datetime.now(timezone.utc).isoformat()

        _EXTERNAL_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _EXTERNAL_TRADES_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as exc:
            logger.error("external_trades: write failed for %s: %s", key, exc)
            raise HTTPException(status_code=500, detail="ingest write failed")

        seen.add(key)
        logger.info(
            "external_trades: accepted %s %s %s qty=%s pnl=%.2f from %s",
            payload.side, payload.symbol, payload.entry_ts,
            payload.qty, payload.realized_pnl, payload.source,
        )
        return {"accepted": True, "already_seen": False, "key": key}


@router.get("/external/recent")
async def list_external_trades(
    source: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Read back ingested external trades. Newest-first.

    Used by the advisor calibration job + the UI to show how sibling-bot
    outcomes are trending. ``source`` filters by caller (e.g. 'tradingbot').
    """
    if not _EXTERNAL_TRADES_PATH.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with _EXTERNAL_TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if source and row.get("source", "").lower() != source.lower():
                    continue
                rows.append(row)
    except Exception as exc:
        logger.warning("external_trades: read failed: %s", exc)
        return []
    # JSONL is append-order; newest is at the bottom — reverse for newest-first.
    rows.reverse()
    return rows[:limit]


@router.get("/")
async def get_trades(
    account_id: str | None = None,
    strategy_id: str | None = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """List trades with optional filters."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    trades = engine.get_trade_history(account_id)
    if strategy_id:
        trades = [t for t in trades if t.strategy_id == strategy_id]
    # Append-only in-memory list is oldest-first; callers expect newest-first.
    trades = list(reversed(trades))
    return [
        {
            "id": t.id,
            "order_id": t.order_id,
            "strategy_id": t.strategy_id,
            "symbol": t.symbol,
            "side": t.side,
            "quantity": t.quantity,
            "price": t.price,
            "fee": t.fee,
            "realized_pnl": t.realized_pnl,
            "timestamp": t.timestamp.isoformat(),
            # Strategy that opened the position (exit fills are placed by the
            # exit managers, so strategy_id alone mis-attributes losses).
            "origin_strategy_id": getattr(t, "origin_strategy_id", None),
        }
        for t in trades[:limit]
    ]


@router.get("/export")
async def export_trades(format: str = "csv") -> Dict[str, str]:
    """Export trades to CSV or JSON."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    trades = engine.get_trade_history()
    import os
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if format == "csv":
        import pandas as pd
        data = [
            {
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "fee": t.fee,
                "realized_pnl": t.realized_pnl,
                "timestamp": t.timestamp.isoformat(),
            }
            for t in trades
        ]
        df = pd.DataFrame(data)
        os.makedirs("./exports", exist_ok=True)
        path = f"./exports/trades_{ts}.csv"
        df.to_csv(path, index=False)
        return {"path": path, "count": str(len(trades))}
    return {"error": "Unsupported format"}
