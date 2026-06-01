"""Mean reversion strategy using RSI and Bollinger Bands."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import numpy as np

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


class MeanReversionStrategy(BaseStrategy):
    """RSI + Bollinger Bands mean reversion strategy."""

    name = "mean_reversion"
    SUPPORTS_MULTI_SYMBOL = True
    # Looser defaults: RSI 45/55 (was 30/70) and tighter Bollinger band std=1.5
    # (was 2.0) so the strategy actually fires entries on normal market noise.
    # The 30/70/2.0 defaults are textbook but too strict for paper-trading
    # observability — this set generates 2-5x more signals.
    DEFAULT_CONFIG = {
        "rsi_period": 14,
        "rsi_overbought": 55,
        "rsi_oversold": 45,
        "bb_period": 20,
        "bb_std": 1.5,
        "touch_tolerance": 0.02,  # within 2% of band counts as a touch
        "position_pct": 0.03,
    }

    @classmethod
    def param_space(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "rsi_period":      {"type": "int",   "low": 5,     "high": 30},
            "rsi_overbought":  {"type": "int",   "low": 50,    "high": 80},
            "rsi_oversold":    {"type": "int",   "low": 20,    "high": 50},
            "bb_period":       {"type": "int",   "low": 10,    "high": 40},
            "bb_std":          {"type": "float", "low": 1.0,   "high": 3.0,  "step": 0.1},
            "touch_tolerance": {"type": "float", "low": 0.005, "high": 0.05, "step": 0.005},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_signal_bar: Dict[str, Any] = {}

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Generate signal based on RSI and Bollinger Bands.

        Buy when RSI < oversold AND price touches lower BB.
        Sell when RSI > overbought AND price touches upper BB.

        Args:
            data: OHLCV DataFrame.
            current_price: Current market price.

        Returns:
            Trading signal.
        """
        data = self._ensure_columns(data)
        cfg = self.config

        rsi_period = cfg["rsi_period"]
        bb_period = cfg["bb_period"]

        if len(data) < max(rsi_period, bb_period) + 5:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=data.attrs.get("symbol", "unknown"),
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
            )

        # RSI calculation
        delta = data["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.rolling(window=rsi_period).mean()
        avg_loss = loss.rolling(window=rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        current_rsi = float(rsi.iloc[-1])

        # Bollinger Bands
        sma = data["close"].rolling(window=bb_period).mean()
        std = data["close"].rolling(window=bb_period).std()
        upper_band = sma + cfg["bb_std"] * std
        lower_band = sma - cfg["bb_std"] * std

        current_upper = float(upper_band.iloc[-1])
        current_lower = float(lower_band.iloc[-1])
        current_sma = float(sma.iloc[-1])

        symbol = data.attrs.get("symbol", "unknown")

        # Per-bar latch — tick frequency >> bar frequency, so without this
        # the same RSI/BB condition fires on every tick all day.
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

        # Overbought / oversold conditions
        is_oversold = current_rsi < cfg["rsi_oversold"]
        is_overbought = current_rsi > cfg["rsi_overbought"]
        tol = float(cfg.get("touch_tolerance", 0.01))
        touches_lower = current_price <= current_lower * (1 + tol)
        touches_upper = current_price >= current_upper * (1 - tol)

        if is_oversold and touches_lower:
            self._last_signal_bar[symbol] = latest_bar
            # Buy signal
            confidence = min(1.0, (cfg["rsi_oversold"] - current_rsi) / cfg["rsi_oversold"] + 0.3)
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "rsi": current_rsi,
                    "bb_upper": current_upper,
                    "bb_lower": current_lower,
                    "bb_sma": current_sma,
                    "price_vs_lower": current_price / current_lower if current_lower > 0 else 1.0,
                },
                suggested_size=self._size_from_equity_pct(current_price, default_pct=0.03),
                stop_loss=current_price * 0.97,
                take_profit=current_price * 1.05,
            )
            self._record_signal(signal)
            return signal

        if is_overbought and touches_upper:
            self._last_signal_bar[symbol] = latest_bar
            # Sell signal
            confidence = min(1.0, (current_rsi - cfg["rsi_overbought"]) / (100 - cfg["rsi_overbought"]) + 0.3)
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "rsi": current_rsi,
                    "bb_upper": current_upper,
                    "bb_lower": current_lower,
                    "bb_sma": current_sma,
                    "price_vs_upper": current_price / current_upper if current_upper > 0 else 1.0,
                },
                suggested_size=self._size_from_equity_pct(current_price, default_pct=0.03),
                stop_loss=current_price * 0.97,
                take_profit=current_price * 1.05,
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
                "rsi": current_rsi,
                "bb_upper": current_upper,
                "bb_lower": current_lower,
            },
        )
