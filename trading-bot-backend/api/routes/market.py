"""Market data API routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
import pandas as pd

from api.models import OHLCVBar, OHLCVResponse, PriceResponse
from bot.config import AssetClass, BotConfig
from data.cache import DataCache
from data.fetcher import (
    MarketData,
    normalize_crypto_symbol,
    normalize_stock_symbol,
    _CG_ID_TO_TICKER,
)

router = APIRouter()

logger = logging.getLogger("volta.api.market")

bot_config = BotConfig()

# Module-level shared MarketData/DataCache so successive /prices calls reuse
# the same in-process cache and HTTP session instead of building new ones.
_shared_market_data: MarketData | None = None


def _get_market_data(request: Request) -> MarketData:
    """Reuse the engine's MarketData if available, otherwise lazy-init shared."""
    engine = getattr(request.app.state, "engine", None)
    if engine is not None and getattr(engine, "market_data", None) is not None:
        return engine.market_data

    global _shared_market_data
    if _shared_market_data is None:
        cfg = getattr(request.app.state, "config", bot_config)
        cache = DataCache(cache_dir=str(Path(cfg.app.data_dir) / "cache"))
        _shared_market_data = MarketData(cache=cache, config=cfg)
    return _shared_market_data


PRICE_CACHE_TTL_SECONDS = 30.0  # tighter than 5min so dashboard feels "live"


async def _bulk_crypto_prices_cmc(
    market_data: MarketData, symbols: List[str], api_key: str
) -> Dict[str, float] | None:
    """Fetch many crypto prices in ONE CoinMarketCap round-trip.

    CMC's free "Basic" tier: 10K calls/month, 30/min — no anonymous IP throttling
    like CoinGecko. Returns None on any failure so the caller can fall back.
    """
    import httpx

    # Map CoinGecko IDs to tickers (CMC uses ticker symbols).
    normalized_cg = [normalize_crypto_symbol(s) for s in symbols]
    tickers = [_CG_ID_TO_TICKER.get(cg, cg.upper()) for cg in normalized_cg]
    cache_keys = normalized_cg

    out: Dict[str, float] = {}
    miss_idx: List[int] = []
    for i, (orig, key) in enumerate(zip(symbols, cache_keys)):
        cached = market_data.cache.get_price(key, ttl_seconds=PRICE_CACHE_TTL_SECONDS)
        if cached is not None:
            out[orig] = cached
        else:
            miss_idx.append(i)

    if not miss_idx:
        return out

    miss_tickers = [tickers[i] for i in miss_idx]
    miss_origs = [symbols[i] for i in miss_idx]
    miss_cache_keys = [cache_keys[i] for i in miss_idx]

    client = await market_data._get_client()
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
    params = {"symbol": ",".join(miss_tickers), "convert": "USD"}
    headers = {"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"}

    try:
        resp = await client.request("GET", url, params=params, headers=headers, timeout=10.0)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data", {})
    except (httpx.HTTPError, Exception):
        return None

    for ticker, orig, ckey in zip(miss_tickers, miss_origs, miss_cache_keys):
        try:
            entries = data.get(ticker)
            if isinstance(entries, list):
                entry = entries[0]
            else:
                entry = entries
            price = float(entry["quote"]["USD"]["price"])
            market_data.cache.store_price(ckey, price)
            out[orig] = price
        except (KeyError, TypeError, ValueError, IndexError):
            out[orig] = 0.0

    return out


async def _bulk_crypto_prices_coingecko(
    market_data: MarketData, symbols: List[str]
) -> Dict[str, float] | None:
    """Fetch many crypto prices in ONE CoinGecko round-trip.

    Returns None if the request fails (rate-limit, network error) so caller
    can fall back to a different provider. Returns a dict of partial results
    on success even if some symbols couldn't be parsed.
    """
    import httpx

    normalized = [normalize_crypto_symbol(s) for s in symbols]
    out: Dict[str, float] = {}
    misses: List[str] = []
    miss_norm: List[str] = []
    for orig, norm in zip(symbols, normalized):
        cached = market_data.cache.get_price(norm, ttl_seconds=PRICE_CACHE_TTL_SECONDS)
        if cached is not None:
            out[orig] = cached
        else:
            misses.append(orig)
            miss_norm.append(norm)

    if not misses:
        return out

    client = await market_data._get_client()
    url = f"{market_data._cg_base_url}/simple/price"
    params = {"ids": ",".join(miss_norm), "vs_currencies": "usd"}

    try:
        resp = await client.request("GET", url, params=params, timeout=8.0)
        if resp.status_code == 429:
            return None  # rate-limited → let caller fall back
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, Exception):
        return None

    for orig, norm in zip(misses, miss_norm):
        try:
            price = float(data[norm]["usd"])
            market_data.cache.store_price(norm, price)
            out[orig] = price
        except (KeyError, TypeError, ValueError):
            out[orig] = 0.0

    return out


async def _bulk_crypto_prices(market_data: MarketData, symbols: List[str]) -> Dict[str, float]:
    """CoinGecko primary, CoinMarketCap fallback.

    CoinGecko has no monthly cap (just 30/min), so it's cheaper for continuous
    polling. CMC's 10K/month free tier kicks in only when CG rate-limits or
    errors out — protecting the monthly budget.
    """
    import os

    cg_result = await _bulk_crypto_prices_coingecko(market_data, symbols)
    if cg_result is not None:
        return cg_result

    cmc_key = os.environ.get("CMC_API_KEY") or os.environ.get("COINMARKETCAP_API_KEY")
    if cmc_key:
        cmc_result = await _bulk_crypto_prices_cmc(market_data, symbols, cmc_key)
        if cmc_result is not None:
            return cmc_result

    # Both providers failed — return zeros so the dashboard renders rather than 5xxs.
    return {s: 0.0 for s in symbols}


@router.get("/prices")
async def get_prices(
    request: Request,
    symbols: str,
    asset_class: str = "crypto",
) -> List[PriceResponse]:
    """Get current prices for multiple symbols.

    Query: ?symbols=bitcoin,ethereum or ?symbols=BTC,ETH&asset_class=crypto

    Crypto prices are fetched in a single bulk request (one CoinGecko call for
    all symbols). Stock prices are fetched in parallel.
    """
    market_data = _get_market_data(request)
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    try:
        ac = AssetClass(asset_class)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid asset_class: {asset_class}")

    now = datetime.now(timezone.utc)

    if ac == AssetClass.CRYPTO:
        prices = await _bulk_crypto_prices(market_data, symbol_list)
        return [PriceResponse(symbol=s, price=prices.get(s, 0.0), timestamp=now) for s in symbol_list]

    # Stocks — fetch in parallel; per-symbol cache still applies.
    async def fetch_one(sym: str) -> PriceResponse:
        try:
            price = await asyncio.wait_for(market_data.get_price(sym, ac), timeout=5.0)
        except Exception:
            price = 0.0
        return PriceResponse(symbol=sym, price=price, timestamp=now)

    results = await asyncio.gather(*(fetch_one(s) for s in symbol_list))
    return list(results)


@router.get("/prices/bulk")
async def get_bulk_prices(
    symbols: str,
    asset_class: str = "crypto",
) -> List[PriceResponse]:
    """Get prices for many symbols at once.

    Query: ?symbols=BTC,ETH,DOGE,PEPE&asset_class=crypto
    """
    return await get_prices(symbols=symbols, asset_class=asset_class)


@router.get("/ohlcv/{symbol}")
async def get_ohlcv(
    symbol: str,
    asset_class: str = "crypto",
    timeframe: str = "1d",
    limit: int = 100,
) -> OHLCVResponse:
    """Get OHLCV data for a symbol."""
    cache = DataCache()
    market_data = MarketData(cache=cache, config=bot_config)
    synthetic = False
    try:
        ac = AssetClass(asset_class)
        df = await market_data.get_ohlcv(symbol, ac, timeframe, limit)
    except Exception:
        # Fallback to synthetic data. Log loudly and flag the response —
        # silently returning fabricated ~$100 bars masks real fetch failures
        # (e.g. wrong asset_class, e.g. SPY requested as crypto) and has
        # produced bogus benchmarks. Callers must inspect `synthetic`.
        synthetic = True
        logger.warning(
            "OHLCV fetch failed for %s (asset_class=%s, timeframe=%s); "
            "returning SYNTHETIC data.",
            symbol, asset_class, timeframe, exc_info=True,
        )
        import numpy as np
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=limit, freq="D")
        np.random.seed(hash(symbol) % (2**31))
        prices = 100 + np.cumsum(np.random.randn(limit) * 2)
        df = pd.DataFrame({
            "timestamp": dates,
            "open": prices * 0.99,
            "high": prices * 1.02,
            "low": prices * 0.98,
            "close": prices,
            "volume": np.random.randint(1000, 10000, limit),
        })
        df.attrs["symbol"] = symbol

    bars = []
    for _, row in df.iterrows():
        ts = row.get("timestamp", pd.Timestamp.now())
        if isinstance(ts, str):
            ts = pd.Timestamp(ts)
        bars.append(
            OHLCVBar(
                timestamp=ts,
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("volume", 0)),
            )
        )

    return OHLCVResponse(
        symbol=symbol,
        timeframe=timeframe,
        data=bars,
        synthetic=synthetic,
    )


@router.get("/symbols")
async def get_symbols() -> Dict[str, List[str]]:
    """Get available symbols."""
    return {
        "crypto": bot_config.market_data.symbols.get("crypto", []) if bot_config.market_data else [],
        "stocks": bot_config.market_data.symbols.get("stocks", []) if bot_config.market_data else [],
    }


@router.get("/search")
async def search_symbols(
    query: str,
    type: str = "all",  # noqa: A002  # "all", "crypto", "stocks"
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search available symbols by name or ticker.

    Query examples:
        - ?query=BTC&type=crypto
        - ?query=apple&type=stocks
        - ?query=eth
    """
    results: List[Dict[str, Any]] = []
    q = query.strip().lower()

    if type not in ("all", "crypto", "stocks"):
        raise HTTPException(status_code=400, detail=f"Invalid type: {type}. Use 'all', 'crypto', or 'stocks'.")

    # Build searchable metadata
    crypto_symbols = bot_config.market_data.symbols.get("crypto", []) if bot_config.market_data else []
    stock_symbols = bot_config.market_data.symbols.get("stocks", []) if bot_config.market_data else []

    if type in ("all", "crypto"):
        for cg_id in crypto_symbols:
            ticker = normalize_crypto_symbol(cg_id).upper()  # attempt reverse lookup
            # Check if query matches CoinGecko ID or ticker
            if q in cg_id.lower() or q in ticker.lower():
                results.append({
                    "symbol": cg_id,
                    "ticker": ticker,
                    "type": "crypto",
                    "name": cg_id.replace("-", " ").title(),
                })

    if type in ("all", "stocks"):
        for ticker in stock_symbols:
            if q in ticker.lower():
                results.append({
                    "symbol": ticker,
                    "ticker": ticker,
                    "type": "stock",
                    "name": ticker,
                })

    return results[:limit]
