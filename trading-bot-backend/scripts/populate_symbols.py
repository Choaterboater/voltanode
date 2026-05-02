#!/usr/bin/env python3
"""Populate symbol list by querying CoinGecko's top cryptocurrencies.

Usage:
    python scripts/populate_symbols.py [--limit 100]

This script queries CoinGecko's free ``/coins/markets`` endpoint and prints
the top-N coin IDs in the YAML list format used by ``config.yaml``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, Dict, List

import httpx


COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"


async def fetch_top_cryptos(
    limit: int = 100,
    vs_currency: str = "usd",
) -> List[Dict[str, Any]]:
    """Fetch top cryptocurrencies from CoinGecko.

    Args:
        limit: Number of coins to fetch (max 250 per page).
        vs_currency: Quote currency for market data.

    Returns:
        List of coin dictionaries.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{COINGECKO_BASE_URL}/coins/markets"
        params = {
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "per_page": str(min(limit, 250)),
            "page": "1",
            "sparkline": "false",
        }
        response = await client.get(url, params=params)
        response.raise_for_status()
        return list(response.json())


def print_yaml_list(coins: List[Dict[str, Any]]) -> None:
    """Print coin IDs as a YAML list snippet."""
    print("    crypto:")
    for coin in coins:
        coin_id = coin.get("id", "unknown")
        name = coin.get("name", "Unknown")
        symbol = coin.get("symbol", "").upper()
        market_cap = coin.get("market_cap", 0)
        print(f"      - {coin_id:<36}  # {symbol} – {name}  (${market_cap:,.0f})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query CoinGecko top cryptos and print YAML list."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of top cryptocurrencies to fetch (default: 100, max: 250).",
    )
    parser.add_argument(
        "--currency",
        type=str,
        default="usd",
        help="Quote currency for market data (default: usd).",
    )
    parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Omit inline comments with symbol names and market caps.",
    )
    args = parser.parse_args()

    print(f"Fetching top {args.limit} cryptocurrencies from CoinGecko …")
    try:
        coins = asyncio.run(
            fetch_top_cryptos(limit=args.limit, vs_currency=args.currency)
        )
    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code} – {e.response.text}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not coins:
        print("No coins returned.", file=sys.stderr)
        return 1

    print(f"\n# Top {len(coins)} cryptocurrencies by market cap")
    print("symbols:")
    if args.no_comments:
        print("    crypto:")
        for coin in coins:
            print(f"      - {coin.get('id', 'unknown')}")
    else:
        print_yaml_list(coins)

    return 0


if __name__ == "__main__":
    sys.exit(main())
