"""News & sentiment analysis module.

Provides news fetching, sentiment scoring, and storage.
"""

from news.models import NewsArticle, SentimentResult
from news.fetcher import NewsFetcher
from news.sentiment import SentimentEngine
from news.storage import NewsStorage

__all__ = ["NewsArticle", "SentimentResult", "NewsFetcher", "SentimentEngine", "NewsStorage"]
