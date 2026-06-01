"""Auto-discovery strategy — universe-scanning composite-score trader.

Each tick, the engine calls this strategy with one of its configured-universe
symbols. We score that single symbol with the same RSI + breakout + relative-volume
composite used by ``GET /advisor/scanner``, then decide:

* **BUY** when the score crosses ``entry_score`` upward AND the directional bias
  is long AND we haven't already taken this leg (per-side latch).
* **SELL** when the score decays below ``exit_score`` OR direction flips short
  AND we have an open leg.

This means we don't need a synchronous batch scan inside ``on_tick`` — the
engine already iterates the universe symbol-by-symbol, and each symbol's score
implicitly creates a leaderboard via the entry/exit thresholds. Operators can
tune the thresholds to widen or narrow the active set.

Per-bar latch + per-side latch + min-hold cooldown match the pattern in
``SimpleTrendStrategy`` so the auto-discovery bot doesn't fight the ensemble
veto or fire churn signals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd

from advisor.scanner import score_symbol
from advisor.llm_advisor import pretrade_check
from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


# Curated default universes — used when an operator registers an
# ``auto_discovery`` strategy without specifying ``config.symbols``. Kept aligned
# with the scanner-route fallback lists in ``api/routes/advisor.py``.
DEFAULT_CRYPTO_UNIVERSE = [
    "BTC", "ETH", "SOL", "AVAX", "LINK", "DOGE", "SHIB", "LTC", "BCH",
    "UNI", "AAVE", "MATIC", "MKR", "SUSHI", "YFI", "ADA", "XRP", "DOT",
    "BNB", "TRX",
]

DEFAULT_STOCK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "AMD",
    "JPM", "BAC", "WMT", "COST", "HD", "JNJ", "UNH", "XOM", "CAT",
    "CRM", "ORCL", "ADBE", "NFLX", "DIS", "AVGO", "PLTR",
    "SPY", "QQQ", "IWM",
]


class AutoDiscoveryStrategy(BaseStrategy):
    """Universe-scanning long-bias strategy keyed off the scanner composite score."""

    name = "auto_discovery"
    SUPPORTS_MULTI_SYMBOL = True

    DEFAULT_CONFIG: Dict[str, Any] = {
        # Universe — leave empty to auto-populate from the asset_class default list.
        "asset_class": "crypto",
        "symbols": [],
        # Composite-score thresholds (0–100).
        "entry_score": 52.0,
        "exit_score": 30.0,
        # Position sizing — same convention as SimpleTrendStrategy.
        "position_pct": 0.05,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.12,
        # Cooldowns / latches.
        "min_hold_minutes": 60,
        # Indicator lookbacks (must match scanner defaults unless tuning).
        "rsi_period": 14,
        "breakout_lookback": 20,
        "volume_lookback": 20,
        # Direction filter: "long_only" (default), "short_only", or "both". Most
        # paper/live brokers don't support shorting crypto so long_only is safe.
        "direction_mode": "long_only",
        # LLM pre-trade gate — when True, every entry BUY (or SELL when
        # short_only) gets a sanity-check from the OpenRouter Haiku chain
        # before submission. Cached 60s per (symbol, side); fails OPEN so
        # an LLM outage never blocks trading.
        "enable_llm_gate": False,
        # Watchlist auto-include — merge symbols from data/watchlist.json
        # whose ``source`` is in ``watchlist_source_allowlist`` into the
        # universe each tick. Lets external apps (e.g. an alerts pipeline
        # POSTing to /watchlist/) get their picks auto-traded without
        # requiring config edits. Manual entries are excluded by default
        # so a typo can't fire a real order.
        "include_watchlist": False,
        "watchlist_source_allowlist": ["squeeze", "scanner", "tradingbot"],
        "watchlist_refresh_seconds": 60,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Auto-populate universe if operator left it empty.
        if not self.config.get("symbols"):
            asset_class = str(self.config.get("asset_class", "crypto")).lower()
            self.config["symbols"] = (
                list(DEFAULT_STOCK_UNIVERSE)
                if asset_class == "stock"
                else list(DEFAULT_CRYPTO_UNIVERSE)
            )

        # Watchlist-merge cache — populated lazily in configured_symbols().
        self._watchlist_cache: list = []
        self._watchlist_cache_at: float = 0.0

        # Per-symbol last-emitted side and bar latches — same shape as SimpleTrend.
        self._last_side: Dict[str, str] = {}        # symbol → "entered" | "exited" | "neutral"
        self._last_signal_bar: Dict[str, Any] = {}  # symbol → bar timestamp
        self._last_fire_ts: Dict[str, pd.Timestamp] = {}  # symbol → last fire time

    def configured_symbols(self) -> list:
        """Return the symbols this bot is scoped to, optionally merged with
        watchlist entries whose ``source`` matches the allowlist.

        Refreshes the watchlist read every ``watchlist_refresh_seconds`` to
        avoid hitting disk on every tick (the engine's tick loop calls this
        per iteration).
        """
        base_symbols = super().configured_symbols()
        if not self.config.get("include_watchlist", False):
            return base_symbols

        import time
        import json
        from pathlib import Path

        ttl = float(self.config.get("watchlist_refresh_seconds", 60))
        now = time.time()
        if now - self._watchlist_cache_at > ttl:
            self._watchlist_cache_at = now
            try:
                path = Path("data") / "watchlist.json"
                if path.exists():
                    raw = json.loads(path.read_text())
                    if not isinstance(raw, list):
                        raw = []
                    asset_class = str(self.config.get("asset_class", "crypto")).lower()
                    allowed = {
                        s.strip().lower()
                        for s in self.config.get("watchlist_source_allowlist") or []
                        if s
                    }
                    cache: list = []
                    for it in raw:
                        if not isinstance(it, dict):
                            continue
                        if str(it.get("asset_type", "")).lower() != asset_class:
                            continue
                        if allowed and str(it.get("source", "")).lower() not in allowed:
                            continue
                        sym = str(it.get("symbol", "")).strip().upper()
                        if sym:
                            cache.append(sym)
                    self._watchlist_cache = cache
                else:
                    self._watchlist_cache = []
            except Exception:
                self._watchlist_cache = []

        # Merge, dedupe, preserve order: configured symbols first, then
        # watchlist additions.
        seen: set = set()
        merged: list = []
        for s in list(base_symbols) + list(self._watchlist_cache):
            if s not in seen:
                seen.add(s)
                merged.append(s)
        return merged

    def _hold(self, symbol: str, trigger: str, **meta: Any) -> Signal:
        """Helper: HOLD signal with metadata."""
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

        rsi_period = int(cfg.get("rsi_period", 14))
        bo_lookback = int(cfg.get("breakout_lookback", 20))
        vol_lookback = int(cfg.get("volume_lookback", 20))

        # Score this symbol with the same scorer the manual /advisor/scanner uses.
        score = score_symbol(
            symbol,
            data,
            rsi_period=rsi_period,
            breakout_lookback=bo_lookback,
            volume_lookback=vol_lookback,
        )

        if score.error is not None:
            return self._hold(symbol, "scorer_error", error=score.error, score=score.score)

        # Per-bar latch — same approach as SimpleTrendStrategy. Once we've
        # emitted a non-HOLD on this bar, hold until the bar advances.
        latest_bar = data.index[-1] if len(data.index) else None
        if latest_bar is not None and self._last_signal_bar.get(symbol) == latest_bar:
            return self._hold(symbol, "already_fired_this_bar", score=score.score)

        entry = float(cfg.get("entry_score", 60.0))
        exit_ = float(cfg.get("exit_score", 30.0))
        sl_pct = float(cfg.get("stop_loss_pct", 0.05))
        tp_pct = float(cfg.get("take_profit_pct", 0.12))
        pos_pct = float(cfg.get("position_pct", 0.05))
        hold_min = float(cfg.get("min_hold_minutes", 60))
        direction_mode = str(cfg.get("direction_mode", "long_only")).lower()

        last_side = self._last_side.get(symbol)
        last_fire = self._last_fire_ts.get(symbol)
        now = pd.Timestamp.now()
        in_cooldown = (
            last_fire is not None
            and (now - last_fire).total_seconds() < hold_min * 60
        )

        wants_long = direction_mode in ("long_only", "both") and score.direction == "long"
        wants_short = direction_mode in ("short_only", "both") and score.direction == "short"

        # ── Entry leg ──
        if score.score >= entry and (wants_long or wants_short):
            if last_side == "entered":
                return self._hold(symbol, "already_entered", score=score.score)
            if in_cooldown:
                return self._hold(symbol, "min_hold_cooldown", score=score.score)

            self._last_side[symbol] = "entered"
            self._last_signal_bar[symbol] = latest_bar
            self._last_fire_ts[symbol] = now

            signal_type = SignalType.BUY if wants_long else SignalType.SELL
            confidence = min(1.0, score.score / 100.0)
            metadata = {
                "trigger": "entry_score_crossed",
                "score": score.score,
                "direction": score.direction,
                "components": {k: v.signal for k, v in score.components.items()},
                "rsi": score.components.get("rsi").value if "rsi" in score.components else None,
                "rel_volume": score.components.get("rel_volume").value if "rel_volume" in score.components else None,
                "breakout_signal": score.components.get("breakout").signal if "breakout" in score.components else None,
            }

            # Optional LLM pre-trade gate. Veto downgrades entry to HOLD,
            # records the rationale in metadata, and releases the per-side
            # latch so a future tick can re-attempt once cache expires.
            if self.config.get("enable_llm_gate", True):
                try:
                    # Opt-in RAG: feed the LLM gate this setup's trade-memory
                    # so it can veto a setup that has repeatedly lost. Default
                    # off; only reads the small memory file on entry attempts
                    # (rare), behind the already-slow LLM gate.
                    mem_brief = None
                    if self.config.get("memory_aware"):
                        try:
                            from learning.trade_memory import TradeMemory
                            if not hasattr(self, "_trade_memory"):
                                self._trade_memory = TradeMemory()
                            mem_brief = self._trade_memory.recall_brief(symbol, self.name) or None
                        except Exception:
                            mem_brief = None
                    verdict = pretrade_check(
                        symbol=symbol,
                        side="BUY" if signal_type == SignalType.BUY else "SELL",
                        confidence=confidence,
                        indicators={
                            "score": score.score,
                            "rsi": metadata.get("rsi"),
                            "rel_volume": metadata.get("rel_volume"),
                            "breakout": metadata.get("breakout_signal"),
                        },
                        current_price=current_price,
                        memory_brief=mem_brief,
                    )
                    if verdict.get("verdict") == "veto":
                        self._last_side[symbol] = last_side  # release latch
                        return Signal(
                            strategy_id=self.strategy_id,
                            symbol=symbol,
                            signal_type=SignalType.HOLD,
                            confidence=0.0,
                            timestamp=pd.Timestamp.now(),
                            metadata={
                                "trigger": "llm_veto",
                                "llm_reason": verdict.get("reason", ""),
                                "llm_model": verdict.get("model", ""),
                                "original_trigger": "entry_score_crossed",
                                "score": score.score,
                            },
                        )
                    metadata["llm_gate"] = verdict.get("verdict", "proceed")
                    metadata["llm_cached"] = verdict.get("cached", False)
                except Exception:
                    # Never let LLM gate failure block trading; fall through
                    metadata["llm_gate"] = "error_proceed"

            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=signal_type,
                confidence=confidence,
                timestamp=pd.Timestamp.now(),
                metadata=metadata,
                suggested_size=(pos_pct * getattr(self, "_equity", 100_000.0)) / current_price if current_price > 0 else 0.0,
                stop_loss=current_price * (1 - sl_pct) if signal_type == SignalType.BUY else current_price * (1 + sl_pct),
                take_profit=current_price * (1 + tp_pct) if signal_type == SignalType.BUY else current_price * (1 - tp_pct),
            )
            self._record_signal(sig)
            return sig

        # ── Exit leg ──
        # Close when score decays below exit_score OR direction flips against us.
        score_decayed = score.score <= exit_
        direction_flipped = (
            (last_side == "entered")
            and direction_mode == "long_only"
            and score.direction == "short"
        )
        if last_side == "entered" and (score_decayed or direction_flipped):
            self._last_side[symbol] = "exited"
            self._last_signal_bar[symbol] = latest_bar
            self._last_fire_ts[symbol] = now

            # If we entered long, exit with SELL; reversed for short_only mode.
            exit_signal_type = SignalType.SELL if direction_mode != "short_only" else SignalType.BUY
            sig = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=exit_signal_type,
                confidence=min(1.0, (entry - score.score) / max(entry, 1e-9) + 0.5),
                timestamp=pd.Timestamp.now(),
                metadata={
                    "trigger": "score_decayed" if score_decayed else "direction_flipped",
                    "score": score.score,
                    "direction": score.direction,
                    "components": {k: v.signal for k, v in score.components.items()},
                },
                # Engine clamps SELL suggested_size to held quantity — pass a
                # generous size and let the engine layer figure the right qty.
                suggested_size=(pos_pct * getattr(self, "_equity", 100_000.0)) / current_price if current_price > 0 else 0.0,
                stop_loss=None,
                take_profit=None,
            )
            self._record_signal(sig)
            return sig

        # Mid-range — keep waiting. Reset latch on neutral so next strong signal fires.
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
