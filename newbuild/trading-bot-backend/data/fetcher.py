"""Market data fetcher with CoinGecko and Yahoo Finance support."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
import pandas as pd
import yfinance as yf

from data.cache import DataCache
from bot.config import AssetClass, BotConfig

# ── Symbol Normalization Maps ──

_CG_TICKER_TO_ID: Dict[str, str] = {
    # Major coins
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "BNB": "binancecoin",
    "DOGE": "dogecoin",
    "SHIB": "shiba-inu",
    "TRX": "tron",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "ETC": "ethereum-classic",
    "XLM": "stellar",
    "FIL": "filecoin",
    "ALGO": "algorand",
    "VET": "vechain",
    "THETA": "theta-token",
    "EOS": "eos",
    "AAVE": "aave",
    "SAND": "the-sandbox",
    "MANA": "decentraland",
    "AXS": "axie-infinity",
    "FTM": "fantom",
    "GRT": "the-graph",
    "XTZ": "tezos",
    "ICP": "internet-computer",
    "NEAR": "near",
    "FLOW": "flow",
    "CAKE": "pancakeswap-token",
    "EGLD": "elrond-erd-2",
    "HBAR": "hedera-hashgraph",
    "KLAY": "klay-token",
    "QNT": "quant-network",
    "MKR": "maker",
    "CRV": "curve-dao-token",
    "COMP": "compound-governance-token",
    "ENJ": "enjincoin",
    "CHZ": "chiliz",
    "BAT": "basic-attention-token",
    "ZIL": "zilliqa",
    "WAVES": "waves",
    "ONE": "harmony",
    "DASH": "dash",
    "NEO": "neo",
    "HOT": "holotoken",
    "RVN": "ravencoin",
    "ZEN": "horizen",
    "KSM": "kusama",
    "AR": "arweave",
    "LRC": "loopring",
    "SKL": "skale",
    "CELO": "celo",
    "AMP": "amp-token",
    "STORJ": "storj",
    "KNC": "kyber-network-crystal",
    "SNX": "synthetix-network-token",
    "YFI": "yearn-finance",
    "BAL": "balancer",
    "SUSHI": "sushiswap",
    "1INCH": "1inch",
    "BAND": "band-protocol",
    "APT": "aptos",
    "SUI": "sui",
    "SEI": "sei-network",
    "TIA": "celestia",
    "DYM": "dymension",
    "STRK": "starknet",
    "WLD": "worldcoin-wld",
    "ARB": "arbitrum",
    "OP": "optimism",
    "IMX": "immutable-x",
    "GALA": "gala",
    "BLUR": "blur",
    "PEPE": "pepe",
    "WIF": "dogwifcoin",
    "BONK": "bonk",
    "FLOKI": "floki",
    "JUP": "jupiter-exchange-solana",
    "PYTH": "pyth-network",
    "RNDR": "render-token",
    "TAO": "bittensor",
    "ARKM": "arkham",
    "PORTAL": "portal-2",
    "DEGEN": "degen-base",
}

# Reverse map: CoinGecko ID -> common ticker
_CG_ID_TO_TICKER: Dict[str, str] = {v: k for k, v in _CG_TICKER_TO_ID.items()}


def normalize_crypto_symbol(symbol: str) -> str:
    """Normalize a crypto symbol to a CoinGecko coin ID.

    Examples:
        - ``normalize_crypto_symbol("BTC") -> "bitcoin"``
        - ``normalize_crypto_symbol("bitcoin") -> "bitcoin"``

    Args:
        symbol: Raw symbol (ticker or CoinGecko ID).

    Returns:
        CoinGecko coin ID.
    """
    raw = symbol.strip().upper()
    return _CG_TICKER_TO_ID.get(raw, symbol.strip().lower())


def normalize_stock_symbol(symbol: str) -> str:
    """Normalize a stock ticker to uppercase.

    Examples:
        - ``normalize_stock_symbol("aapl") -> "AAPL"``
        - ``normalize_stock_symbol("AAPL") -> "AAPL"``

    Args:
        symbol: Raw stock ticker.

    Returns:
        Uppercase ticker string.
    """
    return symbol.strip().upper()


def crypto_id_to_ticker(cg_id: str) -> str:
    """Convert a CoinGecko ID back to a common ticker symbol."""
    return _CG_ID_TO_TICKER.get(cg_id, cg_id.upper())


class MarketData:
    """Unified market data fetcher with caching."""

    def __init__(self, cache: DataCache, config: BotConfig | None = None) -> None:
        """Initialize market data service.

        Args:
            cache: DataCache instance.
            config: Bot configuration.
        """
        self.cache = cache
        self.config = config or BotConfig()
        self._client: httpx.AsyncClient | None = None
        self._cg_base_url = (
            self.config.market_data.coingecko.base_url
            if self.config.market_data
            else "https://api.coingecko.com/api/v3"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    # ── CoinGecko (Crypto) ──

    async def get_crypto_price(self, symbol: str, vs_currency: str = "usd") -> float:
        """Fetch current crypto price from CoinGecko.

        Args:
            symbol: CoinGecko coin ID or common ticker (e.g., "bitcoin", "BTC").
            vs_currency: Quote currency.

        Returns:
            Current price.

        Raises:
            RuntimeError: On API failure.
        """
        symbol = normalize_crypto_symbol(symbol)

        # Check cache first (5 min TTL)
        cached = self.cache.get_price(symbol, ttl_seconds=300.0)
        if cached is not None:
            return cached

        client = await self._get_client()
        url = f"{self._cg_base_url}/simple/price"
        params = {"ids": symbol, "vs_currencies": vs_currency}

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            price = float(data[symbol][vs_currency])
            self.cache.store_price(symbol, price)
            return price
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RuntimeError("CoinGecko rate limit exceeded") from e
            raise RuntimeError(f"CoinGecko API error: {e.response.status_code}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to fetch crypto price: {e}") from e

    async def get_crypto_ohlcv(
        self,
        symbol: str,
        vs_currency: str = "usd",
        days: int = 30,
        interval: str = "daily",
    ) -> pd.DataFrame:
        """Fetch crypto OHLCV from CoinGecko.

        Args:
            symbol: CoinGecko coin ID or common ticker.
            vs_currency: Quote currency.
            days: Number of days of history.
            interval: Data interval.

        Returns:
            OHLCV DataFrame with columns [timestamp, open, high, low, close, volume].
        """
        symbol = normalize_crypto_symbol(symbol)

        # Check cache first (1 day TTL)
        cached = self.cache.get_ohlcv(symbol, interval)
        if cached is not None and len(cached) >= days * 0.9:
            return cached

        client = await self._get_client()
        url = f"{self._cg_base_url}/coins/{symbol}/market_chart"
        params = {"vs_currency": vs_currency, "days": str(days)}

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            # CoinGecko returns prices, market_caps, total_volumes as [timestamp, value]
            prices = data.get("prices", [])
            volumes = data.get("total_volumes", [])

            if not prices:
                raise RuntimeError("No price data returned from CoinGecko")

            # Build OHLCV from prices (using daily high/low approximation)
            df = pd.DataFrame(prices, columns=["timestamp", "close"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            df = df.resample("D").agg({"close": ["first", "max", "min", "last"]})
            df.columns = ["open", "high", "low", "close"]
            df = df.reset_index()

            # Add volume
            if volumes:
                vol_df = pd.DataFrame(volumes, columns=["timestamp", "volume"])
                vol_df["timestamp"] = pd.to_datetime(vol_df["timestamp"], unit="ms", utc=True)
                vol_df.set_index("timestamp", inplace=True)
                vol_df = vol_df.resample("D").sum().reset_index()
                df = df.merge(vol_df, on="timestamp", how="left")
            else:
                df["volume"] = 0.0

            df.fillna(0, inplace=True)
            df.attrs["symbol"] = symbol

            self.cache.store_ohlcv(df, symbol, interval)
            return df

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RuntimeError("CoinGecko rate limit exceeded") from e
            raise RuntimeError(f"CoinGecko API error: {e.response.status_code}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to fetch crypto OHLCV: {e}") from e

    async def get_crypto_market_chart(
        self, symbol: str, vs_currency: str = "usd", days: int = 30
    ) -> pd.DataFrame:
        """Fetch full market chart from CoinGecko.

        Returns DataFrame with [timestamp, price, market_cap, volume].
        """
        symbol = normalize_crypto_symbol(symbol)

        client = await self._get_client()
        url = f"{self._cg_base_url}/coins/{symbol}/market_chart"
        params = {"vs_currency": vs_currency, "days": str(days)}

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            prices = data.get("prices", [])
            market_caps = data.get("market_caps", [])
            volumes = data.get("total_volumes", [])

            df = pd.DataFrame(prices, columns=["timestamp", "price"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

            if market_caps:
                mc = pd.DataFrame(market_caps, columns=["timestamp", "market_cap"])
                mc["timestamp"] = pd.to_datetime(mc["timestamp"], unit="ms", utc=True)
                df = df.merge(mc, on="timestamp", how="left")

            if volumes:
                vol = pd.DataFrame(volumes, columns=["timestamp", "volume"])
                vol["timestamp"] = pd.to_datetime(vol["timestamp"], unit="ms", utc=True)
                df = df.merge(vol, on="timestamp", how="left")

            df.attrs["symbol"] = symbol
            return df

        except Exception as e:
            raise RuntimeError(f"Failed to fetch market chart: {e}") from e

    async def get_top_cryptos(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get top cryptocurrencies by market cap from CoinGecko.

        Uses the free ``/coins/markets`` endpoint (no API key required
        for the top 100 results).

        Args:
            limit: Number of coins to return (max 250 per page).

        Returns:
            List of coin dictionaries with keys such as ``id``, ``symbol``,
            ``name``, ``current_price``, ``market_cap``, ``total_volume``,
            ``price_change_percentage_24h``.
        """
        client = await self._get_client()
        url = f"{self._cg_base_url}/coins/markets"
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": str(min(limit, 250)),
            "page": "1",
            "sparkline": "false",
        }

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return list(response.json())
        except Exception as e:
            raise RuntimeError(f"Failed to fetch top cryptos: {e}") from e

    # ── Yahoo Finance (Stocks) ──

    def get_stock_ohlcv(
        self, ticker: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        """Fetch stock OHLCV from Yahoo Finance.

        Args:
            ticker: Stock ticker symbol.
            period: Data period (e.g., "1y", "1mo", "5d").
            interval: Data interval (e.g., "1d", "1h", "15m").

        Returns:
            OHLCV DataFrame.
        """
        ticker = normalize_stock_symbol(ticker)

        # Check cache first
        cached = self.cache.get_ohlcv(ticker, interval)
        if cached is not None:
            return cached

        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)
            if df.empty:
                raise RuntimeError(f"No data returned for {ticker}")

            df = df.reset_index()
            # yfinance columns are already Capitalized
            col_map = {
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
            df.rename(columns=col_map, inplace=True)
            # Handle timezone-aware DatetimeIndex
            if "Date" in df.columns:
                df.rename(columns={"Date": "timestamp"}, inplace=True)
            elif "Datetime" in df.columns:
                df.rename(columns={"Datetime": "timestamp"}, inplace=True)
            elif "date" in df.columns:
                df.rename(columns={"date": "timestamp"}, inplace=True)
            elif "datetime" in df.columns:
                df.rename(columns={"datetime": "timestamp"}, inplace=True)

            # Ensure required columns exist
            for col in ["open", "high", "low", "close", "volume"]:
                if col not in df.columns:
                    df[col] = df.get("close", 0.0)

            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            df.attrs["symbol"] = ticker

            self.cache.store_ohlcv(df, ticker, interval)
            return df

        except Exception as e:
            raise RuntimeError(f"Failed to fetch stock OHLCV for {ticker}: {e}") from e

    def get_stock_price(self, ticker: str) -> float:
        """Get current stock price.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Current price.
        """
        ticker = normalize_stock_symbol(ticker)

        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            price = info.get("regularMarketPrice", info.get("currentPrice"))
            if price is None:
                # Fallback to fast_info
                price = stock.fast_info.last_price
            return float(price)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch stock price for {ticker}: {e}") from e

    # ── Generic ──

    async def get_price(self, symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> float:
        """Route to correct provider based on asset class.

        Args:
            symbol: Trading symbol.
            asset_class: Asset class enum.

        Returns:
            Current price.
        """
        if asset_class == AssetClass.CRYPTO:
            return await self.get_crypto_price(symbol)
        elif asset_class == AssetClass.STOCK:
            return self.get_stock_price(symbol)
        else:
            raise ValueError(f"Unsupported asset class: {asset_class}")

    async def get_ohlcv(
        self,
        symbol: str,
        asset_class: AssetClass = AssetClass.CRYPTO,
        timeframe: str = "1d",
        limit: int = 500,
    ) -> pd.DataFrame:
        """Unified OHLCV fetcher.

        Args:
            symbol: Trading symbol.
            asset_class: Asset class enum.
            timeframe: Data timeframe.
            limit: Maximum rows to return.

        Returns:
            OHLCV DataFrame.
        """
        if asset_class == AssetClass.CRYPTO:
            days_map = {"1d": 30, "1h": 30, "15m": 7, "1w": 180}
            days = days_map.get(timeframe, 30)
            df = await self.get_crypto_ohlcv(symbol, days=days)
            return df.tail(limit).reset_index(drop=True)
        elif asset_class == AssetClass.STOCK:
            period_map = {"1d": "1y", "1h": "3mo", "15m": "5d", "1wk": "5y"}
            period = period_map.get(timeframe, "1y")
            df = self.get_stock_ohlcv(symbol, period=period)
            return df.tail(limit).reset_index(drop=True)
        else:
            raise ValueError(f"Unsupported asset class: {asset_class}")

    # ── Streaming Simulation ──

    async def price_stream(
        self, symbols: List[str], interval_sec: float = 5.0
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Simulated async price stream.

        Args:
            symbols: List of symbols to stream.
            interval_sec: Seconds between ticks.

        Yields:
            Tick data dictionaries.
        """
        import random
        # Get initial prices
        prices: Dict[str, float] = {}
        for symbol in symbols:
            try:
                prices[symbol] = await self.get_crypto_price(symbol)
            except Exception:
                prices[symbol] = 100.0  # Fallback

        while True:
            for symbol in symbols:
                # Simulate small random price movement
                base = prices[symbol]
                move = random.uniform(-0.005, 0.005)
                prices[symbol] = base * (1 + move)
                yield {
                    "symbol": symbol,
                    "price": prices[symbol],
                    "timestamp": datetime.now(timezone.utc),
                }
            await asyncio.sleep(interval_sec)
