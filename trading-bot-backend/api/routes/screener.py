"""Stock screener API routes.

Currently exposes Greenblatt's Magic Formula. The pattern can be cloned
for additional screeners (Piotroski F-Score, Twin Momentum, Lynch Growth,
etc.) without changing this file's structure.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Query

from screeners import MagicFormulaScreener, DEFAULT_UNIVERSE

logger = logging.getLogger("volta.api.screener")

router = APIRouter()


@router.get("/")
async def list_screeners() -> Dict[str, Any]:
    """List available screener strategies + their descriptions."""
    return {
        "screeners": [
            {
                "id": "magic-formula",
                "name": "Greenblatt Magic Formula",
                "category": "value",
                "description": (
                    "Ranks the universe by Earnings Yield (EBIT/EV) and Return on Capital. "
                    "Best score = cheap company that's also good. From Joel Greenblatt's "
                    "*The Little Book That Beats the Market*."
                ),
                "endpoint": "/screener/magic-formula",
            },
        ],
        "default_universe_size": len(DEFAULT_UNIVERSE),
    }


@router.get("/magic-formula")
async def magic_formula(
    top_n: int = Query(default=30, ge=5, le=100),
    min_market_cap_b: float = Query(default=1.0, ge=0.0, description="Minimum market cap in $B"),
) -> Dict[str, Any]:
    """Run the Magic Formula screener on the default universe."""
    screener = MagicFormulaScreener()
    picks = await asyncio.to_thread(
        screener.run, top_n, min_market_cap_b * 1e9
    )
    return {
        "screener": "Greenblatt Magic Formula",
        "universe_size": len(DEFAULT_UNIVERSE),
        "min_market_cap_b": min_market_cap_b,
        "top_n": top_n,
        "count": len(picks),
        "picks": [p.to_dict() for p in picks],
    }
