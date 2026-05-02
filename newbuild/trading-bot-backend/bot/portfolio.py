"""Portfolio and position management."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bot.config import PositionSide


@dataclass
class Position:
    """Represents an open trading position."""
    symbol: str
    side: PositionSide
    size: float  # absolute quantity
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None
    status: str = "open"

    @property
    def market_value(self) -> float:
        """Calculate the market value of the position."""
        return self.size * self.current_price

    @property
    def cost_basis(self) -> float:
        """Calculate the cost basis of the position."""
        return self.size * self.entry_price

    def update_price(self, price: float) -> None:
        """Update the current price and recalculate unrealized P&L."""
        self.current_price = price
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (price - self.entry_price) * self.size
        else:
            self.unrealized_pnl = (self.entry_price - price) * self.size

    def close(self, price: float) -> float:
        """Close the position at the given price.

        Args:
            price: The exit price.

        Returns:
            Realized P&L.
        """
        self.update_price(price)
        self.realized_pnl = self.unrealized_pnl
        self.unrealized_pnl = 0.0
        self.closed_at = datetime.now(timezone.utc)
        self.status = "closed"
        return self.realized_pnl

    def to_dict(self) -> Dict[str, Any]:
        """Convert position to dictionary."""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "size": self.size,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "market_value": self.market_value,
            "opened_at": self.opened_at.isoformat(),
            "status": self.status,
        }


@dataclass
class PortfolioSnapshot:
    """Snapshot of portfolio state at a point in time."""
    account_id: str
    timestamp: datetime
    balances: Dict[str, float]
    positions: List[Position]
    total_equity: float
    unrealized_pnl: float
    realized_pnl: float


class Portfolio:
    """Virtual portfolio for a single account."""

    def __init__(self, account_id: str, initial_balance: Dict[str, float]) -> None:
        """Initialize a portfolio.

        Args:
            account_id: Unique identifier for the account.
            initial_balance: Mapping of asset to amount, e.g., {"USDT": 10000.0}.
        """
        self.account_id = account_id
        self._balances: Dict[str, float] = dict(initial_balance)
        self._positions: Dict[str, Position] = {}
        self._realized_pnl: float = 0.0
        self._trade_history: List[Dict[str, Any]] = []

    # ── Balance ──

    def deposit(self, asset: str, amount: float) -> None:
        """Deposit funds into the portfolio."""
        self._balances[asset] = self._balances.get(asset, 0.0) + amount

    def withdraw(self, asset: str, amount: float) -> bool:
        """Withdraw funds from the portfolio.

        Returns:
            True if withdrawal was successful, False if insufficient balance.
        """
        if self._balances.get(asset, 0.0) < amount:
            return False
        self._balances[asset] -= amount
        return True

    def get_balance(self, asset: str) -> float:
        """Get the balance of a specific asset."""
        return self._balances.get(asset, 0.0)

    def get_all_balances(self) -> Dict[str, float]:
        """Get all asset balances."""
        return dict(self._balances)

    def get_total_equity(self, prices: Dict[str, float]) -> float:
        """Calculate total equity across all balances and positions.

        Args:
            prices: Mapping of symbol to current price for valuation.

        Returns:
            Total equity in the portfolio's base currency.
        """
        equity = 0.0
        for asset, amount in self._balances.items():
            price = prices.get(asset, 1.0) if asset != "USDT" else 1.0
            equity += amount * price
        for pos in self._positions.values():
            equity += pos.unrealized_pnl
        return equity

    # ── Positions ──

    def open_position(
        self, symbol: str, side: PositionSide, size: float, price: float
    ) -> Position:
        """Open a new position.

        Args:
            symbol: Trading symbol.
            side: Long or short.
            size: Position size (absolute quantity).
            price: Entry price.

        Returns:
            The newly created Position.
        """
        position = Position(
            symbol=symbol,
            side=side,
            size=size,
            entry_price=price,
            current_price=price,
        )
        self._positions[symbol] = position
        return position

    def close_position(self, symbol: str, price: float) -> tuple[Position, float]:
        """Close a position at the given price.

        Args:
            symbol: The symbol of the position to close.
            price: The exit price.

        Returns:
            Tuple of (closed_position, realized_pnl).

        Raises:
            KeyError: If the symbol has no open position.
        """
        if symbol not in self._positions:
            raise KeyError(f"No open position for {symbol}")
        position = self._positions[symbol]
        realized_pnl = position.close(price)
        self._realized_pnl += realized_pnl
        del self._positions[symbol]
        return position, realized_pnl

    def update_position_price(self, symbol: str, current_price: float) -> None:
        """Update the current price of a position."""
        if symbol in self._positions:
            self._positions[symbol].update_price(current_price)

    def get_position(self, symbol: str) -> Position | None:
        """Get an open position by symbol."""
        return self._positions.get(symbol)

    def get_all_positions(self) -> List[Position]:
        """Get all open positions."""
        return list(self._positions.values())

    def get_open_position_symbols(self) -> List[str]:
        """Get symbols of all open positions."""
        return list(self._positions.keys())

    def get_exposure(self, asset: str) -> float:
        """Get total exposure to an asset.

        Returns:
            Total size of positions in the asset.
        """
        total = 0.0
        for pos in self._positions.values():
            if pos.symbol == asset or pos.symbol.startswith(asset):
                total += pos.size
        return total

    @property
    def total_unrealized_pnl(self) -> float:
        """Sum of all open position unrealized P&L."""
        return sum(p.unrealized_pnl for p in self._positions.values())

    @property
    def total_realized_pnl(self) -> float:
        """Total realized P&L across all closed trades."""
        return self._realized_pnl

    # ── Snapshots ──

    def snapshot(self, timestamp: datetime | None = None) -> PortfolioSnapshot:
        """Create a portfolio snapshot.

        Args:
            timestamp: Optional timestamp (defaults to now).

        Returns:
            PortfolioSnapshot dataclass.
        """
        ts = timestamp or datetime.now(timezone.utc)
        return PortfolioSnapshot(
            account_id=self.account_id,
            timestamp=ts,
            balances=self.get_all_balances(),
            positions=self.get_all_positions(),
            total_equity=0.0,  # Requires external prices
            unrealized_pnl=self.total_unrealized_pnl,
            realized_pnl=self.total_realized_pnl,
        )

    # ── Trade History ──

    def record_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float,
        realized_pnl: float | None = None,
    ) -> None:
        """Record a completed trade."""
        self._trade_history.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "fee": fee,
                "realized_pnl": realized_pnl,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def get_trade_history(self) -> List[Dict[str, Any]]:
        """Get all recorded trades."""
        return list(self._trade_history)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize portfolio to dictionary."""
        return {
            "account_id": self.account_id,
            "balances": self._balances,
            "positions": [p.to_dict() for p in self.get_all_positions()],
            "unrealized_pnl": self.total_unrealized_pnl,
            "realized_pnl": self.total_realized_pnl,
        }
