"""News & sentiment API routes."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from news.fetcher import NewsFetcher
from news.sentiment import SentimentEngine
from news.storage import NewsStorage

logger = logging.getLogger("volta.api")

router = APIRouter()

# Global instances (initialized on first use)
_fetcher: Optional[NewsFetcher] = None
_engine: Optional[SentimentEngine] = None
_storage: Optional[NewsStorage] = None


def _get_fetcher() -> Optional[NewsFetcher]:
    global _fetcher
    if _fetcher is None:
        _fetcher = NewsFetcher()
    return _fetcher


def _get_engine() -> SentimentEngine:
    global _engine
    if _engine is None:
        _engine = SentimentEngine()
    return _engine


def _get_storage() -> NewsStorage:
    global _storage
    if _storage is None:
        _storage = NewsStorage()
    return _storage


def init_news(
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_api_key: Optional[str] = None,
    llm_model: Optional[str] = None,
    db_path: Optional[str] = None,
    hybrid_mode: bool = True,
    hybrid_threshold: float = 0.6,
) -> None:
    """Initialize news module with explicit config."""
    global _fetcher, _engine, _storage
    _fetcher = NewsFetcher(api_key=api_key, api_secret=api_secret)
    _engine = SentimentEngine(
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        hybrid_mode=hybrid_mode,
        hybrid_threshold=hybrid_threshold,
    )
    if db_path:
        _storage = NewsStorage(db_path=db_path)
    else:
        _storage = NewsStorage()


@router.get("/articles")
async def get_articles(
    symbol: Optional[str] = None,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    """Get stored news articles."""
    storage = _get_storage()
    articles = storage.get_articles(symbol=symbol, hours=hours, limit=limit)
    return [a.to_dict() for a in articles]


@router.post("/fetch")
async def fetch_news(
    symbols: Optional[List[str]] = None,
    limit: int = Query(50, ge=1, le=200),
    hours: int = Query(24, ge=1, le=168),
    analyze: bool = True,
) -> Dict[str, Any]:
    """Fetch fresh news from Alpaca and optionally analyze sentiment."""
    fetcher = _get_fetcher()
    if fetcher is None:
        raise HTTPException(status_code=503, detail="News fetcher not initialized")

    articles = fetcher.fetch(symbols=symbols, limit=limit, hours_lookback=hours)
    if not articles:
        return {"fetched": 0, "new": 0, "analyzed": 0, "articles": []}

    storage = _get_storage()
    engine = _get_engine()

    new_count = 0
    analyzed_count = 0

    for article in articles:
        saved = storage.save_article(article)
        if saved:
            new_count += 1

        if analyze:
            results = engine.analyze(article)
            for result in results:
                storage.save_sentiment(result)
                analyzed_count += 1

    return {
        "fetched": len(articles),
        "new": new_count,
        "analyzed": analyzed_count,
        "articles": [a.to_dict() for a in articles[:20]],
    }


@router.get("/sentiment/{symbol}")
async def get_symbol_sentiment(
    symbol: str,
    hours: int = Query(24, ge=1, le=168),
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Get sentiment scores for a symbol."""
    storage = _get_storage()
    scores = storage.get_sentiment_for_symbol(symbol, hours=hours, model=model)
    summary = storage.get_symbol_sentiment_summary(symbol, hours=hours)

    return {
        "symbol": symbol,
        "scores": [s.to_dict() for s in scores],
        "summary": summary.to_dict() if summary else None,
    }


@router.get("/trending")
async def get_trending(
    hours: int = Query(24, ge=1, le=168),
    min_articles: int = Query(3, ge=1, le=50),
) -> List[Dict[str, Any]]:
    """Get trending symbols by news volume."""
    storage = _get_storage()
    trending = storage.get_trending_symbols(hours=hours, min_articles=min_articles)
    return [t.to_dict() for t in trending]


@router.get("/status")
async def news_status() -> Dict[str, Any]:
    """Check news module configuration status."""
    fetcher = _get_fetcher()
    engine = _get_engine()

    # Check Ollama availability
    ollama_available = False
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        ollama_available = resp.status_code == 200
    except Exception:
        pass

    return {
        "alpaca_configured": bool(fetcher and fetcher.api_key and fetcher.api_secret),
        "llm_provider": engine.llm_provider or None,
        "llm_configured": bool(
            engine.llm_provider
            and (engine.llm_api_key or engine.llm_provider.lower() == "ollama")
        ),
        "hybrid_mode": engine.hybrid_mode,
        "hybrid_threshold": engine.hybrid_threshold,
        "vader_available": engine._get_vader() is not None,
        "ollama_available": ollama_available,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/cleanup")
async def cleanup_news(days: int = Query(7, ge=1, le=90)) -> Dict[str, Any]:
    """Delete old news data."""
    storage = _get_storage()
    deleted = storage.cleanup_old(days=days)
    return {"deleted_rows": deleted, "days_threshold": days}
