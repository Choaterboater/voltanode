"""AI Advisor API routes."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from advisor.analyzer import SymbolAnalyzer
from advisor.models import AnalysisResult, IndicatorReading, PriceTarget
from advisor.pairlist import apply_chain as apply_pairlist_chain, default_chain as default_pairlist_chain
from advisor.fundamentals import fetch_stock_fundamentals
from advisor.long_term import LongTermScore, rank_long_term, score_long_term
from advisor.research import build_research_report
from advisor.scanner import ScannerScore, rank_scores, score_symbol
from advisor.squeeze import (
    SqueezeScore,
    passes_structural_filters,
    score_squeeze,
)
from advisor.universes import movers as fetch_movers, sp500_universe
from data.finra_short_volume import (
    ShortVolumeSnapshot,
    latest_short_volume_snapshot,
)
from data.fundamentals import fetch_fundamentals
from data.sec_edgar import Filing as SecFiling, fetch_recent_filings
from data.cache import DataCache
from data.fetcher import MarketData
from bot.config import BotConfig
from api.scan_cache import cache_get, cache_set, make_key

logger = logging.getLogger("volta.advisor")

router = APIRouter()


# ── Request / Response Models ──

class AnalyzeRequest(BaseModel):
    """POST request body for symbol analysis."""
    symbol: str
    asset_type: str = "crypto"  # "crypto" or "stock"
    lookback_days: int = 90
    advanced: bool = False  # Force OpenRouter (cloud LLM) instead of local Ollama


class IndicatorReadingModel(BaseModel):
    """Indicator reading response item."""
    name: str
    value: float
    signal: str
    strength: float
    description: str


class PriceTargetModel(BaseModel):
    """Price target response item."""
    label: str
    price: float
    probability: float
    rationale: str


class LLMCommentaryModel(BaseModel):
    """Optional LLM-generated commentary blended with the deterministic verdict."""
    rationale: str
    agreement: str  # "agrees" | "disagrees" | "mixed"
    adjusted_confidence: float  # 0-100
    key_factors: List[str] = []
    news_impact: str = "none"  # "high" | "medium" | "low" | "none"
    article_count: int = 0
    model: str = ""
    alternative_verdict: str = ""  # "" | "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL"
    risk_factors: List[str] = []
    catalysts: List[str] = []


class AnalysisResponse(BaseModel):
    """Full analysis response."""
    symbol: str
    display_name: str = ""
    exchange: str = ""
    sector: str = ""
    current_price: float
    asset_type: str
    verdict: str
    confidence: float
    summary: str
    indicators: List[IndicatorReadingModel]
    price_targets: List[PriceTargetModel]
    risk_level: str
    suggested_position_size: float
    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    take_profit: float
    time_horizon: str
    chart_data: dict = {}
    llm_commentary: Optional[LLMCommentaryModel] = None


# ── Helpers ──

def _analysis_to_response(result: AnalysisResult) -> AnalysisResponse:
    """Convert internal AnalysisResult to API response model."""
    commentary = None
    if result.llm_commentary is not None:
        c = result.llm_commentary
        commentary = LLMCommentaryModel(
            rationale=c.rationale,
            agreement=c.agreement,
            adjusted_confidence=c.adjusted_confidence,
            key_factors=c.key_factors,
            news_impact=c.news_impact,
            article_count=c.article_count,
            model=c.model,
            alternative_verdict=c.alternative_verdict,
            risk_factors=getattr(c, "risk_factors", []) or [],
            catalysts=getattr(c, "catalysts", []) or [],
        )

    return AnalysisResponse(
        symbol=result.symbol,
        display_name=getattr(result, "display_name", "") or "",
        exchange=getattr(result, "exchange", "") or "",
        sector=getattr(result, "sector", "") or "",
        current_price=result.current_price,
        asset_type=result.asset_type,
        verdict=result.verdict,
        confidence=result.confidence,
        summary=result.summary,
        indicators=[
            IndicatorReadingModel(
                name=r.name,
                value=r.value,
                signal=r.signal,
                strength=r.strength,
                description=r.description,
            )
            for r in result.indicators
        ],
        price_targets=[
            PriceTargetModel(
                label=t.label,
                price=t.price,
                probability=t.probability,
                rationale=t.rationale,
            )
            for t in result.price_targets
        ],
        risk_level=result.risk_level,
        suggested_position_size=result.suggested_position_size,
        entry_zone_low=result.entry_zone[0],
        entry_zone_high=result.entry_zone[1],
        stop_loss=result.stop_loss,
        take_profit=result.take_profit,
        time_horizon=result.time_horizon,
        chart_data=result.chart_data,
        llm_commentary=commentary,
    )


# ── Endpoints ──

@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_symbol(request: AnalyzeRequest) -> AnalysisResponse:
    """Analyse a symbol and return a professional trading recommendation.

    **Crypto**: use CoinGecko ID, e.g. ``bitcoin``, ``ethereum``.
    **Stocks**: use Yahoo ticker, e.g. ``AAPL``, ``TSLA``.
    """
    cache = DataCache(cache_dir="./data/cache")
    market_data = MarketData(cache=cache, config=BotConfig())
    analyzer = SymbolAnalyzer(market_data=market_data)
    try:
        result = await analyzer.analyze(
            symbol=request.symbol,
            asset_type=request.asset_type,
            lookback_days=request.lookback_days,
            advanced=request.advanced,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _analysis_to_response(result)


@router.get("/analyze")
async def analyze_symbol_get(
    symbol: str = Query(..., description="Trading symbol (e.g. bitcoin or AAPL)"),
    asset_type: str = Query(default="crypto", description="'crypto' or 'stock'"),
    lookback_days: int = Query(default=90, ge=7, le=730, description="Days of history"),
    advanced: bool = Query(default=False, description="Use OpenRouter cloud LLM"),
) -> AnalysisResponse:
    """GET version of /analyze for easy browser testing."""
    cache = DataCache(cache_dir="./data/cache")
    market_data = MarketData(cache=cache, config=BotConfig())
    analyzer = SymbolAnalyzer(market_data=market_data)
    try:
        result = await analyzer.analyze(
            symbol=symbol,
            asset_type=asset_type,
            lookback_days=lookback_days,
            advanced=advanced,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _analysis_to_response(result)


# ── Multi-dimension research report (Kavout/InvestGPT-style) ──

@router.get("/research")
async def research_symbol(
    symbol: str = Query(..., description="Trading symbol"),
    asset_type: str = Query(default="stock"),
    lookback_days: int = Query(default=365, ge=7, le=730),
    advanced: bool = Query(default=False, description="Use OpenRouter for richer narrative"),
) -> Dict[str, Any]:
    """Run a Kavout-style multi-dimensional research report.

    Combines the existing TA pipeline with yfinance fundamentals and the
    aggregated news-sentiment summary. Returns weighted Fundamental /
    Technical / Sentiment scores plus an LLM-generated narrative
    (Investment Thesis, Bull/Bear, Action Plan, Bottom Line).
    """
    cache = DataCache(cache_dir="./data/cache")
    market_data = MarketData(cache=cache, config=BotConfig())
    analyzer = SymbolAnalyzer(market_data=market_data)
    try:
        ta = await analyzer.analyze(
            symbol=symbol,
            asset_type=asset_type,
            lookback_days=lookback_days,
            advanced=False,  # we run our own LLM here, skip the second-opinion call
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    import asyncio as _asyncio
    report = await _asyncio.to_thread(build_research_report, ta, advanced, lookback_days)
    return report.to_dict()


# ── Symbol lookup (search by name OR ticker) ──

# Hardcoded crypto map (CoinGecko IDs are not searchable via yfinance) — covers
# the common ones; everything else still works as a direct ticker.
_CRYPTO_LOOKUP = {
    "bitcoin": ("bitcoin", "Bitcoin"),
    "btc": ("bitcoin", "Bitcoin"),
    "ethereum": ("ethereum", "Ethereum"),
    "eth": ("ethereum", "Ethereum"),
    "solana": ("solana", "Solana"),
    "sol": ("solana", "Solana"),
    "avalanche": ("avalanche-2", "Avalanche"),
    "avax": ("avalanche-2", "Avalanche"),
    "chainlink": ("chainlink", "Chainlink"),
    "link": ("chainlink", "Chainlink"),
    "polkadot": ("polkadot", "Polkadot"),
    "dot": ("polkadot", "Polkadot"),
    "cardano": ("cardano", "Cardano"),
    "ada": ("cardano", "Cardano"),
    "ripple": ("ripple", "XRP"),
    "xrp": ("ripple", "XRP"),
    "dogecoin": ("dogecoin", "Dogecoin"),
    "doge": ("dogecoin", "Dogecoin"),
    "shiba": ("shiba-inu", "Shiba Inu"),
    "shib": ("shiba-inu", "Shiba Inu"),
    "matic": ("matic-network", "Polygon"),
    "polygon": ("matic-network", "Polygon"),
}


@router.get("/lookup")
async def symbol_lookup(
    q: str = Query(..., min_length=1, description="Free-text query: ticker or company name"),
    limit: int = Query(default=8, ge=1, le=20),
) -> Dict[str, Any]:
    """Resolve a free-text query to a list of (symbol, name, asset_type) hits.

    Searches yfinance for stock matches and a curated crypto list. Returned
    list is ordered by best match first.
    """
    q_lower = q.strip().lower()
    if not q_lower:
        return {"query": q, "hits": []}

    hits: List[Dict[str, Any]] = []

    # Crypto direct match first (cheap, no network)
    for key, (cg_id, name) in _CRYPTO_LOOKUP.items():
        if key.startswith(q_lower) or q_lower in key:
            hits.append({
                "symbol": cg_id,
                "name": name,
                "asset_type": "crypto",
                "exchange": "CoinGecko",
            })
        if len(hits) >= limit:
            break

    # yfinance search for stocks — tolerant of partial names ("apple", "amazon")
    try:
        import yfinance as yf
        import asyncio as _asyncio
        def _search():
            try:
                s = yf.Search(q, max_results=limit)
                return list(s.quotes or [])
            except Exception:
                return []
        quotes = await _asyncio.to_thread(_search)
        for quo in quotes:
            sym = (quo.get("symbol") or "").strip().upper()
            if not sym:
                continue
            name = quo.get("longname") or quo.get("shortname") or sym
            qtype = (quo.get("quoteType") or "").upper()
            # Skip funds / options / futures — keep equity + ETFs only for cleanliness.
            if qtype not in ("EQUITY", "ETF", ""):
                continue
            hits.append({
                "symbol": sym,
                "name": name,
                "asset_type": "stock",
                "exchange": quo.get("exchange") or "",
            })
            if len(hits) >= limit:
                break
    except Exception as exc:
        # yfinance not available or rate-limited — return whatever we have
        pass

    # Dedup while preserving order
    seen = set()
    unique: List[Dict[str, Any]] = []
    for h in hits:
        key = (h["asset_type"], h["symbol"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)

    return {"query": q, "hits": unique[:limit]}


# ── Market Scanner ──────────────────────────────────────────────────────

# Hardcoded fallback / default stock universe for the scanner. Equity sleeve plus
# core liquid ETFs — broad enough that the scanner has signal even when an
# operator hasn't registered any stock strategies yet. Easy to grow over time.
_DEFAULT_STOCK_UNIVERSE: List[str] = [
    # Mega-cap tech (already covered by active bots — kept so the scanner can rank them)
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "AMD",
    # Sector diversifiers
    "JPM", "BAC", "WMT", "COST", "HD", "JNJ", "UNH", "XOM", "CAT",
    # Adjacent tech / growth
    "CRM", "ORCL", "ADBE", "NFLX", "DIS", "AVGO", "PLTR",
    # Broad-market ETFs
    "SPY", "QQQ", "IWM",
]

# Crypto fallback list (used if CoinGecko top-N fetch fails). Keep aligned with
# data/fetcher.py's _CG_TICKER_TO_ID — anything outside that map can't be priced.
_DEFAULT_CRYPTO_UNIVERSE: List[str] = [
    "BTC", "ETH", "SOL", "AVAX", "LINK", "DOGE", "SHIB", "LTC", "BCH",
    "UNI", "AAVE", "MATIC", "MKR", "SUSHI", "YFI", "ADA", "XRP", "DOT",
    "BNB", "TRX",
]


def _load_active_registered() -> List[Dict[str, Any]]:
    """Read active strategies from registered_strategies.json. Empty list on error."""
    path = Path("data") / "registered_strategies.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        logger.warning("scanner: failed reading %s: %s", path, exc)
        return []
    return [e for e in data if e.get("is_active")]


def _build_coverage_map() -> Dict[str, List[str]]:
    """Map symbol -> [strategy_id, ...] from active strategies in registered_strategies.json.

    Symbols are upper-cased so the lookup is case-insensitive. Includes ALL asset
    classes — used for tagging scanner results with their covering strategies.
    """
    coverage: Dict[str, List[str]] = {}
    for entry in _load_active_registered():
        cfg = entry.get("config") or {}
        syms = list(cfg.get("symbols") or [])
        if not syms and cfg.get("symbol"):
            syms = [cfg["symbol"]]
        sid = entry.get("strategy_id", "")
        for sym in syms:
            if not isinstance(sym, str):
                continue
            coverage.setdefault(sym.upper(), []).append(sid)
    return coverage


def _registered_symbols_for_class(asset_class: str) -> List[str]:
    """Distinct active-strategy symbols whose ``config.asset_class`` matches.

    Strategies that don't declare ``asset_class`` are skipped (avoids the crypto/
    stock leak when the universe-builder merges these into the scanner pool).
    """
    out: List[str] = []
    seen: set = set()
    for entry in _load_active_registered():
        cfg = entry.get("config") or {}
        if str(cfg.get("asset_class", "")).lower() != asset_class.lower():
            continue
        syms = list(cfg.get("symbols") or [])
        if not syms and cfg.get("symbol"):
            syms = [cfg["symbol"]]
        for sym in syms:
            if not isinstance(sym, str):
                continue
            up = sym.upper()
            if up in seen:
                continue
            seen.add(up)
            out.append(up)
    return out


async def _scanner_universe(
    asset_class: str,
    market_data: MarketData,
    limit_universe: int,
    explicit_symbols: Optional[str],
    include_sp500: bool = False,
    include_movers: bool = False,
) -> List[str]:
    """Build the candidate symbol list for a scanner run.

    Source-merging order (each step deduped, preserving first occurrence):
      1. ``explicit_symbols`` (if provided, short-circuits everything else)
      2. Curated default for the asset class
      3. Stock-class registered active strategies (stocks only)
      4. ``movers()`` — Yahoo day_gainers + most_actives (stocks only, when
         ``include_movers``). This is what catches RXT-shape outliers.
      5. ``sp500_universe()`` — full S&P 500 (stocks only, when ``include_sp500``)

    The result is truncated to ``limit_universe`` so the scanner doesn't
    accidentally fan out to 500 OHLCV fetches when the caller didn't ask for it.
    """
    if explicit_symbols:
        return [s.strip().upper() for s in explicit_symbols.split(",") if s.strip()]

    if asset_class == "crypto":
        try:
            top_coins = await market_data.get_top_cryptos(limit=limit_universe)
            symbols = [
                (c.get("symbol") or "").upper()
                for c in top_coins
                if c.get("symbol")
            ]
            symbols = [s for s in symbols if s]
            if symbols:
                return symbols
        except Exception as exc:
            logger.warning("scanner: get_top_cryptos failed (%s); using fallback list", exc)
        return _DEFAULT_CRYPTO_UNIVERSE[:limit_universe]

    if asset_class == "stock":
        # 1. Curated default + 2. registered active stock strategies.
        registered = _registered_symbols_for_class("stock")
        merged: List[str] = list(dict.fromkeys(_DEFAULT_STOCK_UNIVERSE + registered))

        # 3. Movers feed — fires by default so you don't have to pre-know which
        #    tickers are about to rip. Each Yahoo fetch is throttle-safe and
        #    cached for 5 minutes inside ``advisor.universes``.
        if include_movers:
            try:
                m = await fetch_movers(limit_per_feed=25)
                for sym in m:
                    if sym not in merged:
                        merged.append(sym)
            except Exception as exc:
                logger.warning("scanner: movers fetch failed (%s)", exc)

        # 4. Full S&P 500 — opt-in. Order matters: movers come first so they're
        #    not pushed past ``limit_universe`` when SP500 is also requested.
        if include_sp500:
            try:
                sp = await sp500_universe()
                for sym in sp:
                    if sym not in merged:
                        merged.append(sym)
            except Exception as exc:
                logger.warning("scanner: sp500 fetch failed (%s)", exc)

        return merged[:limit_universe]

    raise HTTPException(
        status_code=400,
        detail=f"asset_class must be 'crypto' or 'stock' (got {asset_class!r})",
    )


async def _fetch_score_one(
    symbol: str,
    asset_class: str,
    market_data: MarketData,
    sem: asyncio.Semaphore,
    crypto_days: int,
    stock_period: str,
    pairlist_filters: Optional[List[object]] = None,
) -> ScannerScore:
    """Fetch OHLCV for one symbol and score it. Errors are captured into the score.

    If ``pairlist_filters`` is provided, each filter's ``check(symbol, df)`` is
    called after OHLCV fetch and before scoring. The first failing filter
    short-circuits and returns a sentinel score with ``error="filtered:..."``
    so the caller can see exactly which gate dropped the symbol and why.
    """
    async with sem:
        try:
            if asset_class == "crypto":
                df = await market_data.get_crypto_ohlcv(
                    symbol, vs_currency="usd", days=crypto_days, interval="daily"
                )
            else:
                df = await asyncio.to_thread(
                    market_data.get_stock_ohlcv, symbol, stock_period, "1d"
                )
            if df is None or df.empty:
                return ScannerScore(
                    symbol=symbol, score=0.0, direction="neutral",
                    current_price=0.0, bars=0, error="empty_dataframe",
                )
            # Ensure lower-case columns (indicators expect lower-case)
            df = df.copy()
            df.columns = [str(c).lower() for c in df.columns]
            # Volume column may be missing on some sources — synth a zero series
            if "volume" not in df.columns:
                df["volume"] = 0.0

            # Pairlist filters — drop illiquid / too-young / wide-spread /
            # dead-flat / pumping symbols BEFORE scoring. Tagged error so
            # the scanner response surfaces the reason in `failed`.
            if pairlist_filters:
                for f in pairlist_filters:
                    verdict = f.check(symbol, df)
                    if not verdict.passed:
                        return ScannerScore(
                            symbol=symbol, score=0.0, direction="neutral",
                            current_price=float(df["close"].iloc[-1]) if "close" in df.columns else 0.0,
                            bars=len(df),
                            error=f"filtered:{type(f).__name__}:{verdict.reason}",
                        )

            return score_symbol(symbol, df)
        except Exception as exc:
            logger.warning("scanner: %s fetch/score failed: %s", symbol, exc)
            return ScannerScore(
                symbol=symbol, score=0.0, direction="neutral",
                current_price=0.0, bars=0, error=str(exc)[:200],
            )


@router.get("/scanner")
async def market_scanner(
    asset_class: str = Query(default="crypto", description="'crypto' or 'stock'"),
    top: int = Query(default=20, ge=1, le=200, description="Max ranked results to return"),
    min_score: float = Query(default=0.0, ge=0.0, le=100.0, description="Drop entries below this composite score"),
    limit_universe: int = Query(default=30, ge=5, le=600, description="Cap universe size before scoring"),
    symbols: Optional[str] = Query(default=None, description="Comma-separated explicit symbol list (overrides auto-universe)"),
    direction: Optional[str] = Query(default=None, description="Filter to 'long' or 'short' only"),
    concurrency: int = Query(default=10, ge=1, le=20, description="Parallel OHLCV fetches"),
    crypto_days: int = Query(default=60, ge=30, le=365, description="Days of crypto OHLCV history"),
    stock_period: str = Query(default="3mo", description="yfinance period string for stocks"),
    include_sp500: bool = Query(default=False, description="(stock only) Merge full S&P 500 list into the universe"),
    include_movers: bool = Query(default=True, description="(stock only) Merge Yahoo day_gainers + most_actives so unknown movers (e.g. RXT) get scored"),
    fast: bool = Query(default=False, description="Fast mode: cap universe at 25, higher concurrency, shorter crypto history"),
    nocache: bool = Query(default=False, description="Bypass the 5-minute scan response cache"),
    # ── Pairlist filters (freqtrade-style quality gates) ───────────────────
    enable_pairlist: bool = Query(default=True, description="Apply quality gates (volume/age/price/spread/volatility/blacklist) before scoring"),
    min_quote_volume_usd: float = Query(default=1_000_000.0, ge=0, description="Min 24h dollar-volume to keep a symbol (0 = disabled)"),
    min_bars: int = Query(default=30, ge=0, le=500, description="Min OHLCV bars of history required"),
    pl_min_price: Optional[float] = Query(default=None, ge=0, description="Minimum current price floor. Defaults: 0 for crypto (don't drop DOGE/SHIB/TRX), $1 for stock (drop penny stocks). Pass an explicit value to override."),
    pl_max_price: float = Query(default=0.0, ge=0, description="Maximum current price (0 = no ceiling)"),
    max_spread_pct: float = Query(default=0.08, ge=0, le=1.0, description="Max avg (high-low)/close as bid-ask proxy"),
    min_atr_pct: float = Query(default=0.005, ge=0, le=1.0, description="Min ATR/price — drop dead-flat names"),
    max_atr_pct: float = Query(default=0.15, ge=0, le=1.0, description="Max ATR/price — drop pump rockets"),
    blacklist: Optional[str] = Query(default=None, description="Comma-separated symbols to exclude (matches base form too — 'ADA' excludes ADAUSD)"),
) -> Dict[str, Any]:
    """Rank tradable assets by composite signal strength (RSI extreme + breakout + relative volume).

    Manual-review tool: surfaces opportunities the active bots may not be covering.
    Each result is tagged with whether one of your active strategies is already trading it.

    **Crypto universe:** CoinGecko top-N by market cap (falls back to a curated list if the API errors).

    **Stock universe:** A curated S&P-leader + ETF list, merged with whatever stock symbols are
    currently in active registered strategies. With ``include_movers=true`` (default) we also
    pull Yahoo's day_gainers + most_actives feeds so out-of-watchlist names that are *currently*
    moving still get ranked. With ``include_sp500=true`` we add the full ~500 S&P constituents
    (raises ``limit_universe`` if you want them all scored).

    Pass ``symbols=BTC,ETH,DOGE`` to override the auto-universe with a specific list.

    Pass ``fast=true`` for a lighter pass (smaller universe, higher concurrency).
    Repeat identical queries within 5 minutes are served from an in-memory cache
    unless ``nocache=true``.
    """
    if fast:
        limit_universe = min(limit_universe, 25)
        crypto_days = min(crypto_days, 30)
        concurrency = max(concurrency, 12)

    effective_pl_min_price = (
        pl_min_price if pl_min_price is not None
        else (0.0 if asset_class == "crypto" else 1.0)
    )

    cache_key = make_key(
        "scanner",
        asset_class=asset_class,
        top=top,
        min_score=min_score,
        limit_universe=limit_universe,
        symbols=symbols,
        direction=direction,
        concurrency=concurrency,
        crypto_days=crypto_days,
        stock_period=stock_period,
        include_sp500=include_sp500,
        include_movers=include_movers,
        fast=fast,
        enable_pairlist=enable_pairlist,
        min_quote_volume_usd=min_quote_volume_usd,
        min_bars=min_bars,
        pl_min_price=effective_pl_min_price,
        pl_max_price=pl_max_price,
        max_spread_pct=max_spread_pct,
        min_atr_pct=min_atr_pct,
        max_atr_pct=max_atr_pct,
        blacklist=blacklist,
    )
    cached = cache_get(cache_key, nocache=nocache)
    if cached is not None:
        return cached

    cache = DataCache(cache_dir="./data/cache")
    market_data = MarketData(cache=cache, config=BotConfig())

    # Asset-class-aware default for the price floor — $1 sensibly drops US
    # penny stocks but wrongly nukes liquid sub-$1 crypto (DOGE, SHIB, TRX).
    pl_min_price = effective_pl_min_price

    universe = await _scanner_universe(
        asset_class,
        market_data,
        limit_universe,
        symbols,
        include_sp500=include_sp500,
        include_movers=include_movers,
    )
    if not universe:
        return {
            "asset_class": asset_class,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "universe_size": 0,
            "scored": 0,
            "failed_count": 0,
            "results": [],
            "failed": [],
        }

    sem = asyncio.Semaphore(concurrency)
    started = datetime.now(timezone.utc)

    # Build the pairlist filter chain once, share across the gather()
    pairlist_filters: Optional[List[object]] = None
    if enable_pairlist:
        blacklist_syms = [s.strip() for s in (blacklist or "").split(",") if s.strip()] if blacklist else []
        pairlist_filters = default_pairlist_chain(
            blacklist=blacklist_syms,
            min_quote_volume_usd=min_quote_volume_usd,
            min_price=pl_min_price,
            max_price=(pl_max_price if pl_max_price > 0 else None),
            min_bars=min_bars,
            max_spread_pct=max_spread_pct,
            min_atr_pct=min_atr_pct,
            max_atr_pct=max_atr_pct,
        )

    scores = await asyncio.gather(
        *[
            _fetch_score_one(
                sym, asset_class, market_data, sem, crypto_days, stock_period,
                pairlist_filters=pairlist_filters,
            )
            for sym in universe
        ]
    )
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    valid = rank_scores(scores, top=None, min_score=min_score)
    if direction in ("long", "short"):
        valid = [s for s in valid if s.direction == direction]

    coverage = _build_coverage_map()
    payload_results: List[Dict[str, Any]] = []
    for s in valid[:top]:
        d = s.to_dict()
        d["covered_by_active_bot"] = s.symbol in coverage
        d["active_strategies"] = coverage.get(s.symbol, [])
        payload_results.append(d)

    failed = [
        {"symbol": s.symbol, "error": s.error}
        for s in scores
        if s.error is not None
    ]

    # Break out the "filtered" rejects so the operator can see *why* the
    # pairlist gates dropped names, separately from real fetch failures.
    filtered = [
        {"symbol": s.symbol, "reason": s.error.removeprefix("filtered:")}
        for s in scores
        if s.error and s.error.startswith("filtered:")
    ]
    fetch_failed = [
        {"symbol": s.symbol, "error": s.error}
        for s in scores
        if s.error and not s.error.startswith("filtered:")
    ]

    payload = {
        "asset_class": asset_class,
        "scanned_at": started.isoformat(),
        "elapsed_ms": elapsed_ms,
        "universe_size": len(universe),
        "scored": len([s for s in scores if s.error is None]),
        "filtered_count": len(filtered),
        "failed_count": len(fetch_failed),
        "filters": {
            "min_score": min_score,
            "direction": direction,
            "top": top,
            "pairlist_enabled": enable_pairlist,
            "fast": fast,
        },
        "results": payload_results,
        "filtered": filtered[:20],  # which symbols the pairlist gates dropped
        "failed": fetch_failed[:20],
    }
    cache_set(cache_key, payload)
    return payload


# ── Evaluator-chain scanner (Phase 5 pattern) ──────────────────────────
#
# Same three signals as /advisor/scanner (RSI extreme, breakout proximity,
# relative volume), but composed via the OctoBot-style EvaluatorChain so
# each evaluator's verdict is visible per-symbol and weights are tunable
# without editing aggregation logic. Adding a new signal (e.g. orderbook
# imbalance, social sentiment, on-chain flow) is now "register an Evaluator
# subclass + give it a weight" — zero changes to this endpoint.

async def _fetch_chain_one(
    symbol: str,
    asset_class: str,
    market_data: MarketData,
    sem: asyncio.Semaphore,
    crypto_days: int,
    stock_period: str,
    chain,  # EvaluatorChain — typing avoided to dodge import-cycle on startup
):
    """Fetch OHLCV and run the chain. Mirrors _fetch_score_one's shape."""
    from advisor.evaluators.base import ChainResult, DIR_NEUTRAL, EvaluatorContext
    async with sem:
        try:
            if asset_class == "crypto":
                df = await market_data.get_crypto_ohlcv(
                    symbol, vs_currency="usd", days=crypto_days, interval="daily"
                )
            else:
                df = await asyncio.to_thread(
                    market_data.get_stock_ohlcv, symbol, stock_period, "1d"
                )
            if df is None or df.empty:
                return ChainResult(
                    symbol=symbol, composite_score=0.0, direction=DIR_NEUTRAL,
                    weights=chain.weights, error="empty_dataframe",
                )
            df = df.copy()
            df.columns = [str(c).lower() for c in df.columns]
            if "volume" not in df.columns:
                df["volume"] = 0.0
            ctx = EvaluatorContext(symbol=symbol, asset_class=asset_class)
            return chain.evaluate(symbol, df, ctx)
        except Exception as exc:
            logger.warning("chain: %s fetch/eval failed: %s", symbol, exc)
            return ChainResult(
                symbol=symbol, composite_score=0.0, direction=DIR_NEUTRAL,
                weights=chain.weights, error=str(exc)[:200],
            )


@router.get("/scanner/chain")
async def market_scanner_chain(
    asset_class: str = Query(default="crypto", description="'crypto' or 'stock'"),
    top: int = Query(default=20, ge=1, le=200),
    min_score: float = Query(default=0.0, ge=0.0, le=100.0),
    limit_universe: int = Query(default=50, ge=5, le=600),
    symbols: Optional[str] = Query(default=None,
        description="Comma-separated explicit symbol list (overrides auto-universe)"),
    direction: Optional[str] = Query(default=None, description="'long' or 'short'"),
    concurrency: int = Query(default=5, ge=1, le=20),
    crypto_days: int = Query(default=60, ge=30, le=365),
    stock_period: str = Query(default="3mo"),
    include_movers: bool = Query(default=True),
    rsi_period: int = Query(default=14, ge=5, le=50),
    breakout_lookback: int = Query(default=20, ge=5, le=100),
    volume_lookback: int = Query(default=20, ge=5, le=100),
    weight_rsi: float = Query(default=0.40, ge=0.0, le=1.0),
    weight_breakout: float = Query(default=0.30, ge=0.0, le=1.0),
    weight_rel_volume: float = Query(default=0.30, ge=0.0, le=1.0),
    weight_news_sentiment: float = Query(default=0.20, ge=0.0, le=1.0,
        description="News evaluator weight. Set 0 to disable news voting."),
    news_hours: int = Query(default=24, ge=1, le=168,
        description="Lookback window for news aggregation."),
) -> Dict[str, Any]:
    """Composite scanner via the evaluator-chain pattern.

    Returns per-symbol verdicts from each evaluator alongside the aggregated
    composite score and direction. Identical signal math to /advisor/scanner
    (same RSI/breakout/volume math reused via wrappers), but the wire format
    surfaces each evaluator's opinion separately so the operator can see
    *why* a symbol scored where it did, and tune weights without code changes.

    Weight params don't need to sum to 1.0 — the chain normalizes internally.
    """
    from advisor.evaluators import build_default_chain

    cache = DataCache(cache_dir="./data/cache")
    market_data = MarketData(cache=cache, config=BotConfig())

    universe = await _scanner_universe(
        asset_class, market_data, limit_universe, symbols,
        include_sp500=False, include_movers=include_movers,
    )
    if not universe:
        return {
            "asset_class": asset_class,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "universe_size": 0, "scored": 0, "results": [],
        }

    chain = build_default_chain(
        weights={
            "rsi": weight_rsi,
            "breakout": weight_breakout,
            "rel_volume": weight_rel_volume,
            "news_sentiment": weight_news_sentiment,
        },
        rsi_period=rsi_period,
        breakout_lookback=breakout_lookback,
        volume_lookback=volume_lookback,
        include_news=(weight_news_sentiment > 0),
        news_hours=news_hours,
    )

    sem = asyncio.Semaphore(concurrency)
    started = datetime.now(timezone.utc)
    results = await asyncio.gather(
        *[
            _fetch_chain_one(
                sym, asset_class, market_data, sem, crypto_days, stock_period, chain,
            )
            for sym in universe
        ]
    )
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    valid = [r for r in results if r.error is None and r.composite_score >= min_score]
    valid.sort(key=lambda r: r.composite_score, reverse=True)
    if direction in ("long", "short"):
        valid = [r for r in valid if r.direction == direction]

    return {
        "asset_class": asset_class,
        "scanned_at": started.isoformat(),
        "elapsed_ms": elapsed_ms,
        "universe_size": len(universe),
        "scored": len(valid),
        "weights": chain.weights,
        "evaluators": [ev.name for ev, _ in chain._items],
        "results": [r.to_dict() for r in valid[:top]],
        "failed": [
            {"symbol": r.symbol, "error": r.error}
            for r in results if r.error is not None
        ][:20],
    }


# ── Long-term (year+) holding screener ─────────────────────────────────
#
# Different beast from /scanner (swing setups) and /squeeze (catalyst plays):
# this ranks names by long-horizon quality — fundamentals (50%) + sustained
# trend (30%) + low volatility (20%). Reuses fetch_stock_fundamentals and
# the same OHLCV path as /scanner; the universe defaults to S&P 500 because
# yfinance fundamentals are the load-bearing signal here. Crypto names
# score with neutral fundamentals (50/100 per score_fundamentals) but the
# trend + vol components still differentiate within asset class.

async def _fetch_long_term_one(
    symbol: str,
    asset_class: str,
    market_data: MarketData,
    sem: asyncio.Semaphore,
    stock_period: str = "2y",
    crypto_days: int = 730,
) -> LongTermScore:
    """Fetch fundamentals + OHLCV in parallel, score one symbol."""
    async with sem:
        try:
            # Fundamentals run in a thread (yfinance is blocking).
            if asset_class == "stock":
                snap_task = asyncio.to_thread(fetch_stock_fundamentals, symbol)
                ohlcv_task = asyncio.to_thread(
                    market_data.get_stock_ohlcv, symbol, stock_period, "1d"
                )
            else:
                from advisor.fundamentals import fetch_crypto_fundamentals
                snap_task = asyncio.to_thread(fetch_crypto_fundamentals, symbol)
                ohlcv_task = market_data.get_crypto_ohlcv(
                    symbol, vs_currency="usd", days=crypto_days, interval="daily"
                )
            snap, df = await asyncio.gather(snap_task, ohlcv_task)

            if df is None or df.empty:
                return LongTermScore(
                    symbol=symbol, score=0.0, current_price=0.0, bars=0,
                    error="empty_ohlcv",
                )
            df = df.copy()
            df.columns = [str(c).lower() for c in df.columns]
            return score_long_term(symbol, df, snap)
        except Exception as exc:
            logger.warning("long-term: %s fetch/score failed: %s", symbol, exc)
            return LongTermScore(
                symbol=symbol, score=0.0, current_price=0.0, bars=0,
                error=str(exc)[:200],
            )


@router.get("/long-term")
async def long_term_screener(
    asset_class: str = Query(default="stock", description="'stock' or 'crypto'"),
    top: int = Query(default=25, ge=1, le=200),
    min_score: float = Query(default=0.0, ge=0.0, le=100.0),
    limit_universe: int = Query(default=50, ge=5, le=600),
    symbols: Optional[str] = Query(default=None,
        description="Comma-separated explicit symbol list (overrides default universe)"),
    concurrency: int = Query(default=6, ge=1, le=12,
        description="Parallel fetches. yfinance + CoinGecko both rate-limit."),
    stock_period: str = Query(default="2y",
        description="yfinance period for stocks — need >= 1y for the 200dma + 1y-return signal"),
    crypto_days: int = Query(default=730, ge=365, le=1095),
    weight_fundamentals: float = Query(default=0.50, ge=0.0, le=1.0),
    weight_trend: float = Query(default=0.30, ge=0.0, le=1.0),
    weight_low_volatility: float = Query(default=0.20, ge=0.0, le=1.0),
    sector: Optional[str] = Query(default=None,
        description="Filter to a specific sector (case-insensitive substring match on yfinance sector field)"),
    max_price: Optional[float] = Query(default=None, ge=0.0,
        description="Drop picks above this share price (e.g. 50 for sub-$50 names). Applied after scoring."),
    min_price: Optional[float] = Query(default=None, ge=0.0,
        description="Drop penny stocks below this share price."),
    nocache: bool = Query(default=False, description="Bypass the 5-minute scan response cache"),
) -> Dict[str, Any]:
    """Long-term (year+) holding candidates.

    Composite score per symbol:
      - 50% fundamentals (P/E, growth, ROE, margins, debt — via score_fundamentals)
      - 30% trend (close > 200dma + 1-year return, saturates at +30%)
      - 20% low volatility (annualized stddev — <20% full credit, >60% zero)

    Defaults to scanning the S&P 500. For crypto, ranks the top market-cap
    coins by trend + vol since fundamentals are neutral across the class.

    This is NOT a market-timing tool — it's a "what's worth buying and
    forgetting about" filter. Use /advisor/research on the top picks for
    LLM-driven per-symbol deep dives.
    """
    cache_key = make_key(
        "long_term",
        asset_class=asset_class,
        top=top,
        min_score=min_score,
        limit_universe=limit_universe,
        symbols=symbols,
        concurrency=concurrency,
        stock_period=stock_period,
        crypto_days=crypto_days,
        weight_fundamentals=weight_fundamentals,
        weight_trend=weight_trend,
        weight_low_volatility=weight_low_volatility,
        sector=sector,
        max_price=max_price,
        min_price=min_price,
    )
    cached = cache_get(cache_key, nocache=nocache)
    if cached is not None:
        return cached

    cache = DataCache(cache_dir="./data/cache")
    market_data = MarketData(cache=cache, config=BotConfig())

    # Universe selection
    if symbols:
        universe = [s.strip().upper() for s in symbols.split(",") if s.strip()][:limit_universe]
    elif asset_class == "stock":
        # S&P 500 is the canonical long-term universe — already curated for
        # quality + liquidity, fundamentals are reliable via yfinance.
        # sp500_universe is async (CSV fetch + 24h cache); must be awaited
        # before slicing or we get "coroutine is not subscriptable" → 502.
        try:
            sp500 = await sp500_universe()
            universe = sp500[:limit_universe]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"sp500 universe fetch failed: {exc}")
    else:
        # Crypto: rely on the scanner's universe builder, which pulls
        # top-N market-cap coins from CoinGecko.
        universe = await _scanner_universe(
            asset_class, market_data, limit_universe, None,
            include_sp500=False, include_movers=False,
        )

    if not universe:
        return {
            "asset_class": asset_class,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "universe_size": 0, "scored": 0, "results": [],
        }

    sem = asyncio.Semaphore(concurrency)
    started = datetime.now(timezone.utc)
    raw_results = await asyncio.gather(
        *[
            _fetch_long_term_one(
                sym, asset_class, market_data, sem, stock_period, crypto_days,
            )
            for sym in universe
        ]
    )
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    # Optional sector filter — applied AFTER scoring so the operator can see
    # what was dropped without re-running.
    if sector:
        s_low = sector.lower()
        raw_results = [
            r for r in raw_results
            if r.error is not None or (r.sector and s_low in r.sector.lower())
        ]

    # Price-cap / -floor filters for budget-aware picking. Applied after
    # scoring; errored rows pass through so the failed[] surface still
    # shows fetch failures. current_price=0 means we never got a quote —
    # treat as "unknown price" and let it through so the operator can
    # decide.
    if max_price is not None or min_price is not None:
        def _passes_price(r: "LongTermScore") -> bool:
            if r.error is not None:
                return True
            if not r.current_price:
                return True
            if max_price is not None and r.current_price > max_price:
                return False
            if min_price is not None and r.current_price < min_price:
                return False
            return True
        raw_results = [r for r in raw_results if _passes_price(r)]

    weights = {
        "fundamentals": weight_fundamentals,
        "trend": weight_trend,
        "low_volatility": weight_low_volatility,
    }
    # Re-score with operator weights if non-default. Cheap: just re-applies
    # the weighted sum to existing components.
    if (weight_fundamentals, weight_trend, weight_low_volatility) != (0.50, 0.30, 0.20):
        total = sum(weights.values()) or 1.0
        norm = {k: v / total for k, v in weights.items()}
        for r in raw_results:
            if r.components:
                r.score = (
                    norm["fundamentals"] * r.components["fundamentals"].score
                    + norm["trend"] * r.components["trend"].score
                    + norm["low_volatility"] * r.components["low_volatility"].score
                ) * 100.0

    valid = rank_long_term(raw_results, top=top, min_score=min_score)
    failed = [
        {"symbol": r.symbol, "error": r.error}
        for r in raw_results
        if r.error not in (None, "insufficient_history_for_trend_or_vol")
    ]

    payload = {
        "asset_class": asset_class,
        "scanned_at": started.isoformat(),
        "elapsed_ms": elapsed_ms,
        "universe_size": len(universe),
        "scored": len(valid),
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "results": [r.to_dict() for r in valid],
        "failed": failed[:20],
    }
    cache_set(cache_key, payload)
    return payload


# ── Squeeze screener ────────────────────────────────────────────────────

# Default sector blocklist mirrors the screenshot's "utilities/REITs" filter.
_DEFAULT_SQUEEZE_SECTOR_BLOCK = ["utilities", "reit"]


async def _squeeze_score_one(
    ticker: str,
    market_data: MarketData,
    has_recent_13d: bool,
    finra_snap: Optional[ShortVolumeSnapshot],
    sem: asyncio.Semaphore,
    *,
    min_market_cap: float,
    max_market_cap: float,
    max_float_shares: float,
    min_price: float,
    max_price: Optional[float],
    min_avg_daily_volume: float,
    sector_blocklist: List[str],
    fetch_technical: bool,
) -> Dict[str, Any]:
    """Fetch fundamentals, apply structural filters, score. Returns response payload."""
    async with sem:
        fund = await fetch_fundamentals(ticker)

        base = {
            "ticker": ticker.upper(),
            "name": fund.name,
            "sector": fund.sector,
            "industry": fund.industry,
            "market_cap": fund.market_cap,
            "float_shares": fund.float_shares,
            "current_price": fund.current_price,
            "avg_daily_volume_10d": fund.avg_daily_volume_10d,
            "short_pct_of_float": fund.short_pct_of_float,
            "days_to_cover": fund.short_ratio_days_to_cover,
            "earnings_qoq_growth": fund.earnings_qoq_growth,
            "earnings_growth_yoy": fund.earnings_growth_yoy,
            # Distinguish "yfinance returned no data" from "EPS is literally
            # flat 0%". UI should render "—" when has_earnings_data=false
            # instead of "+0.0%" which is misleading on a missing field.
            "has_earnings_data": fund.has_earnings_growth_data,
            "next_earnings_date": fund.next_earnings_date,
            "has_recent_13d_filing": has_recent_13d,
            "quarterly_eps": [
                {
                    "period_end": q.period_end,
                    "eps": q.eps,
                    "estimate": q.estimate,
                    "surprise_pct": q.surprise_pct,
                }
                for q in (fund.quarterly_eps or [])
            ],
        }

        passes, reject_reason = passes_structural_filters(
            fund,
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
            max_float_shares=max_float_shares,
            min_price=min_price,
            max_price=max_price,
            min_avg_daily_volume=min_avg_daily_volume,
            sector_blocklist=sector_blocklist,
        )
        if not passes:
            return {**base, "passes_filters": False, "reject_reason": reject_reason}

        # Technical breakout score (optional — can disable for speed on large scans).
        scanner_score: Optional[float] = None
        day_pct_change: Optional[float] = None
        sparkline: Optional[List[float]] = None
        if fetch_technical:
            try:
                df = await asyncio.to_thread(
                    market_data.get_stock_ohlcv, ticker, "3mo", "1d"
                )
                if df is not None and not df.empty:
                    df = df.copy()
                    df.columns = [str(c).lower() for c in df.columns]
                    if "volume" not in df.columns:
                        df["volume"] = 0.0
                    tech = score_symbol(ticker, df)
                    if tech.error is None:
                        scanner_score = tech.score
                    # Day % change: latest vs prior close.
                    if len(df) >= 2 and df["close"].iloc[-2] > 0:
                        day_pct_change = float(
                            (df["close"].iloc[-1] - df["close"].iloc[-2])
                            / df["close"].iloc[-2]
                        )
                    # Sparkline: last 20 daily closes for the inline chart.
                    tail = df["close"].tail(20).tolist()
                    sparkline = [float(x) for x in tail if x is not None and x == x]
            except Exception as exc:
                logger.debug("squeeze: technical fetch failed for %s: %s", ticker, exc)

        off_ex_pct = finra_snap.off_exchange_short_pct if finra_snap else None

        sq = score_squeeze(
            ticker,
            fund,
            has_recent_13d_filing=has_recent_13d,
            scanner_score=scanner_score,
            off_exchange_short_pct=off_ex_pct,
        )

        payload: Dict[str, Any] = {
            **base,
            "passes_filters": True,
            "scanner_score": scanner_score,
            "day_pct_change": day_pct_change,
            "sparkline": sparkline,
            **sq.to_dict(),
        }
        if finra_snap is not None:
            payload["finra"] = {
                "trade_date": finra_snap.trade_date,
                "short_volume_total": finra_snap.short_volume_total,
                "total_volume": finra_snap.total_volume,
                "short_pct_total": round(finra_snap.short_pct_total, 2),
                "off_exchange_short_volume": finra_snap.off_exchange_short_volume,
                "off_exchange_total_volume": finra_snap.off_exchange_total_volume,
                "off_exchange_short_pct": round(finra_snap.off_exchange_short_pct, 2),
            }
        return payload


@router.get("/squeeze")
async def squeeze_screener(
    days_back: int = Query(default=7, ge=1, le=60, description="Window for SC 13D / 13G filings"),
    min_score: float = Query(default=2.5, ge=0.0, le=10.0, description="Drop entries below this composite score"),
    tier: Optional[str] = Query(default=None, description="Comma-separated tier filter: ADD,WATCHLIST,BASE,DISMISS"),
    extra_symbols: Optional[str] = Query(default=None, description="Extra tickers to score in addition to recent filings (comma-separated)"),
    only_filings: bool = Query(default=False, description="Skip the registered-strategy + extra_symbols seed; rank filings only"),
    min_market_cap: float = Query(default=100_000_000, ge=0),
    max_market_cap: float = Query(default=5_000_000_000, ge=0),
    max_float_shares: float = Query(default=500_000_000, ge=0),
    min_price: float = Query(default=1.0, ge=0.0),
    max_price: Optional[float] = Query(default=20.0, ge=0.0, description="Price ceiling — most squeeze setups are sub-$20. Pass 0 or omit for no ceiling."),
    min_avg_daily_volume: float = Query(default=100_000, ge=0),
    sector_blocklist: str = Query(default="utilities,reit", description="Comma-separated sector substrings to exclude"),
    fetch_technical: bool = Query(default=True, description="Score technical breakout via /scanner internals (slower)"),
    concurrency: int = Query(default=8, ge=1, le=20),
    max_results: int = Query(default=40, ge=1, le=200),
    max_candidates: int = Query(default=80, ge=1, le=300, description="Cap tickers scored per scan (filings + extras)"),
    nocache: bool = Query(default=False, description="Bypass the 5-minute scan response cache"),
) -> Dict[str, Any]:
    """Squeeze screener — GME / CAR / RXT-shape setups.

    Pulls SC 13D / 13D-A / 13G / 13G-A filings from SEC EDGAR over the last
    ``days_back`` days, applies structural filters (MC band, float cap, sector
    block, ADV floor), and scores each survivor on six factors:

    1. Short interest %
    2. Float size (smaller = better)
    3. Days to cover
    4. Earnings trend (QoQ + YoY) — the RXT insight
    5. Recent 13D / 13G filing (catalyst signal, +1 pt if in window)
    6. Technical breakout from /advisor/scanner (optional, ``fetch_technical``)

    **Data caveats** (returned in each result's ``warnings``):
    - SI% is FINRA bi-monthly with ~2-week lag — fine for swing/position
      setups, not for intraday squeeze tracking.
    - Earnings-trend uses yfinance pre-computed fields; can be stale by a quarter.
    - Cash-settled swaps are invisible — read the actual 13D doc for activist
      filings.
    """
    started = datetime.now(timezone.utc)
    blocklist = [s.strip().lower() for s in sector_blocklist.split(",") if s.strip()]

    effective_max_price: Optional[float] = (
        None if (max_price is None or max_price <= 0) else max_price
    )

    cache_key = make_key(
        "squeeze",
        days_back=days_back,
        min_score=min_score,
        tier=tier,
        extra_symbols=extra_symbols,
        only_filings=only_filings,
        min_market_cap=min_market_cap,
        max_market_cap=max_market_cap,
        max_float_shares=max_float_shares,
        min_price=min_price,
        max_price=effective_max_price,
        min_avg_daily_volume=min_avg_daily_volume,
        sector_blocklist=blocklist,
        fetch_technical=fetch_technical,
        concurrency=concurrency,
        max_results=max_results,
        max_candidates=max_candidates,
    )
    cached = cache_get(cache_key, nocache=nocache)
    if cached is not None:
        return cached

    # 1. Pull recent 13D/13G filings.
    filings: List[SecFiling] = await fetch_recent_filings(days_back=days_back, max_results=300)
    filing_tickers: List[str] = [f.ticker for f in filings]
    filing_set = set(filing_tickers)
    filing_lookup = {f.ticker: f for f in filings}

    # 2. Build candidate set: filings + (optionally) extra symbols.
    candidates: List[str] = list(filing_tickers)
    if not only_filings:
        if extra_symbols:
            for s in extra_symbols.split(","):
                s = s.strip().upper()
                if s and s not in candidates:
                    candidates.append(s)

    candidates = candidates[:max_candidates]

    # 3. Score each candidate (fundamentals → filter → squeeze score).
    market_data = MarketData(cache=DataCache(cache_dir="./data/cache"), config=BotConfig())
    sem = asyncio.Semaphore(concurrency)

    # Pre-load FINRA's freshest short-volume snapshot once per scan (cached
    # across calls anyway) so each ticker's lookup is O(1) inside the loop.
    finra_map = await latest_short_volume_snapshot()
    finra_trade_date = (
        next(iter(finra_map.values())).trade_date
        if finra_map
        else None
    )

    score_tasks = [
        _squeeze_score_one(
            t,
            market_data,
            has_recent_13d=(t in filing_set),
            finra_snap=(finra_map.get(t) if finra_map else None),
            sem=sem,
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
            max_float_shares=max_float_shares,
            min_price=min_price,
            max_price=effective_max_price,
            min_avg_daily_volume=min_avg_daily_volume,
            sector_blocklist=blocklist,
            fetch_technical=fetch_technical,
        )
        for t in candidates
    ]
    raw_results = await asyncio.gather(*score_tasks, return_exceptions=True)

    # 4. Split into passed / rejected / errored.
    passed: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for t, r in zip(candidates, raw_results):
        if isinstance(r, Exception):
            errors.append({"ticker": t, "error": str(r)[:200]})
            continue
        if r.get("passes_filters"):
            passed.append(r)
        else:
            rejected.append({"ticker": r["ticker"], "reason": r.get("reject_reason")})

    # 5. Filter + sort by squeeze score.
    if min_score > 0:
        passed = [p for p in passed if p.get("score", 0) >= min_score]
    if tier:
        wanted = {t.strip().upper() for t in tier.split(",") if t.strip()}
        passed = [p for p in passed if p.get("tier") in wanted]
    passed.sort(key=lambda p: p.get("score", 0), reverse=True)

    # 6. Decorate with filing context (form, filed_at, filer).
    for p in passed:
        f = filing_lookup.get(p["ticker"])
        if f:
            p["filing"] = {
                "form": f.form,
                "filed_at": f.filed_at,
                "filer_name": f.filer_name,
                "edgar_url": f.edgar_url,
            }

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    payload = {
        "scanned_at": started.isoformat(),
        "elapsed_ms": elapsed_ms,
        "filters": {
            "days_back": days_back,
            "min_score": min_score,
            "tier": tier,
            "min_market_cap": min_market_cap,
            "max_market_cap": max_market_cap,
            "max_float_shares": max_float_shares,
            "min_price": min_price,
            "max_price": effective_max_price,
            "min_avg_daily_volume": min_avg_daily_volume,
            "sector_blocklist": blocklist,
            "fetch_technical": fetch_technical,
            "max_candidates": max_candidates,
        },
        "filings_count": len(filings),
        "candidates_scored": len(candidates),
        "passed_filters": len([r for r in raw_results if isinstance(r, dict) and r.get("passes_filters")]),
        "errors_count": len(errors),
        "finra_trade_date": finra_trade_date,
        "results": passed[:max_results],
        "rejected_sample": rejected[:20],
        "errors_sample": errors[:5],
        "data_caveats": [
            "Yahoo SI lags FINRA bi-monthly reporting by ~2 weeks. OK for swing setups, not intraday.",
            "FINRA daily off-exchange short volume is T+1 and only covers reg-SHO eligible NMS securities.",
            "Earnings-trend uses yfinance pre-computed fields; can lag one quarter.",
            "Cash-settled swaps don't show in 13D headers — read the doc for activist filings.",
        ],
    }
    cache_set(cache_key, payload)
    return payload
