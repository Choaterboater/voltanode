"""AI Advisor API routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from advisor.analyzer import SymbolAnalyzer
from advisor.models import AnalysisResult, IndicatorReading, PriceTarget
from advisor.research import build_research_report
from data.cache import DataCache
from data.fetcher import MarketData
from bot.config import BotConfig

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
    report = await _asyncio.to_thread(build_research_report, ta, advanced)
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
