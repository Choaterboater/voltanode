"""Daily P&L tracker with automatic midnight reset.

Records each fill, computes running daily P&L, and auto-resets at midnight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List

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

    def __init__(self) -> None:
        self.daily_pnl: float = 0.0
        self.trades_today: List[TradeRecord] = []
        self._reset_date: date = datetime.now(timezone.utc).date()
        self._cost_basis: dict = {}  # symbol -> avg entry price

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
            basis = self._cost_basis.get(symbol, fill.filled_price)
            pnl = (fill.filled_price - basis) * fill.filled_qty - fill.fee
            # Reduce or clear cost basis
            if symbol in self._cost_basis:
                # Simple model: clear on first sell — tracks net position pnl
                pass
            return pnl
        else:
            # Buy — update running cost basis (weighted average)
            old_basis = self._cost_basis.get(symbol, 0.0)
            old_qty = sum(t.fill.filled_qty for t in self.trades_today if t.fill.symbol == symbol and t.fill.side == OrderSide.BUY)
            total_qty = old_qty + fill.filled_qty
            if total_qty > 0:
                new_basis = (old_basis * old_qty + fill.filled_price * fill.filled_qty) / total_qty
                self._cost_basis[symbol] = new_basis
            return 0.0  # No realized P&L on buys

    def _check_reset(self) -> None:
        """Reset state if we've crossed into a new day."""
        today = datetime.now(timezone.utc).date()
        if today != self._reset_date:
            self.daily_pnl = 0.0
            self.trades_today.clear()
            self._cost_basis.clear()
            self._reset_date = today

    def get_status(self) -> dict:
        """Return current tracker status."""
        self._check_reset()
        return {
            "daily_pnl": round(self.daily_pnl, 4),
            "trade_count": len(self.trades_today),
            "date": self._reset_date.isoformat(),
        }
