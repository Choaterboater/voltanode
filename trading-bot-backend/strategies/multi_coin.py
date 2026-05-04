"""Multi-coin momentum strategy — watches a basket of cryptos, holds the strongest."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


_DEFAULT_WATCH_LIST: List[str] = [
    "BTC", "ETH", "SOL", "BNB", "ADA", "XRP", "AVAX", "DOGE",
    "DOT", "LINK", "MATIC", "LTC", "UNI", "ATOM", "NEAR",
    "ARB", "OP", "APT", "SUI", "FTM",
]


class MultiCoinMomentumStrategy(BaseStrategy):
    """Watches a basket of crypto coins and holds the one with the strongest momentum.

    Scores each coin on every tick using EMA separation normalised by ATR.
    Enters the best coin when the score clears a threshold and exits (rotates)
    when a significantly better opportunity appears or the current trend flips.
    """

    name = "multi_coin"
    NEEDS_OHLCV = True  # tick loop must supply ohlcv_data for each symbol

    DEFAULT_CONFIG: Dict[str, Any] = {
        "symbols": _DEFAULT_WATCH_LIST,
        "asset_class": "crypto",
        "fast_ema": 12,
        "slow_ema": 26,
        "trend_ema": 100,
        "min_score": 0.30,       # minimum momentum score to enter a position
        "rotation_gap": 0.50,    # new coin must beat current by this much to rotate
        "position_usd": 1000.0,  # dollar size per entry
    }

    def __init__(self, strategy_id: str, config: Dict[str, Any]) -> None:
        super().__init__(strategy_id, config)
        self._scores: Dict[str, float] = {}      # symbol -> latest momentum score
        self._current_symbol: str | None = None  # coin we are currently long

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def watch_symbols(self) -> List[str]:
        """All symbols this strategy monitors."""
        return list(self.config.get("symbols", _DEFAULT_WATCH_LIST))

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        # Unused — on_tick is fully overridden in this strategy.
        return Signal(
            strategy_id=self.strategy_id,
            symbol="",
            signal_type=SignalType.HOLD,
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
        )

    def on_tick(self, tick: Any, portfolio: Any, **kwargs: Any) -> Signal | None:
        ohlcv_data: pd.DataFrame | None = kwargs.get("ohlcv_data")
        symbol = tick.symbol

        # ── 1. Update score for this coin ──
        if ohlcv_data is not None and not ohlcv_data.empty and len(ohlcv_data) >= 30:
            self._scores[symbol] = self._compute_score(ohlcv_data, tick.price)
        elif symbol not in self._scores:
            self._scores[symbol] = 0.0

        # ── 2. Currently holding a position ──
        pos = (
            portfolio.get_position(self._current_symbol)
            if portfolio and self._current_symbol
            else None
        )

        if pos and self._current_symbol:
            curr_score = self._scores.get(self._current_symbol, 0.0)

            # Exit: trend has flipped negative for the coin we hold
            if symbol == self._current_symbol and self._scores[symbol] < 0:
                self._current_symbol = None
                return Signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    confidence=min(1.0, abs(self._scores[symbol])),
                    timestamp=pd.Timestamp.now(),
                    suggested_size=pos.size,
                    metadata={"reason": "trend_flipped"},
                )

            # Rotate: a clearly better coin has appeared
            best_sym, best_score = self._best_opportunity(exclude=self._current_symbol)
            if (
                best_sym
                and best_score >= curr_score + self.config["rotation_gap"]
                and symbol == self._current_symbol  # fire on current-coin tick to sell first
            ):
                self._current_symbol = best_sym
                return Signal(
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    confidence=min(1.0, best_score - curr_score),
                    timestamp=pd.Timestamp.now(),
                    suggested_size=pos.size,
                    metadata={"reason": "rotating_to", "target": best_sym},
                )

            return None  # hold current position

        # ── 3. No position — enter the best coin ──
        best_sym, best_score = self._best_opportunity()
        if (
            best_sym == symbol
            and best_score >= self.config["min_score"]
        ):
            self._current_symbol = symbol
            size = self.config["position_usd"] / tick.price if tick.price > 0 else 0.0
            return Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=min(1.0, best_score / 2.0),
                timestamp=pd.Timestamp.now(),
                suggested_size=size,
                stop_loss=tick.price * 0.95,
                take_profit=tick.price * 1.12,
                metadata={"score": round(best_score, 3), "ranked": self._top_ranked()},
            )

        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_score(self, data: pd.DataFrame, current_price: float) -> float:
        """EMA momentum score normalised by ATR.  Positive = bullish, negative = bearish."""
        cfg = self.config
        fast = int(cfg["fast_ema"])
        slow = int(cfg["slow_ema"])
        trend = int(cfg["trend_ema"])

        if len(data) < slow + 5:
            return 0.0

        close = data["close"]
        ema_fast = float(close.ewm(span=fast, adjust=False).mean().iloc[-1])
        ema_slow = float(close.ewm(span=slow, adjust=False).mean().iloc[-1])

        # ATR for normalisation
        tr = pd.concat([
            data["high"] - data["low"],
            (data["high"] - data["close"].shift(1)).abs(),
            (data["low"] - data["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr_val = tr.rolling(14, min_periods=1).mean().iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            atr_val = max(current_price * 0.02, 1e-9)

        raw_score = (ema_fast - ema_slow) / atr_val

        # Trend filter: halve the score when price is below the long-term EMA
        if len(data) >= trend:
            ema_trend = float(close.ewm(span=trend, adjust=False).mean().iloc[-1])
            if current_price <= ema_trend:
                raw_score *= 0.5

        return float(raw_score)

    def _best_opportunity(self, exclude: str | None = None) -> Tuple[str | None, float]:
        """Return (symbol, score) of the best bullish opportunity."""
        candidates = {
            s: sc
            for s, sc in self._scores.items()
            if s != exclude and sc > 0
        }
        if not candidates:
            return None, 0.0
        best = max(candidates, key=lambda s: candidates[s])
        return best, candidates[best]

    def _top_ranked(self) -> List[Dict[str, Any]]:
        """Return the top-5 ranked coins by score (for metadata / debug)."""
        sorted_coins = sorted(self._scores.items(), key=lambda x: x[1], reverse=True)
        return [{"symbol": s, "score": round(sc, 3)} for s, sc in sorted_coins[:5]]
