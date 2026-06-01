"""Funding-rate contrarian strategy (long-only spot).

Perp funding is a crowding gauge:
- Very NEGATIVE funding ⇒ shorts crowded, paying longs ⇒ squeeze-up fuel ⇒
  contrarian LONG on spot.
- Very POSITIVE funding ⇒ longs crowded / overheated ⇒ exit.

Reads a per-bar ``funding_rate`` column (backtest — see
``data.funding.attach_funding_to_ohlcv``) or the live funding cache
(``data.funding.cached_funding_signal``). HOLDs when no funding data, so it's
safe to run without the funding feed wired.
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


class FundingCarryStrategy(BaseStrategy):
    name = "funding_carry"
    SUPPORTS_MULTI_SYMBOL = True

    DEFAULT_CONFIG: Dict[str, Any] = {
        # Daily (summed 8h) funding thresholds.
        "enter_funding": -0.0003,   # <= this (crowded short) -> LONG
        "exit_funding": 0.0005,     # >= this (crowded long)  -> EXIT
        "position_pct": 0.05,
        "stop_loss_pct": 0.10,
        "take_profit_pct": 0.20,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_signal_bar: Dict[str, Any] = {}

    def _funding_rate(self, data: pd.DataFrame, symbol: str):
        # Backtest: per-bar column attached to the OHLCV frame.
        if "funding_rate" in getattr(data, "columns", []):
            try:
                v = float(data["funding_rate"].iloc[-1])
                if v == v:  # not NaN
                    return v
            except Exception:
                pass
        # Live: the cache populated by the funding background loop.
        try:
            from data.funding import cached_funding_signal
            sig = cached_funding_signal(symbol)
            return sig.funding_rate if sig else None
        except Exception:
            return None

    def _hold(self, symbol: str, trigger: str, **meta: Any) -> Signal:
        return Signal(
            strategy_id=self.strategy_id, symbol=symbol, signal_type=SignalType.HOLD,
            confidence=0.0, timestamp=pd.Timestamp.now(), metadata={"trigger": trigger, **meta},
        )

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        symbol = str(data.attrs.get("symbol", "")).upper()
        fr = self._funding_rate(data, symbol)
        if fr is None:
            return self._hold(symbol, "no_funding_data")

        latest_bar = self._bar_key(data.index[-1] if len(data.index) else None)
        if latest_bar is not None and self._last_signal_bar.get(symbol) == latest_bar:
            return self._hold(symbol, "already_fired_this_bar", funding=fr)

        cfg = self.config
        enter = float(cfg.get("enter_funding", -0.0003))
        exit_ = float(cfg.get("exit_funding", 0.0005))
        pos_pct = float(cfg.get("position_pct", 0.05))
        sl = float(cfg.get("stop_loss_pct", 0.10))
        tp = float(cfg.get("take_profit_pct", 0.20))

        if fr <= enter:
            self._last_signal_bar[symbol] = latest_bar
            sig = Signal(
                strategy_id=self.strategy_id, symbol=symbol, signal_type=SignalType.BUY,
                confidence=min(1.0, abs(fr) / abs(enter)) if enter else 0.5,
                timestamp=pd.Timestamp.now(),
                metadata={"trigger": "crowded_short_funding", "funding": fr},
                suggested_size=self._size_from_equity_pct(current_price, default_pct=pos_pct),
                stop_loss=current_price * (1 - sl),
                take_profit=current_price * (1 + tp),
            )
            self._record_signal(sig)
            return sig

        if fr >= exit_:
            self._last_signal_bar[symbol] = latest_bar
            sig = Signal(
                strategy_id=self.strategy_id, symbol=symbol, signal_type=SignalType.SELL,
                confidence=min(1.0, fr / exit_) if exit_ else 0.5,
                timestamp=pd.Timestamp.now(),
                metadata={"trigger": "crowded_long_funding", "funding": fr},
                suggested_size=self._size_from_equity_pct(current_price, default_pct=pos_pct),
            )
            self._record_signal(sig)
            return sig

        return self._hold(symbol, "funding_neutral", funding=fr)
