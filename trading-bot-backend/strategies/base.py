"""Abstract base strategy class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

from bot.config import SignalType
from bot.orders import FillResult, Order, OrderSide
from bot.portfolio import Portfolio


@dataclass
class Signal:
    """Trading signal emitted by a strategy."""
    strategy_id: str
    symbol: str
    signal_type: SignalType
    confidence: float  # 0.0 – 1.0
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    suggested_size: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None

    def to_order(self, account_id: str = "default") -> Order | None:
        """Convert signal to an Order if applicable."""
        if self.signal_type == SignalType.BUY:
            return Order.market(
                symbol=self.symbol,
                side=OrderSide.BUY,
                quantity=self.suggested_size or 0.0,
                account_id=account_id,
                strategy_id=self.strategy_id,
            )
        if self.signal_type == SignalType.SELL:
            return Order.market(
                symbol=self.symbol,
                side=OrderSide.SELL,
                quantity=self.suggested_size or 0.0,
                account_id=account_id,
                strategy_id=self.strategy_id,
            )
        return None


@dataclass
class StrategyMetrics:
    """Performance metrics for a strategy."""
    strategy_id: str
    total_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    sharpe_ratio: float | None
    max_drawdown: float
    current_streak: int
    total_pnl: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "avg_profit": self.avg_profit,
            "avg_loss": self.avg_loss,
            "profit_factor": self.profit_factor,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "current_streak": self.current_streak,
            "total_pnl": self.total_pnl,
        }


@dataclass
class TickData:
    """Price tick data for strategy on_tick."""
    symbol: str
    price: float
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    name: str = "base"
    DEFAULT_CONFIG: Dict[str, Any] = {}

    @classmethod
    def param_space(cls) -> Dict[str, Dict[str, Any]]:
        """Tunable parameter ranges for hyperopt. Empty = opts out.

        Spec shape per key:
            {"type": "int"|"float"|"categorical",
             "low": ..., "high": ...,    # int/float
             "step": ...,                # optional, float
             "log": True,                # optional, float, log-scale sampling
             "choices": [...]}           # categorical
        """
        return {}

    def __init__(self, strategy_id: str, config: Dict[str, Any]) -> None:
        """Initialize strategy.

        Args:
            strategy_id: Unique strategy identifier.
            config: Strategy-specific configuration.
        """
        self.strategy_id = strategy_id
        self.config = {**self.DEFAULT_CONFIG, **config}
        self.is_active = True
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_pnl = 0.0
        self._history: List[Signal] = []
        self._trades: List[Dict[str, Any]] = []

    # ── Required ──

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Analyze data and emit a trading signal.

        Args:
            data: OHLCV DataFrame up to current point.
            current_price: Current market price.

        Returns:
            Signal with confidence and metadata.
        """
        ...

    # ── Lifecycle ──

    #: Strategies that should fire on multiple symbols within a single bot
    #: instance set this to True. Single-symbol strategies (Grid, Breakout,
    #: Arbitrage) leave it False.
    SUPPORTS_MULTI_SYMBOL: bool = False

    def configured_symbols(self) -> List[str]:
        """Return the list of symbols this strategy instance is scoped to.

        Reads ``config.symbols`` (list) or ``config.symbol`` (single). Empty
        list means 'no symbol filter' (legacy behaviour).
        """
        symbols = self.config.get("symbols")
        if symbols and isinstance(symbols, (list, tuple)):
            return [str(s).strip().upper() for s in symbols if str(s).strip()]
        sym = self.config.get("symbol")
        if sym:
            return [str(sym).strip().upper()]
        return []

    def _size_from_equity_pct(self, current_price: float, default_pct: float = 0.03) -> float:
        """Return quantity for a configurable percent-of-equity position.

        Older strategies used a hardcoded $1k notional, which leaves most of
        a paper account idle. ``position_pct`` is a decimal fraction here
        (0.05 = 5%) to match auto_discovery / squeeze.
        """
        if current_price <= 0:
            return 0.0
        pct = float(self.config.get("position_pct", default_pct) or default_pct)
        pct = max(0.0, min(pct, 0.20))
        equity = float(getattr(self, "_equity", 100_000.0) or 100_000.0)
        return (equity * pct) / current_price

    def _apply_volatility_target(self, signal: "Signal | None", ohlcv_data: Any) -> "Signal | None":
        """Scale a BUY's suggested size to a volatility target (opt-in).

        Enabled per-bot via ``config['volatility_target']``::

            {"enabled": true, "daily_vol": 0.03, "lookback": 20,
             "scale_min": 0.3, "scale_max": 2.5}

        ``scale = clamp(daily_vol / realized_daily_vol, scale_min, scale_max)``.
        Default off — when the block is absent the signal is returned unchanged,
        so existing bots behave exactly as before. The engine's
        ``max_position_size_pct`` cap still bounds the up-scaled size.
        """
        try:
            vt = self.config.get("volatility_target") or {}
            if not vt.get("enabled"):
                return signal
            if signal is None or signal.signal_type != SignalType.BUY:
                return signal
            if not signal.suggested_size or signal.suggested_size <= 0:
                return signal
            if ohlcv_data is None or "close" not in getattr(ohlcv_data, "columns", []):
                return signal
            lookback = int(vt.get("lookback", 20))
            closes = ohlcv_data["close"].astype(float).tail(lookback + 1)
            if len(closes) < 5:
                return signal
            rets = closes.pct_change().dropna()
            realized = float(rets.std())
            if realized <= 0:
                return signal
            target = float(vt.get("daily_vol", 0.03))
            lo = float(vt.get("scale_min", 0.3))
            hi = float(vt.get("scale_max", 2.5))
            scale = max(lo, min(target / realized, hi))
            meta = signal.metadata if isinstance(signal.metadata, dict) else {}
            meta["vol_target"] = {
                "realized_daily": round(realized, 5),
                "target_daily": target,
                "scale": round(scale, 3),
                "size_before": signal.suggested_size,
            }
            signal.suggested_size = signal.suggested_size * scale
            signal.metadata = meta
        except Exception:
            return signal
        return signal

    def _apply_cost_gate(self, signal: "Signal | None", current_price: float) -> "Signal | None":
        """Downgrade a BUY to HOLD when its target can't beat round-trip cost.

        Enabled per-bot via ``config['cost_gate']``::

            {"enabled": true, "round_trip_bps": 30.0, "margin": 1.5}

        ``round_trip_bps`` should cover entry+exit fees + slippage + half-spread
        (default 30 bps ≈ 10 bps fee + 5 bps slippage, each side). A BUY whose
        take-profit is closer than ``round_trip_bps * margin`` is rejected.
        Signals without a take-profit are left untouched (can't assess). Default
        off — absent block ⇒ unchanged behavior.
        """
        try:
            cg = self.config.get("cost_gate") or {}
            if not cg.get("enabled"):
                return signal
            if signal is None or signal.signal_type != SignalType.BUY:
                return signal
            tp = signal.take_profit
            if not tp or not current_price or current_price <= 0:
                return signal
            tp_bps = abs(float(tp) - current_price) / current_price * 1e4
            round_trip_bps = float(cg.get("round_trip_bps", 30.0))
            margin = float(cg.get("margin", 1.5))
            required = round_trip_bps * margin
            if tp_bps < required:
                return Signal(
                    strategy_id=self.strategy_id,
                    symbol=signal.symbol,
                    signal_type=SignalType.HOLD,
                    confidence=0.0,
                    timestamp=signal.timestamp,
                    metadata={
                        "trigger": "cost_gate",
                        "tp_bps": round(tp_bps, 1),
                        "required_bps": round(required, 1),
                        "original_trigger": (signal.metadata or {}).get("trigger"),
                    },
                )
        except Exception:
            return signal
        return signal

    def _apply_funding_gate(self, signal: "Signal | None", symbol: str) -> "Signal | None":
        """Veto a BUY into a crowded-long perp funding regime (opt-in).

        Enabled per-bot via ``config['funding_gate']``::

            {"enabled": true, "max_age_s": 900}

        Reads ``data.funding.cached_funding_signal`` (cache only, no network).
        ``None`` (no/stale data) ⇒ no opinion ⇒ allow. Default off. Only crypto
        symbols will have a funding regime; equities return ``None`` ⇒ allowed.
        """
        try:
            fg = self.config.get("funding_gate") or {}
            if not fg.get("enabled"):
                return signal
            if signal is None or signal.signal_type != SignalType.BUY:
                return signal
            from data.funding import cached_funding_signal

            fsig = cached_funding_signal(symbol, max_age_s=float(fg.get("max_age_s", 900.0)))
            if fsig is None or not fsig.blocks_new_long:
                return signal
            return Signal(
                strategy_id=self.strategy_id,
                symbol=signal.symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=signal.timestamp,
                metadata={
                    "trigger": "funding_gate",
                    "regime": fsig.regime,
                    "funding_rate": fsig.funding_rate,
                    "original_trigger": (signal.metadata or {}).get("trigger"),
                },
            )
        except Exception:
            return signal

    def _apply_regime_gate(self, signal: "Signal | None", ohlcv_data: Any) -> "Signal | None":
        """Veto a BUY when price is below the trend EMA — a confirmed downtrend.

        Enabled per-bot via ``config['regime_gate']``::

            {"enabled": true, "trend_ema": 100}

        Long-biased dip-buyers / scanners bled by opening longs into a falling
        market (the crypto bear: BTC -36%, ETH -26%). When the latest close is
        below the EMA, downgrade the BUY to HOLD. SELLs are never gated. Default
        off — absent block ⇒ unchanged behavior. Needs >= trend_ema bars to act,
        so short backtests / unit fixtures are unaffected.
        """
        try:
            rg = self.config.get("regime_gate") or {}
            if not rg.get("enabled"):
                return signal
            if signal is None or signal.signal_type != SignalType.BUY:
                return signal
            if ohlcv_data is None or "close" not in getattr(ohlcv_data, "columns", []):
                return signal
            period = int(rg.get("trend_ema", 100))
            closes = ohlcv_data["close"].astype(float)
            if period <= 0 or len(closes) < period:
                return signal
            trend = float(closes.ewm(span=period, adjust=False).mean().iloc[-1])
            price = float(closes.iloc[-1])
            if price >= trend:
                return signal
            return Signal(
                strategy_id=self.strategy_id,
                symbol=signal.symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                timestamp=signal.timestamp,
                metadata={
                    "trigger": "regime_gate",
                    "price": round(price, 6),
                    "trend_ema": round(trend, 6),
                    "original_trigger": (signal.metadata or {}).get("trigger"),
                },
            )
        except Exception:
            return signal

    def _matches_symbol(self, tick_symbol: str) -> bool:
        """True when the tick's symbol is in this strategy's scope."""
        configured = self.configured_symbols()
        if not configured:
            return True  # no filter configured → legacy: accept all
        target = str(tick_symbol).strip().upper()
        return target in configured

    def on_tick(self, tick: TickData, portfolio: Portfolio, **kwargs: Any) -> Signal | None:
        """Called on every price tick.

        Default implementation filters by configured symbol(s), checks
        global signal-context guards (high VIX, imminent earnings), then
        calls ``generate_signal`` with the OHLCV data when present.

        kwargs may contain:
          ohlcv_data       — OHLCV DataFrame for indicator computation
          signal_context   — SignalContext (macro / sentiment / catalysts)
        """
        if not self._matches_symbol(tick.symbol):
            return None

        # Global signal gates — applied to every strategy by default. Strategies
        # can opt out by setting ``RESPECTS_SIGNAL_CONTEXT = False`` on the class.
        sig_ctx = kwargs.get("signal_context")
        if sig_ctx is not None and getattr(self, "RESPECTS_SIGNAL_CONTEXT", True):
            blocked = self._signal_gate_check(sig_ctx, tick.symbol)
            if blocked:
                return None

        ohlcv_data = kwargs.get("ohlcv_data")
        if ohlcv_data is not None and len(ohlcv_data) > 0:
            ohlcv_data = ohlcv_data.copy()
            ohlcv_data.attrs["symbol"] = tick.symbol
            self._signal_context = sig_ctx  # available to generate_signal subclasses
            # Snapshot live equity so pct-based sizing (auto_discovery,
            # squeeze, simple_trend, news_sentiment) scales against the
            # actual account, not a hardcoded $1k baseline.
            #
            # Broker syncs (Alpaca) populate _balances with overlapping
            # ledger keys: USD (cash), EQUITY (already cash+positions),
            # BUYING_POWER (margin). Summing all keys double-counts wildly,
            # so we mirror api/routes/portfolio.py:152-160's picker:
            # prefer an explicit EQUITY key if present, else sum just the
            # cash keys + position market values.
            try:
                bal = portfolio.get_all_balances() if portfolio else {}
                positions = portfolio.get_all_positions() if portfolio else []
                if bal and any(k.upper() == "EQUITY" for k in bal):
                    eq_key = next(k for k in bal if k.upper() == "EQUITY")
                    _eq = float(bal[eq_key])
                else:
                    cash_keys = {"USD", "USDT", "CASH"}
                    cash = sum(v for k, v in bal.items() if k.upper() in cash_keys)
                    mv = sum(p.market_value or 0.0 for p in positions)
                    _eq = float(cash + mv)
                self._equity = _eq if _eq > 0 else 100_000.0
            except Exception:
                self._equity = 100_000.0
            signal = self.generate_signal(ohlcv_data, tick.price)
            # Volatility-target overlay (opt-in, default off). Scales a BUY's
            # suggested size inversely to recent realized volatility so calm
            # names get more capital and choppy names less — equalizing risk
            # per position. The downstream max_position_size_pct cap still
            # bounds the result.
            signal = self._apply_volatility_target(signal, ohlcv_data)
            # Cost-aware entry gate (opt-in, default off): reject a BUY whose
            # take-profit target can't clear estimated round-trip cost with
            # margin. At minutes cadence, turnover cost dominates PnL — this
            # stops deploying trades that are net-negative before they start.
            signal = self._apply_cost_gate(signal, tick.price)
            # Funding-regime gate (opt-in, default off): veto BUYs into a
            # crowded-long perp funding regime. Reads a cache populated by the
            # background funding loop — ZERO network I/O in the tick path.
            signal = self._apply_funding_gate(signal, tick.symbol)
            # Regime gate (opt-in, default off): veto BUYs into a confirmed
            # downtrend (price below the trend EMA). Stops long-biased
            # dip-buyers / scanners from opening into a falling market — the
            # pattern behind the big crypto losers (ETH/BTC/SOL).
            signal = self._apply_regime_gate(signal, ohlcv_data)
            # Position-aware BUY gate: if the strategy proposes to open a
            # long but the portfolio already has an open long position on
            # the same symbol, downgrade to HOLD. This kills the "every
            # backend restart adds another BUY" bug — strategies' in-memory
            # ``_last_side`` latch is wiped on restart, so without this
            # check they re-fire BUY on every already-held name.
            if signal is not None and signal.signal_type == SignalType.BUY and portfolio is not None:
                try:
                    pos = portfolio.get_position(tick.symbol)
                except Exception:
                    pos = None
                # Treat sub-cent dust as "not held" — leftover fractional
                # remainders from prior sells (size like 7e-9) used to block
                # fresh BUYs forever because the broker can't close them and
                # the gate counted them as a real position. Anything with
                # market value under $1 (or size below the broker's minimum
                # order increment for any reasonable price) is dust.
                _held_size = float(getattr(pos, "size", 0) or 0)
                _held_mv = float(getattr(pos, "market_value", 0) or 0)
                _is_dust = _held_size < 1e-6 or (_held_mv != 0 and abs(_held_mv) < 1.0)
                if pos is not None and _held_size > 0 and not _is_dust and getattr(pos, "status", "") == "open":
                    import logging as _log
                    _log.getLogger("volta.engine").debug(
                        f"position-aware gate: {self.strategy_id} BUY on {tick.symbol} "
                        f"suppressed — already long {float(getattr(pos, 'size', 0))} shares"
                    )
                    return Signal(
                        strategy_id=self.strategy_id,
                        symbol=tick.symbol,
                        signal_type=SignalType.HOLD,
                        confidence=0.0,
                        timestamp=signal.timestamp,
                        metadata={
                            "trigger": "already_holding_long",
                            "held_qty": float(getattr(pos, "size", 0)),
                            "original_trigger": (signal.metadata or {}).get("trigger"),
                        },
                    )
            # Position-aware SELL gate: clamp suggested_size to held qty;
            # downgrade to HOLD when nothing is held or qty is dust. Without
            # this, fixed-dollar SELL sizing can submit qty=0 (rounded down)
            # or a positive qty on symbols we don't hold (the broker just
            # rejects, but it logs rate-limit pressure and noise).
            if signal is not None and signal.signal_type == SignalType.SELL and portfolio is not None:
                try:
                    pos = portfolio.get_position(tick.symbol)
                except Exception:
                    pos = None
                held = float(getattr(pos, "size", 0)) if pos is not None else 0.0
                # Treat anything below 1e-9 as zero — covers float-noise residuals.
                if held <= 1e-9:
                    import logging as _log
                    _log.getLogger("volta.engine").debug(
                        f"position-aware gate: {self.strategy_id} SELL on {tick.symbol} "
                        f"suppressed — nothing held"
                    )
                    return Signal(
                        strategy_id=self.strategy_id,
                        symbol=tick.symbol,
                        signal_type=SignalType.HOLD,
                        confidence=0.0,
                        timestamp=signal.timestamp,
                        metadata={
                            "trigger": "no_position_to_sell",
                            "original_trigger": (signal.metadata or {}).get("trigger"),
                        },
                    )
                # Agentic exit: a strategy SELL on a symbol we hold is a
                # directional exit (trend flip / stop / score decay), not a
                # scale-out. Close the FULL held quantity by default — otherwise
                # a flip signal sized at e.g. 3%-of-equity notional leaves most
                # of the position open against the freshly-confirmed adverse
                # trend (the agentic-exit leak across momentum/macd/MR/bband/
                # swing/news bots, all of which size SELLs off equity, not the
                # held position). Strategies wanting a partial scale-out set
                # metadata['partial']=True; engine-managed take-profit trims use
                # a separate path and never reach this gate.
                _meta = signal.metadata if isinstance(signal.metadata, dict) else {}
                if not _meta.get("partial"):
                    if signal.suggested_size is None or abs(signal.suggested_size - held) > 1e-9:
                        _meta["exit_full_close_from"] = signal.suggested_size
                        signal.suggested_size = held
                        signal.metadata = _meta
                elif signal.suggested_size is not None and signal.suggested_size > held:
                    signal.suggested_size = held
                    _meta["sell_clamped_from"] = "oversize"
                    signal.metadata = _meta
                # Final dust check — qty=0 (post-clamp rounding) should not
                # leave the strategy; let the engine treat as HOLD.
                if signal.suggested_size is not None and signal.suggested_size <= 1e-9:
                    return Signal(
                        strategy_id=self.strategy_id,
                        symbol=tick.symbol,
                        signal_type=SignalType.HOLD,
                        confidence=0.0,
                        timestamp=signal.timestamp,
                        metadata={
                            "trigger": "sell_qty_dust",
                            "original_trigger": (signal.metadata or {}).get("trigger"),
                        },
                    )
            return signal
        return None

    #: Strategies that want to bypass the macro/earnings gates can set this False.
    RESPECTS_SIGNAL_CONTEXT: bool = True

    #: Per-strategy thresholds — override in subclasses to tune.
    VIX_PANIC_THRESHOLD: float = 35.0
    EARNINGS_BLOCK_DAYS: int = 1

    def _signal_gate_check(self, sig_ctx: Any, symbol: str) -> bool:
        """Return True when strategy should skip this tick due to global signals.

        Default rules (conservative):
          - VIX > VIX_PANIC_THRESHOLD → skip new entries
          - Earnings within EARNINGS_BLOCK_DAYS → skip
        """
        try:
            if sig_ctx.vix is not None and sig_ctx.vix > self.VIX_PANIC_THRESHOLD:
                return True
            if sig_ctx.is_blocking_earnings(symbol, days=self.EARNINGS_BLOCK_DAYS):
                return True
        except Exception:
            pass
        return False

    def on_fill(self, fill: FillResult, portfolio: Portfolio) -> None:
        """Callback when an order from this strategy is filled."""
        self.trade_count += 1
        if fill.realized_pnl is not None:
            self.total_pnl += fill.realized_pnl
            if fill.realized_pnl > 0:
                self.win_count += 1
            else:
                self.loss_count += 1
            self._trades.append(
                {
                    "pnl": fill.realized_pnl,
                    "price": fill.filled_price,
                    "timestamp": fill.timestamp,
                }
            )

    def on_init(self, market_data: Any) -> None:
        """Pre-load historical data, warm up indicators."""
        pass

    def on_stop(self) -> None:
        """Cleanup, persist state."""
        pass

    # ── Metrics ──

    def get_metrics(self) -> StrategyMetrics:
        """Return performance metrics for this strategy."""
        win_rate = self.win_count / max(1, self.trade_count) * 100
        profits = [t["pnl"] for t in self._trades if t["pnl"] > 0]
        losses = [t["pnl"] for t in self._trades if t["pnl"] <= 0]
        avg_profit = np.mean(profits) if profits else 0.0
        avg_loss = abs(np.mean(losses)) if losses else 0.0
        profit_factor = (
            sum(profits) / max(1e-9, abs(sum(losses)))
            if losses or profits
            else 0.0
        )
        # Simple drawdown calculation
        max_dd = 0.0
        peak = 0.0
        cum_pnl = 0.0
        for t in self._trades:
            cum_pnl += t["pnl"]
            peak = max(peak, cum_pnl)
            dd = peak - cum_pnl
            max_dd = max(max_dd, dd)

        return StrategyMetrics(
            strategy_id=self.strategy_id,
            total_trades=self.trade_count,
            win_rate=win_rate,
            avg_profit=avg_profit,
            avg_loss=-avg_loss,
            profit_factor=profit_factor,
            sharpe_ratio=None,
            max_drawdown=max_dd,
            current_streak=0,
            total_pnl=self.total_pnl,
        )

    def reset(self) -> None:
        """Reset internal state for backtesting or restart."""
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_pnl = 0.0
        self._history.clear()
        self._trades.clear()

    # ── Helpers ──

    def _record_signal(self, signal: Signal) -> None:
        """Record a generated signal in history."""
        self._history.append(signal)

    @staticmethod
    def _bar_key(index_value: Any) -> Any:
        """Stable per-bar identity for the signal-latch dict.

        Different fetchers can return DataFrames where the last bar is a
        ``pd.Timestamp`` (with or without tz), a python ``datetime``, a
        numpy datetime64, or even a positional int. Comparing those raw
        values cross-type silently fails (the latch never matches), and
        the strategy re-fires the same signal every tick. Normalize to a
        tz-aware UTC ``pd.Timestamp`` when possible, else a string. Same
        bar -> same key regardless of source representation.
        """
        if index_value is None:
            return None
        try:
            ts = pd.Timestamp(index_value)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            return ts
        except Exception:
            return str(index_value)

    @staticmethod
    def _ensure_columns(data: pd.DataFrame) -> pd.DataFrame:
        """Ensure required OHLCV columns exist."""
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(data.columns)
        if missing:
            # Try case-insensitive match
            col_map = {c.lower(): c for c in data.columns}
            for req in missing:
                if req in col_map:
                    data[req] = data[col_map[req]]
        return data
