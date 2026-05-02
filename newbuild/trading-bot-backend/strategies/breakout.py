"""Breakout strategy using support/resistance and volume confirmation."""

from __future__ import annotations

import pandas as pd
import numpy as np

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


class BreakoutStrategy(BaseStrategy):
    """Support/resistance breakout with volume confirmation."""

    name = "breakout"
    DEFAULT_CONFIG = {
        "lookback_period": 20,
        "volume_multiplier": 1.5,
        "breakout_threshold_pct": 0.005,
    }

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Generate signal on support/resistance breakout.

        Buy when price breaks above resistance (lookback high) with volume > avg * multiplier.
        Sell on support breakdown.

        Args:
            data: OHLCV DataFrame.
            current_price: Current market price.

        Returns:
            Trading signal.
        """
        data = self._ensure_columns(data)
        cfg = self.config
        lookback = cfg["lookback_period"]

        if len(data) < lookback + 5:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=data.attrs.get("symbol", "unknown"),
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
            )

        # Support and resistance levels
        resistance = data["high"].rolling(window=lookback).max().iloc[-2]
        support = data["low"].rolling(window=lookback).min().iloc[-2]

        # Volume analysis
        avg_volume = data["volume"].rolling(window=lookback).mean().iloc[-1]
        current_volume = float(data["volume"].iloc[-1])

        # Previous close
        prev_close = float(data["close"].iloc[-2])

        symbol = data.attrs.get("symbol", "unknown")

        # Breakout above resistance
        threshold = resistance * cfg["breakout_threshold_pct"]
        volume_confirmed = current_volume > avg_volume * cfg["volume_multiplier"]

        if current_price > resistance + threshold and volume_confirmed and prev_close <= resistance:
            breakout_pct = (current_price - resistance) / resistance
            confidence = min(1.0, 0.5 + breakout_pct * 10)
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "resistance": float(resistance),
                    "support": float(support),
                    "volume": current_volume,
                    "avg_volume": float(avg_volume),
                    "breakout_pct": float(breakout_pct),
                },
                suggested_size=0.0,
            )
            self._record_signal(signal)
            return signal

        # Breakdown below support
        if current_price < support - threshold and volume_confirmed and prev_close >= support:
            breakdown_pct = (support - current_price) / support
            confidence = min(1.0, 0.5 + breakdown_pct * 10)
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "resistance": float(resistance),
                    "support": float(support),
                    "volume": current_volume,
                    "avg_volume": float(avg_volume),
                    "breakdown_pct": float(breakdown_pct),
                },
                suggested_size=0.0,
            )
            self._record_signal(signal)
            return signal

        return Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=SignalType.HOLD,
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
            metadata={
                "resistance": float(resistance),
                "support": float(support),
                "volume": current_volume,
            },
        )
