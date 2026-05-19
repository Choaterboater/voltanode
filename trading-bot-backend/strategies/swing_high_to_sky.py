"""SwingHighToSky — ported from freqtrade community.

Original: Kevin Ossenbrück (Bloom Trading, Mohsen Hassan)
  https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/SwingHighToSky.py

Heads-up: yesterday's handoff doc described this strategy as a
"donchian breakout with SuperTrend filter" — that's a different strategy.
The actual upstream SwingHighToSky is a CCI + RSI confluence on 15m bars.
We ported what's actually there. A separate Donchian-breakout port could
be a follow-up if the operator wants both.

Entry: CCI(72) deeply negative AND RSI(36) below 90
Exit:  CCI(66) above -106 AND RSI(45) above 88
Default param values are upstream's hyperopt winners.
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


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """Commodity Channel Index (Lambert, 1980).

    CCI = (TP - SMA(TP, n)) / (0.015 * mean_abs_deviation(TP, n))
    where TP = (H + L + C) / 3.
    """
    tp = (high + low + close) / 3.0
    sma = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(
        lambda s: np.fabs(s - s.mean()).mean(), raw=False
    )
    # Avoid div-by-zero on perfectly flat bars
    return (tp - sma) / (0.015 * mad.replace(0, np.nan))


class SwingHighToSkyStrategy(BaseStrategy):
    """CCI + RSI confluence (upstream's hyperopt-tuned defaults baked in)."""

    name = "swing_high_to_sky"
    SUPPORTS_MULTI_SYMBOL = True

    DEFAULT_CONFIG = {
        # Upstream's tuned buy params
        "buy_cci_period": 72,
        "buy_cci_threshold": -175,
        "buy_rsi_period": 36,
        "buy_rsi_threshold": 90,
        # Upstream's tuned sell params
        "sell_cci_period": 66,
        "sell_cci_threshold": -106,
        "sell_rsi_period": 45,
        "sell_rsi_threshold": 88,
        # Upstream bakes ROI/stoploss into the strategy as a time-decay ladder
        # ({"0": 0.27, "33": 0.085, "64": 0.04, "244": 0}). Our Signal model
        # surfaces a single TP — we take the initial 27% rung. The engine's
        # time-based unwind isn't wired here; document the simplification.
        "take_profit_pct": 0.27,
        "stop_loss_pct": 0.343,
        "trade_notional_usd": 1000.0,
    }

    @classmethod
    def param_space(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "buy_cci_period":     {"type": "int",   "low": 10,   "high": 80},
            "buy_cci_threshold":  {"type": "int",   "low": -200, "high": 0},
            "buy_rsi_period":     {"type": "int",   "low": 10,   "high": 80},
            "buy_rsi_threshold":  {"type": "int",   "low": 10,   "high": 90},
            "sell_cci_period":    {"type": "int",   "low": 10,   "high": 80},
            "sell_cci_threshold": {"type": "int",   "low": -200, "high": 200},
            "sell_rsi_period":    {"type": "int",   "low": 10,   "high": 80},
            "sell_rsi_threshold": {"type": "int",   "low": 10,   "high": 95},
            "take_profit_pct":    {"type": "float", "low": 0.03, "high": 0.40, "step": 0.01},
            "stop_loss_pct":      {"type": "float", "low": 0.05, "high": 0.40, "step": 0.01},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_signal_bar: Dict[str, Any] = {}

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        data = self._ensure_columns(data)
        cfg = self.config

        buy_cci_p = int(cfg["buy_cci_period"])
        buy_rsi_p = int(cfg["buy_rsi_period"])
        sell_cci_p = int(cfg["sell_cci_period"])
        sell_rsi_p = int(cfg["sell_rsi_period"])

        symbol = data.attrs.get("symbol", "unknown")
        min_bars = max(buy_cci_p, buy_rsi_p, sell_cci_p, sell_rsi_p) + 5
        if len(data) < min_bars:
            return Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=pd.Timestamp.now(),
                metadata={"trigger": "insufficient_history"},
            )

        high = data["high"]
        low = data["low"]
        close = data["close"]

        buy_cci = _cci(high, low, close, buy_cci_p).iloc[-1]
        buy_rsi = _rsi(close, buy_rsi_p).iloc[-1]
        sell_cci = _cci(high, low, close, sell_cci_p).iloc[-1]
        sell_rsi = _rsi(close, sell_rsi_p).iloc[-1]

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

        buy_cci_thr = float(cfg["buy_cci_threshold"])
        buy_rsi_thr = float(cfg["buy_rsi_threshold"])
        sell_cci_thr = float(cfg["sell_cci_threshold"])
        sell_rsi_thr = float(cfg["sell_rsi_threshold"])

        # Entry: deeply negative CCI AND RSI below its (high) gate. RSI<90 is a
        # soft gate at upstream defaults — basically "RSI hasn't gone parabolic
        # yet, so the CCI dive looks like a real swing low, not a melt-up dip."
        if (np.isfinite(buy_cci) and np.isfinite(buy_rsi) and
                buy_cci < buy_cci_thr and buy_rsi < buy_rsi_thr):
            self._last_signal_bar[symbol] = latest_bar
            cci_strength = min(1.0, abs(buy_cci - buy_cci_thr) / max(1.0, abs(buy_cci_thr)))
            confidence = float(min(1.0, 0.55 + 0.45 * cci_strength))
            notional = float(cfg.get("trade_notional_usd", 1000.0))
            tp = float(cfg.get("take_profit_pct", 0.27))
            sl = float(cfg.get("stop_loss_pct", 0.343))
            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "trigger": "cci_oversold_rsi_gated",
                    "cci": float(buy_cci),
                    "rsi": float(buy_rsi),
                    "cci_threshold": buy_cci_thr,
                    "rsi_threshold": buy_rsi_thr,
                },
                suggested_size=notional / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * (1.0 - sl),
                take_profit=current_price * (1.0 + tp),
            )
            self._record_signal(sig)
            return sig

        # Exit: CCI has lifted above the (negative) exit threshold AND RSI is
        # now elevated. Both conditions must agree — confluence exit.
        if (np.isfinite(sell_cci) and np.isfinite(sell_rsi) and
                sell_cci > sell_cci_thr and sell_rsi > sell_rsi_thr):
            self._last_signal_bar[symbol] = latest_bar
            confidence = float(min(1.0, 0.55 + 0.4 *
                                   max(0.0, (sell_rsi - sell_rsi_thr) /
                                       max(1.0, 100 - sell_rsi_thr))))
            notional = float(cfg.get("trade_notional_usd", 1000.0))
            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "trigger": "cci_recovered_rsi_elevated",
                    "cci": float(sell_cci),
                    "rsi": float(sell_rsi),
                    "cci_threshold": sell_cci_thr,
                    "rsi_threshold": sell_rsi_thr,
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
                "buy_cci": float(buy_cci) if np.isfinite(buy_cci) else None,
                "buy_rsi": float(buy_rsi) if np.isfinite(buy_rsi) else None,
                "sell_cci": float(sell_cci) if np.isfinite(sell_cci) else None,
                "sell_rsi": float(sell_rsi) if np.isfinite(sell_rsi) else None,
            },
        )
