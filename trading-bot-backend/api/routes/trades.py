"""Trades API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List

from bot.engine import PaperTradingEngine

router = APIRouter()

engine: PaperTradingEngine | None = None


def set_engine(e: PaperTradingEngine) -> None:
    global engine
    engine = e


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
