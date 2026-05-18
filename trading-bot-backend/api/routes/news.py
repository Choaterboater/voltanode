"""News & sentiment API routes."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from news.fetcher import NewsFetcher
from news.models import NewsArticle
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


@router.post("/analyze")
async def analyze_headline(
    headline: str,
    summary: str = "",
    source: str = "manual",
    symbols: List[str] = Query(default_factory=list),
) -> Dict[str, Any]:
    """Analyze sentiment of a raw headline (no Alpaca required)."""
    syms = list(symbols) if symbols else []
    article = NewsArticle(
        id="manual-" + datetime.now(timezone.utc).isoformat(),
        headline=headline,
        summary=summary,
        source=source,
        symbols=syms,
    )
    engine = _get_engine()
    # If no symbols provided, analyze generically with a placeholder
    if syms:
        results = engine.analyze(article)
    else:
        results = engine.analyze(article, symbol="GENERAL")
    return {
        "headline": headline,
        "symbols": syms or ["GENERAL"],
        "results": [r.to_dict() for r in results],
    }


@router.post("/cleanup")
async def cleanup_news(days: int = Query(7, ge=1, le=90)) -> Dict[str, Any]:
    """Delete old news data."""
    storage = _get_storage()
    deleted = storage.cleanup_old(days=days)
    return {"deleted_rows": deleted, "days_threshold": days}


# ── News velocity + impact backtest (analysis layer) ────────────────────
#
# /news/velocity/{symbol} returns how fast sentiment is changing — the
# 1h / 6h / 24h windows + a derived velocity tag. Static avg compound
# tells you the news is positive; velocity tells you it's *getting more*
# positive — that's the swing-trade edge.
#
# /news/impact runs a calibration backtest over historical articles:
# scores → forward returns → bucketed stats. Answers "did our +0.5
# articles actually predict +1.2% over 3 days?" empirically.

@router.get("/velocity/{symbol}")
async def news_velocity(
    symbol: str,
    windows: Optional[str] = Query(default=None,
        description="Comma-separated hour windows, shortest first (default '1,6,24')"),
) -> Dict[str, Any]:
    """Sentiment velocity + acceleration for a single symbol."""
    from advisor.news_velocity import DEFAULT_WINDOWS_HOURS, compute_velocity
    if windows:
        try:
            win_tuple = tuple(sorted(int(w.strip()) for w in windows.split(",") if w.strip()))
            if not win_tuple or any(w <= 0 for w in win_tuple):
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400,
                detail="windows must be comma-separated positive integers, e.g. '1,6,24'")
    else:
        win_tuple = DEFAULT_WINDOWS_HOURS

    storage = _get_storage()
    snap = compute_velocity(symbol, storage=storage, windows=win_tuple)
    return snap.to_dict()


@router.get("/impact")
async def news_impact(
    symbols: str = Query(..., description="Comma-separated tickers, e.g. 'NVDA,AAPL,TSLA'"),
    lookback_days: int = Query(default=30, ge=7, le=365),
    horizons: str = Query(default="1,3,5",
        description="Comma-separated forward-return horizons in trading days"),
    min_articles_per_bucket: int = Query(default=3, ge=1, le=50),
) -> Dict[str, Any]:
    """Calibration backtest: do sentiment scores actually predict returns?

    Pulls every article in the lookback window, gets the underlying's
    daily OHLCV via yfinance, computes forward returns at each horizon,
    buckets by score band, and returns mean/median return + hit-rate per
    bucket. Crypto symbols are auto-skipped (no clean yfinance bars).
    """
    from advisor.news_impact import (
        DEFAULT_HORIZONS_DAYS,
        DEFAULT_SCORE_BUCKETS,
        compute_impact,
    )
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="at least one symbol required")
    try:
        horiz = tuple(sorted(int(h.strip()) for h in horizons.split(",") if h.strip()))
        if not horiz or any(h <= 0 or h > 60 for h in horiz):
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400,
            detail="horizons must be comma-separated positive integers (e.g. '1,3,5')")

    storage = _get_storage()
    # Run in a thread — yfinance fetches are blocking and we may hit
    # several symbols in one call.
    import asyncio
    report = await asyncio.to_thread(
        compute_impact,
        sym_list, lookback_days, horiz, DEFAULT_SCORE_BUCKETS,
        storage, min_articles_per_bucket,
    )
    return report.to_dict()
