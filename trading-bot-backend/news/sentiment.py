"""Sentiment analysis engine with VADER (local) and LLM (Kimi/Claude/OpenAI) backends."""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from news.models import NewsArticle, SentimentResult

logger = logging.getLogger("volta.news")


class SentimentEngine:
    """Dual-tier sentiment analysis.

    - **Fast tier**: VADER (free, local, no API key needed)
    - **Smart tier**: LLM (Kimi, Claude, OpenAI, Ollama) for deeper analysis
    """

    def __init__(
        self,
        llm_provider: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> None:
        """Initialize sentiment engine.

        Args:
            llm_provider: "kimi", "claude", "openai", or None for VADER-only.
            llm_api_key: API key for the chosen provider.
            llm_model: Model name (e.g., "claude-3-haiku", "gpt-3.5-turbo").
        """
        self.llm_provider = llm_provider or os.environ.get("LLM_PROVIDER", "")
        self.llm_api_key = llm_api_key or os.environ.get("LLM_API_KEY", "")
        self.llm_model = llm_model or os.environ.get("LLM_MODEL", "")
        self._vader = None

    # ------------------------------------------------------------------
    # VADER (fast, free, local)
    # ------------------------------------------------------------------

    def _get_vader(self):
        """Lazy-load VADER."""
        if self._vader is None:
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                self._vader = SentimentIntensityAnalyzer()
            except ImportError:
                logger.warning("vaderSentiment not installed. Run: pip install vaderSentiment")
                return None
        return self._vader

    def analyze_vader(self, article: NewsArticle, symbol: str) -> Optional[SentimentResult]:
        """Analyze sentiment using VADER.

        Returns None if VADER is not installed.
        """
        analyzer = self._get_vader()
        if analyzer is None:
            return None

        text = f"{article.headline}. {article.summary}"
        scores = analyzer.polarity_scores(text)

        compound = scores["compound"]
        if compound >= 0.05:
            confidence = min(1.0, abs(compound) * 1.5)
        elif compound <= -0.05:
            confidence = min(1.0, abs(compound) * 1.5)
        else:
            confidence = 1.0 - abs(compound) * 10  # neutral = lower confidence

        return SentimentResult(
            article_id=article.id,
            symbol=symbol,
            compound_score=compound,
            positive_score=scores["pos"],
            negative_score=scores["neg"],
            neutral_score=scores["neu"],
            confidence=round(confidence, 4),
            model="vader",
        )

    # ------------------------------------------------------------------
    # LLM (smart, API-based)
    # ------------------------------------------------------------------

    def analyze_llm(self, article: NewsArticle, symbol: str) -> Optional[SentimentResult]:
        """Analyze sentiment using an LLM API.

        Returns None if no provider is configured or the call fails.
        """
        if not self.llm_provider or not self.llm_api_key:
            return None

        prompt = self._build_prompt(article, symbol)

        try:
            if self.llm_provider.lower() == "kimi":
                result = self._call_kimi(prompt)
            elif self.llm_provider.lower() in ("claude", "anthropic"):
                result = self._call_claude(prompt)
            elif self.llm_provider.lower() == "openai":
                result = self._call_openai(prompt)
            elif self.llm_provider.lower() == "ollama":
                result = self._call_ollama(prompt)
            else:
                logger.warning(f"Unknown LLM provider: {self.llm_provider}")
                return None
            return self._parse_llm_result(result, article.id, symbol, self.llm_provider or "llm")
        except Exception as exc:
            logger.error(f"LLM sentiment analysis failed: {exc}")
            return None

    @staticmethod
    def _build_prompt(article: NewsArticle, symbol: str) -> str:
        return (
            f"Analyze the market sentiment of this news article for {symbol}.\n\n"
            f"Headline: {article.headline}\n"
            f"Summary: {article.summary}\n"
            f"Source: {article.source}\n\n"
            "Respond with ONLY a JSON object in this exact format:\n"
            "{\n"
            '  "compound_score": float (-1.0 to 1.0),\n'
            '  "positive_score": float (0.0 to 1.0),\n'
            '  "negative_score": float (0.0 to 1.0),\n'
            '  "neutral_score": float (0.0 to 1.0),\n'
            '  "confidence": float (0.0 to 1.0),\n'
            '  "impact_assessment": "high" | "medium" | "low",\n'
            '  "key_themes": ["string", ...]\n'
            "}\n"
            "Be objective and focus on price-relevant information."
        )

    def _call_kimi(self, prompt: str) -> str:
        """Call Moonshot Kimi API."""
        import requests
        model = self.llm_model or "moonshot-v1-8k"
        resp = requests.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_claude(self, prompt: str) -> str:
        """Call Anthropic Claude API."""
        import requests
        model = self.llm_model or "claude-3-haiku-20240307"
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.llm_api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI-compatible API (OpenAI, Groq, OpenRouter, etc.)."""
        import requests
        model = self.llm_model or "gpt-3.5-turbo"
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _call_ollama(self, prompt: str) -> str:
        """Call local Ollama instance.

        Requires Ollama running locally (http://localhost:11434).
        """
        import requests
        model = self.llm_model or "llama3.2:3b"
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["response"]

    @staticmethod
    def _parse_llm_result(text: str, article_id: str, symbol: str, model_name: str = "llm") -> SentimentResult:
        """Extract JSON from LLM response."""
        # Try to find JSON block
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        data = json.loads(text)
        return SentimentResult(
            article_id=article_id,
            symbol=symbol,
            compound_score=float(data.get("compound_score", 0)),
            positive_score=float(data.get("positive_score", 0)),
            negative_score=float(data.get("negative_score", 0)),
            neutral_score=float(data.get("neutral_score", 0)),
            confidence=float(data.get("confidence", 0)),
            model=model_name,
            impact_assessment=data.get("impact_assessment", ""),
            key_themes=data.get("key_themes", []),
        )

    # ------------------------------------------------------------------
    # Combined analysis
    # ------------------------------------------------------------------

    def analyze(
        self, article: NewsArticle, symbol: Optional[str] = None
    ) -> List[SentimentResult]:
        """Analyze sentiment for an article.

        If no symbol is provided, analyzes for each symbol mentioned.

        Hybrid mode (default):
            - VADER always runs (fast, free)
            - LLM only runs when VADER confidence is below threshold
              or the sentiment is near-neutral (uncertain)

        Non-hybrid mode:
            - Both VADER and LLM run on every article.
        """
        targets = [symbol] if symbol else article.symbols
        results: List[SentimentResult] = []

        for sym in targets:
            # Fast tier: VADER always runs
            vader_result = self.analyze_vader(article, sym)
            if vader_result:
                results.append(vader_result)

            # Decide whether to run LLM
            run_llm = False
            if self.llm_provider:
                if self.hybrid_mode and vader_result:
                    # Run LLM if VADER is uncertain
                    if vader_result.confidence < self.hybrid_threshold:
                        run_llm = True
                    # Run LLM if sentiment is near-neutral (borderline)
                    if abs(vader_result.compound_score) < 0.15:
                        run_llm = True
                elif not self.hybrid_mode:
                    run_llm = True

            if run_llm:
                llm_result = self.analyze_llm(article, sym)
                if llm_result:
                    results.append(llm_result)

        return results
