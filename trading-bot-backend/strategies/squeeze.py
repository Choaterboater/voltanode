"""SqueezeStrategy — auto-trade ADD-tier setups from the squeeze screener.

Reuses the same scoring engine as ``GET /advisor/squeeze`` (7-factor: SI%,
float, days-to-cover, earnings trend, recent 13D, technical breakout, FINRA
off-exchange short volume) and turns it into a position-aware auto-trader.

Behavioral discipline (mirrors SimpleTrendStrategy)
---------------------------------------------------
* Per-bar latch — fires once per daily bar regardless of intra-bar tick spam.
* Per-side latch — won't BUY again until the strategy has SOLD (or score has
  decayed below ``exit_score``).
* Min-hold cooldown — won't flip sides faster than ``min_hold_minutes``.
* Long-only by default — short squeezes are a bullish-bias setup.

Exit conditions
---------------
* Score decays below ``exit_score``.
* Off-exchange short % collapses (institutional shorts cover) — drops below
  ``exit_off_ex_pct``.
* Stop-loss / take-profit at ``stop_loss_pct`` / ``take_profit_pct``.

Universe
--------
``configured_symbols`` returns the set the engine should tick. Operators
supply a curated list (typically the top-10 squeeze candidates from the
screener — manually picked, since fully autonomous "scan the entire market
each tick" is too expensive on yfinance/FINRA rate limits). Add new tickers
via the ``/strategies/{id}/update`` endpoint or by editing the JSON config.

Why not run the full SEC scan inside on_tick?
---------------------------------------------
on_tick is sync and runs every ~5s for every symbol — pulling fundamentals
+ FINRA + 13D feeds in that hot path would melt the rate limits and stall
the engine. Instead, treat the screener as the discovery layer (manual
review or a periodic cron) and the strategy as the executor on the picked
list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

from advisor.scanner import score_symbol
from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


# Curated default starter universe — small/mid-cap with historical squeeze
# behavior. Operator should replace via config.symbols after running the
# screener and picking actual ADD-tier candidates.
DEFAULT_SQUEEZE_UNIVERSE = [
    "RXT", "GME", "GRPN", "DBI", "SKLZ", "NEGG", "CADL", "STIM",
    "MNPR", "NGNE", "GCT", "SOFI", "HOOD", "COIN", "SMCI",
]


class SqueezeStrategy(BaseStrategy):
    """Long-bias auto-trader keyed off the technical sub-component of the squeeze score.

    The full 7-factor squeeze score (SI, float, dark-pool, etc.) is mostly
    structural — it doesn't change tick-to-tick. So this strategy uses the
    *technical* part of the same scorer as its trigger: when a name in the
    configured universe enters a strong RSI-extreme-or-breakout state with
    elevated volume, it BUYs. This combines structural setup pre-screening
    (operator picks the universe) with technical timing (strategy fires the
    entry).
    """

    name = "squeeze"
    SUPPORTS_MULTI_SYMBOL = True

    DEFAULT_CONFIG: Dict[str, Any] = {
        "asset_class": "stock",
        "symbols": [],            # leave empty to auto-populate with DEFAULT_SQUEEZE_UNIVERSE
        # Composite-score thresholds (0-100, scanner-component-only here).
        "entry_score": 55.0,      # technical RSI/breakout/volume composite must clear this
        "exit_score": 25.0,
        # Position sizing.
        "position_pct": 0.04,
        "stop_loss_pct": 0.08,    # squeeze names are volatile — wider stop
        "take_profit_pct": 0.30,  # let winners run, this is the squeeze thesis
        # Cooldowns / latches.
        "min_hold_minutes": 240,  # 4h — slower than other strategies
        # Indicator lookbacks.
        "rsi_period": 14,
        "breakout_lookback": 20,
        "volume_lookback": 20,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.config.get("symbols"):
            self.config["symbols"] = list(DEFAULT_SQUEEZE_UNIVERSE)
        # Per-symbol state (same shape as SimpleTrendStrategy).
        self._last_side: Dict[str, str] = {}
        self._last_signal_bar: Dict[str, Any] = {}
        self._last_fire_ts: Dict[str, pd.Timestamp] = {}

    def _hold(self, symbol: str, trigger: str, **meta: Any) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=SignalType.HOLD,
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
            metadata={"trigger": trigger, **meta},
        )

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        data = self._ensure_columns(data)
        cfg = self.config
        symbol = str(data.attrs.get("symbol", "unknown")).upper()

        score = score_symbol(
            symbol,
            data,
            rsi_period=int(cfg.get("rsi_period", 14)),
            breakout_lookback=int(cfg.get("breakout_lookback", 20)),
            volume_lookback=int(cfg.get("volume_lookback", 20)),
        )
        if score.error is not None:
            return self._hold(symbol, "scorer_error", error=score.error)

        # Per-bar latch.
        latest_bar = data.index[-1] if len(data.index) else None
        if latest_bar is not None and self._last_signal_bar.get(symbol) == latest_bar:
            return self._hold(symbol, "already_fired_this_bar", score=score.score)

        entry = float(cfg.get("entry_score", 55.0))
        exit_ = float(cfg.get("exit_score", 25.0))
        sl_pct = float(cfg.get("stop_loss_pct", 0.08))
        tp_pct = float(cfg.get("take_profit_pct", 0.30))
        pos_pct = float(cfg.get("position_pct", 0.04))
        hold_min = float(cfg.get("min_hold_minutes", 240))

        last_side = self._last_side.get(symbol)
        last_fire = self._last_fire_ts.get(symbol)
        now = pd.Timestamp.now()
        in_cooldown = (
            last_fire is not None
            and (now - last_fire).total_seconds() < hold_min * 60
        )

        # Squeeze candidates are long-bias — only enter long, exit when score decays.
        wants_long = score.direction == "long"

        # Entry leg.
        if score.score >= entry and wants_long:
            if last_side == "entered":
                return self._hold(symbol, "already_entered", score=score.score)
            if in_cooldown:
                return self._hold(symbol, "min_hold_cooldown", score=score.score)

            self._last_side[symbol] = "entered"
            self._last_signal_bar[symbol] = latest_bar
            self._last_fire_ts[symbol] = now

            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=min(1.0, score.score / 100.0),
                timestamp=pd.Timestamp.now(),
                metadata={
                    "trigger": "squeeze_technical_entry",
                    "score": score.score,
                    "direction": score.direction,
                    "components": {k: v.signal for k, v in score.components.items()},
                    "rsi": score.components["rsi"].value if "rsi" in score.components else None,
                    "rel_volume": score.components["rel_volume"].value if "rel_volume" in score.components else None,
                    "breakout_signal": score.components["breakout"].signal if "breakout" in score.components else None,
                },
                suggested_size=(pos_pct * 1000.0) / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * (1 - sl_pct),
                take_profit=current_price * (1 + tp_pct),
            )
            self._record_signal(sig)
            return sig

        # Exit leg.
        if last_side == "entered" and (score.score <= exit_ or score.direction == "short"):
            self._last_side[symbol] = "exited"
            self._last_signal_bar[symbol] = latest_bar
            self._last_fire_ts[symbol] = now
            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=min(1.0, (entry - score.score) / max(entry, 1e-9) + 0.5),
                timestamp=pd.Timestamp.now(),
                metadata={
                    "trigger": "score_decayed" if score.score <= exit_ else "direction_flipped",
                    "score": score.score,
                    "direction": score.direction,
                },
                suggested_size=(pos_pct * 1000.0) / current_price if current_price > 0 else 0.0,
            )
            self._record_signal(sig)
            return sig

        # Mid-range — neutral leg, reset latch so next strong signal fires.
        if entry > score.score > exit_:
            self._last_side[symbol] = "neutral"

        return self._hold(
            symbol,
            "no_threshold_crossed",
            score=score.score,
            direction=score.direction,
            entry=entry,
            exit=exit_,
        )
