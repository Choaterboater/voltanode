"""Simple trend-following strategy — fires often, no waiting for crossover.

Rules:
- BUY when close > EMA(fast) AND we don't already hold the symbol
- SELL when close < EMA(slow) AND we hold the symbol

Compared to MomentumStrategy this skips the moment-of-crossover requirement,
so it fires within the first tick a symbol is in an uptrend rather than only
on the bar where fast crosses slow. Useful for getting trades to actually
happen on a sideways or slowly-trending market.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


class SimpleTrendStrategy(BaseStrategy):
    """Permissive EMA trend-follower."""

    name = "simple_trend"
    SUPPORTS_MULTI_SYMBOL = True
    DEFAULT_CONFIG = {
        "fast_ema": 12,
        "slow_ema": 26,
        "position_pct": 0.10,  # use 10% of free balance per entry
        "stop_loss_pct": 0.04,
        "take_profit_pct": 0.08,
    }

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        data = self._ensure_columns(data)
        cfg = self.config
        fast = int(cfg.get("fast_ema", 12))
        slow = int(cfg.get("slow_ema", 26))
        symbol = data.attrs.get("symbol", "unknown")

        if len(data) < slow + 2:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
            )

        ema_fast = data["close"].ewm(span=fast, adjust=False).mean().iloc[-1]
        ema_slow = data["close"].ewm(span=slow, adjust=False).mean().iloc[-1]

        sl_pct = float(cfg.get("stop_loss_pct", 0.04))
        tp_pct = float(cfg.get("take_profit_pct", 0.08))
        pos_pct = float(cfg.get("position_pct", 0.10))

        # Price vs trend: above fast EMA → trending up; below slow EMA → trending down.
        if current_price > ema_fast and current_price > ema_slow:
            confidence = min(1.0, (current_price - ema_slow) / max(ema_slow, 1e-9) * 5 + 0.5)
            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "fast_ema": float(ema_fast),
                    "slow_ema": float(ema_slow),
                    "trigger": "price_above_emas",
                },
                suggested_size=(pos_pct * 1000.0) / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * (1 - sl_pct),
                take_profit=current_price * (1 + tp_pct),
            )
            self._record_signal(sig)
            return sig

        if current_price < ema_fast and current_price < ema_slow:
            confidence = min(1.0, (ema_slow - current_price) / max(ema_slow, 1e-9) * 5 + 0.5)
            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "fast_ema": float(ema_fast),
                    "slow_ema": float(ema_slow),
                    "trigger": "price_below_emas",
                },
                suggested_size=(pos_pct * 1000.0) / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * (1 + sl_pct),
                take_profit=current_price * (1 - tp_pct),
            )
            self._record_signal(sig)
            return sig

        return Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=SignalType.HOLD,
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
            metadata={"fast_ema": float(ema_fast), "slow_ema": float(ema_slow)},
        )
