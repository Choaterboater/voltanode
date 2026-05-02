"""Data caching layer: CSV and JSON with TTL."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


class DataCache:
    """Multi-layer cache: memory (simple dict) -> CSV fallback."""

    def __init__(self, cache_dir: str = "./data/cache") -> None:
        """Initialize cache.

        Args:
            cache_dir: Directory for CSV cache files.
        """
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._prices: Dict[str, tuple[float, datetime]] = {}  # symbol -> (price, timestamp)

    def _ohlcv_path(self, symbol: str, timeframe: str) -> Path:
        """Get cache file path for OHLCV data."""
        safe_symbol = symbol.replace("/", "_").replace("-", "_")
        return self._cache_dir / f"{safe_symbol}_{timeframe}.csv"

    def _price_path(self, symbol: str) -> Path:
        """Get cache file path for price data."""
        safe_symbol = symbol.replace("/", "_").replace("-", "_")
        return self._cache_dir / f"{safe_symbol}_price.json"

    def get_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 500) -> pd.DataFrame | None:
        """Get cached OHLCV data.

        Args:
            symbol: Trading symbol.
            timeframe: Timeframe string.
            limit: Maximum number of rows.

        Returns:
            DataFrame if cached and not expired (1 day TTL), None otherwise.
        """
        path = self._ohlcv_path(symbol, timeframe)
        if not path.exists():
            return None
        # Check TTL (1 day for OHLCV)
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(timezone.utc) - mtime > timedelta(days=1):
            return None
        try:
            df = pd.read_csv(path, parse_dates=["timestamp"])
            if len(df) > limit:
                df = df.tail(limit)
            return df
        except Exception:
            return None

    def store_ohlcv(self, df: pd.DataFrame, symbol: str, timeframe: str) -> None:
        """Store OHLCV data to cache.

        Args:
            df: OHLCV DataFrame.
            symbol: Trading symbol.
            timeframe: Timeframe string.
        """
        path = self._ohlcv_path(symbol, timeframe)
        try:
            df.to_csv(path, index=False)
        except Exception:
            pass

    def get_price(self, symbol: str, ttl_seconds: float = 300.0) -> float | None:
        """Get cached price.

        Args:
            symbol: Trading symbol.
            ttl_seconds: Time-to-live for price cache.

        Returns:
            Price if cached and not expired, None otherwise.
        """
        # Check in-memory first
        if symbol in self._prices:
            price, ts = self._prices[symbol]
            if datetime.now(timezone.utc) - ts < timedelta(seconds=ttl_seconds):
                return price

        # Check file cache
        path = self._price_path(symbol)
        if not path.exists():
            return None
        try:
            with open(path, "r") as f:
                data = json.load(f)
            ts = datetime.fromisoformat(data["timestamp"])
            if datetime.now(timezone.utc) - ts < timedelta(seconds=ttl_seconds):
                return data["price"]
        except Exception:
            return None
        return None

    def store_price(self, symbol: str, price: float, timestamp: datetime | None = None) -> None:
        """Store price to cache.

        Args:
            symbol: Trading symbol.
            price: Current price.
            timestamp: Optional timestamp (defaults to now).
        """
        ts = timestamp or datetime.now(timezone.utc)
        self._prices[symbol] = (price, ts)
        path = self._price_path(symbol)
        try:
            with open(path, "w") as f:
                json.dump({"price": price, "timestamp": ts.isoformat()}, f)
        except Exception:
            pass

    def export_to_csv(self, symbol: str, timeframe: str, path: str) -> None:
        """Export cached OHLCV to a specific CSV path.

        Args:
            symbol: Trading symbol.
            timeframe: Timeframe string.
            path: Export destination path.
        """
        df = self.get_ohlcv(symbol, timeframe)
        if df is not None:
            df.to_csv(path, index=False)

    def clear_cache(self, symbol: str | None = None) -> None:
        """Clear cache for a symbol or all symbols.

        Args:
            symbol: Optional symbol to clear. If None, clears all cache.
        """
        if symbol is None:
            # Clear all cache files
            for path in self._cache_dir.iterdir():
                if path.is_file():
                    path.unlink()
            self._prices.clear()
        else:
            safe = symbol.replace("/", "_").replace("-", "_")
            for path in self._cache_dir.iterdir():
                if path.name.startswith(safe):
                    path.unlink()
            self._prices.pop(symbol, None)
