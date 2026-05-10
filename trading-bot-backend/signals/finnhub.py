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


# Tokens that strongly suggest the filer is an entity / institutional holder
# rather than an individual corporate insider. Conservative — keeps anything
# that looks like a person name. Case-insensitive substring match.
_INSTITUTIONAL_TOKENS = (
    " lp",
    " l.p.",
    " llc",
    " l.l.c.",
    " inc.",
    " inc ",
    " ltd",
    " corp.",
    " corp ",
    " corporation",
    " holdings",
    " partners",
    " partnership",
    " capital",
    " management",
    " advisors",
    " advisers",
    " fund",
    " trust company",
    " investments",
    " investment",
    " group ltd",
    " group lp",
    " group llc",
    " sponsor",
    " hedge",
    " bank",
    " bancorp",
    " plc",
    " limited",
    " s.a.",
    " sa ",
)


def _looks_institutional(name: str) -> bool:
    """Heuristic: True if the filer name looks like a fund/LP/corporation
    rather than a person.

    We add a leading space to the lower-cased name so substring tests like
    ' lp' don't accidentally match "Phillip" or "philip". A trailing space
    is also useful for words that should match only at word boundaries.
    """
    if not name:
        return False
    needle = " " + name.lower().strip() + " "
    return any(tok in needle for tok in _INSTITUTIONAL_TOKENS)


def insider_transactions(
    symbol: str,
    limit: int = 20,
    reference_price: Optional[float] = None,
) -> List[InsiderTransaction]:
    """Recent insider Form 4 transactions for a ticker.

    Args:
        symbol: Ticker.
        limit: Max transactions to return.
        reference_price: Current market price. When provided, rows whose
            ``transactionPrice`` deviates by >2× are dropped — kills
            derivative-settlement filings that report synthetic prices
            (e.g. swap unwinds) and would otherwise inflate aggregate
            values into the billions for normal mid-caps.
            When omitted, falls back to a median-based filter that's
            less robust but still drops the worst outliers.
    """
    if not is_configured():
        return []
    # Cache key includes ref price so a subsequent call with a different
    # reference doesn't return a stale-filtered list.
    ref_key = f"{reference_price:.2f}" if reference_price else "auto"
    cache_key = f"insider:{symbol.upper()}:{ref_key}"
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

    # Choose a reference price for sanity-filtering. Prefer the explicit
    # market price passed by the caller (most accurate); fall back to
    # median of all reported transactionPrices, which is rough — biased
    # by huge derivative-settlement filings, but still kills outliers
    # 3+ orders of magnitude off.
    sanity_ref: Optional[float] = reference_price
    if sanity_ref is None:
        raw_prices: List[float] = []
        for row in rows:
            try:
                p = float(row.get("transactionPrice", 0) or 0)
                if p > 0:
                    raw_prices.append(p)
            except (TypeError, ValueError):
                continue
        if raw_prices:
            sp = sorted(raw_prices)
            sanity_ref = sp[len(sp) // 2]

    # Asymmetric bounds. The dangerous outliers are derivative-settlement
    # filings reported at synthetic prices ABOVE the market (Pentwater
    # reporting CAR sales at $700 when the stock is $160 — these inflate
    # totals into the billions). Trades reported BELOW current market are
    # almost always legitimate older transactions (the stock has run up
    # since), so we leave the lower bound very loose to avoid filtering
    # real history (e.g. RXT sold at $1 → now trades at $3.87 — keep).
    upper_mult = 2.5 if reference_price else 5.0
    lower_mult = 0.05 if reference_price else 0.05

    out: List[InsiderTransaction] = []
    skipped_price_outliers = 0
    skipped_institutional = 0
    for row in rows:
        try:
            shares = float(row.get("share", 0) or 0)
            price = float(row.get("transactionPrice", 0) or 0)
            name_raw = str(row.get("name", "") or "")

            # Name-based institutional filter. Form 4 mostly carries
            # corporate-insider trades (officers, directors), but the same
            # endpoint occasionally surfaces filings from large institutional
            # holders unwinding derivative positions — those report
            # synthetic prices that pollute aggregate totals (the CAR /
            # Pentwater Capital $42B inflation). Skip names that look like
            # entities, not individuals.
            if _looks_institutional(name_raw):
                skipped_institutional += 1
                continue

            # Sanity bound vs. reference. Catches any remaining
            # synthetic-price filings that slip past the name filter.
            if sanity_ref and price > 0:
                ratio = price / sanity_ref
                if ratio > upper_mult or ratio < lower_mult:
                    skipped_price_outliers += 1
                    continue
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
    if skipped_price_outliers > 0 or skipped_institutional > 0:
        logger.info(
            "insider %s: dropped %d institutional + %d price-outlier rows (ref=%s, source=%s)",
            symbol,
            skipped_institutional,
            skipped_price_outliers,
            f"${sanity_ref:.2f}" if sanity_ref else "n/a",
            "explicit" if reference_price else "median-fallback",
        )
    out.sort(key=lambda t: t.transaction_date, reverse=True)
    _set_cache(cache_key, out)
    return out[:limit]


def insider_summary(
    symbol: str,
    reference_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Aggregate of insider activity over the last 180 days for a ticker.

    Pass ``reference_price`` (current market price) when known so the
    aggregator can drop derivative-settlement filings whose reported prices
    don't correspond to the real market — protects the totals from being
    inflated by Pentwater-Capital-style swap unwinds.
    """
    txns = insider_transactions(symbol, limit=100, reference_price=reference_price)
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
