"""BbandRsi mean-reversion strategy — ported from freqtrade community.

Original: Gert Wohlgemuth's BbandRsi
  https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/berlinguyinca/BbandRsi.py
Originally converted from Mynt's C# implementation.

Why a separate strategy from ``mean_reversion.py``? Our existing one is
intentionally looser (RSI 45/55, BB touch tolerance, dual-sided exits) to
generate enough paper-trading observability. BbandRsi is the textbook-strict
variant: 30/70 RSI, close MUST be fully below the lower band, BBs computed
on typical price (HLC/3) instead of close, exit on pure RSI>70 with no band
requirement. Different signal regime — keep both, let the operator pick.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


class BbandRsiStrategy(BaseStrategy):
    """RSI < 30 + close below lower BB (computed on typical price)."""

    name = "bband_rsi"
    SUPPORTS_MULTI_SYMBOL = True

    DEFAULT_CONFIG = {
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "bb_period": 20,
        "bb_std": 2.0,
        # Upstream bakes ROI/stoploss into the strategy. We surface them on
        # the Signal so the engine's exit machinery picks them up the same way
        # it does for our other strategies.
        "take_profit_pct": 0.10,
        "stop_loss_pct": 0.25,
        # Notional dollars per entry — matches the size formula used in
        # mean_reversion.py so portfolio-sizing semantics stay consistent
        # across strategies in the same bot.
        "trade_notional_usd": 1000.0,
    }

    @classmethod
    def param_space(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "rsi_period":       {"type": "int",   "low": 5,    "high": 30},
            "rsi_oversold":     {"type": "int",   "low": 15,   "high": 45},
            "rsi_overbought":   {"type": "int",   "low": 55,   "high": 85},
            "bb_period":        {"type": "int",   "low": 10,   "high": 40},
            "bb_std":           {"type": "float", "low": 1.0,  "high": 3.5, "step": 0.1},
            "take_profit_pct":  {"type": "float", "low": 0.03, "high": 0.25, "step": 0.01},
            "stop_loss_pct":    {"type": "float", "low": 0.05, "high": 0.35, "step": 0.01},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Per-symbol last bar we fired on — matches the latch pattern used by
        # mean_reversion / macd / momentum to prevent re-firing every tick
        # inside one bar. Restart wipes it; the position-aware BUY gate in
        # BaseStrategy.on_tick catches the resulting re-fire on already-held
        # symbols.
        self._last_signal_bar: Dict[str, Any] = {}

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        data = self._ensure_columns(data)
        cfg = self.config

        rsi_period = int(cfg["rsi_period"])
        bb_period = int(cfg["bb_period"])

        symbol = data.attrs.get("symbol", "unknown")
        if len(data) < max(rsi_period, bb_period) + 5:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
                metadata={"trigger": "insufficient_history"},
            )

        # Typical price (HLC/3) — matches qtpylib.typical_price the upstream uses.
        typical = (data["high"] + data["low"] + data["close"]) / 3.0

        # Bollinger Bands over typical price
        bb_mid = typical.rolling(window=bb_period).mean()
        bb_sd = typical.rolling(window=bb_period).std()
        bb_lower = bb_mid - cfg["bb_std"] * bb_sd
        bb_upper = bb_mid + cfg["bb_std"] * bb_sd

        # RSI on close (upstream uses talib RSI on close, not typical)
        rsi = _rsi(data["close"], rsi_period)

        last_close = float(data["close"].iloc[-1])
        last_rsi = float(rsi.iloc[-1])
        last_lower = float(bb_lower.iloc[-1])
        last_mid = float(bb_mid.iloc[-1])
        last_upper = float(bb_upper.iloc[-1])

        # Per-bar latch
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

        rsi_oversold = float(cfg["rsi_oversold"])
        rsi_overbought = float(cfg["rsi_overbought"])

        # Upstream entry condition: RSI < oversold AND close < lower band
        # (strict — no touch_tolerance, fully below the band).
        if np.isfinite(last_rsi) and np.isfinite(last_lower) and \
                last_rsi < rsi_oversold and last_close < last_lower:
            self._last_signal_bar[symbol] = latest_bar
            # Confidence climbs as we move further below the band + deeper oversold.
            band_dip = max(0.0, (last_lower - last_close) / last_lower) if last_lower > 0 else 0.0
            rsi_dip = max(0.0, (rsi_oversold - last_rsi) / rsi_oversold) if rsi_oversold > 0 else 0.0
            confidence = min(1.0, 0.5 + band_dip * 5 + rsi_dip * 0.5)
            notional = float(cfg.get("trade_notional_usd", 1000.0))
            tp = float(cfg.get("take_profit_pct", 0.10))
            sl = float(cfg.get("stop_loss_pct", 0.25))
            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "trigger": "rsi_oversold_below_lower_band",
                    "rsi": last_rsi,
                    "close": last_close,
                    "bb_lower": last_lower,
                    "bb_mid": last_mid,
                    "bb_upper": last_upper,
                },
                suggested_size=notional / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * (1.0 - sl),
                take_profit=current_price * (1.0 + tp),
            )
            self._record_signal(sig)
            return sig

        # Upstream exit condition: pure RSI > overbought (no BB requirement).
        if np.isfinite(last_rsi) and last_rsi > rsi_overbought:
            self._last_signal_bar[symbol] = latest_bar
            confidence = min(1.0, 0.5 + max(0.0, (last_rsi - rsi_overbought) / max(1.0, 100 - rsi_overbought)) * 0.5)
            notional = float(cfg.get("trade_notional_usd", 1000.0))
            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "trigger": "rsi_overbought",
                    "rsi": last_rsi,
                    "close": last_close,
                    "bb_lower": last_lower,
                    "bb_mid": last_mid,
                    "bb_upper": last_upper,
                },
                suggested_size=notional / current_price if current_price > 0 else 0.0,
            )
            self._record_signal(sig)
            return sig

        return Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=SignalType.HOLD,
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
            metadata={
                "rsi": last_rsi,
                "bb_lower": last_lower,
                "bb_mid": last_mid,
                "bb_upper": last_upper,
            },
        )
