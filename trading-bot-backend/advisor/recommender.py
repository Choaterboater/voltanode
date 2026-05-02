"""Multi-factor recommendation engine.

Synthesises indicator readings across trend, momentum, volume, volatility,
institutional, and sentiment categories into a weighted final verdict.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from advisor.indicators import (
    compute_adx,
    compute_atr,
    compute_bollinger_bands,
    compute_ema,
    compute_ichimoku,
    compute_macd,
    compute_pivot_points,
    compute_rsi,
    compute_sma,
    compute_supertrend,
    compute_vwap,
)


class RecommendationEngine:
    """Synthesises all signals into a final verdict with confidence."""

    INDICATOR_WEIGHTS = {
        "trend": 0.25,         # EMA, Supertrend, Ichimoku, ADX
        "momentum": 0.20,    # RSI, MACD, Stochastic, Williams %R
        "volume": 0.15,      # OBV, CMF, MFI
        "volatility": 0.15,  # Bollinger, ATR
        "institutional": 0.15,  # VWAP, Pivot Points
        "sentiment": 0.10,   # Price vs key levels
    }

    # Mapping of individual indicator -> category
    CATEGORY_MAP = {
        "sma_20": "trend",
        "sma_50": "trend",
        "ema_20": "trend",
        "ema_50": "trend",
        "supertrend": "trend",
        "adx": "trend",
        "ichimoku": "trend",
        "rsi": "momentum",
        "macd": "momentum",
        "stochastic": "momentum",
        "williams_r": "momentum",
        "mfi": "momentum",
        "obv": "volume",
        "cmf": "volume",
        "bollinger": "volatility",
        "atr": "volatility",
        "vwap": "institutional",
        "pivot_points": "institutional",
        "fibonacci": "sentiment",
        "efi": "volume",
    }

    def recommend(
        self,
        indicator_readings: List[Dict[str, any]],
        data: pd.DataFrame,
        current_price: float,
    ) -> Tuple[str, float, str]:
        """Generate final recommendation.

        Args:
            indicator_readings: List of dicts with keys name, value, signal, strength.
            data: OHLCV DataFrame.
            current_price: Last known price.

        Returns:
            Tuple of (verdict, confidence_score_0_100, summary_text).
        """
        if not indicator_readings:
            return "HOLD", 50.0, "Insufficient data for analysis."

        # Aggregate scores per category
        category_scores: Dict[str, List[float]] = {k: [] for k in self.INDICATOR_WEIGHTS}
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        key_reasons: List[str] = []

        for reading in indicator_readings:
            # Handle both dataclass objects and dicts
            if hasattr(reading, "name"):
                name = reading.name
                signal = reading.signal
                strength = reading.strength
                description = reading.description
            else:
                name = reading.get("name", "")
                signal = reading.get("signal", "neutral")
                strength = reading.get("strength", 0.5)
                description = reading.get("description", "")

            # Normalise signal to numeric score: bullish=+1, bearish=-1, neutral=0
            if signal == "bullish":
                score = strength
                bullish_count += 1
            elif signal == "bearish":
                score = -strength
                bearish_count += 1
            else:
                score = 0.0
                neutral_count += 1

            cat = self._map_to_category(name)
            category_scores[cat].append(score)

            # Collect standout reasons
            if strength > 0.7 and signal != "neutral":
                key_reasons.append(description)

        # Compute weighted composite score (-1.0 to +1.0)
        composite = 0.0
        weight_sum = 0.0
        for cat, weight in self.INDICATOR_WEIGHTS.items():
            scores = category_scores[cat]
            if scores:
                cat_avg = np.mean(scores)
            else:
                cat_avg = 0.0
            composite += cat_avg * weight
            weight_sum += weight

        if weight_sum > 0:
            composite /= weight_sum

        # Determine verdict and confidence
        verdict, confidence = self._verdict_from_score(composite, data, current_price)

        # Build human-readable summary
        summary = self._build_summary(
            verdict, confidence, composite, bullish_count, bearish_count, neutral_count, key_reasons, data, current_price
        )

        return verdict, confidence, summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _map_to_category(self, indicator_name: str) -> str:
        """Map an indicator name to its analysis category."""
        indicator_name = indicator_name.lower().replace(" ", "_")
        for key, cat in self.CATEGORY_MAP.items():
            if key in indicator_name:
                return cat
        return "sentiment"

    def _verdict_from_score(self, composite: float, data: pd.DataFrame, current_price: float) -> Tuple[str, float]:
        """Map composite score to verdict and confidence.

        Args:
            composite: -1.0 (strong bearish) to +1.0 (strong bullish).
            data: OHLCV DataFrame for volatility context.
            current_price: Current price.

        Returns:
            (verdict string, confidence 0-100).
        """
        # Base confidence from |composite|
        base_conf = min(abs(composite) * 100, 100.0)

        # Volatility adjustment — high vol reduces confidence
        try:
            atr = compute_atr(data, 14).iloc[-1]
            atr_pct = atr / current_price if current_price > 0 else 0
            if atr_pct > 0.05:
                base_conf *= 0.85
            elif atr_pct > 0.03:
                base_conf *= 0.92
        except Exception:
            pass

        # Trend strength bonus
        try:
            adx = compute_adx(data, 14)
            adx_val = adx["adx"].iloc[-1]
            if adx_val > 25:
                base_conf = min(base_conf * 1.05, 95.0)
            elif adx_val < 15:
                base_conf *= 0.90
        except Exception:
            pass

        confidence = round(max(0.0, min(100.0, base_conf)), 1)

        # Verdict thresholds
        if composite >= 0.60:
            return "STRONG_BUY", confidence
        elif composite >= 0.25:
            return "BUY", confidence
        elif composite <= -0.60:
            return "STRONG_SELL", confidence
        elif composite <= -0.25:
            return "SELL", confidence
        else:
            return "HOLD", confidence

    def _build_summary(
        self,
        verdict: str,
        confidence: float,
        composite: float,
        bullish_count: int,
        bearish_count: int,
        neutral_count: int,
        key_reasons: List[str],
        data: pd.DataFrame,
        current_price: float,
    ) -> str:
        """Build rich, human-readable summary text."""
        total = bullish_count + bearish_count + neutral_count
        if total == 0:
            return "No indicators available. HOLD with 50% confidence."

        # Sentence 1: overall stance
        direction = "bullish" if composite > 0 else "bearish" if composite < 0 else "neutral"
        strength_word = "strong" if abs(composite) > 0.5 else "moderate" if abs(composite) > 0.25 else "weak"

        parts: List[str] = []
        parts.append(
            f"Analysis of {total} indicators reveals a {strength_word} {direction} bias ({bullish_count} bullish, {bearish_count} bearish, {neutral_count} neutral)."
        )

        # Sentence 2: top reasons
        top_reasons = key_reasons[:3]
        if top_reasons:
            parts.append("Key observations: " + "; ".join(top_reasons) + ".")

        # Sentence 3: context-specific colour
        try:
            rsi = compute_rsi(data, 14).iloc[-1]
            if not pd.isna(rsi):
                if rsi > 70:
                    parts.append("RSI indicates overbought conditions, suggesting caution for new longs.")
                elif rsi < 30:
                    parts.append("RSI indicates oversold conditions, presenting potential buying opportunity.")
        except Exception:
            pass

        try:
            vwap = compute_vwap(data).iloc[-1]
            if not pd.isna(vwap):
                if current_price > vwap:
                    parts.append(f"Price trading above VWAP ({round(vwap, 2)}) signals institutional accumulation.")
                else:
                    parts.append(f"Price below VWAP ({round(vwap, 2)}) suggests institutional distribution.")
        except Exception:
            pass

        try:
            st = compute_supertrend(data, 10, 3.0)
            direction_val = st["direction"].iloc[-1]
            if direction_val == 1:
                parts.append("Supertrend is bullish, confirming upward momentum.")
            else:
                parts.append("Supertrend is bearish, confirming downward momentum.")
        except Exception:
            pass

        try:
            macd = compute_macd(data)
            hist = macd["histogram"].iloc[-1]
            prev_hist = macd["histogram"].iloc[-2] if len(macd["histogram"]) > 1 else hist
            if abs(hist) < abs(prev_hist) * 0.5 and hist * prev_hist > 0:
                parts.append("MACD histogram is shrinking, suggesting momentum may be fading.")
            elif hist > 0 and prev_hist <= 0:
                parts.append("MACD histogram turned positive — bullish crossover signal.")
            elif hist < 0 and prev_hist >= 0:
                parts.append("MACD histogram turned negative — bearish crossover signal.")
        except Exception:
            pass

        # Final sentence: verdict
        parts.append(f"Overall: {verdict.replace('_', ' ')} with {confidence}% confidence.")

        return " ".join(parts)
