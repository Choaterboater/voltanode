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
from dataclasses import dataclass
from typing import Dict, Optional

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
