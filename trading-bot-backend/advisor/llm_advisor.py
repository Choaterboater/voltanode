"""Hybrid LLM commentary layer for the AI Advisor.

Takes the deterministic TA output (indicator readings, verdict, confidence,
price targets) plus the last 24h of news for the symbol, and asks the
configured LLM (Ollama / OpenAI / Anthropic / OpenRouter) for a written
narrative + agreement check + blended confidence.

The LLM is fed structured numeric inputs and real article snippets — it does
NOT invent prices. If the LLM is unreachable or unconfigured, this module
returns ``None`` so the caller falls back to pure TA gracefully.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests

from advisor.models import AnalysisResult, IndicatorReading, LLMCommentary

logger = logging.getLogger("volta.advisor.llm")


# ──────────────────────────────────────────────────────────────────────
# Symbol mapping helpers
# ──────────────────────────────────────────────────────────────────────

# CoinGecko-id → ticker (matches news storage which uses tickers)
_CG_TO_TICKER: Dict[str, str] = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "cardano": "ADA",
    "ripple": "XRP", "polkadot": "DOT", "chainlink": "LINK", "avalanche-2": "AVAX",
    "matic-network": "MATIC", "binancecoin": "BNB", "dogecoin": "DOGE",
    "shiba-inu": "SHIB", "tron": "TRX", "litecoin": "LTC", "bitcoin-cash": "BCH",
    "uniswap": "UNI", "cosmos": "ATOM", "ethereum-classic": "ETC", "stellar": "XLM",
    "filecoin": "FIL", "algorand": "ALGO", "near": "NEAR", "aave": "AAVE",
}


def _normalize_symbol_for_news(symbol: str, asset_type: str) -> str:
    """Convert advisor symbol into the ticker form news storage uses (UPPER)."""
    s = (symbol or "").strip()
    if asset_type == "crypto":
        return _CG_TO_TICKER.get(s.lower(), s.upper())
    return s.upper()


# ──────────────────────────────────────────────────────────────────────
# News retrieval
# ──────────────────────────────────────────────────────────────────────

def _fetch_recent_news(ticker: str, hours: int = 24, limit: int = 8) -> Dict[str, Any]:
    """Pull recent articles + sentiment summary for a ticker.

    Returns ``{"articles": [...], "summary": {...}}`` or ``{}`` on failure.
    Uses the existing news storage so this never makes external API calls.
    """
    try:
        from news.storage import NewsStorage
        storage = NewsStorage()
        scores = storage.get_sentiment_for_symbol(ticker, hours=hours)
        if not scores:
            return {"articles": [], "summary": None}

        # Build summary
        compounds = [s.compound_score for s in scores]
        avg = sum(compounds) / len(compounds)
        label = "bullish" if avg > 0.2 else "bearish" if avg < -0.2 else "neutral"

        # Pull article details (deduped by article_id)
        seen: set = set()
        rows: List[Dict[str, Any]] = []
        articles = storage.get_articles(symbols=[ticker], hours=hours, limit=limit * 2)
        for a in articles:
            if a.id in seen:
                continue
            seen.add(a.id)
            score = next((s for s in scores if s.article_id == str(a.id) or s.article_id == a.id), None)
            rows.append({
                "headline": a.headline,
                "summary": (a.summary or "")[:240],
                "source": a.source,
                "compound": round(score.compound_score, 3) if score else None,
                "impact": (score.impact_assessment if score else None) or "—",
                "themes": list(getattr(score, "key_themes", []) or [])[:3] if score else [],
            })
            if len(rows) >= limit:
                break

        return {
            "articles": rows,
            "summary": {
                "article_count": len(scores),
                "avg_compound": round(avg, 3),
                "label": label,
            },
        }
    except Exception as exc:
        logger.warning(f"News retrieval for advisor failed for {ticker}: {exc}")
        return {}


# ──────────────────────────────────────────────────────────────────────
# Prompt construction
# ──────────────────────────────────────────────────────────────────────

def _format_indicators(readings: List[IndicatorReading], top_n: int = 6) -> str:
    """Pick the strongest signals (any direction) and render as bullets."""
    sorted_r = sorted(readings, key=lambda r: r.strength, reverse=True)
    lines = []
    for r in sorted_r[:top_n]:
        lines.append(
            f"  - {r.name}: {r.signal} (strength {r.strength:.2f}, value {r.value:.4f}) — {r.description}"
        )
    return "\n".join(lines) if lines else "  (no readings)"


def _format_news(news_data: Dict[str, Any]) -> str:
    summary = news_data.get("summary")
    articles = news_data.get("articles", [])
    if not summary or not articles:
        return "  (no recent news for this symbol)"
    head = (
        f"  Sentiment summary over last 24h: avg_compound={summary['avg_compound']}, "
        f"label={summary['label']}, articles={summary['article_count']}\n"
        f"  Recent headlines:"
    )
    bullets = []
    for a in articles[:6]:
        themes = ", ".join(a.get("themes") or [])
        themes_str = f" | themes: {themes}" if themes else ""
        compound = a.get("compound")
        compound_str = f" | sent: {compound:+.2f}" if compound is not None else ""
        bullets.append(
            f"    • [{a['source']}] {a['headline']}"
            f" (impact: {a['impact']}{compound_str}{themes_str})"
        )
    return f"{head}\n" + "\n".join(bullets)


def _build_prompt(result: AnalysisResult, news_data: Dict[str, Any]) -> str:
    """Construct the structured prompt sent to the LLM."""
    targets_str = "\n".join(
        f"  - {t.label}: ${t.price:.4f} (probability {t.probability:.0%}) — {t.rationale}"
        for t in result.price_targets[:4]
    ) or "  (no targets)"

    return f"""You are a professional trading analyst providing a SECOND OPINION on a deterministic technical analysis verdict. Be concise, factual, and ground every claim in the data given. Do NOT invent prices, percentages, or facts not present in the inputs.

SYMBOL: {result.symbol} ({result.asset_type})
CURRENT PRICE: ${result.current_price:.4f}

DETERMINISTIC TA VERDICT: {result.verdict} (confidence {result.confidence:.1f}%)
TA SUMMARY: {result.summary}
RISK LEVEL: {result.risk_level} | TIME HORIZON: {result.time_horizon}

TOP INDICATOR READINGS (sorted by strength):
{_format_indicators(result.indicators)}

PRICE TARGETS (technical):
{targets_str}

RECENT NEWS:
{_format_news(news_data)}

TASK: Reply with ONLY a JSON object — no prose before or after — with this exact shape:
{{
  "agreement": "agrees" | "disagrees" | "mixed",
  "alternative_verdict": "" | "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL",
  "adjusted_confidence": <number 0-100>,
  "news_impact": "high" | "medium" | "low" | "none",
  "key_factors": ["...", "...", "..."],
  "rationale": "2-3 sentence narrative tying TA + news together"
}}

Rules:
- "agreement" = whether the news/context supports the TA verdict
- "alternative_verdict" = REQUIRED when "agreement" is "disagrees": the action you would take instead (BUY/SELL/HOLD/STRONG_BUY/STRONG_SELL). Empty string ONLY when you agree or are mixed.
- "adjusted_confidence" = your blended confidence after considering news; if no news, return the TA confidence rounded
- "news_impact" = how materially the news could move price ("none" if there's no news)
- "key_factors" = 3-5 concrete drivers, e.g. "RSI 72 overbought", "META beat earnings", "no fresh catalysts"
- "rationale" = plain English, max 3 sentences. If you disagree, briefly justify your alternative_verdict.
"""


# ──────────────────────────────────────────────────────────────────────
# LLM transports
# ──────────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, model: str, timeout: float = 60.0) -> Optional[str]:
    base = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        r = requests.post(
            f"{base}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json().get("response", "")
    except Exception as exc:
        logger.warning(f"Ollama call failed: {exc}")
        return None


def _call_openai_compat(prompt: str, model: str, base_url: str, api_key: str, timeout: float = 60.0) -> Optional[str]:
    """OpenAI-compatible Chat Completions endpoint (also works for OpenRouter)."""
    try:
        r = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning(f"{base_url} call failed: {exc}")
        return None


def _call_anthropic(prompt: str, model: str, api_key: str, timeout: float = 60.0) -> Optional[str]:
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data["content"][0]["text"]
    except Exception as exc:
        logger.warning(f"Anthropic call failed: {exc}")
        return None


# ──────────────────────────────────────────────────────────────────────
# Response parsing
# ──────────────────────────────────────────────────────────────────────

def _parse_response(raw: str, fallback_confidence: float) -> Dict[str, Any]:
    """Extract the JSON blob; tolerate code fences and surrounding prose."""
    if not raw:
        return {}
    # Strip code fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    # Find the outermost {...}
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}

    # Coerce / validate
    agreement = str(obj.get("agreement", "mixed")).lower()
    if agreement not in ("agrees", "disagrees", "mixed"):
        agreement = "mixed"
    try:
        adj_conf = float(obj.get("adjusted_confidence", fallback_confidence))
        adj_conf = max(0.0, min(100.0, adj_conf))
    except (TypeError, ValueError):
        adj_conf = fallback_confidence
    news_impact = str(obj.get("news_impact", "none")).lower()
    if news_impact not in ("high", "medium", "low", "none"):
        news_impact = "none"
    factors = obj.get("key_factors", [])
    if not isinstance(factors, list):
        factors = []
    factors = [str(f).strip() for f in factors if str(f).strip()][:5]
    rationale = str(obj.get("rationale", "")).strip()

    alt_verdict = str(obj.get("alternative_verdict", "")).strip().upper()
    valid_verdicts = {"", "BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL"}
    if alt_verdict not in valid_verdicts:
        alt_verdict = ""

    return {
        "agreement": agreement,
        "alternative_verdict": alt_verdict,
        "adjusted_confidence": adj_conf,
        "news_impact": news_impact,
        "key_factors": factors,
        "rationale": rationale,
    }


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

def generate_commentary(
    result: AnalysisResult, override_provider: Optional[str] = None
) -> Optional[LLMCommentary]:
    """Produce blended LLM commentary for an analysis result.

    When ``override_provider`` is supplied (e.g. ``"openrouter"`` from the
    Advanced toggle), it takes precedence over ``LLM_PROVIDER``. OpenRouter
    reads ``OPENROUTER_API_KEY`` so it doesn't collide with whatever
    ``LLM_API_KEY`` is set to for the default provider.

    Returns ``None`` if no LLM is configured or the call fails — callers should
    fall back to pure TA in that case.
    """
    provider = (override_provider or os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if not provider:
        return None

    ticker = _normalize_symbol_for_news(result.symbol, result.asset_type)
    news_data = _fetch_recent_news(ticker)
    prompt = _build_prompt(result, news_data)

    raw: Optional[str] = None
    model_name = ""

    if provider == "ollama":
        model_name = os.environ.get("LLM_MODEL", "llama3.1:8b")
        raw = _call_ollama(prompt, model_name)
    elif provider == "openai":
        api_key = os.environ.get("LLM_API_KEY", "")
        if not api_key:
            logger.warning("LLM_PROVIDER=openai but LLM_API_KEY not set")
            return None
        model_name = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        raw = _call_openai_compat(prompt, model_name, "https://api.openai.com/v1", api_key)
    elif provider == "openrouter":
        # Prefer a dedicated OPENROUTER_API_KEY so users can keep a local
        # Ollama default while still wiring up cloud-grade analysis.
        api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("LLM_API_KEY", "")
        if not api_key:
            logger.warning("Advanced LLM requested but OPENROUTER_API_KEY not set")
            return None
        model_name = (
            os.environ.get("OPENROUTER_MODEL")
            or os.environ.get("LLM_MODEL", "anthropic/claude-3.5-sonnet")
        )
        raw = _call_openai_compat(prompt, model_name, "https://openrouter.ai/api/v1", api_key)
    elif provider == "anthropic":
        api_key = os.environ.get("LLM_API_KEY", "")
        if not api_key:
            return None
        model_name = os.environ.get("LLM_MODEL", "claude-3-5-sonnet-latest")
        raw = _call_anthropic(prompt, model_name, api_key)
    else:
        logger.warning(f"Unknown LLM_PROVIDER: {provider}")
        return None

    if not raw:
        return None

    parsed = _parse_response(raw, fallback_confidence=result.confidence)
    if not parsed:
        return None

    article_count = (news_data.get("summary") or {}).get("article_count", 0)
    alt = parsed.get("alternative_verdict", "")
    # Don't surface an alternative_verdict that's the same as the TA verdict
    if alt and alt == result.verdict.upper():
        alt = ""
    return LLMCommentary(
        rationale=parsed.get("rationale", ""),
        agreement=parsed.get("agreement", "mixed"),
        adjusted_confidence=parsed.get("adjusted_confidence", result.confidence),
        key_factors=parsed.get("key_factors", []),
        news_impact=parsed.get("news_impact", "none"),
        article_count=article_count,
        model=model_name,
        alternative_verdict=alt,
    )
