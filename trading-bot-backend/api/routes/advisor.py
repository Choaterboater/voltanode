"""AI Advisor API routes."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from advisor.analyzer import SymbolAnalyzer
from advisor.models import AnalysisResult, IndicatorReading, PriceTarget
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
