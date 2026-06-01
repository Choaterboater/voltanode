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

from typing import Any, Dict, Optional

import pandas as pd

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


class SimpleTrendStrategy(BaseStrategy):
    """Permissive EMA trend-follower with signal-flip debounce.

    One trade per signal flip — once it BUYs, it won't BUY again until the
    signal goes through SELL or HOLD; once it SELLs, won't SELL again until
    BUY or HOLD. Prevents tick-spam on a sustained trend.
    """

    name = "simple_trend"
    SUPPORTS_MULTI_SYMBOL = True
    DEFAULT_CONFIG = {
        "fast_ema": 12,
        "slow_ema": 26,
        "position_pct": 0.10,  # use 10% of free balance per entry
        "stop_loss_pct": 0.04,
        "take_profit_pct": 0.08,
        # Hysteresis: price must clear EMA band by this fraction before flip.
        # 0.005 = 0.5% buffer kills "barely above EMA" noise oscillation.
        "hysteresis_pct": 0.003,
        # Minimum hold time after a fire before allowing the opposite side.
        "min_hold_minutes": 15,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Per-symbol last emitted side ("buy" / "sell" / None) so we only
        # fire a fresh order when the side flips.
        self._last_side: Dict[str, str] = {}
        # Per-symbol last bar timestamp we emitted ANY non-HOLD signal for.
        # Without this, a price oscillating around the EMA band within a
        # single bar can fire BUY -> reset to neutral -> BUY again etc.
        self._last_signal_bar: Dict[str, Any] = {}
        # Per-symbol last fire timestamp — enforces min_hold_minutes between
        # opposite-side fires, smoothing intra-day chop.
        self._last_fire_ts: Dict[str, Any] = {}

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

        # Per-bar latch — strategy is called every ~5s tick but bars roll
        # over only daily/hourly. Once we've fired on this bar, hold until
        # the bar advances regardless of intra-bar EMA oscillation.
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

        ema_fast = data["close"].ewm(span=fast, adjust=False).mean().iloc[-1]
        ema_slow = data["close"].ewm(span=slow, adjust=False).mean().iloc[-1]

        sl_pct = float(cfg.get("stop_loss_pct", 0.04))
        tp_pct = float(cfg.get("take_profit_pct", 0.08))
        pos_pct = float(cfg.get("position_pct", 0.10))
        hyst = float(cfg.get("hysteresis_pct", 0.005))
        hold_min = float(cfg.get("min_hold_minutes", 30))

        # Hysteresis bands — price must clear the EMAs by `hyst` before
        # flipping. Kills "price oscillates 0.2% across the EMA" churn.
        buy_threshold_fast = ema_fast * (1 + hyst)
        buy_threshold_slow = ema_slow * (1 + hyst)
        sell_threshold_fast = ema_fast * (1 - hyst)
        sell_threshold_slow = ema_slow * (1 - hyst)

        # Min-hold cooldown — block opposite-side flip if too recent.
        last_fire = self._last_fire_ts.get(symbol)
        now = pd.Timestamp.now()
        in_cooldown = (
            last_fire is not None
            and (now - last_fire).total_seconds() < hold_min * 60
        )

        # Price vs trend: above fast EMA → trending up; below slow EMA → trending down.
        if current_price > buy_threshold_fast and current_price > buy_threshold_slow:
            if self._last_side.get(symbol) == "buy":
                # Already long on this leg — wait for trend flip before re-entering.
                return Signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    signal_type=SignalType.HOLD,
                    confidence=0.0,
                    timestamp=pd.Timestamp.now(),
                    metadata={"trigger": "already_long"},
                )
            if in_cooldown and self._last_side.get(symbol) == "sell":
                return Signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    signal_type=SignalType.HOLD,
                    confidence=0.0,
                    timestamp=pd.Timestamp.now(),
                    metadata={"trigger": "min_hold_cooldown"},
                )
            self._last_side[symbol] = "buy"
            self._last_signal_bar[symbol] = latest_bar
            self._last_fire_ts[symbol] = now
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
                suggested_size=(pos_pct * getattr(self, "_equity", 100_000.0)) / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * (1 - sl_pct),
                take_profit=current_price * (1 + tp_pct),
            )
            self._record_signal(sig)
            return sig

        if current_price < sell_threshold_fast and current_price < sell_threshold_slow:
            if self._last_side.get(symbol) == "sell":
                return Signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    signal_type=SignalType.HOLD,
                    confidence=0.0,
                    timestamp=pd.Timestamp.now(),
                    metadata={"trigger": "already_short"},
                )
            if in_cooldown and self._last_side.get(symbol) == "buy":
                return Signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    signal_type=SignalType.HOLD,
                    confidence=0.0,
                    timestamp=pd.Timestamp.now(),
                    metadata={"trigger": "min_hold_cooldown"},
                )
            self._last_side[symbol] = "sell"
            self._last_signal_bar[symbol] = latest_bar
            self._last_fire_ts[symbol] = now
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
                suggested_size=(pos_pct * getattr(self, "_equity", 100_000.0)) / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * (1 + sl_pct),
                take_profit=current_price * (1 - tp_pct),
            )
            self._record_signal(sig)
            return sig

        # Price between the EMAs — neutral. Reset latch so next clear breakout
        # in either direction fires a fresh trade.
        self._last_side[symbol] = "neutral"
        return Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=SignalType.HOLD,
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
            metadata={"fast_ema": float(ema_fast), "slow_ema": float(ema_slow)},
        )
