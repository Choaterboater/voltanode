"""Crypto perpetual funding-rate + open-interest regime signal.

Funding rate is the periodic payment between perp longs and shorts. It is a
cheap, retail-accessible crowding gauge:

- **Strongly positive** funding ⇒ longs are paying shorts ⇒ crowded long ⇒
  late/overheated; new longs are buying into leverage that has to unwind.
- **Strongly negative** funding ⇒ shorts are paying longs ⇒ crowded short ⇒
  squeeze fuel; contrarian-bullish for spot.

This module exposes a PURE classifier (``classify_funding_regime``) that is
fully unit-tested, plus a best-effort Binance fetch that degrades gracefully
(returns ``None`` on any error/timeout) so it can never wedge the tick loop.

Wiring into live gating is intentionally left to the caller — see
``docs/ALPHA_ROADMAP.md`` (NEXT tier). Nothing here changes trading behavior
until a strategy/engine consults ``funding_signal()``.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("volta.funding")

# 8h funding-rate thresholds (decimal, e.g. 0.0005 = 0.05% per 8h ≈ 0.15%/day).
# Defaults are deliberately conservative; tune per asset.
CROWDED_LONG = 0.0005
CROWDED_SHORT = -0.0005

# Best-effort fetch cache so a 5s tick loop doesn't hammer the exchange.
_CACHE: Dict[str, "FundingSignal"] = {}
_CACHE_TS: Dict[str, float] = {}
_CACHE_TTL_S = 300.0


@dataclass
class FundingSignal:
    """Classified funding-rate regime for one symbol."""

    symbol: str
    funding_rate: float            # latest 8h funding rate (decimal)
    open_interest: Optional[float]  # contracts, if available
    regime: str                     # "crowded_long" | "crowded_short" | "neutral"
    bias: str                       # "bearish" | "bullish" | "neutral"
    blocks_new_long: bool           # advisory: veto fresh longs into crowded-long

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "funding_rate": self.funding_rate,
            "open_interest": self.open_interest,
            "regime": self.regime,
            "bias": self.bias,
            "blocks_new_long": self.blocks_new_long,
        }


def classify_funding_regime(
    funding_rate: float,
    open_interest: Optional[float] = None,
    *,
    crowded_long: float = CROWDED_LONG,
    crowded_short: float = CROWDED_SHORT,
    symbol: str = "",
) -> FundingSignal:
    """Pure classifier — no I/O. Maps a funding rate to a tradeable regime.

    - rate >= crowded_long  -> crowded_long / bearish / blocks new longs
    - rate <= crowded_short -> crowded_short / bullish (squeeze setup)
    - otherwise             -> neutral
    """
    if funding_rate >= crowded_long:
        regime, bias, block = "crowded_long", "bearish", True
    elif funding_rate <= crowded_short:
        regime, bias, block = "crowded_short", "bullish", False
    else:
        regime, bias, block = "neutral", "neutral", False
    return FundingSignal(
        symbol=symbol,
        funding_rate=float(funding_rate),
        open_interest=open_interest,
        regime=regime,
        bias=bias,
        blocks_new_long=block,
    )


def _to_binance_perp(symbol: str) -> str:
    """Map a bare crypto symbol/CoinGecko id to a Binance USDT-perp symbol."""
    s = str(symbol).strip().upper()
    aliases = {
        "BITCOIN": "BTC", "ETHEREUM": "ETH", "SOLANA": "SOL", "CARDANO": "ADA",
        "RIPPLE": "XRP", "DOGECOIN": "DOGE", "POLKADOT": "DOT", "CHAINLINK": "LINK",
    }
    s = aliases.get(s, s)
    for suffix in ("-USD", "USD", "-USDT", "USDT", "/USDT", "/USD"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return f"{s}USDT"


def fetch_binance_funding(symbol: str, timeout: float = 6.0) -> Optional[Dict[str, float]]:
    """Best-effort fetch of latest funding rate + open interest from Binance.

    Returns ``{"funding_rate": float, "open_interest": float | None}`` or
    ``None`` on ANY failure (network, 4xx/5xx, parse). Never raises.
    """
    try:
        import requests

        perp = _to_binance_perp(symbol)
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": perp},
            timeout=timeout,
        )
        if r.status_code >= 400:
            return None
        rate = float(r.json().get("lastFundingRate", 0.0))

        oi: Optional[float] = None
        try:
            r2 = requests.get(
                "https://fapi.binance.com/fapi/v1/openInterest",
                params={"symbol": perp},
                timeout=timeout,
            )
            if r2.status_code < 400:
                oi = float(r2.json().get("openInterest", 0.0))
        except Exception:
            oi = None

        return {"funding_rate": rate, "open_interest": oi}
    except Exception as exc:  # pragma: no cover - network path
        logger.debug(f"funding fetch failed for {symbol}: {exc}")
        return None


def cached_funding_signal(symbol: str, max_age_s: float = 900.0) -> Optional[FundingSignal]:
    """Read a symbol's regime from cache with ZERO network I/O.

    Returns ``None`` if nothing is cached or the cached value is older than
    ``max_age_s`` (stale ⇒ "no opinion" rather than acting on hours-old data
    if the refresher died). This is what the tick-loop funding gate calls so it
    never blocks on the network.
    """
    key = _to_binance_perp(symbol)
    ts = _CACHE_TS.get(key)
    if ts is None or (time.time() - ts) > max_age_s:
        return None
    return _CACHE.get(key)


def refresh_funding(symbols) -> int:
    """Force-refresh a list of symbols into the cache (does network I/O).

    Intended to run in a background thread (see the funding loop in
    ``api/main.py``), NOT in the tick path. Returns the count refreshed; never
    raises (per-symbol failures are swallowed).
    """
    n = 0
    for s in symbols or []:
        try:
            if funding_signal(s, use_cache=False) is not None:
                n += 1
        except Exception:
            pass
    return n


def prime_cache(symbol: str, funding_rate: float, open_interest: Optional[float] = None) -> FundingSignal:
    """Inject a classified regime into the cache (no I/O). Used by tests and
    callers that source funding rates elsewhere."""
    sig = classify_funding_regime(funding_rate, open_interest, symbol=symbol)
    key = _to_binance_perp(symbol)
    _CACHE[key] = sig
    _CACHE_TS[key] = time.time()
    return sig


def funding_signal(symbol: str, *, use_cache: bool = True) -> Optional[FundingSignal]:
    """Fetch + classify a symbol's funding regime (cached ~5 min).

    Returns ``None`` when live data is unavailable so callers can treat the
    overlay as "no opinion" rather than failing.
    """
    key = _to_binance_perp(symbol)
    if use_cache:
        last = _CACHE_TS.get(key)
        if last is not None and (time.time() - last) < _CACHE_TTL_S:
            return _CACHE.get(key)

    data = fetch_binance_funding(symbol)
    if data is None:
        return None
    sig = classify_funding_regime(
        data["funding_rate"], data.get("open_interest"), symbol=symbol
    )
    _CACHE[key] = sig
    _CACHE_TS[key] = time.time()
    return sig


# ── Historical funding (for backtesting a funding strategy) ────────────────

def _to_hl_coin(symbol: str) -> str:
    """Bare coin ticker for Hyperliquid (BTCUSDT/bitcoin/BTC-USD -> BTC)."""
    s = str(symbol).strip().upper()
    s = _CG_ALIASES_HL.get(s, s)
    for suf in ("-USDT", "USDT", "-USD", "/USD", "/USDT", "USD"):
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


_CG_ALIASES_HL = {
    "BITCOIN": "BTC", "ETHEREUM": "ETH", "SOLANA": "SOL", "CARDANO": "ADA",
    "RIPPLE": "XRP", "DOGECOIN": "DOGE", "POLKADOT": "DOT", "CHAINLINK": "LINK",
}


def fetch_hyperliquid_funding_history(symbol: str, days: int = 365, max_pages: int = 25,
                                      timeout: float = 12.0) -> List[Tuple[int, float]]:
    """Historical HOURLY funding from Hyperliquid — FREE, no key, US-accessible.

    Paginates the /info ``fundingHistory`` endpoint (500 records/request) back
    ``days``. Returns ``[(time_ms, rate), ...]`` oldest→newest, ``[]`` on error.
    """
    try:
        import requests

        coin = _to_hl_coin(symbol)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start = now_ms - int(days) * 86_400_000
        out: List[Tuple[int, float]] = []
        for _ in range(max_pages):
            r = requests.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "fundingHistory", "coin": coin, "startTime": start},
                timeout=timeout,
            )
            if r.status_code >= 400:
                break
            rows = r.json() or []
            if not rows:
                break
            for x in rows:
                try:
                    out.append((int(x["time"]), float(x["fundingRate"])))
                except (KeyError, TypeError, ValueError):
                    continue
            last_t = int(rows[-1]["time"])
            if len(rows) < 500 or last_t >= now_ms:
                break
            start = last_t + 1
        out.sort(key=lambda t: t[0])
        return out
    except Exception as exc:  # pragma: no cover - network path
        logger.debug(f"hyperliquid funding history failed for {symbol}: {exc}")
        return []


def _fetch_binance_funding_history(symbol: str, limit: int = 1000, timeout: float = 10.0) -> List[Tuple[int, float]]:
    """Historical 8h funding from Binance perps. Returns ``[]`` on failure
    (incl. HTTP 451 — Binance is geo-blocked in the US)."""
    try:
        import requests

        perp = _to_binance_perp(symbol)
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": perp, "limit": min(int(limit), 1000)},
            timeout=timeout,
        )
        if r.status_code >= 400:
            return []
        rows = r.json() or []
        out = []
        for x in rows:
            try:
                out.append((int(x["fundingTime"]), float(x["fundingRate"])))
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda t: t[0])
        return out
    except Exception as exc:  # pragma: no cover - network path
        logger.debug(f"binance funding history failed for {symbol}: {exc}")
        return []


def fetch_funding_history(symbol: str, limit: int = 1000, timeout: float = 10.0) -> List[Tuple[int, float]]:
    """Best-effort historical funding, oldest→newest. Tries Hyperliquid first
    (free + US-accessible), falls back to Binance (works outside the US).
    ``[]`` if both fail. Never raises."""
    hl = fetch_hyperliquid_funding_history(symbol, timeout=timeout)
    if hl:
        return hl
    return _fetch_binance_funding_history(symbol, limit=limit, timeout=timeout)


def daily_funding(symbol: str, limit: int = 1000) -> Dict[str, float]:
    """Map ``YYYY-MM-DD`` -> summed funding for that day (the day's carry).

    Funding pays ~3×/day (8h); summing gives the daily funding cost/credit,
    the natural per-(daily-)bar feature. ``{}`` if unavailable.
    """
    out: Dict[str, float] = defaultdict(float)
    for ts_ms, rate in fetch_funding_history(symbol, limit):
        day = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        out[day] += rate
    return dict(out)


def attach_funding_to_ohlcv(df: Any, symbol: str) -> Any:
    """Add a forward-filled, date-aligned ``funding_rate`` column to a daily
    OHLCV DataFrame. Returns the df unchanged (no column) if funding data is
    unavailable — so a funding strategy degrades to HOLD rather than erroring.
    """
    fmap = daily_funding(symbol)
    if not fmap:
        return df
    try:
        import numpy as np
        import pandas as pd

        if "timestamp" in df.columns:
            dates = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        else:
            dates = pd.to_datetime(df.index, utc=True, errors="coerce")
        keys = [d.strftime("%Y-%m-%d") if d is not None and not pd.isna(d) else None for d in dates]
        col = pd.Series([fmap.get(k, np.nan) for k in keys], index=df.index)
        df = df.copy()
        df["funding_rate"] = col.ffill().fillna(0.0)
    except Exception as exc:
        logger.debug(f"attach_funding_to_ohlcv failed for {symbol}: {exc}")
    return df
