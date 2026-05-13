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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from advisor.models import AnalysisResult, IndicatorReading, LLMCommentary

logger = logging.getLogger("volta.advisor.llm")


# ──────────────────────────────────────────────────────────────────────
# LLM call stats — one row per attempt to data/collector/llm_model_stats.jsonl
# ──────────────────────────────────────────────────────────────────────
# Lets us see actual rate-limit pain and reorder the chain based on
# evidence instead of guessing.

_LLM_STATS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "collector" / "llm_model_stats.jsonl"
)
_LLM_STATS_LOCK = threading.Lock()


def record_llm_attempt(
    model: str,
    purpose: str,
    attempt: int,
    success: bool,
    latency_ms: float,
    error: Optional[str] = None,
    http_status: Optional[int] = None,
) -> None:
    """Append one row describing a single LLM model call.

    `purpose` is a short tag: 'sentiment', 'advisor', 'pretrade', 'research'.
    `attempt` is the 1-based position in the fallback chain.
    Silent on write failure — never let logging break a trade path.
    """
    try:
        _LLM_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "purpose": purpose,
            "attempt": attempt,
            "success": success,
            "latency_ms": round(latency_ms, 1),
            "error": error,
            "http_status": http_status,
        }
        with _LLM_STATS_LOCK, _LLM_STATS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────
# Symbol mapping helpers
# ──────────────────────────────────────────────────────────────────────

# CoinGecko-id → ticker (matches news storage which uses tickers)
_CG_TO_TICKER: Dict[str, str] = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "cardano": "ADA",
    "ripple": "XRP", "polkadot": "DOT", "chainlink": "LINK", "avalanche-2": "AVAX",
    "polygon-ecosystem-token": "MATIC", "binancecoin": "BNB", "dogecoin": "DOGE",
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


def _build_prompt(result: AnalysisResult, news_data: Dict[str, Any], heavy: bool = False) -> str:
    """Construct the structured prompt sent to the LLM.

    When ``heavy=True`` the prompt asks for richer reasoning — extra ``risk_factors``
    and ``catalysts`` arrays — leveraging the larger model's capacity.
    """
    targets_str = "\n".join(
        f"  - {t.label}: ${t.price:.4f} (probability {t.probability:.0%}) — {t.rationale}"
        for t in result.price_targets[:4]
    ) or "  (no targets)"
    extra_fields = ""
    extra_rules = ""
    if heavy:
        extra_fields = (
            ',\n  "risk_factors": ["specific downside risks visible in the data, 2-4 items"]'
            ',\n  "catalysts": ["specific upside catalysts or watch-items, 2-4 items"]'
        )
        extra_rules = (
            "\n- HEAVY MODE: also populate risk_factors and catalysts. Be specific — "
            "reference the actual indicators or headlines, no generic boilerplate."
        )

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
  "rationale": "2-3 sentence narrative tying TA + news together"{extra_fields}
}}

Rules:
- "agreement" = whether the news/context supports the TA verdict
- "alternative_verdict" = REQUIRED when "agreement" is "disagrees": the action you would take instead (BUY/SELL/HOLD/STRONG_BUY/STRONG_SELL). Empty string ONLY when you agree or are mixed.
- ANTI-OVERREACTION: you are reading TA indicators only — you do NOT have access to fundamentals, valuation, or earnings data. Therefore you MUST NOT swing more than ONE verdict step from the TA verdict. Allowed alternatives:
    TA HOLD       → BUY or SELL only (NEVER STRONG_BUY/STRONG_SELL)
    TA BUY        → STRONG_BUY or HOLD only
    TA SELL       → STRONG_SELL or HOLD only
    TA STRONG_BUY → BUY only (down-shift only, never further up)
    TA STRONG_SELL→ SELL only
  Reserve STRONG_BUY / STRONG_SELL ONLY when the TA verdict is already in that direction.
- "adjusted_confidence" = your blended confidence after considering news; if no news, return the TA confidence rounded. Do NOT swing the confidence by more than 25 points from the TA confidence.
- "news_impact" = how materially the news could move price ("none" if there's no news)
- "key_factors" = 3-5 concrete drivers, e.g. "RSI 72 overbought", "META beat earnings", "no fresh catalysts"
- "rationale" = plain English, max 3 sentences. If you disagree, briefly justify your alternative_verdict.{extra_rules}
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


_HEAVY_MODELS = [
    "inclusionai/ring-2.6-1t:free",            # 1T MoE — biggest available
    "openai/gpt-oss-120b:free",                # 120B, very reliable
    "nvidia/nemotron-3-super-120b-a12b:free",  # 120B
    "minimax/minimax-m2.5:free",               # large MoE, 196K ctx
    "z-ai/glm-4.5-air:free",                   # solid mid-large
]

_FAST_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",  # 70B, fast & reliable
    "google/gemma-4-31b-it:free",              # 31B, very fast
    "qwen/qwen3-next-80b-a3b-instruct:free",   # 80B Qwen3
    "tencent/hy3-preview:free",                # Hunyuan 3 preview
    "openai/gpt-oss-120b:free",                # last-resort heavy fallback
]


def _openrouter_model_chain(heavy: bool = False) -> List[str]:
    """Build the ordered list of OpenRouter model ids to try.

    Two preset chains:
      - ``heavy=True`` (Advanced toggle): 120B+/1T frontier models first.
        Slower (~3-15s) but substantially smarter reasoning and structure.
      - ``heavy=False`` (Standard): fast 30-70B models first. ~1-3s typical.

    The configured ``OPENROUTER_MODEL`` (or ``LLM_MODEL`` if set) is always
    tried first regardless of heavy. ``OPENROUTER_FALLBACK_MODELS`` overrides
    the default fallbacks (applied to whichever preset is selected).
    """
    primary = (
        os.environ.get("OPENROUTER_MODEL")
        or os.environ.get("LLM_MODEL", "")
    ).strip()
    # Skip non-OpenRouter primaries (e.g. Ollama tags like "qwen2.5:14b").
    if primary and "/" not in primary:
        primary = ""
    fb_env = os.environ.get("OPENROUTER_FALLBACK_MODELS", "").strip()
    if fb_env:
        fallbacks = [m.strip() for m in fb_env.split(",") if m.strip()]
    else:
        fallbacks = _HEAVY_MODELS if heavy else _FAST_MODELS
    chain: List[str] = []
    for m in [primary, *fallbacks]:
        if m and m not in chain:
            chain.append(m)
    return chain


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

    risks = obj.get("risk_factors", [])
    if not isinstance(risks, list):
        risks = []
    risks = [str(r).strip() for r in risks if str(r).strip()][:5]
    cats = obj.get("catalysts", [])
    if not isinstance(cats, list):
        cats = []
    cats = [str(c).strip() for c in cats if str(c).strip()][:5]

    return {
        "agreement": agreement,
        "alternative_verdict": alt_verdict,
        "adjusted_confidence": adj_conf,
        "news_impact": news_impact,
        "key_factors": factors,
        "rationale": rationale,
        "risk_factors": risks,
        "catalysts": cats,
    }


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

def generate_commentary(
    result: AnalysisResult,
    override_provider: Optional[str] = None,
    heavy: bool = False,
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
    prompt = _build_prompt(result, news_data, heavy=heavy)

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
        # Fallback chain — try the configured model first, then drop down
        # through a list of free OpenRouter models so a single 429 doesn't
        # collapse the Advanced path.
        models = _openrouter_model_chain(heavy=heavy)
        for attempt, candidate in enumerate(models, 1):
            t0 = time.time()
            raw = _call_openai_compat(prompt, candidate, "https://openrouter.ai/api/v1", api_key)
            record_llm_attempt(
                model=candidate,
                purpose="advisor",
                attempt=attempt,
                success=bool(raw),
                latency_ms=(time.time() - t0) * 1000,
            )
            if raw:
                model_name = candidate
                break
        if not raw:
            logger.warning(f"All OpenRouter models in chain failed: {models}")
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
    # Anti-overreaction: TA-only signal shouldn't swing more than one verdict
    # step. Without fundamentals, the LLM has no business going from HOLD →
    # STRONG_SELL or BUY → STRONG_SELL. Clamp server-side as a safety net.
    alt = _clamp_verdict_swing(result.verdict.upper(), alt)
    # Cap confidence swing to ±25 points so a TA-only LLM can't crater
    # confidence based purely on indicator tone.
    raw_conf = float(parsed.get("adjusted_confidence", result.confidence) or result.confidence)
    base_conf = float(result.confidence)
    clamped_conf = max(base_conf - 25, min(base_conf + 25, raw_conf))
    return LLMCommentary(
        rationale=parsed.get("rationale", ""),
        agreement=parsed.get("agreement", "mixed"),
        adjusted_confidence=round(clamped_conf, 1),
        key_factors=parsed.get("key_factors", []),
        news_impact=parsed.get("news_impact", "none"),
        article_count=article_count,
        model=model_name,
        alternative_verdict=alt,
        risk_factors=parsed.get("risk_factors", []),
        catalysts=parsed.get("catalysts", []),
    )


_VERDICT_LADDER = ["STRONG_SELL", "SELL", "HOLD", "BUY", "STRONG_BUY"]


def _clamp_verdict_swing(ta_verdict: str, llm_verdict: str) -> str:
    """Cap the LLM's alternative_verdict to one step away from TA on the
    BUY/HOLD/SELL ladder. TA-only LLM has no business jumping further."""
    if not llm_verdict:
        return ""
    try:
        ta_idx = _VERDICT_LADDER.index(ta_verdict)
        llm_idx = _VERDICT_LADDER.index(llm_verdict)
    except ValueError:
        return llm_verdict  # unrecognized — let it through, route validates
    if abs(llm_idx - ta_idx) <= 1:
        return llm_verdict
    # Clamp toward TA: shift to the closer of (ta-1, ta+1)
    direction = 1 if llm_idx > ta_idx else -1
    clamped_idx = max(0, min(len(_VERDICT_LADDER) - 1, ta_idx + direction))
    return _VERDICT_LADDER[clamped_idx]


# ──────────────────────────────────────────────────────────────────────────
# Pre-trade LLM gate (used by auto_discovery / squeeze before a BUY fires)
# ──────────────────────────────────────────────────────────────────────────
#
# Lightweight sanity check that runs in the strategy hot path before an
# auto-discovered BUY is submitted. Keeps prompts tiny (~200 tokens) and
# caches verdicts per (symbol, side) for 60s so a flapping signal doesn't
# burn the LLM budget. Fails OPEN — if the LLM is unreachable or slow we
# proceed with the original signal rather than block all trades.
#
# Cost envelope: with auto_discovery + squeeze covering ~30 symbols and a
# 60s cache TTL, worst case is ~30 calls/min (~1800/hr). On the OpenRouter
# free chain that's well inside daily limits.

_PRETRADE_CACHE: Dict[tuple, Dict[str, Any]] = {}
_PRETRADE_TTL_SECONDS: float = 60.0


def _pretrade_prompt(symbol: str, side: str, confidence: float, indicators: Dict[str, Any], current_price: float) -> str:
    rsi = indicators.get("rsi")
    breakout = indicators.get("breakout")
    rel_vol = indicators.get("rel_volume")
    score = indicators.get("score")
    return f"""You are a risk reviewer for an automated trading bot. The bot wants to {side} {symbol} based on a technical setup. Decide if there is anything OBVIOUSLY wrong with this trade right now.

SETUP:
- side: {side}
- symbol: {symbol}
- current_price: {current_price}
- bot_confidence: {confidence:.2f}
- indicators:
  - composite_score: {score}
  - rsi: {rsi}
  - breakout_position: {breakout}
  - relative_volume: {rel_vol}

Reply with ONE LINE of valid JSON, no markdown:
{{"verdict":"proceed"|"veto","reason":"<one short phrase>"}}

Rules:
- "proceed" by default — only "veto" if the setup is clearly broken (RSI > 85 chasing on a BUY, RSI < 15 on a SELL with no oversold reversion sign, near-zero volume, contradictory readings).
- Be conservative about vetoing — false positives stop the bot from making money.
- Do NOT veto based on missing data; treat missing as neutral.
- "reason" max 12 words."""


def _parse_pretrade(raw: str) -> Dict[str, Any]:
    """Parse the LLM's one-line JSON. Fail-open: any error → proceed."""
    try:
        # Strip markdown fences if the model returned them despite instructions.
        s = raw.strip()
        if s.startswith("```"):
            s = s.split("```", 2)[1]
            if s.lower().startswith("json"):
                s = s[4:]
            s = s.strip("` \n")
        obj = json.loads(s)
        verdict = str(obj.get("verdict", "")).strip().lower()
        if verdict not in ("proceed", "veto"):
            verdict = "proceed"
        reason = str(obj.get("reason", ""))[:80]
        return {"verdict": verdict, "reason": reason}
    except Exception:
        return {"verdict": "proceed", "reason": "parse_error"}


def pretrade_check(
    symbol: str,
    side: str,
    confidence: float,
    indicators: Dict[str, Any],
    current_price: float,
    timeout: float = 3.0,
    ttl: float = _PRETRADE_TTL_SECONDS,
) -> Dict[str, Any]:
    """Synchronous LLM sanity check for a pending trade. Returns dict with
    keys ``verdict`` (proceed|veto), ``reason``, ``cached``, ``model``.

    Cached for ``ttl`` seconds per (symbol, side). Fails open on any error:
    if the LLM is unreachable or times out, returns proceed so the bot is
    never blocked by an LLM outage.
    """
    import time

    key = (str(symbol).upper(), str(side).upper())
    now = time.monotonic()
    cached = _PRETRADE_CACHE.get(key)
    if cached and cached["expires_at"] > now:
        return {**cached["result"], "cached": True}

    provider = (os.environ.get("LLM_PROVIDER") or "openrouter").strip().lower()
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("LLM_API_KEY", "")
    if not api_key:
        return {"verdict": "proceed", "reason": "no_llm_key", "cached": False, "model": ""}

    prompt = _pretrade_prompt(symbol, side, confidence, indicators, current_price)
    raw: Optional[str] = None
    model_name = ""
    # Fast chain only — pretrade is hot path, no heavy frontier models.
    for attempt, candidate in enumerate(_openrouter_model_chain(heavy=False), 1):
        t0 = time.time()
        raw = _call_openai_compat(
            prompt,
            candidate,
            "https://openrouter.ai/api/v1",
            api_key,
            timeout=timeout,
        )
        record_llm_attempt(
            model=candidate,
            purpose="pretrade",
            attempt=attempt,
            success=bool(raw),
            latency_ms=(time.time() - t0) * 1000,
        )
        if raw:
            model_name = candidate
            break

    if not raw:
        # Don't cache failures — next call gets another shot.
        return {"verdict": "proceed", "reason": "llm_unreachable", "cached": False, "model": ""}

    result = _parse_pretrade(raw)
    result["model"] = model_name
    _PRETRADE_CACHE[key] = {"expires_at": now + ttl, "result": result}
    return {**result, "cached": False}
