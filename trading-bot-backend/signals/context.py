"""SignalContext — unified read-only view of external signals for strategies.

Strategies receive a ``SignalContext`` instance via ``BaseStrategy.on_tick``
so they can gate entries/exits on macro state, sentiment extremes, and
catalyst proximity without each strategy having to call the signal
modules itself.

Usage in a strategy:

    def on_tick(self, tick, portfolio, *, signal_context=None, **kwargs):
        if signal_context is None:
            return ...                                # no signal data, fall through
        if signal_context.vix > 30:
            return None                               # panic — skip entries
        if signal_context.is_blocking_earnings(tick.symbol, days=2):
            return None                               # earnings imminent
        if signal_context.fear_greed_value < 25 and rsi < 30:
            return Signal(..., signal_type=BUY, ...)  # buy capitulation

The aggregator is built once per tick cycle (in api.main._run_tick_loop)
and cached so per-symbol Finnhub lookups don't fire 60×/min.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("volta.signals.context")


@dataclass
class SignalContext:
    """Read-only snapshot of external signals at one tick."""

    fear_greed_value: Optional[int] = None  # 0-100
    fear_greed_label: str = ""
    fear_greed_is_extreme_fear: bool = False
    fear_greed_is_extreme_greed: bool = False

    # FRED macro values (None when feed unconfigured / unavailable)
    vix: Optional[float] = None
    fed_funds: Optional[float] = None
    treasury_10y: Optional[float] = None
    treasury_2y: Optional[float] = None
    yield_curve_spread: Optional[float] = None  # 10y - 2y; <0 = inverted
    # Inflation:
    cpi: Optional[float] = None
    ppi_final: Optional[float] = None  # PPI Final Demand — leads CPI 1-3 months
    core_pce: Optional[float] = None  # Fed's actual target inflation gauge
    unemployment: Optional[float] = None
    # Credit spreads — direct read on corporate refi pressure. Widening
    # IG spreads mean BAA-rated co's refinance at materially higher
    # cost; HY OAS spike = distress in the riskier debt strata.
    baa_10y_spread: Optional[float] = None    # Investment-grade spread
    hy_oas: Optional[float] = None            # High-yield option-adjusted spread

    # Per-symbol caches populated lazily
    _earnings_cache: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    _insider_cache: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Convenience derived properties

    @property
    def vix_panic(self) -> bool:
        return self.vix is not None and self.vix > 30

    @property
    def vix_elevated(self) -> bool:
        return self.vix is not None and self.vix > 20

    @property
    def yield_curve_inverted(self) -> bool:
        return self.yield_curve_spread is not None and self.yield_curve_spread < 0

    # Per-symbol queries

    def is_blocking_earnings(self, symbol: str, days: int = 2) -> bool:
        """True when ``symbol`` has earnings within ``days`` days.

        Uses the per-tick Finnhub cache so each symbol queries the API at
        most once per dispatcher cycle. Always returns False for crypto
        and when Finnhub isn't configured.
        """
        ent = self._get_earnings(symbol)
        if not ent:
            return False
        du = ent.get("days_until")
        if du is None:
            return False
        return 0 <= du <= days

    def days_until_earnings(self, symbol: str) -> Optional[int]:
        ent = self._get_earnings(symbol)
        if not ent:
            return None
        du = ent.get("days_until")
        return du if isinstance(du, int) else None

    def insider_tone(self, symbol: str) -> str:
        """Returns 'bullish' / 'bearish' / 'neutral' or '' when unavailable."""
        snap = self._get_insider(symbol)
        return snap.get("tone", "") if snap else ""

    def insider_net_value(self, symbol: str) -> float:
        snap = self._get_insider(symbol)
        return float(snap.get("net_value_usd", 0.0)) if snap else 0.0

    # ── Internal lookup helpers ──

    def _get_earnings(self, symbol: str) -> Dict[str, Any]:
        cached = self._earnings_cache.get(symbol.upper())
        if cached is not None:
            return cached
        try:
            from signals import finnhub
            if not finnhub.is_configured():
                self._earnings_cache[symbol.upper()] = {}
                return {}
            entry = finnhub.earnings_for_symbol(symbol)
            if entry is None:
                self._earnings_cache[symbol.upper()] = {}
                return {}
            from dataclasses import asdict
            d = asdict(entry)
            try:
                from datetime import datetime, timezone
                edate = datetime.strptime(d["date"], "%Y-%m-%d").date()
                today = datetime.now(timezone.utc).date()
                d["days_until"] = max(0, (edate - today).days)
            except (ValueError, TypeError):
                d["days_until"] = None
            self._earnings_cache[symbol.upper()] = d
            return d
        except Exception as exc:
            logger.debug(f"earnings lookup failed for {symbol}: {exc}")
            self._earnings_cache[symbol.upper()] = {}
            return {}

    def _get_insider(self, symbol: str) -> Dict[str, Any]:
        cached = self._insider_cache.get(symbol.upper())
        if cached is not None:
            return cached
        try:
            from signals import finnhub
            if not finnhub.is_configured():
                self._insider_cache[symbol.upper()] = {}
                return {}
            snap = finnhub.insider_summary(symbol) or {}
            self._insider_cache[symbol.upper()] = snap
            return snap
        except Exception as exc:
            logger.debug(f"insider lookup failed for {symbol}: {exc}")
            self._insider_cache[symbol.upper()] = {}
            return {}


def build_signal_context() -> SignalContext:
    """Build a fresh SignalContext per tick cycle.

    Macro + Fear & Greed are pulled once here; per-symbol Finnhub data is
    populated lazily by the strategy queries on demand.
    """
    ctx = SignalContext()

    # F&G — no key required
    try:
        from signals.fear_greed import fetch_fear_greed
        fg = fetch_fear_greed()
        if fg is not None:
            ctx.fear_greed_value = int(fg.value)
            ctx.fear_greed_label = fg.label
            ctx.fear_greed_is_extreme_fear = fg.is_extreme_fear
            ctx.fear_greed_is_extreme_greed = fg.is_extreme_greed
    except Exception as exc:
        logger.debug(f"F&G fetch in context failed: {exc}")

    # FRED macro — only if key set
    try:
        from signals import fred
        if fred.is_configured():
            snap = fred.fetch_macro_snapshot()
            if snap is not None:
                series = snap.series
                if "VIXCLS" in series:
                    ctx.vix = series["VIXCLS"].value
                if "DFF" in series:
                    ctx.fed_funds = series["DFF"].value
                if "DGS10" in series:
                    ctx.treasury_10y = series["DGS10"].value
                if "DGS2" in series:
                    ctx.treasury_2y = series["DGS2"].value
                if "T10Y2Y" in series:
                    ctx.yield_curve_spread = series["T10Y2Y"].value
                if "CPIAUCSL" in series:
                    ctx.cpi = series["CPIAUCSL"].value
                if "PPIFIS" in series:
                    ctx.ppi_final = series["PPIFIS"].value
                if "PCEPILFE" in series:
                    ctx.core_pce = series["PCEPILFE"].value
                if "UNRATE" in series:
                    ctx.unemployment = series["UNRATE"].value
                if "BAA10Y" in series:
                    ctx.baa_10y_spread = series["BAA10Y"].value
                if "BAMLH0A0HYM2" in series:
                    ctx.hy_oas = series["BAMLH0A0HYM2"].value
    except Exception as exc:
        logger.debug(f"FRED fetch in context failed: {exc}")

    return ctx
