"""Finnhub signals: earnings calendar, insider Form 4 trades, news.

Free tier: 60 calls/min. Single env var ``FINNHUB_API_KEY``.

Capabilities exposed:
  - upcoming_earnings(days_ahead=14)  → calendar of imminent earnings
  - insider_transactions(symbol)       → recent Form 4s for a ticker
  - earnings_for_symbol(symbol)        → next earnings date for one ticker

These power "don't enter a long 24h before earnings" guards and reveal
when execs are loading up vs. dumping their own stock.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("volta.signals.finnhub")

_BASE_URL = "https://finnhub.io/api/v1"
_TTL_SECONDS = 30 * 60.0  # 30 min cache; calendars don't change often
_CACHE: Dict[str, Any] = {}


@dataclass
class EarningsEntry:
    symbol: str
    date: str
    eps_estimate: Optional[float] = None
    eps_actual: Optional[float] = None
    revenue_estimate: Optional[float] = None
    revenue_actual: Optional[float] = None
    hour: str = ""  # "bmo" / "amc" / ""


@dataclass
class InsiderTransaction:
    symbol: str
    name: str
    transaction_date: str
    transaction_code: str  # "P"=Purchase, "S"=Sale, "M"=Option exercise, etc.
    shares: float
    price: float
    value_usd: Optional[float] = None


def _api_key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "").strip()


def is_configured() -> bool:
    return bool(_api_key())


def _cached(key: str) -> Optional[Any]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    if time.monotonic() - entry["ts"] > _TTL_SECONDS:
        return None
    return entry["data"]


def _set_cache(key: str, data: Any) -> None:
    _CACHE[key] = {"data": data, "ts": time.monotonic()}


def upcoming_earnings(days_ahead: int = 14) -> List[EarningsEntry]:
    """Return the earnings calendar for the next ``days_ahead`` days."""
    if not is_configured():
        return []
    cache_key = f"earnings:{days_ahead}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    today = datetime.now(timezone.utc).date()
    until = today + timedelta(days=days_ahead)
    try:
        r = requests.get(
            f"{_BASE_URL}/calendar/earnings",
            params={
                "from": today.isoformat(),
                "to": until.isoformat(),
                "token": _api_key(),
            },
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(f"Finnhub earnings fetch failed: {exc}")
        return []

    rows = body.get("earningsCalendar") or []
    out: List[EarningsEntry] = []
    for row in rows:
        try:
            out.append(EarningsEntry(
                symbol=str(row.get("symbol", "")).upper(),
                date=str(row.get("date", "")),
                eps_estimate=_safe_float(row.get("epsEstimate")),
                eps_actual=_safe_float(row.get("epsActual")),
                revenue_estimate=_safe_float(row.get("revenueEstimate")),
                revenue_actual=_safe_float(row.get("revenueActual")),
                hour=str(row.get("hour", "")),
            ))
        except Exception:
            continue
    out.sort(key=lambda e: e.date)
    _set_cache(cache_key, out)
    return out


def earnings_for_symbol(symbol: str, days_ahead: int = 90) -> Optional[EarningsEntry]:
    """Return the next earnings entry for one ticker, if any."""
    cal = upcoming_earnings(days_ahead=days_ahead)
    target = symbol.upper()
    for e in cal:
        if e.symbol == target:
            return e
    return None


def insider_transactions(symbol: str, limit: int = 20) -> List[InsiderTransaction]:
    """Recent insider Form 4 transactions for a ticker."""
    if not is_configured():
        return []
    cache_key = f"insider:{symbol.upper()}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached[:limit]

    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=180)
    try:
        r = requests.get(
            f"{_BASE_URL}/stock/insider-transactions",
            params={
                "symbol": symbol.upper(),
                "from": since.isoformat(),
                "to": today.isoformat(),
                "token": _api_key(),
            },
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(f"Finnhub insider fetch failed for {symbol}: {exc}")
        return []

    rows = body.get("data") or []
    out: List[InsiderTransaction] = []
    for row in rows:
        try:
            shares = float(row.get("share", 0) or 0)
            price = float(row.get("transactionPrice", 0) or 0)
            value = shares * price if shares and price else None
            out.append(InsiderTransaction(
                symbol=symbol.upper(),
                name=str(row.get("name", "")),
                transaction_date=str(row.get("transactionDate", "")),
                transaction_code=str(row.get("transactionCode", "")),
                shares=shares,
                price=price,
                value_usd=value,
            ))
        except Exception:
            continue
    out.sort(key=lambda t: t.transaction_date, reverse=True)
    _set_cache(cache_key, out)
    return out[:limit]


def insider_summary(symbol: str) -> Dict[str, Any]:
    """Aggregate of insider activity over the last 180 days for a ticker."""
    txns = insider_transactions(symbol, limit=100)
    buys = [t for t in txns if t.transaction_code.upper() == "P"]
    sells = [t for t in txns if t.transaction_code.upper() == "S"]
    buy_value = sum((t.value_usd or 0) for t in buys)
    sell_value = sum((t.value_usd or 0) for t in sells)
    net = buy_value - sell_value
    return {
        "symbol": symbol.upper(),
        "buys": len(buys),
        "sells": len(sells),
        "buy_value_usd": round(buy_value, 2),
        "sell_value_usd": round(sell_value, 2),
        "net_value_usd": round(net, 2),
        "tone": "bullish" if net > 0 else ("bearish" if net < 0 else "neutral"),
        "transactions": [asdict(t) for t in txns[:20]],
    }


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        f = float(v)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None
