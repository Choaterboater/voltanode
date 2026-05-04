"""Trading signal API routes.

Surfaces external read-only signals (Fear & Greed today; FRED + Finnhub
to follow) so the frontend can display them and strategies can read them
via the engine's signal_context.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from signals.fear_greed import fetch_fear_greed

router = APIRouter()


@router.get("/fear-greed")
async def get_fear_greed() -> Dict[str, Any]:
    """Crypto Fear & Greed Index (alternative.me). 0=Extreme Fear, 100=Extreme Greed."""
    sig = fetch_fear_greed()
    if sig is None:
        raise HTTPException(status_code=502, detail="Fear & Greed feed unavailable")
    return sig.to_dict()


@router.get("/")
async def list_signals() -> Dict[str, Any]:
    """Snapshot of all available signals — used by Home/dashboard widgets."""
    out: Dict[str, Any] = {}
    fg = fetch_fear_greed()
    if fg is not None:
        out["fear_greed"] = fg.to_dict()
    return out
