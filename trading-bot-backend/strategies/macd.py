"""MACD strategy using signal line crossovers."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import numpy as np

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


class MACDStrategy(BaseStrategy):
    """MACD signal line crossover strategy."""

    name = "macd"
    SUPPORTS_MULTI_SYMBOL = True
    DEFAULT_CONFIG = {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "position_pct": 0.03,
        # Crossover-moment entries bled when the crossover fired inside a
        # broader downtrend (live: 44% win rate, net negative). Veto BUYs
        # below the trend EMA by default; explicit {"enabled": false}
        # in a registered config still wins via the shallow config merge.
        "regime_gate": {"enabled": True, "trend_ema": 100},
    }

    @classmethod
    def param_space(cls) -> Dict[str, Dict[str, Any]]:
        # Constraint fast<slow is enforced in the hyperopt objective
        # (returns -inf when violated); cheaper than constraining the sampler.
        return {
            "fast":   {"type": "int", "low": 5,  "high": 20},
            "slow":   {"type": "int", "low": 20, "high": 50},
            "signal": {"type": "int", "low": 5,  "high": 15},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_signal_bar: Dict[str, Any] = {}

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Generate signal based on MACD crossover.

        Buy when MACD line crosses above signal line.
        Sell when MACD crosses below.

        Args:
            data: OHLCV DataFrame.
            current_price: Current market price.

        Returns:
            Trading signal.
        """
        data = self._ensure_columns(data)
        cfg = self.config
        fast = cfg["fast"]
        slow = cfg["slow"]
        signal_period = cfg["signal"]

        if len(data) < slow + signal_period + 5:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=data.attrs.get("symbol", "unknown"),
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
            )

        close = data["close"]
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram = macd_line - signal_line

        prev_macd = float(macd_line.iloc[-2])
        prev_signal = float(signal_line.iloc[-2])
        curr_macd = float(macd_line.iloc[-1])
        curr_signal = float(signal_line.iloc[-1])
        curr_histogram = float(histogram.iloc[-1])

        symbol = data.attrs.get("symbol", "unknown")

        # Per-bar latch — bars are daily; without this the same crossover
        # fires every ~5s tick all day.
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
        cross_up = prev_macd <= prev_signal and curr_macd > curr_signal
        cross_down = prev_macd >= prev_signal and curr_macd < curr_signal

        # Histogram momentum confirmation
        hist_positive = curr_histogram > 0
        hist_negative = curr_histogram < 0

        if cross_up and hist_positive:
            self._last_signal_bar[symbol] = latest_bar
            # Normalize confidence by MACD distance from zero relative to price
            distance = abs(curr_macd - curr_signal)
            confidence = min(1.0, 0.5 + distance / (current_price * 0.01))
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "macd": curr_macd,
                    "signal": curr_signal,
                    "histogram": curr_histogram,
                    "crossover": "up",
                },
                suggested_size=self._size_from_equity_pct(current_price, default_pct=0.03),
                stop_loss=current_price * 0.95,
                take_profit=current_price * 1.08,
            )
            self._record_signal(signal)
            return signal

        if cross_down and hist_negative:
            self._last_signal_bar[symbol] = latest_bar
            distance = abs(curr_macd - curr_signal)
            confidence = min(1.0, 0.5 + distance / (current_price * 0.01))
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "macd": curr_macd,
                    "signal": curr_signal,
                    "histogram": curr_histogram,
                    "crossover": "down",
                },
                suggested_size=self._size_from_equity_pct(current_price, default_pct=0.03),
                stop_loss=current_price * 0.95,
                take_profit=current_price * 1.08,
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
                "macd": curr_macd,
                "signal": curr_signal,
                "histogram": curr_histogram,
            },
        )
