"""Multi-dimensional research report (Kavout InvestGPT-style).

Combines:
  - Technical Dimension (existing TA pipeline) — weight 30%
  - Fundamental Dimension (yfinance metrics + scoring) — weight 40%
  - Sentiment Dimension (news + LLM hybrid) — weight 30%

Each dimension produces an independent 0-100 score and a brief rationale.
The weighted overall score drives the verdict bucket. An optional LLM call
(Ollama by default, OpenRouter when advanced=True) produces the rich
narrative report — investment thesis, bull/bear, key drivers, action plan.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from advisor.fundamentals import FundamentalSnapshot, fetch_fundamentals, score_fundamentals
from advisor.models import AnalysisResult

logger = logging.getLogger("volta.advisor.research")


# ── Public schema ─────────────────────────────────────────────────────


@dataclass
class DimensionScore:
    """One dimension's score + narrative."""

    name: str  # "fundamental" / "technical" / "sentiment"
    score: int  # 0-100
    weight: float  # 0-1
    label: str  # "POSITIVE", "NEUTRAL", "NEGATIVE", etc.
    rationale: str  # one-line summary of contributing factors
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchReport:
    """Full multi-dimension research report."""

    symbol: str
    display_name: str
    asset_type: str
    current_price: float
    overall_score: int  # 0-100, weighted
    overall_label: str  # "STRONG_BUY" / "BUY" / "HOLD" / "SELL" / "STRONG_SELL"
    confidence: int  # 0-100
    optimal_timeframe: str  # "1-3 months" / "3-6 months" / "6-12 months"

    fundamental: DimensionScore
    technical: DimensionScore
    sentiment: DimensionScore

    # Catalysts
    next_earnings_date: Optional[str] = None
    analyst_target_median: Optional[float] = None
    analyst_count: Optional[int] = None
    sector: str = ""
    industry: str = ""

    # LLM-produced narrative sections (filled when generate_narrative succeeds)
    company_overview: str = ""
    investment_thesis: str = ""
    key_drivers: List[str] = field(default_factory=list)
    bull_case: str = ""
    bear_case: str = ""
    action_plan: Dict[str, str] = field(default_factory=dict)
    bottom_line: str = ""
    llm_model: str = ""

    fundamentals_raw: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""

    # External signal context (best-effort, empty when keys/data missing)
    macro_context: Dict[str, Any] = field(default_factory=dict)
    insider_context: Dict[str, Any] = field(default_factory=dict)
    earnings_context: Dict[str, Any] = field(default_factory=dict)
    fear_greed_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ── Scoring ──────────────────────────────────────────────────────────


def _score_technical(result: AnalysisResult) -> DimensionScore:
    """Technical score derived from the existing TA confidence + verdict.

    confidence is 0-100, verdict shifts the centerpoint:
      STRONG_BUY  → +20
      BUY         → +10
      HOLD        →   0
      SELL        → -10
      STRONG_SELL → -20
    """
    base = float(result.confidence)
    shift = {
        "STRONG_BUY": 20,
        "BUY": 10,
        "HOLD": 0,
        "SELL": -10,
        "STRONG_SELL": -20,
    }.get(result.verdict.upper(), 0)
    score = max(0, min(100, int(base + shift)))

    bullish = sum(1 for ind in result.indicators if ind.signal == "bullish")
    bearish = sum(1 for ind in result.indicators if ind.signal == "bearish")
    neutral = sum(1 for ind in result.indicators if ind.signal == "neutral")
    rationale = f"{bullish} bullish / {bearish} bearish / {neutral} neutral indicators; TA verdict {result.verdict}"
    label = _score_to_label(score)
    return DimensionScore(
        name="technical",
        score=score,
        weight=0.30,
        label=label,
        rationale=rationale,
        details={"verdict": result.verdict, "ta_confidence": result.confidence,
                 "bullish": bullish, "bearish": bearish, "neutral": neutral},
    )


def _score_sentiment(symbol: str, asset_type: str) -> DimensionScore:
    """Sentiment score from the news storage's per-symbol summary.

    Maps avg compound score (-1..+1) to 0-100 and pulls article count
    + label so the LLM can reference recent news.
    """
    try:
        from api.routes import news as news_routes
        storage = news_routes._get_storage()
    except Exception:
        return DimensionScore(name="sentiment", score=50, weight=0.30,
                              label="NEUTRAL", rationale="news subsystem unavailable")

    ticker = symbol.upper()
    if asset_type == "crypto":
        # Map common ids → tickers (news storage uses tickers)
        from advisor.llm_advisor import _CG_TO_TICKER
        ticker = _CG_TO_TICKER.get(symbol.lower(), symbol.upper())

    summary = None
    article_count = 0
    avg_compound = 0.0
    try:
        summary_obj = storage.get_symbol_sentiment_summary(ticker, hours=72)
        if summary_obj:
            summary = summary_obj
            article_count = getattr(summary_obj, "article_count", 0) or 0
            avg_compound = float(getattr(summary_obj, "avg_compound", 0.0) or 0.0)
    except Exception as exc:
        logger.debug(f"sentiment summary fetch failed for {ticker}: {exc}")

    if article_count == 0:
        return DimensionScore(name="sentiment", score=50, weight=0.30,
                              label="NEUTRAL", rationale=f"No recent news for {ticker} (last 72h)")

    score = int(50 + avg_compound * 50)
    score = max(0, min(100, score))
    label = _score_to_label(score)
    direction = "bullish" if avg_compound > 0.1 else ("bearish" if avg_compound < -0.1 else "mixed")
    rationale = f"{article_count} articles in last 72h, avg compound {avg_compound:+.2f} ({direction})"
    return DimensionScore(
        name="sentiment",
        score=score,
        weight=0.30,
        label=label,
        rationale=rationale,
        details={"article_count": article_count, "avg_compound": round(avg_compound, 3)},
    )


def _score_to_label(score: int) -> str:
    if score >= 75:
        return "POSITIVE"
    if score >= 60:
        return "NEUTRAL/POSITIVE"
    if score >= 40:
        return "NEUTRAL"
    if score >= 25:
        return "NEUTRAL/NEGATIVE"
    return "NEGATIVE"


def _verdict_from_score(score: int) -> Tuple[str, str]:
    """Overall score → (verdict, friendly label)."""
    if score >= 80:
        return "STRONG_BUY", "Strong Buy"
    if score >= 65:
        return "BUY", "Buy / Buy on Dips"
    if score >= 45:
        return "HOLD", "Hold"
    if score >= 30:
        return "SELL", "Reduce / Sell"
    return "STRONG_SELL", "Strong Sell"


# ── Public entry point ──────────────────────────────────────────────


def _timeframe_for_lookback(lookback_days: int, asset_type: str) -> str:
    """Map the user-selected lookback window to a human-readable horizon string.

    The frontend's range buttons (1mo / 3mo / 1yr) pass through as
    lookback_days = 30 / 90 / 365 — the result here should track that selection
    instead of being a constant per asset class.
    """
    d = int(lookback_days or 0)
    if d <= 14:
        return "days to 2 weeks"
    if d <= 35:
        return "2-6 weeks"
    if d <= 100:
        return "1-3 months"
    if d <= 200:
        return "3-6 months"
    if d <= 400:
        return "6-12 months"
    return "12+ months"


def build_research_report(
    ta_result: AnalysisResult,
    advanced: bool = False,
    lookback_days: Optional[int] = None,
) -> ResearchReport:
    """Assemble the multi-dimension report from an existing TA analysis.

    ``lookback_days`` should be the same value the caller passed to
    ``SymbolAnalyzer.analyze`` so the report's ``optimal_timeframe`` matches
    what the user actually requested. When omitted, falls back to a sensible
    default per asset class.
    """
    snap = fetch_fundamentals(ta_result.symbol, ta_result.asset_type)
    f_score, f_rationale = score_fundamentals(snap)

    fundamental = DimensionScore(
        name="fundamental",
        score=f_score,
        weight=0.40 if ta_result.asset_type == "stock" else 0.20,
        label=_score_to_label(f_score),
        rationale=f_rationale,
        details=snap.to_dict(),
    )
    technical = _score_technical(ta_result)
    sentiment = _score_sentiment(ta_result.symbol, ta_result.asset_type)

    # Crypto: shift weight off fundamentals onto technicals + sentiment
    if ta_result.asset_type != "stock":
        technical.weight = 0.50
        sentiment.weight = 0.30

    total_w = fundamental.weight + technical.weight + sentiment.weight
    overall = int(round(
        (fundamental.score * fundamental.weight
         + technical.score * technical.weight
         + sentiment.score * sentiment.weight) / total_w
    ))
    verdict, _label = _verdict_from_score(overall)
    confidence = max(40, min(95, overall))  # confidence floor for sane UI

    # Honour the user-selected lookback window when present; fall back to the
    # historical asset-class default only if the caller didn't pass one through.
    if lookback_days is not None:
        timeframe = _timeframe_for_lookback(int(lookback_days), ta_result.asset_type)
    else:
        timeframe = "6-12 months" if ta_result.asset_type == "stock" else "1-3 months"

    # Pull external signal context (FRED macro, Finnhub earnings/insider,
    # alternative.me Fear & Greed). All best-effort — None when keys missing.
    macro_ctx = _fetch_macro_context()
    insider_ctx = _fetch_insider_context(
        ta_result.symbol, ta_result.asset_type, current_price=ta_result.current_price
    )
    earnings_ctx = _fetch_next_earnings(ta_result.symbol, ta_result.asset_type, snap.next_earnings_date)
    fg_ctx = _fetch_fear_greed_context()

    report = ResearchReport(
        symbol=ta_result.symbol.upper(),
        display_name=getattr(ta_result, "display_name", "") or snap.name or ta_result.symbol.upper(),
        asset_type=ta_result.asset_type,
        current_price=ta_result.current_price,
        overall_score=overall,
        overall_label=verdict,
        confidence=confidence,
        optimal_timeframe=timeframe,
        fundamental=fundamental,
        technical=technical,
        sentiment=sentiment,
        next_earnings_date=earnings_ctx.get("date") or snap.next_earnings_date,
        analyst_target_median=snap.analyst_target_median,
        analyst_count=snap.analyst_count,
        sector=snap.sector,
        industry=snap.industry,
        fundamentals_raw=snap.to_dict(),
        generated_at=datetime.now(timezone.utc).isoformat(),
        macro_context=macro_ctx,
        insider_context=insider_ctx,
        earnings_context=earnings_ctx,
        fear_greed_context=fg_ctx,
    )

    # Optional rich narrative — best-effort, never fatal
    try:
        narrative = _generate_narrative(report, ta_result, advanced=advanced)
        if narrative:
            report.company_overview = narrative.get("company_overview", "")
            report.investment_thesis = narrative.get("investment_thesis", "")
            report.key_drivers = narrative.get("key_drivers", []) or []
            report.bull_case = narrative.get("bull_case", "")
            report.bear_case = narrative.get("bear_case", "")
            report.action_plan = narrative.get("action_plan", {}) or {}
            report.bottom_line = narrative.get("bottom_line", "")
            report.llm_model = narrative.get("model", "")
    except Exception as exc:
        logger.warning(f"Research narrative generation failed: {exc}")

    return report


# ── External signal context fetchers ────────────────────────────────


def _fetch_macro_context() -> Dict[str, Any]:
    """Pull FRED snapshot for the LLM prompt. Empty when key missing."""
    try:
        from signals import fred
        if not fred.is_configured():
            return {}
        snap = fred.fetch_macro_snapshot()
        if snap is None:
            return {}
        out: Dict[str, Any] = {}
        for sid, obs in snap.series.items():
            out[sid] = {
                "value": obs.value,
                "date": obs.date,
                "change": obs.change,
                "name": obs.name,
            }
        return out
    except Exception as exc:
        logger.debug(f"macro context fetch failed: {exc}")
        return {}


def _fetch_insider_context(
    symbol: str,
    asset_type: str,
    current_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Pull insider Form 4 summary (Finnhub) for stocks.

    Passes ``current_price`` through so the aggregator can drop
    derivative-settlement filings whose reported prices are unrelated to
    the real market (CAR / Pentwater $700 issue → kept totals from
    inflating to fictitious billions).
    """
    if asset_type != "stock":
        return {}
    try:
        from signals import finnhub
        if not finnhub.is_configured():
            return {}
        return finnhub.insider_summary(symbol, reference_price=current_price)
    except Exception as exc:
        logger.debug(f"insider context fetch failed for {symbol}: {exc}")
        return {}


def _fetch_next_earnings(symbol: str, asset_type: str, fallback_date: Optional[str]) -> Dict[str, Any]:
    """Look up the next earnings event via Finnhub. Falls back to yfinance ts."""
    if asset_type != "stock":
        return {}
    try:
        from signals import finnhub
        if finnhub.is_configured():
            entry = finnhub.earnings_for_symbol(symbol)
            if entry is not None:
                from dataclasses import asdict as _asdict
                d = _asdict(entry)
                # Days until
                try:
                    edate = datetime.strptime(d["date"], "%Y-%m-%d").date()
                    today = datetime.now(timezone.utc).date()
                    d["days_until"] = max(0, (edate - today).days)
                except (ValueError, TypeError):
                    d["days_until"] = None
                return d
    except Exception as exc:
        logger.debug(f"earnings context fetch failed for {symbol}: {exc}")
    if fallback_date:
        try:
            edate = datetime.fromisoformat(fallback_date).date()
            today = datetime.now(timezone.utc).date()
            # If the "next" earnings date yfinance returned is actually in the
            # past (yfinance falls back to the last reported quarter when the
            # next one hasn't been formally announced), project +90 days as an
            # estimate so the UI shows a forward-looking horizon. Mark source
            # explicitly so callers / the LLM can disambiguate.
            from datetime import timedelta as _td
            if edate < today:
                projected = edate + _td(days=90)
                # Keep adding quarters until we land in the future.
                while projected < today:
                    projected = projected + _td(days=90)
                return {
                    "symbol": symbol.upper(),
                    "date": projected.isoformat(),
                    "last_reported_date": fallback_date,
                    "days_until": (projected - today).days,
                    "source": "estimated",  # ~quarterly projection from last reported
                }
            return {
                "symbol": symbol.upper(),
                "date": fallback_date,
                "days_until": max(0, (edate - today).days),
                "source": "yfinance",
            }
        except (ValueError, TypeError):
            pass
    return {}


def _fetch_fear_greed_context() -> Dict[str, Any]:
    """Crypto Fear & Greed snapshot (relevant for both crypto and risk-on/off context)."""
    try:
        from signals.fear_greed import fetch_fear_greed
        sig = fetch_fear_greed()
        if sig is None:
            return {}
        return {
            "value": sig.value,
            "label": sig.label,
            "is_extreme_fear": sig.is_extreme_fear,
            "is_extreme_greed": sig.is_extreme_greed,
        }
    except Exception:
        return {}


# ── LLM narrative generation ────────────────────────────────────────


def _directional_levels(price: float, ta_result: AnalysisResult) -> Dict[str, str]:
    """Build LONG/SHORT level pairs from the analyzer's stop-distance.

    The analyzer's ``stop_loss`` / ``take_profit`` numbers are TA-verdict-
    aware: for HOLD they're a symmetric reference band around price, for
    BUY/SELL they're directional. The LLM may recommend a different
    direction than the TA verdict (e.g. research-narrative says SHORT
    while TA says HOLD), so we derive the absolute stop/target distances
    here and present BOTH sets so the LLM picks the matching one.
    """
    sl = getattr(ta_result, "stop_loss", None) or price
    tp = getattr(ta_result, "take_profit", None) or price
    # Distance is always the absolute deviation from current price.
    stop_dist = max(abs(price - sl), 0.001)
    tp_dist = max(abs(tp - price), 0.001)

    long_stop = price - stop_dist
    long_tp = price + tp_dist
    short_stop = price + stop_dist  # cover if price rises
    short_tp = price - tp_dist      # profit if price falls

    pct = lambda x: ((x - price) / price * 100) if price else 0
    return {
        "long_stop": f"{long_stop:,.2f}",
        "long_stop_pct": pct(long_stop),
        "long_tp": f"{long_tp:,.2f}",
        "long_tp_pct": pct(long_tp),
        "short_stop": f"{short_stop:,.2f}",
        "short_stop_pct": pct(short_stop),
        "short_tp": f"{short_tp:,.2f}",
        "short_tp_pct": pct(short_tp),
    }


_RESEARCH_PROMPT = """You are an equity research analyst writing a multi-dimensional report
on {symbol} ({display_name}). The deterministic scoring layer has already
computed three dimensions:

COMPANY (what they do):
{business_summary}

RECENT HEADLINES (last 7 days, most relevant first):
{news_block}

FUNDAMENTAL ({f_weight:.0%} weight) — score {f_score}/100, label {f_label}
  rationale: {f_rationale}
  key metrics: P/E {pe}, forward P/E {fpe}, PEG {peg}, P/S {ps}, ROE {roe},
               profit margin {pm}, revenue growth {rg}, debt/equity {de},
               analyst median target ${target}, analyst count {acount},
               sector {sector}.

TECHNICAL ({t_weight:.0%} weight) — score {t_score}/100, label {t_label}
  rationale: {t_rationale}
  TA verdict: {ta_verdict} at {ta_conf}% confidence
  current price: ${price}

RISK & SIZING (computed by deterministic risk engine — USE THESE NUMBERS,
do not invent tighter stops):
  risk_level: {risk_level} (low / moderate / high / extreme)
  suggested entry zone: ${entry_low} – ${entry_high}
  computed stop_loss (TA-verdict aware): ${stop_loss}  ({stop_pct:+.1f}% from current)
  computed take_profit (TA-verdict aware): ${take_profit}  ({tp_pct:+.1f}% from current)
  suggested position size: {pos_pct:.1f}% of capital
  time horizon: {time_horizon}

DIRECTIONAL TRADE LEVELS (use the set matching your trade recommendation;
based on horizon-scaled risk-tier, NOT the TA verdict):
  If recommending LONG:
    - entry near current price ${price}
    - stop-loss BELOW at ${long_stop}  ({long_stop_pct:+.1f}% from current)
    - take-profit ABOVE at ${long_tp}  ({long_tp_pct:+.1f}% from current)
  If recommending SHORT:
    - entry near current price ${price}
    - stop-loss (cover if price RISES) at ${short_stop}  ({short_stop_pct:+.1f}% from current)
    - take-profit (profit if price FALLS) at ${short_tp}  ({short_tp_pct:+.1f}% from current)

SENTIMENT ({s_weight:.0%} weight) — score {s_score}/100, label {s_label}
  rationale: {s_rationale}

MACRO CONTEXT (current US economy):
{macro_block}

EARNINGS / CATALYSTS:
{earnings_block}

INSIDER ACTIVITY (Form 4 last 180 days):
{insider_block}

MARKET SENTIMENT (crypto Fear & Greed proxy for risk-on/off):
{fg_block}

OVERALL composite score: {overall}/100 → {verdict}

When forming your thesis, EXPLICITLY weave macro / earnings proximity /
insider tone / RECENT HEADLINES into the narrative. Quote specific headlines
as catalysts when relevant — e.g. product launches, regulatory rulings,
earnings beats/misses, acquisitions, lawsuits, partnerships. Examples:
  - If earnings are within 7 days → caution against new entries.
  - If insiders are net selling significantly → flag as red flag.
  - If VIX > 25 or yield curve inverted → adjust risk framing.
  - If 10y-2y has just un-inverted → mention reflation tone.
  - If headlines mention a near-term catalyst (FDA decision, product launch,
    legal ruling) → name it explicitly in the thesis or bull/bear case.

Produce a JSON object with exactly these keys (no markdown, no extra text):
{{
  "company_overview": "2-3 sentence plain-English description of what the company does + 1-2 sentences on the BIGGEST current project / catalyst / story driving the stock right now (use the recent headlines)",
  "investment_thesis": "2-4 sentence thesis on whether to buy/hold/sell now",
  "key_drivers": ["driver 1", "driver 2", "driver 3", "driver 4"],
  "bull_case": "1-2 sentences of the strongest bull argument",
  "bear_case": "1-2 sentences of the strongest bear argument",
  "action_plan": {{
    "growth_investor": "BUY / HOLD / AVOID + one-sentence rationale",
    "value_investor": "BUY / HOLD / AVOID + one-sentence rationale",
    "trader": "specific entry / exit levels for the short-term trade. USE the computed stop_loss and take_profit numbers in the RISK & SIZING block above — do NOT invent tighter stops. For SHORT trades, use clear language: 'cover if price RISES to $X (stop)' and 'profit at $Y if price falls' — avoid the word 'downside' as a profit target since it is ambiguous on a short. Be explicit about direction and which side of the entry is profit vs loss.",
    "already_holding": "what to do with existing position"
  }},
  "bottom_line": "1-2 sentence final takeaway including any specific price levels"
}}
"""


def _generate_narrative(
    report: ResearchReport, ta_result: AnalysisResult, advanced: bool
) -> Optional[Dict[str, Any]]:
    """Call the LLM to produce the rich narrative sections."""
    snap_data = report.fundamentals_raw

    def fmt(v: Any, pct: bool = False, money: bool = False, default: str = "n/a") -> str:
        if v is None:
            return default
        try:
            f = float(v)
            if pct:
                return f"{f * 100:.1f}%"
            if money:
                return f"{f:,.2f}"
            return f"{f:,.2f}"
        except (TypeError, ValueError):
            return str(v)

    business_summary = (snap_data.get("business_summary") or "").strip() or "n/a"
    news_block = _format_news_block(report.symbol)

    prompt = _RESEARCH_PROMPT.format(
        symbol=report.symbol,
        display_name=report.display_name,
        business_summary=business_summary,
        news_block=news_block,
        f_weight=report.fundamental.weight,
        f_score=report.fundamental.score,
        f_label=report.fundamental.label,
        f_rationale=report.fundamental.rationale,
        pe=fmt(snap_data.get("trailing_pe")),
        fpe=fmt(snap_data.get("forward_pe")),
        peg=fmt(snap_data.get("peg_ratio")),
        ps=fmt(snap_data.get("price_to_sales")),
        roe=fmt(snap_data.get("return_on_equity"), pct=True),
        pm=fmt(snap_data.get("profit_margin"), pct=True),
        rg=fmt(snap_data.get("revenue_growth"), pct=True),
        de=fmt(snap_data.get("debt_to_equity")),
        target=fmt(snap_data.get("analyst_target_median"), money=True),
        acount=snap_data.get("analyst_count") or "n/a",
        sector=snap_data.get("sector") or "n/a",
        t_weight=report.technical.weight,
        t_score=report.technical.score,
        t_label=report.technical.label,
        t_rationale=report.technical.rationale,
        ta_verdict=ta_result.verdict,
        ta_conf=ta_result.confidence,
        price=f"{report.current_price:,.2f}",
        risk_level=getattr(ta_result, "risk_level", "n/a"),
        entry_low=f"{getattr(ta_result, 'entry_zone', (0, 0))[0]:,.2f}",
        entry_high=f"{getattr(ta_result, 'entry_zone', (0, 0))[1]:,.2f}",
        stop_loss=f"{getattr(ta_result, 'stop_loss', 0):,.2f}",
        take_profit=f"{getattr(ta_result, 'take_profit', 0):,.2f}",
        stop_pct=(
            (getattr(ta_result, "stop_loss", 0) - report.current_price)
            / report.current_price * 100
            if report.current_price else 0
        ),
        tp_pct=(
            (getattr(ta_result, "take_profit", 0) - report.current_price)
            / report.current_price * 100
            if report.current_price else 0
        ),
        pos_pct=getattr(ta_result, "suggested_position_size", 0) * 100,
        time_horizon=getattr(ta_result, "time_horizon", "n/a"),
        # Direction-aware levels — derived from |stop_distance| so SHORT
        # recommendations get a wider stop ABOVE current and target BELOW,
        # and LONGs get the mirror, regardless of the TA-verdict's symmetry.
        **_directional_levels(report.current_price, ta_result),
        s_weight=report.sentiment.weight,
        s_score=report.sentiment.score,
        s_label=report.sentiment.label,
        s_rationale=report.sentiment.rationale,
        overall=report.overall_score,
        verdict=report.overall_label,
        macro_block=_format_macro_block(report.macro_context),
        earnings_block=_format_earnings_block(report.earnings_context),
        insider_block=_format_insider_block(report.insider_context),
        fg_block=_format_fg_block(report.fear_greed_context),
    )

    # First attempt — if JSON parse fails, retry once with a stricter
    # reminder. LLMs occasionally emit malformed JSON (trailing commas,
    # markdown fences, prose). Without retry the user has to click
    # "Run research" again to get a result.
    raw, model_name = _call_research_llm(prompt, advanced=advanced)
    parsed = _parse_research_json(raw) if raw else None
    if parsed is None:
        retry_prompt = prompt + (
            "\n\nIMPORTANT: Your previous response could not be parsed as JSON. "
            "Reply with ONLY the JSON object, nothing else. No markdown fences, "
            "no preamble, no trailing commentary. Start with { and end with }."
        )
        raw2, model_name = _call_research_llm(retry_prompt, advanced=advanced)
        parsed = _parse_research_json(raw2) if raw2 else None
        if parsed is None:
            logger.warning(f"Research narrative failed to parse after 2 attempts ({report.symbol})")
            return None
    parsed["model"] = model_name
    return parsed


def _call_research_llm(prompt: str, advanced: bool) -> Tuple[Optional[str], str]:
    """Dispatch to OpenRouter primarily; fall back to local Ollama on failure.

    The provider preference is:
      1. OpenRouter (cloud Qwen 72B free by default — fast, smart)
      2. Local Ollama (offline fallback when OpenRouter unconfigured / down)

    ``advanced=True`` forces OpenRouter and refuses the Ollama fallback —
    used when the user explicitly wants cloud-only quality.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("LLM_API_KEY", "")

    # Try OpenRouter first when key is set
    if api_key:
        from advisor.llm_advisor import _openrouter_model_chain
        chain = _openrouter_model_chain(heavy=advanced)
        for candidate in chain:
            raw = _call_openai_compat(prompt, candidate, "https://openrouter.ai/api/v1", api_key)
            if raw:
                return raw, candidate
        if advanced:
            logger.warning(f"All OpenRouter models failed and advanced=True (no Ollama fallback)")
            return None, ""

    if advanced:
        # Advanced explicitly requested but no key → fail closed instead of
        # silently degrading to local
        logger.warning("Advanced research requested but OPENROUTER_API_KEY not set")
        return None, ""

    # Offline fallback — local Ollama
    model = os.environ.get("LOCAL_LLM_MODEL") or "qwen2.5:14b-instruct-q4_K_M"
    return _call_ollama(prompt, model), model


def _call_ollama(prompt: str, model: str, timeout: float = 120.0) -> Optional[str]:
    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False,
                  "format": "json", "options": {"temperature": 0.4}},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json().get("response", "")
    except Exception as exc:
        logger.warning(f"Ollama research call failed: {exc}")
        return None


def _call_openai_compat(prompt: str, model: str, base_url: str, api_key: str,
                        timeout: float = 90.0) -> Optional[str]:
    try:
        r = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are an equity research analyst. Reply with strict JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 1500,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning(f"OpenRouter call failed: {exc}")
        return None


def _parse_research_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull a JSON object out of the LLM response (handles fenced blocks)."""
    if not text:
        return None
    text = text.strip()
    # Strip markdown fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    # Find first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = text[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        logger.warning(f"Research JSON parse failed: {exc}")
        return None


# ── Prompt block formatters ─────────────────────────────────────────


def _format_news_block(symbol: str, hours: int = 168, limit: int = 8) -> str:
    """Pull recent news headlines for the symbol so the LLM can name real
    catalysts. 7-day window by default — long enough to capture last week's
    moves but recent enough to be relevant.
    """
    try:
        from news.storage import NewsStorage
        storage = NewsStorage()
        articles = storage.get_articles(symbols=[symbol.upper()], hours=hours, limit=limit)
        if not articles:
            return "  (no news in last 7 days)"
        lines: List[str] = []
        for a in articles[:limit]:
            ts = getattr(a, "published_at", None) or getattr(a, "fetched_at", None)
            ts_str = ""
            if ts:
                try:
                    ts_str = (str(ts)[:10])
                except Exception:
                    pass
            head = f"  - [{ts_str}] {a.headline}"
            if getattr(a, "summary", None):
                head += f" — {a.summary[:140]}"
            lines.append(head)
        return "\n".join(lines)
    except Exception as exc:
        logger.debug(f"news block fetch failed for {symbol}: {exc}")
        return "  (news lookup failed)"


def _format_macro_block(macro: Dict[str, Any]) -> str:
    if not macro:
        return "  (FRED feed not configured — no macro context available)"
    lines: List[str] = []
    for sid, obs in macro.items():
        v = obs.get("value")
        chg = obs.get("change")
        chg_str = f" (Δ {chg:+.2f})" if chg is not None else ""
        if v is not None:
            lines.append(f"  {obs.get('name', sid)}: {v:.2f}{chg_str} as of {obs.get('date', '')}")
    return "\n".join(lines) if lines else "  (no macro data)"


def _format_earnings_block(earn: Dict[str, Any]) -> str:
    if not earn:
        return "  No upcoming earnings tracked for this symbol."
    date = earn.get("date") or "unknown"
    days = earn.get("days_until")
    eps = earn.get("eps_estimate")
    rev = earn.get("revenue_estimate")
    hour = earn.get("hour", "")
    parts = [f"  Next earnings: {date}"]
    if days is not None:
        urgency = ""
        if days <= 2:
            urgency = " (IMMINENT — within 2 days)"
        elif days <= 7:
            urgency = " (within 1 week)"
        elif days <= 14:
            urgency = " (within 2 weeks)"
        parts.append(f"  Days until: {days}{urgency}")
    if hour:
        parts.append(f"  Time: {'before market open' if hour == 'bmo' else 'after market close' if hour == 'amc' else hour}")
    if eps is not None:
        parts.append(f"  Consensus EPS estimate: {eps:.2f}")
    if rev is not None:
        parts.append(f"  Consensus revenue estimate: ${rev:,.0f}")
    return "\n".join(parts)


def _format_insider_block(insider: Dict[str, Any]) -> str:
    if not insider:
        return "  (Finnhub not configured or no insider data)"
    buys = insider.get("buys", 0)
    sells = insider.get("sells", 0)
    buy_v = insider.get("buy_value_usd", 0) or 0
    sell_v = insider.get("sell_value_usd", 0) or 0
    net_v = insider.get("net_value_usd", 0) or 0
    tone = insider.get("tone", "neutral")
    if buys == 0 and sells == 0:
        return "  No insider transactions in the last 180 days."
    flag = ""
    if abs(net_v) > 100_000_000:
        flag = " — MATERIAL SIZE"
    return (
        f"  Buys: {buys} (${buy_v:,.0f})  /  Sells: {sells} (${sell_v:,.0f})\n"
        f"  Net: ${net_v:,.0f} → tone {tone.upper()}{flag}"
    )


def _format_fg_block(fg: Dict[str, Any]) -> str:
    if not fg:
        return "  (Fear & Greed unavailable)"
    v = fg.get("value", 50)
    label = fg.get("label", "")
    flag = ""
    if fg.get("is_extreme_fear"):
        flag = " — historically a contrarian buy zone"
    elif fg.get("is_extreme_greed"):
        flag = " — historically a contrarian caution zone"
    return f"  Crypto F&G index: {v}/100 ({label}){flag}"
