"""Mean reversion strategy using RSI and Bollinger Bands."""

from __future__ import annotations

import pandas as pd
import numpy as np

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


class MeanReversionStrategy(BaseStrategy):
    """RSI + Bollinger Bands mean reversion strategy."""

    name = "mean_reversion"
    DEFAULT_CONFIG = {
        "rsi_period": 14,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
        "bb_period": 20,
        "bb_std": 2.0,
    }

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

        # Overbought / oversold conditions
        is_oversold = current_rsi < cfg["rsi_oversold"]
        is_overbought = current_rsi > cfg["rsi_overbought"]
        touches_lower = current_price <= current_lower * 1.01  # within 1% of lower band
        touches_upper = current_price >= current_upper * 0.99  # within 1% of upper band

        if is_oversold and touches_lower:
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
                suggested_size=0.0,
            )
            self._record_signal(signal)
            return signal

        if is_overbought and touches_upper:
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
                "rsi": current_rsi,
                "bb_upper": current_upper,
                "bb_lower": current_lower,
            },
        )
