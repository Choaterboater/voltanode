"""Momentum strategy using EMA crossover trend following."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import numpy as np

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):
    """EMA crossover trend following strategy."""

    name = "momentum"
    SUPPORTS_MULTI_SYMBOL = True
    DEFAULT_CONFIG = {
        "fast_ema": 12,
        "slow_ema": 26,
        "signal_ema": 9,
        "trend_filter_ema": 200,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Per-symbol last bar timestamp we emitted a non-HOLD signal for.
        # Strategy.on_tick is called every ~5s but bars are daily/hourly —
        # without this latch, the same crossover fires hundreds of times
        # within a single bar.
        self._last_signal_bar: Dict[str, Any] = {}

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Generate signal based on EMA crossover.

        Buy when fast EMA crosses above slow EMA AND price > trend filter EMA.
        Sell when fast crosses below.

        Args:
            data: OHLCV DataFrame.
            current_price: Current market price.

        Returns:
            Trading signal.
        """
        data = self._ensure_columns(data)
        cfg = self.config

        fast = cfg["fast_ema"]
        slow = cfg["slow_ema"]
        trend = cfg["trend_filter_ema"]

        if len(data) < max(fast, slow, trend) + 5:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=data.attrs.get("symbol", "unknown"),
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
            )

        ema_fast = data["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = data["close"].ewm(span=slow, adjust=False).mean()
        ema_trend = data["close"].ewm(span=trend, adjust=False).mean()

        prev_fast = ema_fast.iloc[-2]
        prev_slow = ema_slow.iloc[-2]
        curr_fast = ema_fast.iloc[-1]
        curr_slow = ema_slow.iloc[-1]
        curr_trend = ema_trend.iloc[-1]

        symbol = data.attrs.get("symbol", "unknown")

        # Per-bar latch: skip if we already fired on this bar's index. Bars
        # come in daily here so without this we'd re-fire the same cross
        # every ~5s for the rest of the day.
        latest_bar = self._bar_key(data.index[-1] if len(data.index) else None)
        if latest_bar is not None and self._last_signal_bar.get(symbol) == latest_bar:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
                metadata={"trigger": "already_fired_this_bar"},
            )

        # Crossover detection
        cross_up = prev_fast <= prev_slow and curr_fast > curr_slow
        cross_down = prev_fast >= prev_slow and curr_fast < curr_slow

        # Trend filter
        above_trend = current_price > curr_trend

        # ATR for position sizing / confidence
        atr = self._calculate_atr(data, 14)

        if cross_up and above_trend:
            self._last_signal_bar[symbol] = latest_bar
            # Calculate confidence based on momentum strength
            momentum = abs(curr_fast - curr_slow) / (atr if atr > 0 else 1.0)
            confidence = min(1.0, 0.5 + min(momentum * 0.1, 0.5))
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "fast_ema": float(curr_fast),
                    "slow_ema": float(curr_slow),
                    "trend_ema": float(curr_trend),
                    "atr": float(atr),
                },
                suggested_size=1000.0 / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * 0.95,
                take_profit=current_price * 1.1,
            )
            self._record_signal(signal)
            return signal

        if cross_down:
            self._last_signal_bar[symbol] = latest_bar
            momentum = abs(curr_fast - curr_slow) / (atr if atr > 0 else 1.0)
            confidence = min(1.0, 0.5 + min(momentum * 0.1, 0.5))
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "fast_ema": float(curr_fast),
                    "slow_ema": float(curr_slow),
                    "trend_ema": float(curr_trend),
                    "atr": float(atr),
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
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
            metadata={
                "fast_ema": float(curr_fast),
                "slow_ema": float(curr_slow),
            },
        )

    @staticmethod
    def _calculate_atr(data: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]
        return float(atr) if pd.notna(atr) else 0.0
