"""Daily P&L tracker with automatic midnight reset.

Records each fill, computes running daily P&L, and auto-resets at midnight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from bot.orders import FillResult


@dataclass
class TradeRecord:
    fill: FillResult
    pnl: float
    timestamp: datetime


class DailyPnlTracker:
    """Tracks realized P&L per trading day.

    - Auto-resets at midnight (UTC).
    - Computes P&L per fill using simple cost-basis model.
    - Maintains a list of today's trades for inspection.
    """

    def __init__(
        self,
        position_provider: Optional[Callable[[], Dict[str, Tuple[float, float]]]] = None,
    ) -> None:
        self.daily_pnl: float = 0.0
        self.trades_today: List[TradeRecord] = []
        self._reset_date: date = datetime.now(timezone.utc).date()
        self._cost_basis: dict = {}  # symbol -> avg entry price (today only)
        # Net qty per symbol for the day. Used to weight cost-basis updates
        # correctly when buys and sells interleave (buy 100 / sell 50 / buy 50
        # must not weight the second buy against 100, only against 50).
        self._net_qty: dict = {}
        # Optional callable returning {symbol: (entry_price, qty)} for currently
        # open positions. Lets a SELL of a position we haven't seen TODAY
        # (held overnight, or opened before a restart) realize correct daily
        # P&L from the real entry price instead of falling back to fill_price
        # (=> 0 P&L), which left the daily-loss breaker blind to those losers
        # (audit 2026-06-09).
        self._position_provider = position_provider

    def record(self, fill: FillResult) -> float:
        """Record a fill and compute its contribution to daily P&L.

        Args:
            fill: FillResult from a broker or simulator.

        Returns:
            The P&L attributed to this fill.
        """
        self._check_reset()
        pnl = self._calculate_pnl(fill)
        self.daily_pnl += pnl
        self.trades_today.append(
            TradeRecord(fill=fill, pnl=pnl, timestamp=datetime.now(timezone.utc))
        )
        return pnl

    def _calculate_pnl(self, fill: FillResult) -> float:
        """Compute P&L for a single fill.

        For sell fills:
            P&L = (fill_price - cost_basis) * qty - fee
        For buy fills:
            Update cost basis (no P&L realized yet).
        """
        from bot.config import OrderSide

        symbol = fill.symbol
        if fill.side == OrderSide.SELL:
            # PnL on the closed portion only. If no basis yet today, try the
            # position provider (overnight / pre-restart hold) before falling
            # back to fill_price (=> 0 PnL) — otherwise the daily-loss breaker
            # is blind to losses on positions not opened today.
            basis = self._cost_basis.get(symbol)
            if basis is None:
                basis = self._seed_basis(symbol)
            if basis is None:
                basis = fill.filled_price
            pnl = (fill.filled_price - basis) * fill.filled_qty - fill.fee
            new_qty = self._net_qty.get(symbol, 0.0) - fill.filled_qty
            if new_qty <= 1e-12:
                # Position fully closed today — drop basis so a re-entry
                # later in the day starts fresh instead of inheriting stale.
                self._cost_basis.pop(symbol, None)
                self._net_qty.pop(symbol, None)
            else:
                self._net_qty[symbol] = new_qty
            return pnl
        else:
            # Buy — update running cost basis weighted by current net qty
            # (not naive sum of today's BUYs, which double-counts when a
            # SELL has already reduced the position).
            old_basis = self._cost_basis.get(symbol, 0.0)
            old_qty = max(0.0, self._net_qty.get(symbol, 0.0))
            total_qty = old_qty + fill.filled_qty
            if total_qty > 0:
                new_basis = (old_basis * old_qty + fill.filled_price * fill.filled_qty) / total_qty
                self._cost_basis[symbol] = new_basis
                self._net_qty[symbol] = total_qty
            return 0.0  # No realized P&L on buys

    def _seed_basis(self, symbol: str) -> Optional[float]:
        """Entry price of an open position not yet tracked today, via the
        position provider. Returns None if no provider or no match — caller
        then falls back to fill_price. Symbol match is normalized so 'BTC',
        'BTCUSD' and 'BTC/USD' all reconcile.
        """
        if self._position_provider is None:
            return None
        try:
            positions = self._position_provider() or {}
        except Exception:
            return None
        norm = str(symbol).upper().replace("/", "").replace("-", "")
        for sym, val in positions.items():
            psym = str(sym).upper().replace("/", "").replace("-", "")
            if psym != norm and not psym.startswith(norm) and not norm.startswith(psym):
                continue
            try:
                entry_price = float(val[0])
            except (TypeError, ValueError, IndexError):
                continue
            if entry_price > 0:
                return entry_price
        return None

    def _check_reset(self) -> None:
        """Reset state if we've crossed into a new day."""
        today = datetime.now(timezone.utc).date()
        if today != self._reset_date:
            self.daily_pnl = 0.0
            self.trades_today.clear()
            self._cost_basis.clear()
            self._net_qty.clear()
            self._reset_date = today

    def get_status(self) -> dict:
        """Return current tracker status."""
        self._check_reset()
        return {
            "daily_pnl": round(self.daily_pnl, 4),
            "trade_count": len(self.trades_today),
            "date": self._reset_date.isoformat(),
        }
