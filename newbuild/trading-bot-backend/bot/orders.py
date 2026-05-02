"""Order types, fill results, and execution simulation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

import numpy as np

from bot.config import OrderSide, OrderType


class OrderStatus(Enum):
    """Order lifecycle status."""
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Represents a trading order."""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "GTC"  # GTC, IOC, FOK
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    strategy_id: str | None = None
    account_id: str = "default"
    status: OrderStatus = field(default=OrderStatus.PENDING)
    filled_quantity: float = 0.0
    avg_fill_price: float | None = None
    fee: float = 0.0

    @property
    def is_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.status == OrderStatus.FILLED or (
            self.filled_quantity > 0 and self.filled_quantity >= self.quantity
        )

    @property
    def remaining_quantity(self) -> float:
        """Return unfilled quantity."""
        return max(0.0, self.quantity - self.filled_quantity)

    @classmethod
    def market(
        cls,
        symbol: str,
        side: OrderSide,
        quantity: float,
        account_id: str = "default",
        strategy_id: str | None = None,
    ) -> "Order":
        """Create a market order."""
        return cls(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            account_id=account_id,
            strategy_id=strategy_id,
        )

    @classmethod
    def limit(
        cls,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        account_id: str = "default",
        strategy_id: str | None = None,
    ) -> "Order":
        """Create a limit order."""
        return cls(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=price,
            account_id=account_id,
            strategy_id=strategy_id,
        )

    @classmethod
    def stop(
        cls,
        symbol: str,
        side: OrderSide,
        quantity: float,
        stop_price: float,
        account_id: str = "default",
        strategy_id: str | None = None,
    ) -> "Order":
        """Create a stop order."""
        return cls(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP_LOSS,
            quantity=quantity,
            stop_price=stop_price,
            account_id=account_id,
            strategy_id=strategy_id,
        )

    @classmethod
    def stop_limit(
        cls,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        stop_price: float,
        account_id: str = "default",
        strategy_id: str | None = None,
    ) -> "Order":
        """Create a stop-limit order."""
        return cls(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP_LIMIT,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            account_id=account_id,
            strategy_id=strategy_id,
        )


@dataclass
class FillResult:
    """Result of an order fill."""
    order_id: str
    symbol: str
    filled_qty: float
    filled_price: float
    fee: float
    slippage: float
    timestamp: datetime
    side: OrderSide
    realized_pnl: float | None = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert fill result to dictionary."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "filled_qty": self.filled_qty,
            "filled_price": self.filled_price,
            "fee": self.fee,
            "slippage": self.slippage,
            "timestamp": self.timestamp.isoformat(),
            "side": self.side.value,
            "realized_pnl": self.realized_pnl,
        }


class ExecutionSimulator:
    """Simulates realistic order execution with slippage and fees."""

    def __init__(
        self,
        fee_rate: float = 0.001,
        slippage_model: str = "fixed",
        slippage_bps: float = 5.0,
    ) -> None:
        """Initialize execution simulator.

        Args:
            fee_rate: Trading fee as decimal (e.g., 0.001 = 0.1%).
            slippage_model: Model type - "fixed", "proportional", or "volatility".
            slippage_bps: Slippage in basis points.
        """
        self.fee_rate = fee_rate
        self.slippage_model = slippage_model
        self.slippage_bps = slippage_bps

    def apply_slippage(
        self,
        price: float,
        side: OrderSide,
        volatility: float | None = None,
    ) -> float:
        """Apply slippage to a price.

        Args:
            price: The base market price.
            side: Order side (buy = worse price, sell = worse price).
            volatility: Optional volatility for volatility-based slippage.

        Returns:
            Price after slippage is applied.
        """
        if self.slippage_model == "fixed":
            slippage_pct = self.slippage_bps / 10000.0
        elif self.slippage_model == "proportional":
            slippage_pct = self.slippage_bps / 10000.0 * np.random.uniform(0.5, 1.5)
        elif self.slippage_model == "volatility" and volatility is not None:
            slippage_pct = self.slippage_bps / 10000.0 * volatility * 100
        else:
            slippage_pct = self.slippage_bps / 10000.0

        # Slippage is adverse: buy higher, sell lower
        if side == OrderSide.BUY:
            return price * (1.0 + slippage_pct)
        return price * (1.0 - slippage_pct)

    def calculate_fee(self, notional: float) -> float:
        """Calculate trading fee.

        Args:
            notional: Total trade notional value.

        Returns:
            Fee amount.
        """
        return notional * self.fee_rate

    def execute(
        self,
        order: Order,
        current_price: float,
        market_depth: Dict[str, Any] | None = None,
    ) -> FillResult | None:
        """Execute an order at current market conditions.

        Args:
            order: The order to execute.
            current_price: Current market price.
            market_depth: Optional market depth data.

        Returns:
            FillResult if order is filled, None if it cannot be filled.
        """
        now = datetime.now(timezone.utc)
        filled_price = current_price

        if order.order_type == OrderType.MARKET:
            filled_price = self.apply_slippage(current_price, order.side)
            filled_qty = order.quantity
        elif order.order_type == OrderType.LIMIT and order.price is not None:
            # Limit buy: fill when price <= limit
            # Limit sell: fill when price >= limit
            if order.side == OrderSide.BUY and current_price <= order.price:
                filled_price = self.apply_slippage(min(current_price, order.price), order.side)
                filled_qty = order.quantity
            elif order.side == OrderSide.SELL and current_price >= order.price:
                filled_price = self.apply_slippage(max(current_price, order.price), order.side)
                filled_qty = order.quantity
            else:
                return None
        elif order.order_type == OrderType.STOP_LOSS and order.stop_price is not None:
            # Stop buy: fill when price >= stop
            # Stop sell: fill when price <= stop
            if order.side == OrderSide.BUY and current_price >= order.stop_price:
                filled_price = self.apply_slippage(current_price, order.side)
                filled_qty = order.quantity
            elif order.side == OrderSide.SELL and current_price <= order.stop_price:
                filled_price = self.apply_slippage(current_price, order.side)
                filled_qty = order.quantity
            else:
                return None
        elif order.order_type == OrderType.STOP_LIMIT and order.stop_price is not None and order.price is not None:
            # Stop-limit: trigger on stop, then limit execution
            if order.side == OrderSide.BUY and current_price >= order.stop_price and current_price <= order.price:
                filled_price = self.apply_slippage(min(current_price, order.price), order.side)
                filled_qty = order.quantity
            elif order.side == OrderSide.SELL and current_price <= order.stop_price and current_price >= order.price:
                filled_price = self.apply_slippage(max(current_price, order.price), order.side)
                filled_qty = order.quantity
            else:
                return None
        elif order.order_type == OrderType.TAKE_PROFIT and order.stop_price is not None:
            # Take profit buy: fill when price <= trigger
            # Take profit sell: fill when price >= trigger
            if order.side == OrderSide.BUY and current_price <= order.stop_price:
                filled_price = self.apply_slippage(current_price, order.side)
                filled_qty = order.quantity
            elif order.side == OrderSide.SELL and current_price >= order.stop_price:
                filled_price = self.apply_slippage(current_price, order.side)
                filled_qty = order.quantity
            else:
                return None
        else:
            return None

        notional = filled_qty * filled_price
        fee = self.calculate_fee(notional)
        slippage = filled_price - current_price if order.side == OrderSide.BUY else current_price - filled_price

        return FillResult(
            order_id=order.id,
            symbol=order.symbol,
            filled_qty=filled_qty,
            filled_price=filled_price,
            fee=fee,
            slippage=abs(slippage),
            timestamp=now,
            side=order.side,
            realized_pnl=None,
        )
