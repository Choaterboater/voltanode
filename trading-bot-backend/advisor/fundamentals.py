"""Fundamental data fetcher for stocks (yfinance) and crypto (lite).

Pulled at /advisor/research time so the LLM can score the Fundamentals
dimension alongside Technicals and Sentiment. All fields are best-effort —
missing values come back as None and the scorer treats them neutrally.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("volta.advisor.fundamentals")


@dataclass
class FundamentalSnapshot:
    """Snapshot of fundamental metrics for one symbol."""

    symbol: str
    asset_type: str  # "stock" or "crypto"
    name: str = ""
    sector: str = ""
    industry: str = ""
    currency: str = "USD"
    business_summary: str = ""  # one-paragraph "what they do" from yfinance

    # Valuation
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_sales: Optional[float] = None
    price_to_book: Optional[float] = None
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None

    # Profitability
    return_on_equity: Optional[float] = None
    return_on_assets: Optional[float] = None
    profit_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    gross_margin: Optional[float] = None

    # Balance sheet
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None

    # Growth (YoY)
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    earnings_qoq_growth: Optional[float] = None

    # Analyst & sentiment
    analyst_target_mean: Optional[float] = None
    analyst_target_median: Optional[float] = None
    analyst_target_high: Optional[float] = None
    analyst_target_low: Optional[float] = None
    analyst_count: Optional[int] = None
    recommendation_key: str = ""
    recommendation_mean: Optional[float] = None  # 1=Strong Buy, 5=Strong Sell

    # Short interest
    short_percent_of_float: Optional[float] = None
    short_ratio: Optional[float] = None

    # Catalysts
    next_earnings_date: Optional[str] = None  # ISO date

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def fetch_stock_fundamentals(symbol: str) -> FundamentalSnapshot:
    """Pull fundamentals via yfinance for a stock ticker."""
    snap = FundamentalSnapshot(symbol=symbol.upper(), asset_type="stock")
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
    except Exception as exc:
        logger.warning(f"yfinance lookup failed for {symbol}: {exc}")
        return snap

    snap.name = info.get("longName") or info.get("shortName") or symbol.upper()
    snap.sector = info.get("sector") or ""
    snap.industry = info.get("industry") or ""
    snap.currency = info.get("currency") or "USD"
    summary = info.get("longBusinessSummary") or info.get("description") or ""
    # Cap at 800 chars so the LLM prompt doesn't balloon — yfinance summaries
    # are sometimes 2-3KB which crowds the rest of the prompt.
    snap.business_summary = summary[:800].strip() if summary else ""

    snap.trailing_pe = _safe_float(info.get("trailingPE"))
    snap.forward_pe = _safe_float(info.get("forwardPE"))
    snap.peg_ratio = _safe_float(info.get("pegRatio") or info.get("trailingPegRatio"))
    snap.price_to_sales = _safe_float(info.get("priceToSalesTrailing12Months"))
    snap.price_to_book = _safe_float(info.get("priceToBook"))
    snap.market_cap = _safe_float(info.get("marketCap"))
    snap.enterprise_value = _safe_float(info.get("enterpriseValue"))

    snap.return_on_equity = _safe_float(info.get("returnOnEquity"))
    snap.return_on_assets = _safe_float(info.get("returnOnAssets"))
    snap.profit_margin = _safe_float(info.get("profitMargins"))
    snap.operating_margin = _safe_float(info.get("operatingMargins"))
    snap.gross_margin = _safe_float(info.get("grossMargins"))

    snap.debt_to_equity = _safe_float(info.get("debtToEquity"))
    snap.current_ratio = _safe_float(info.get("currentRatio"))

    snap.revenue_growth = _safe_float(info.get("revenueGrowth"))
    snap.earnings_growth = _safe_float(info.get("earningsGrowth"))
    snap.earnings_qoq_growth = _safe_float(info.get("earningsQuarterlyGrowth"))

    snap.analyst_target_mean = _safe_float(info.get("targetMeanPrice"))
    snap.analyst_target_median = _safe_float(info.get("targetMedianPrice"))
    snap.analyst_target_high = _safe_float(info.get("targetHighPrice"))
    snap.analyst_target_low = _safe_float(info.get("targetLowPrice"))
    snap.analyst_count = _safe_int(info.get("numberOfAnalystOpinions"))
    snap.recommendation_key = str(info.get("recommendationKey") or "")
    snap.recommendation_mean = _safe_float(info.get("recommendationMean"))

    snap.short_percent_of_float = _safe_float(info.get("shortPercentOfFloat"))
    snap.short_ratio = _safe_float(info.get("shortRatio"))

    ts = info.get("earningsTimestamp")
    if ts:
        try:
            snap.next_earnings_date = datetime.fromtimestamp(
                int(ts), tz=timezone.utc
            ).date().isoformat()
        except (ValueError, TypeError):
            pass

    return snap


def fetch_crypto_fundamentals(symbol: str) -> FundamentalSnapshot:
    """Crypto fundamentals are sparser — name + asset class only."""
    snap = FundamentalSnapshot(symbol=symbol.upper(), asset_type="crypto")
    snap.name = symbol.replace("-", " ").replace("_", " ").title()
    return snap


def score_fundamentals(snap: FundamentalSnapshot) -> Tuple[int, str]:
    """Score 0-100 with a one-line rationale.

    Profitability, valuation, growth, and balance-sheet contributions are
    summed. Missing fields are skipped (no penalty). Crypto returns a
    neutral 50 since no traditional fundamentals apply.
    """
    if snap.asset_type != "stock":
        return 50, "Crypto: no fundamental scoring available"

    parts: List[Tuple[str, float]] = []

    if snap.return_on_equity is not None:
        roe = snap.return_on_equity * 100
        if roe > 25:
            parts.append(("strong ROE", 30))
        elif roe > 15:
            parts.append(("solid ROE", 15))
        elif roe < 5:
            parts.append(("weak ROE", -20))

    if snap.profit_margin is not None:
        pm = snap.profit_margin * 100
        if pm > 20:
            parts.append(("excellent margins", 20))
        elif pm > 10:
            parts.append(("decent margins", 8))
        elif pm < 0:
            parts.append(("unprofitable", -25))

    if snap.revenue_growth is not None:
        rg = snap.revenue_growth * 100
        if rg > 20:
            parts.append(("high revenue growth", 25))
        elif rg > 5:
            parts.append(("moderate growth", 8))
        elif rg < 0:
            parts.append(("revenue declining", -25))

    if snap.peg_ratio is not None:
        if snap.peg_ratio < 1:
            parts.append(("undervalued vs growth (PEG<1)", 15))
        elif snap.peg_ratio < 2:
            parts.append(("fairly valued (PEG~1-2)", 0))
        else:
            parts.append(("expensive vs growth (PEG>2)", -10))

    if snap.trailing_pe is not None and snap.trailing_pe > 0:
        if snap.trailing_pe < 15:
            parts.append(("low P/E", 8))
        elif snap.trailing_pe > 35:
            parts.append(("rich P/E", -10))

    if snap.debt_to_equity is not None:
        if snap.debt_to_equity < 50:
            parts.append(("low debt", 8))
        elif snap.debt_to_equity > 200:
            parts.append(("highly leveraged", -15))

    if snap.recommendation_mean is not None:
        if snap.recommendation_mean < 2:
            parts.append(("analyst consensus: Buy", 10))
        elif snap.recommendation_mean > 3.5:
            parts.append(("analyst consensus: Sell", -15))

    raw = sum(p[1] for p in parts)
    score = max(0, min(100, 50 + raw))
    rationale = "; ".join(p[0] for p in parts[:4]) if parts else "Insufficient fundamental data"
    return int(score), rationale


def fetch_fundamentals(symbol: str, asset_type: str) -> FundamentalSnapshot:
    """Top-level dispatch."""
    if asset_type == "stock":
        return fetch_stock_fundamentals(symbol)
    return fetch_crypto_fundamentals(symbol)


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
