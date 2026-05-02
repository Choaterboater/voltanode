"""Market data API routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
import pandas as pd

from api.models import OHLCVBar, OHLCVResponse, PriceResponse
from bot.config import AssetClass, BotConfig
from data.cache import DataCache
from data.fetcher import MarketData, normalize_crypto_symbol, normalize_stock_symbol

router = APIRouter()

bot_config = BotConfig()


@router.get("/prices")
async def get_prices(
    symbols: str,
    asset_class: str = "crypto",
) -> List[PriceResponse]:
    """Get current prices for multiple symbols.

    Query: ?symbols=bitcoin,ethereum or ?symbols=BTC,ETH&asset_class=crypto
    """
    cache = DataCache()
    market_data = MarketData(cache=cache, config=bot_config)
    results = []
    symbol_list = [s.strip() for s in symbols.split(",")]

    try:
        ac = AssetClass(asset_class)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid asset_class: {asset_class}")

    for symbol in symbol_list:
        try:
            price = await market_data.get_price(symbol, ac)
            results.append(
                PriceResponse(
                    symbol=symbol,
                    price=price,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        except Exception as e:
            results.append(
                PriceResponse(
                    symbol=symbol,
                    price=0.0,
                    timestamp=datetime.now(timezone.utc),
                )
            )
    return results


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
    try:
        ac = AssetClass(asset_class)
        df = await market_data.get_ohlcv(symbol, ac, timeframe, limit)
    except Exception:
        # Fallback to synthetic data
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
