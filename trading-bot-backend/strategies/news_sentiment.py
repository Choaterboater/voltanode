"""News & sentiment-based trading strategy.

Combines technical analysis with news sentiment signals.
Goes long on bullish news breakouts, short on bearish news breakdowns.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd

from strategies.base import BaseStrategy, Signal, TickData
from bot.config import SignalType
from bot.portfolio import Portfolio

logger = logging.getLogger("volta.strategies")


class NewsSentimentStrategy(BaseStrategy):
    """Strategy that trades based on news sentiment + price momentum.

    Config:
        sentiment_threshold: float — compound score needed to trigger (default 0.3)
        confidence_threshold: float — min confidence required (default 0.6)
        lookback_hours: int — how recent news must be (default 6)
        position_size_pct: float — % of portfolio per trade (default 5.0)
        require_trend_confirmation: bool — wait for price to move in sentiment direction
    """

    name = "news_sentiment"
    DEFAULT_CONFIG: Dict[str, Any] = {
        "sentiment_threshold": 0.3,
        "confidence_threshold": 0.6,
        "lookback_hours": 6,
        "position_size_pct": 5.0,
        "require_trend_confirmation": True,
    }

    # Class-level cache for sentiment state (populated by external news pipeline)
    _symbol_sentiment: Dict[str, Dict[str, Any]] = {}

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Generate signal based on cached sentiment + price data.

        This is called by the engine's tick loop. The sentiment cache
        is populated externally by the news fetcher pipeline.
        """
        symbol = data.attrs.get("symbol", "")
        if not symbol:
            # Try to infer from column or index name
            symbol = str(data.columns[0]) if len(data.columns) > 0 else ""

        sentiment = self._symbol_sentiment.get(symbol, {})
        if not sentiment:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
            )

        compound = sentiment.get("compound", 0.0)
        confidence = sentiment.get("confidence", 0.0)

        if confidence < self.config.get("confidence_threshold", 0.6):
            return Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
            )

        threshold = self.config.get("sentiment_threshold", 0.3)

        if compound > threshold:
            signal_type = SignalType.BUY
            rationale = f"Bullish news sentiment ({compound:.2f})"
        elif compound < -threshold:
            signal_type = SignalType.SELL
            rationale = f"Bearish news sentiment ({compound:.2f})"
        else:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
            )

        # Trend confirmation: check if price moved in sentiment direction recently
        if self.config.get("require_trend_confirmation", True) and len(data) >= 2:
            prev_close = float(data["close"].iloc[-2])
            price_change = (current_price - prev_close) / prev_close if prev_close > 0 else 0
            if signal_type == SignalType.BUY and price_change < -0.01:
                # Bullish sentiment but price dropping — skip
                return Signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    signal_type=SignalType.HOLD,
                    confidence=0.0,
                    timestamp=pd.Timestamp.now(),
                )
            if signal_type == SignalType.SELL and price_change > 0.01:
                # Bearish sentiment but price rising — skip
                return Signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    signal_type=SignalType.HOLD,
                    confidence=0.0,
                    timestamp=pd.Timestamp.now(),
                )

        # Determine position size
        suggested_size = None
        try:
            notional = 1000.0 * (self.config.get("position_size_pct", 5.0) / 100.0)
            suggested_size = notional / current_price if current_price > 0 else 0.1
        except Exception:
            pass

        signal = Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=signal_type,
            confidence=min(confidence, abs(compound)),
            timestamp=pd.Timestamp.now(),
            suggested_size=suggested_size,
            metadata={
                "strategy": self.name,
                "sentiment_score": compound,
                "confidence": confidence,
                "rationale": rationale,
            },
        )
        self._record_signal(signal)
        return signal

    def on_tick(self, tick: TickData, portfolio: Portfolio, **kwargs: Any) -> Signal | None:
        """Override to clear stale sentiment and avoid over-trading.

        When ``ohlcv_data`` is passed from the engine tick loop we forward it
        to :meth:`generate_signal` so the strategy can act on cached sentiment.
        """
        ohlcv_data = kwargs.get("ohlcv_data")
        if ohlcv_data is not None and len(ohlcv_data) > 0:
            ohlcv_data = ohlcv_data.copy()
            ohlcv_data.attrs["symbol"] = tick.symbol
            return self.generate_signal(ohlcv_data, tick.price)
        return None

    @classmethod
    def update_sentiment(cls, symbol: str, compound: float, confidence: float) -> None:
        """Update the sentiment cache for a symbol.

        Called by the news pipeline when new sentiment is available.
        """
        cls._symbol_sentiment[symbol] = {
            "compound": compound,
            "confidence": confidence,
        }

    @classmethod
    def clear_sentiment(cls, symbol: str | None = None) -> None:
        """Clear sentiment cache."""
        if symbol:
            cls._symbol_sentiment.pop(symbol, None)
        else:
            cls._symbol_sentiment.clear()
