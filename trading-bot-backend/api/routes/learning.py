"""Learning / supervisor API routes.

    GET /learning/stats -> per-strategy ENTRY-attributed performance + bench
                           status. This is the honest scoreboard: round trips
                           are attributed to the strategy that OPENED the
                           position (TradeMemory FIFO with the phantom-lot
                           guard), not to the exit manager that closed it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter

from learning.supervisor import StrategySupervisor

logger = logging.getLogger("volta.api.learning")

router = APIRouter()

# Shared instance — the background learning loop uses this same object so the
# bench watermarks the route reports are the ones actually enforced.
supervisor = StrategySupervisor()


@router.get("/stats")
async def learning_stats() -> Dict[str, Any]:
    """Entry-attributed per-strategy performance and supervisor bench status."""
    import asyncio

    from learning.trade_memory import TradeMemory
    from api.routes import strategies as strategies_routes

    try:
        # Full jsonl read — keep it off the event loop shared with the 5s tick.
        records: List[Dict[str, Any]] = await asyncio.to_thread(lambda: TradeMemory().all())
    except Exception as exc:
        logger.warning("learning stats: trade memory unavailable: %s", exc)
        records = []

    rows = supervisor.stats(records, strategies_routes._registered_strategies)
    return {
        "strategies": rows,
        "rules": {
            "min_trades": supervisor.min_trades,
            "min_profit_factor": supervisor.min_pf,
            "rebench_fresh_trades": supervisor.rebench_fresh_trades,
        },
        "note": (
            "profit_factor is ENTRY-attributed (round trips credited to the "
            "strategy that opened the position, not the exit manager). "
            "Strategies with n=0 have no closed round trips yet."
        ),
    }
