"""Pairlist filters — quality gates between universe-build and strategy evaluation.

Modeled on freqtrade's pairlist chain. Each filter takes a symbol + its OHLCV
dataframe and returns a ``FilterVerdict`` (pass/fail + reason). The chain runs
in declared order; first fail short-circuits.

Why this layer exists: the scanner used to just score every symbol in the
universe. That meant illiquid micro-caps, listed-yesterday tickers, and
brand-new crypto launches all competed on the same composite score with
mega-caps. The filters drop those before scoring, so the leaderboard reflects
tradeable assets only.

Filters provided here, all freqtrade-equivalent:

* ``VolumeFilter`` — minimum 24h dollar-volume floor (skip illiquid)
* ``AgeFilter``    — minimum bars of history (skip just-listed)
* ``PriceFilter``  — price floor + ceiling (drop penny stocks, drop $5000+)
* ``SpreadFilter`` — max (high-low)/close as bid-ask proxy (skip thin books)
* ``VolatilityFilter`` — min/max ATR% (drop dead-flat *and* unstable rockets)
* ``BlacklistFilter`` — explicit symbol exclusion (operator-controlled)

Compose via ``apply_chain()`` — returns ``(passing_symbols, rejections)``
where rejections is ``{symbol: reason}`` so the scanner UI can show *why*
something was dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


@dataclass(frozen=True)
class FilterVerdict:
    """Single filter's verdict for one symbol."""

    passed: bool
    reason: str = ""  # empty when passed=True


# ─── Individual filters ───────────────────────────────────────────────────


@dataclass
class VolumeFilter:
    """Minimum 24h dollar-volume. Uses the most recent N bars × their close.

    For daily bars, ``bars=1`` is yesterday's notional. For 1h bars, ``bars=24``
    is the last day. The scanner uses daily bars so default is 1.
    """

    min_quote_volume_usd: float = 1_000_000.0
    bars: int = 1

    def check(self, symbol: str, df: pd.DataFrame) -> FilterVerdict:
        if df is None or df.empty or "volume" not in df.columns or "close" not in df.columns:
            return FilterVerdict(False, "no_volume_data")
        recent = df.tail(self.bars)
        notional = float((recent["close"] * recent["volume"]).sum())
        if notional < self.min_quote_volume_usd:
            return FilterVerdict(
                False,
                f"volume ${notional:,.0f} < ${self.min_quote_volume_usd:,.0f}",
            )
        return FilterVerdict(True)


@dataclass
class AgeFilter:
    """Require minimum bars of trading history.

    Strategies that look at MAs, RSI, ATR etc. need a runway. The scanner's
    composite score uses up to 50 bars of context; anything shorter is noise.
    """

    min_bars: int = 30

    def check(self, symbol: str, df: pd.DataFrame) -> FilterVerdict:
        n = 0 if df is None else len(df)
        if n < self.min_bars:
            return FilterVerdict(False, f"only {n} bars (need {self.min_bars})")
        return FilterVerdict(True)


@dataclass
class PriceFilter:
    """Current-price floor and ceiling.

    Default floor catches penny stocks (sub-$1) where spreads dominate edge.
    No default ceiling — set ``max_price`` if you don't want $5000 names
    inflating per-share notional.
    """

    min_price: float = 1.0
    max_price: Optional[float] = None

    def check(self, symbol: str, df: pd.DataFrame) -> FilterVerdict:
        if df is None or df.empty or "close" not in df.columns:
            return FilterVerdict(False, "no_close_data")
        price = float(df["close"].iloc[-1])
        if price < self.min_price:
            return FilterVerdict(False, f"price ${price:.4f} < ${self.min_price}")
        if self.max_price is not None and price > self.max_price:
            return FilterVerdict(False, f"price ${price:.2f} > ${self.max_price}")
        return FilterVerdict(True)


@dataclass
class SpreadFilter:
    """Max average (high-low)/close as a bid-ask spread proxy.

    True bid-ask isn't in OHLCV, but daily H-L range is highly correlated with
    typical spreads for less-liquid names. Wide range over recent days = bad
    fills coming. Default 8% drops the worst micro-caps without trimming
    high-volatility but tight-spread names like SOL or NVDA.
    """

    max_avg_range_pct: float = 0.08
    bars: int = 10

    def check(self, symbol: str, df: pd.DataFrame) -> FilterVerdict:
        required = {"high", "low", "close"}
        if df is None or df.empty or not required.issubset(df.columns):
            return FilterVerdict(False, "no_hlc_data")
        recent = df.tail(self.bars)
        ranges = (recent["high"] - recent["low"]) / recent["close"].replace(0, float("nan"))
        avg = float(ranges.mean())
        if pd.isna(avg) or avg > self.max_avg_range_pct:
            return FilterVerdict(False, f"range {avg:.1%} > {self.max_avg_range_pct:.1%}")
        return FilterVerdict(True)


@dataclass
class VolatilityFilter:
    """Min/max ATR% over a lookback window.

    Drops two extremes: dead-flat names (ATR < min — no edge to capture) and
    pumping-rocket names (ATR > max — likely already exhausted the move).
    """

    min_atr_pct: float = 0.005   # 0.5% per bar — anything lower has no edge
    max_atr_pct: float = 0.15    # 15% per bar — past this is a pump, not a trend
    bars: int = 14

    def check(self, symbol: str, df: pd.DataFrame) -> FilterVerdict:
        required = {"high", "low", "close"}
        if df is None or df.empty or not required.issubset(df.columns):
            return FilterVerdict(False, "no_hlc_data")
        if len(df) < self.bars + 1:
            return FilterVerdict(False, f"not enough bars for ATR{self.bars}")

        recent = df.tail(self.bars + 1).copy()
        prev_close = recent["close"].shift(1)
        tr = pd.concat(
            [
                (recent["high"] - recent["low"]).abs(),
                (recent["high"] - prev_close).abs(),
                (recent["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = float(tr.tail(self.bars).mean())
        last_close = float(recent["close"].iloc[-1])
        if last_close <= 0:
            return FilterVerdict(False, "zero_close")
        atr_pct = atr / last_close

        if atr_pct < self.min_atr_pct:
            return FilterVerdict(False, f"ATR {atr_pct:.2%} < {self.min_atr_pct:.2%} (flat)")
        if atr_pct > self.max_atr_pct:
            return FilterVerdict(False, f"ATR {atr_pct:.2%} > {self.max_atr_pct:.2%} (rocket)")
        return FilterVerdict(True)


@dataclass
class BlacklistFilter:
    """Explicit symbol exclusion. Case-insensitive, suffix-aware.

    Matches base form too — ``ADA`` in blacklist excludes ``ADAUSD``,
    ``ADA/USD``, and ``ADA-USD``. Use this for non-tradeable broker assets
    (e.g. Alpaca paper doesn't support ADA — drop it permanently from scoring).
    """

    symbols: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self._blocked = {s.upper().strip() for s in self.symbols if s.strip()}

    def check(self, symbol: str, df: pd.DataFrame) -> FilterVerdict:
        s = symbol.upper().strip()
        candidates = {s, s.replace("/USD", ""), s.replace("USD", ""), s.replace("-USD", "")}
        if candidates & self._blocked:
            return FilterVerdict(False, "blacklisted")
        return FilterVerdict(True)


# ─── Chain runner ─────────────────────────────────────────────────────────


def apply_chain(
    candidates: Iterable[Tuple[str, pd.DataFrame]],
    filters: Sequence[object],
) -> Tuple[List[str], Dict[str, str]]:
    """Run each candidate through every filter in order.

    Returns:
        passing  — symbols that cleared every filter, original order preserved
        rejected — {symbol: first_failing_reason}

    Filters are duck-typed: any object with a ``check(symbol, df) -> FilterVerdict``
    method is accepted. Order matters — cheap filters (price, blacklist) should
    come before expensive ones (volatility/ATR over a window).
    """
    passing: List[str] = []
    rejected: Dict[str, str] = {}
    for symbol, df in candidates:
        verdict_reason: Optional[str] = None
        for f in filters:
            v: FilterVerdict = f.check(symbol, df)
            if not v.passed:
                verdict_reason = f"{type(f).__name__}: {v.reason}"
                break
        if verdict_reason is None:
            passing.append(symbol)
        else:
            rejected[symbol] = verdict_reason
    return passing, rejected


def default_chain(
    *,
    blacklist: Sequence[str] = (),
    min_quote_volume_usd: float = 1_000_000.0,
    min_price: float = 1.0,
    max_price: Optional[float] = None,
    min_bars: int = 30,
    max_spread_pct: float = 0.08,
    min_atr_pct: float = 0.005,
    max_atr_pct: float = 0.15,
) -> List[object]:
    """Sensible default chain. Ordered cheap-first for short-circuit efficiency."""
    return [
        BlacklistFilter(symbols=blacklist),
        AgeFilter(min_bars=min_bars),
        PriceFilter(min_price=min_price, max_price=max_price),
        VolumeFilter(min_quote_volume_usd=min_quote_volume_usd),
        SpreadFilter(max_avg_range_pct=max_spread_pct),
        VolatilityFilter(min_atr_pct=min_atr_pct, max_atr_pct=max_atr_pct),
    ]
