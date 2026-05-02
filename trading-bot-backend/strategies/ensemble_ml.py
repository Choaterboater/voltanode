"""Ensemble ML strategy combining multiple indicators with weighted scoring."""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal

# Try to import sklearn; fallback to rule-based if not available
try:
    from sklearn.ensemble import RandomForestClassifier
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


class EnsembleMLStrategy(BaseStrategy):
    """Multi-indicator weighted scoring ensemble with optional ML."""

    name = "ensemble_ml"
    DEFAULT_CONFIG = {
        "indicators": {
            "rsi": {"weight": 0.2, "period": 14},
            "macd": {"weight": 0.3},
            "ema_cross": {"weight": 0.2, "fast": 12, "slow": 26},
            "bb_position": {"weight": 0.15, "period": 20},
            "volume_trend": {"weight": 0.15},
        },
        "buy_threshold": 0.6,
        "sell_threshold": -0.6,
        "use_ml": False,
    }

    def __init__(self, strategy_id: str, config: Dict[str, Any]) -> None:
        super().__init__(strategy_id, config)
        self._ml_model: Any | None = None
        self._feature_buffer: list[list[float]] = []
        self._label_buffer: list[int] = []
        if SKLEARN_AVAILABLE and self.config.get("use_ml", False):
            self._ml_model = RandomForestClassifier(
                n_estimators=50, max_depth=5, random_state=42
            )

    def _score_rsi(self, rsi: float) -> float:
        """Convert RSI to a score in [-1, 1].

        RSI < 30 -> positive (bullish reversal expected)
        RSI > 70 -> negative (bearish reversal expected)
        """
        if rsi < 30:
            return 1.0 - (rsi / 30)  # Strong positive when oversold
        if rsi > 70:
            return -((rsi - 70) / 30)  # Strong negative when overbought
        # Neutral zone: linear interpolation
        return (50 - rsi) / 20

    def _score_macd(self, macd_line: float, signal_line: float) -> float:
        """Score MACD crossover momentum."""
        diff = macd_line - signal_line
        # Normalize by typical MACD magnitude
        magnitude = max(abs(macd_line), abs(signal_line), 1.0)
        return np.clip(diff / magnitude * 2, -1, 1)

    def _score_ema_cross(self, fast: float, slow: float) -> float:
        """Score EMA crossover."""
        if slow == 0:
            return 0.0
        diff_pct = (fast - slow) / slow
        return np.clip(diff_pct * 50, -1, 1)

    def _score_bb_position(self, price: float, upper: float, lower: float) -> float:
        """Score Bollinger Band position.

        Near lower band = positive (bounce expected)
        Near upper band = negative (reversal expected)
        """
        if upper == lower:
            return 0.0
        position = (price - lower) / (upper - lower)
        # Map 0->1 to 1->-1
        return 1.0 - 2.0 * position

    def _score_volume_trend(self, volume: float, avg_volume: float) -> float:
        """Score volume trend."""
        if avg_volume == 0:
            return 0.0
        ratio = volume / avg_volume
        if ratio > 2.0:
            return 1.0  # Very high volume
        if ratio > 1.5:
            return 0.5
        if ratio > 1.0:
            return 0.2
        if ratio > 0.5:
            return -0.2
        return -0.5  # Low volume

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Generate signal using weighted ensemble of indicators.

        BUY if composite_score > buy_threshold (0.6)
        SELL if composite_score < sell_threshold (-0.6)
        """
        data = self._ensure_columns(data)
        cfg = self.config
        indicators = cfg["indicators"]
        buy_threshold = cfg.get("buy_threshold", 0.6)
        sell_threshold = cfg.get("sell_threshold", -0.6)

        if len(data) < 50:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=data.attrs.get("symbol", "unknown"),
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
            )

        scores: Dict[str, float] = {}
        weights: Dict[str, float] = {}

        close = data["close"]
        volume = data["volume"]

        # RSI score
        if "rsi" in indicators:
            rsi_cfg = indicators["rsi"]
            period = rsi_cfg.get("period", 14)
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = (-delta).clip(lower=0)
            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss.rolling(window=period).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            current_rsi = float(rsi.iloc[-1])
            scores["rsi"] = self._score_rsi(current_rsi)
            weights["rsi"] = rsi_cfg.get("weight", 0.2)

        # MACD score
        if "macd" in indicators:
            macd_cfg = indicators["macd"]
            ema_fast = close.ewm(span=12, adjust=False).mean()
            ema_slow = close.ewm(span=26, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            scores["macd"] = self._score_macd(
                float(macd_line.iloc[-1]), float(signal_line.iloc[-1])
            )
            weights["macd"] = macd_cfg.get("weight", 0.3)

        # EMA cross score
        if "ema_cross" in indicators:
            ema_cfg = indicators["ema_cross"]
            fast_span = ema_cfg.get("fast", 12)
            slow_span = ema_cfg.get("slow", 26)
            ema_f = close.ewm(span=fast_span, adjust=False).mean()
            ema_s = close.ewm(span=slow_span, adjust=False).mean()
            scores["ema_cross"] = self._score_ema_cross(
                float(ema_f.iloc[-1]), float(ema_s.iloc[-1])
            )
            weights["ema_cross"] = ema_cfg.get("weight", 0.2)

        # Bollinger position score
        if "bb_position" in indicators:
            bb_cfg = indicators["bb_position"]
            period = bb_cfg.get("period", 20)
            std_dev = bb_cfg.get("std", 2.0)
            sma = close.rolling(window=period).mean()
            std = close.rolling(window=period).std()
            upper = sma + std_dev * std
            lower = sma - std_dev * std
            scores["bb_position"] = self._score_bb_position(
                current_price,
                float(upper.iloc[-1]),
                float(lower.iloc[-1]),
            )
            weights["bb_position"] = bb_cfg.get("weight", 0.15)

        # Volume trend score
        if "volume_trend" in indicators:
            vol_cfg = indicators["volume_trend"]
            avg_volume = float(volume.rolling(window=20).mean().iloc[-1])
            current_volume = float(volume.iloc[-1])
            scores["volume_trend"] = self._score_volume_trend(
                current_volume, avg_volume
            )
            weights["volume_trend"] = vol_cfg.get("weight", 0.15)

        # Calculate weighted composite score
        composite = 0.0
        total_weight = 0.0
        for key in scores:
            composite += scores[key] * weights[key]
            total_weight += weights[key]

        if total_weight > 0:
            composite /= total_weight

        symbol = data.attrs.get("symbol", "unknown")

        # ML enhancement (if enabled and enough data)
        if SKLEARN_AVAILABLE and self._ml_model is not None and len(self._feature_buffer) >= 100:
            features = [
                scores.get("rsi", 0),
                scores.get("macd", 0),
                scores.get("ema_cross", 0),
                scores.get("bb_position", 0),
                scores.get("volume_trend", 0),
            ]
            try:
                prediction = self._ml_model.predict([features])[0]
                # Blend ML with rule-based
                composite = 0.7 * composite + 0.3 * (prediction * 2 - 1)
            except Exception:
                pass

        # Collect features for future training
        if SKLEARN_AVAILABLE and self._ml_model is not None:
            features = [
                scores.get("rsi", 0),
                scores.get("macd", 0),
                scores.get("ema_cross", 0),
                scores.get("bb_position", 0),
                scores.get("volume_trend", 0),
            ]
            self._feature_buffer.append(features)
            if len(self._feature_buffer) > 200:
                self._feature_buffer.pop(0)

        confidence = abs(composite)

        if composite > buy_threshold:
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=min(1.0, confidence),
                timestamp=pd.Timestamp.now(),
                metadata={
                    "composite_score": float(composite),
                    "component_scores": {k: float(v) for k, v in scores.items()},
                    "weights": {k: float(v) for k, v in weights.items()},
                },
                suggested_size=1000.0 / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * 0.95,
                take_profit=current_price * 1.1,
            )
            self._record_signal(signal)
            return signal

        if composite < sell_threshold:
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=min(1.0, confidence),
                timestamp=pd.Timestamp.now(),
                metadata={
                    "composite_score": float(composite),
                    "component_scores": {k: float(v) for k, v in scores.items()},
                    "weights": {k: float(v) for k, v in weights.items()},
                },
                suggested_size=1000.0 / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * 0.95,
                take_profit=current_price * 1.1,
            )
            self._record_signal(signal)
            return signal

        return Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=SignalType.HOLD,
            confidence=min(1.0, confidence),
            timestamp=pd.Timestamp.now(),
            metadata={
                "composite_score": float(composite),
                "component_scores": {k: float(v) for k, v in scores.items()},
                "weights": {k: float(v) for k, v in weights.items()},
            },
        )

    def _train_ml_model(self) -> None:
        """Train the ML model on buffered features (if sklearn available)."""
        if not SKLEARN_AVAILABLE or self._ml_model is None:
            return
        if len(self._feature_buffer) < 50 or len(self._label_buffer) < 50:
            return
        try:
            X = np.array(self._feature_buffer[-len(self._label_buffer):])
            y = np.array(self._label_buffer)
            self._ml_model.fit(X, y)
        except Exception:
            pass
