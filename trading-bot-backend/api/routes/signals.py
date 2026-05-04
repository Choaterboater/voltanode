"""Trading signal API routes.

Surfaces external read-only signals (Fear & Greed today; FRED + Finnhub
to follow) so the frontend can display them and strategies can read them
via the engine's signal_context.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from signals.fear_greed import fetch_fear_greed
from signals import fred as fred_signals
from signals import finnhub as finnhub_signals

router = APIRouter()


@router.get("/fear-greed")
async def get_fear_greed() -> Dict[str, Any]:
    """Crypto Fear & Greed Index (alternative.me). 0=Extreme Fear, 100=Extreme Greed."""
    sig = fetch_fear_greed()
    if sig is None:
        raise HTTPException(status_code=502, detail="Fear & Greed feed unavailable")
    return sig.to_dict()


@router.get("/macro")
async def get_macro() -> Dict[str, Any]:
    """FRED macro snapshot: VIX, Fed funds, 10y, 10y-2y spread, CPI, unemployment."""
    if not fred_signals.is_configured():
        raise HTTPException(status_code=503, detail="FRED_API_KEY not set")
    snap = fred_signals.fetch_macro_snapshot()
    if snap is None:
        raise HTTPException(status_code=502, detail="FRED feed unavailable")
    return snap.to_dict()


@router.get("/earnings")
async def get_earnings_calendar(days_ahead: int = 14) -> Dict[str, Any]:
    """Upcoming earnings (Finnhub) for the next ``days_ahead`` days."""
    if not finnhub_signals.is_configured():
        raise HTTPException(status_code=503, detail="FINNHUB_API_KEY not set")
    entries = finnhub_signals.upcoming_earnings(days_ahead=days_ahead)
    from dataclasses import asdict
    return {
        "days_ahead": days_ahead,
        "count": len(entries),
        "entries": [asdict(e) for e in entries],
    }


@router.get("/earnings/{symbol}")
async def get_earnings_for_symbol(symbol: str) -> Dict[str, Any]:
    """Next earnings event for a single ticker."""
    if not finnhub_signals.is_configured():
        raise HTTPException(status_code=503, detail="FINNHUB_API_KEY not set")
    entry = finnhub_signals.earnings_for_symbol(symbol)
    if entry is None:
        return {"symbol": symbol.upper(), "next": None}
    from dataclasses import asdict
    return {"symbol": symbol.upper(), "next": asdict(entry)}


@router.get("/insider/{symbol}")
async def get_insider_summary(symbol: str) -> Dict[str, Any]:
    """Aggregate insider Form 4 activity for a ticker (last 180 days)."""
    if not finnhub_signals.is_configured():
        raise HTTPException(status_code=503, detail="FINNHUB_API_KEY not set")
    return finnhub_signals.insider_summary(symbol)


@router.get("/")
async def list_signals() -> Dict[str, Any]:
    """Snapshot of all available signals — used by Home/dashboard widgets."""
    out: Dict[str, Any] = {}
    fg = fetch_fear_greed()
    if fg is not None:
        out["fear_greed"] = fg.to_dict()
    if fred_signals.is_configured():
        macro = fred_signals.fetch_macro_snapshot()
        if macro is not None:
            out["macro"] = macro.to_dict()
    out["providers"] = {
        "fear_greed": True,  # always available, no key
        "fred": fred_signals.is_configured(),
        "finnhub": finnhub_signals.is_configured(),
    }
    return out
