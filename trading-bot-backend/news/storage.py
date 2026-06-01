"""SQLite storage for news articles and sentiment scores."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from news.models import NewsArticle, SentimentResult, SymbolSentiment

logger = logging.getLogger("volta.news")


class NewsStorage:
    """Persistent storage for news and sentiment in SQLite."""

    def __init__(self, db_path: str = "data/news.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,
                    headline TEXT NOT NULL,
                    summary TEXT,
                    source TEXT,
                    symbols TEXT,  -- JSON list
                    url TEXT,
                    author TEXT,
                    created_at TEXT,
                    content TEXT,
                    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_articles_symbols ON articles(symbols);
                CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at);

                CREATE TABLE IF NOT EXISTS sentiment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    compound_score REAL,
                    positive_score REAL,
                    negative_score REAL,
                    neutral_score REAL,
                    confidence REAL,
                    model TEXT,
                    impact_assessment TEXT,
                    key_themes TEXT,  -- JSON list
                    analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (article_id) REFERENCES articles(id)
                );
                CREATE INDEX IF NOT EXISTS idx_sentiment_symbol ON sentiment(symbol);
                CREATE INDEX IF NOT EXISTS idx_sentiment_analyzed ON sentiment(analyzed_at);
            """)
            conn.commit()

    def save_article(self, article: NewsArticle) -> bool:
        """Save an article. Returns False if already exists."""
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO articles
                    (id, headline, summary, source, symbols, url, author, created_at, content)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article.id,
                        article.headline,
                        article.summary,
                        article.source,
                        json.dumps(article.symbols),
                        article.url,
                        article.author,
                        article.created_at.isoformat(),
                        article.content,
                    ),
                )
                conn.commit()
                return conn.total_changes > 0
        except Exception as exc:
            logger.error(f"Failed to save article: {exc}")
            return False

    def save_sentiment(self, result: SentimentResult) -> None:
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO sentiment
                    (article_id, symbol, compound_score, positive_score, negative_score,
                     neutral_score, confidence, model, impact_assessment, key_themes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.article_id,
                        result.symbol,
                        result.compound_score,
                        result.positive_score,
                        result.negative_score,
                        result.neutral_score,
                        result.confidence,
                        result.model,
                        result.impact_assessment,
                        json.dumps(result.key_themes),
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.error(f"Failed to save sentiment: {exc}")

    def get_articles(
        self,
        symbol: Optional[str] = None,
        hours: int = 24,
        limit: int = 50,
    ) -> List[NewsArticle]:
        """Get recent articles, optionally filtered by symbol."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        with self._connection() as conn:
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM articles WHERE created_at > ? AND symbols LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (cutoff, f'%"{symbol}"%', limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM articles WHERE created_at > ? ORDER BY created_at DESC LIMIT ?",
                    (cutoff, limit),
                ).fetchall()

        return [self._row_to_article(r) for r in rows]

    def get_sentiment_for_symbol(
        self, symbol: str, hours: int = 24, model: Optional[str] = None
    ) -> List[SentimentResult]:
        """Get sentiment scores for a symbol."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        with self._connection() as conn:
            if model:
                rows = conn.execute(
                    "SELECT * FROM sentiment WHERE symbol = ? AND analyzed_at > ? AND model = ? ORDER BY analyzed_at DESC",
                    (symbol, cutoff, model),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sentiment WHERE symbol = ? AND analyzed_at > ? ORDER BY analyzed_at DESC",
                    (symbol, cutoff),
                ).fetchall()

        return [self._row_to_sentiment(r) for r in rows]

    def get_symbol_sentiment_summary(
        self, symbol: str, hours: int = 24
    ) -> Optional[SymbolSentiment]:
        """Get aggregated sentiment summary for a symbol."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as count,
                    AVG(compound_score) as avg_compound,
                    AVG(confidence) as avg_confidence
                FROM sentiment
                WHERE symbol = ? AND analyzed_at > ?
                """,
                (symbol, cutoff),
            ).fetchone()

        if not row or row["count"] == 0:
            return None

        avg_compound = row["avg_compound"] or 0.0
        if avg_compound > 0.15:
            label = "bullish"
        elif avg_compound < -0.15:
            label = "bearish"
        elif abs(avg_compound) <= 0.05:
            label = "neutral"
        else:
            label = "mixed"

        articles = self.get_articles(symbol=symbol, hours=hours, limit=5)

        return SymbolSentiment(
            symbol=symbol,
            article_count=row["count"],
            avg_compound=avg_compound,
            sentiment_label=label,
            latest_headlines=[a.headline for a in articles],
        )

    def get_trading_sentiment(
        self, hours: int = 6, min_articles: int = 1
    ) -> Dict[str, Dict[str, float]]:
        """Per-symbol aggregated sentiment for the live trading cache.

        Returns ``{SYMBOL: {"compound", "confidence", "count"}}`` over the last
        ``hours``, restricted to symbols with at least ``min_articles`` scored
        articles. Keys are upper-cased to match engine tick symbols. This is the
        bridge the news loop pushes into ``NewsSentimentStrategy`` — without it
        the registered news bots read an empty cache and HOLD forever.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        out: Dict[str, Dict[str, float]] = {}
        with self._connection() as conn:
            # Normalize both sides with datetime(): rows written via the
            # CURRENT_TIMESTAMP default are "YYYY-MM-DD HH:MM:SS" while cutoff
            # is ISO ("...T...+00:00"); a raw string compare mismatches the
            # separator/offset and silently drops fresh rows.
            rows = conn.execute(
                """
                SELECT symbol,
                       COUNT(*) AS count,
                       AVG(compound_score) AS avg_compound,
                       AVG(confidence) AS avg_confidence
                FROM sentiment
                WHERE datetime(analyzed_at) > datetime(?)
                GROUP BY symbol
                HAVING count >= ?
                """,
                (cutoff, min_articles),
            ).fetchall()
        for r in rows:
            sym = (r["symbol"] or "").strip().upper()
            if not sym:
                continue
            out[sym] = {
                "compound": float(r["avg_compound"] or 0.0),
                "confidence": float(r["avg_confidence"] or 0.0),
                "count": int(r["count"] or 0),
            }
        return out

    def get_trending_symbols(self, hours: int = 24, min_articles: int = 3) -> List[SymbolSentiment]:
        """Get symbols with significant news volume."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, COUNT(*) as count, AVG(compound_score) as avg_compound
                FROM sentiment
                WHERE analyzed_at > ?
                GROUP BY symbol
                HAVING count >= ?
                ORDER BY count DESC
                """,
                (cutoff, min_articles),
            ).fetchall()

        results = []
        for row in rows:
            avg = row["avg_compound"] or 0.0
            if avg > 0.15:
                label = "bullish"
            elif avg < -0.15:
                label = "bearish"
            elif abs(avg) <= 0.05:
                label = "neutral"
            else:
                label = "mixed"

            results.append(
                SymbolSentiment(
                    symbol=row["symbol"],
                    article_count=row["count"],
                    avg_compound=avg,
                    sentiment_label=label,
                    latest_headlines=[],
                    trending=True,
                )
            )
        return results

    def cleanup_old(self, days: int = 7) -> int:
        """Delete articles and sentiment older than N days. Returns rows deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connection() as conn:
            conn.execute("DELETE FROM sentiment WHERE analyzed_at < ?", (cutoff,))
            conn.execute("DELETE FROM articles WHERE created_at < ?", (cutoff,))
            conn.commit()
            return conn.total_changes

    @staticmethod
    def _row_to_article(row: sqlite3.Row) -> NewsArticle:
        symbols = json.loads(row["symbols"]) if row["symbols"] else []
        created = row["created_at"] or ""
        try:
            created_at = datetime.fromisoformat(created)
        except Exception:
            created_at = datetime.now(timezone.utc)
        return NewsArticle(
            id=row["id"],
            headline=row["headline"],
            summary=row["summary"] or "",
            source=row["source"] or "",
            symbols=symbols,
            url=row["url"] or "",
            author=row["author"] or "",
            created_at=created_at,
            content=row["content"] or "",
        )

    @staticmethod
    def _row_to_sentiment(row: sqlite3.Row) -> SentimentResult:
        themes = json.loads(row["key_themes"]) if row["key_themes"] else []
        analyzed = row["analyzed_at"] or ""
        try:
            analyzed_at = datetime.fromisoformat(analyzed)
        except Exception:
            analyzed_at = datetime.now(timezone.utc)
        return SentimentResult(
            article_id=row["article_id"],
            symbol=row["symbol"],
            compound_score=row["compound_score"] or 0.0,
            positive_score=row["positive_score"] or 0.0,
            negative_score=row["negative_score"] or 0.0,
            neutral_score=row["neutral_score"] or 0.0,
            confidence=row["confidence"] or 0.0,
            model=row["model"] or "",
            impact_assessment=row["impact_assessment"] or "",
            key_themes=themes,
            analyzed_at=analyzed_at,
        )
