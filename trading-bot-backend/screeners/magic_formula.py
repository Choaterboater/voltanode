"""Greenblatt Magic Formula screener.

Ranks a stock universe by two metrics:

  Earnings Yield    = EBIT / Enterprise Value
  Return on Capital = EBIT / (Net Working Capital + Net Fixed Assets)
                      ≈ ROIC, approximated by yfinance's returnOnAssets when
                        balance-sheet line items aren't directly exposed

Each stock gets a rank (1..N) on both axes. Combined rank = ey_rank +
roc_rank. Lowest combined rank wins → top picks are companies that are
*cheap* (high earnings yield) AND *good* (high return on capital).

This is the canonical "good companies at fair prices" screen popularised
in Joel Greenblatt's *The Little Book That Beats the Market*. It's not a
trade signal — it's a research starting point.

Free data: pulls from yfinance.Ticker.info, no API key needed.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("volta.screeners.magic_formula")


# A reasonable starter universe — top US large-caps. Users can pass a
# different list to .run() if they want, or we'll expand this later.
DEFAULT_UNIVERSE: List[str] = [
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # Large-cap tech / industrials
    "AMD", "AVGO", "INTC", "ORCL", "CRM", "ADBE", "CSCO", "IBM",
    "AMAT", "ASML", "LRCX", "KLAC", "QCOM", "TXN", "MU",
    # Financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP", "V", "MA",
    # Healthcare / pharma
    "UNH", "JNJ", "PFE", "LLY", "ABBV", "MRK", "TMO", "ABT", "DHR",
    "BMY", "AMGN", "GILD",
    # Consumer
    "WMT", "TGT", "COST", "HD", "LOW", "MCD", "SBUX", "NKE", "DIS",
    "KO", "PEP", "PG", "PM",
    # Energy
    "XOM", "CVX", "COP", "OXY", "SLB", "EOG",
    # Industrials
    "BA", "CAT", "GE", "HON", "UPS", "RTX", "LMT", "DE",
    # ETFs / index proxies (excluded from screen — non-stock)
]


@dataclass
class ScreenerPick:
    symbol: str
    name: str
    sector: str
    market_cap: Optional[float]
    price: Optional[float]
    earnings_yield: Optional[float]   # EBIT / EV (or proxy)
    return_on_capital: Optional[float]  # ROIC proxy
    pe: Optional[float]
    revenue_growth: Optional[float]
    profit_margin: Optional[float]
    earnings_yield_rank: Optional[int]
    roc_rank: Optional[int]
    combined_rank: Optional[int]
    score: Optional[float]  # 0-100, higher = better

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MagicFormulaScreener:
    """Joel Greenblatt's Magic Formula on the configured universe."""

    name = "Greenblatt Magic Formula"

    def __init__(self, universe: Optional[List[str]] = None) -> None:
        self.universe = universe or DEFAULT_UNIVERSE

    def run(self, top_n: int = 30, min_market_cap: float = 1e9) -> List[ScreenerPick]:
        """Score the universe and return top_n picks ranked by combined rank.

        ``min_market_cap`` filters out micro-caps where the formula behaves
        erratically (default $1B).
        """
        rows = self._fetch_metrics_parallel(self.universe)

        # Filter: need both metrics + market cap above floor
        eligible = [
            r for r in rows
            if r["earnings_yield"] is not None
            and r["return_on_capital"] is not None
            and r["market_cap"] is not None
            and r["market_cap"] >= min_market_cap
        ]
        if not eligible:
            return []

        # Higher EY + higher ROC = better. Rank descending.
        ey_sorted = sorted(eligible, key=lambda r: r["earnings_yield"], reverse=True)
        roc_sorted = sorted(eligible, key=lambda r: r["return_on_capital"], reverse=True)
        ey_rank = {r["symbol"]: i + 1 for i, r in enumerate(ey_sorted)}
        roc_rank = {r["symbol"]: i + 1 for i, r in enumerate(roc_sorted)}

        picks: List[ScreenerPick] = []
        n = len(eligible)
        for r in eligible:
            sym = r["symbol"]
            ey = ey_rank[sym]
            roc = roc_rank[sym]
            combined = ey + roc
            # Score 0-100: lower combined rank → higher score.
            # Best possible combined = 2 (rank 1 on both); worst = 2*n.
            score = round(100 * (1 - (combined - 2) / max(1, 2 * n - 2)), 1)
            picks.append(ScreenerPick(
                symbol=sym,
                name=r["name"],
                sector=r["sector"],
                market_cap=r["market_cap"],
                price=r["price"],
                earnings_yield=round(r["earnings_yield"], 4),
                return_on_capital=round(r["return_on_capital"], 4),
                pe=r["pe"],
                revenue_growth=r["revenue_growth"],
                profit_margin=r["profit_margin"],
                earnings_yield_rank=ey,
                roc_rank=roc,
                combined_rank=combined,
                score=score,
            ))

        picks.sort(key=lambda p: p.combined_rank or 1e9)
        return picks[:top_n]

    # ── Metric extraction ──

    def _fetch_metrics_parallel(self, symbols: List[str], max_workers: int = 8) -> List[Dict[str, Any]]:
        """Hit yfinance.info in a thread pool — ~5x speedup vs sequential."""
        out: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {pool.submit(self._fetch_one, sym): sym for sym in symbols}
            for f in as_completed(futs):
                try:
                    row = f.result(timeout=15)
                    if row is not None:
                        out.append(row)
                except Exception as exc:
                    logger.debug(f"fetch failed for {futs[f]}: {exc}")
        return out

    def _fetch_one(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            import yfinance as yf
            info = yf.Ticker(symbol).info or {}
        except Exception:
            return None

        market_cap = _safe_float(info.get("marketCap"))
        ev = _safe_float(info.get("enterpriseValue"))
        ebitda = _safe_float(info.get("ebitda"))
        op_margin = _safe_float(info.get("operatingMargins"))
        revenue = _safe_float(info.get("totalRevenue"))
        roa = _safe_float(info.get("returnOnAssets"))

        # EBIT ≈ revenue * operatingMargins (yfinance doesn't always expose EBIT directly)
        ebit = revenue * op_margin if (revenue is not None and op_margin is not None) else None

        # Earnings Yield = EBIT / EV. Fall back to EBITDA/EV when EBIT missing.
        earnings_yield: Optional[float] = None
        if ev and ev > 0:
            if ebit is not None and ebit > 0:
                earnings_yield = ebit / ev
            elif ebitda is not None and ebitda > 0:
                earnings_yield = (ebitda * 0.85) / ev  # EBIT ≈ 0.85 × EBITDA rough heuristic

        # Return on Capital — true Greenblatt formula needs working capital +
        # net fixed assets, which yfinance doesn't surface cleanly. ROA is
        # the closest single-field proxy (capital used = total assets).
        return_on_capital = roa if roa is not None and roa > 0 else None

        return {
            "symbol": symbol.upper(),
            "name": info.get("longName") or info.get("shortName") or symbol.upper(),
            "sector": info.get("sector") or "",
            "market_cap": market_cap,
            "price": _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
            "earnings_yield": earnings_yield,
            "return_on_capital": return_on_capital,
            "pe": _safe_float(info.get("trailingPE")),
            "revenue_growth": _safe_float(info.get("revenueGrowth")),
            "profit_margin": _safe_float(info.get("profitMargins")),
        }


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        f = float(v)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None
