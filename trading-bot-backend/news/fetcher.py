"""News fetcher for Alpaca News API and other sources."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from news.models import NewsArticle

logger = logging.getLogger("volta.news")


class NewsFetcher:
    """Fetch news from Alpaca Markets News API.

    Free tier: included with any Alpaca account.
    Endpoint: https://data.alpaca.markets/v1beta1/news
    """

    BASE_URL = "https://data.alpaca.markets/v1beta1/news"
    PAPER_BASE = "https://data.sandbox.alpaca.markets/v1beta1/news"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        paper: bool = False,
    ) -> None:
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("ALPACA_SECRET_KEY", "")
        self.base_url = self.PAPER_BASE if paper else self.BASE_URL
        self._session = requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Accept": "application/json",
        })

    def fetch(
        self,
        symbols: Optional[List[str]] = None,
        limit: int = 50,
        hours_lookback: int = 24,
    ) -> List[NewsArticle]:
        """Fetch recent news articles.

        Args:
            symbols: Filter by symbols (e.g., ["AAPL", "BTC-USD"]). None = all news.
            limit: Max articles to return (1-1000).
            hours_lookback: How far back to look.

        Returns:
            List of NewsArticle objects.
        """
        if not self.api_key or not self.api_secret:
            logger.warning("Alpaca API keys not set — skipping news fetch")
            return []

        start = datetime.now(timezone.utc) - timedelta(hours=hours_lookback)
        params: dict = {
            "limit": min(limit, 1000),
            "sort": "desc",  # newest first
            "start": start.isoformat(),
        }
        if symbols:
            params["symbols"] = ",".join(symbols)

        try:
            resp = self._session.get(self.base_url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("news", [])
            return [self._parse_article(a) for a in articles]
        except requests.exceptions.HTTPError as exc:
            logger.error(f"Alpaca news API HTTP error: {exc}")
            return []
        except requests.exceptions.RequestException as exc:
            logger.error(f"Alpaca news API request failed: {exc}")
            return []
        except Exception as exc:
            logger.error(f"Unexpected error fetching news: {exc}")
            return []

    @staticmethod
    def _parse_article(raw: dict) -> NewsArticle:
        """Parse raw Alpaca news JSON into NewsArticle."""
        created = raw.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            created_at = datetime.now(timezone.utc)

        return NewsArticle(
            id=raw.get("id", ""),
            headline=raw.get("headline", ""),
            summary=raw.get("summary", ""),
            source=raw.get("source", ""),
            symbols=raw.get("symbols", []),
            url=raw.get("url", ""),
            author=raw.get("author", ""),
            created_at=created_at,
            content=raw.get("content", ""),
        )
