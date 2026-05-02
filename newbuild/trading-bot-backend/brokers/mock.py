"""Mock broker adapter for testing live mode without real API keys.

Simulates realistic fills with configurable delays, slippage, and price generation.
Useful for integration testing and UI development.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from bot.config import OrderSide, OrderType
from bot.orders import FillResult, Order

from brokers.base import BrokerAdapter, BrokerConnectionError


@dataclass
class MockPosition:
    symbol: str
    size: float
    entry_price: float
    side: str


class MockBroker(BrokerAdapter):
    """Mock broker that simulates a real exchange.

    - No API keys required.
    - Generates synthetic fills with realistic fees and slippage.
    - Adds configurable latency (50-200ms) per operation.
    - Simulates limit order fill logic (price must cross limit).
    - Tracks mock balance and positions internally.
    """

    name = "mock"

    def __init__(self, delay_ms: tuple = (50, 200)) -> None:
        """Initialize mock broker.

        Args:
            delay_ms: Min/max artificial latency in milliseconds.
        """
        self._delay_ms = delay_ms
        self._connected = False
        self._api_key = ""
        self._secret = ""

        # Simulated account state
        self._balances: Dict[str, float] = {"USDT": 10000.0, "USD": 10000.0}
        self._positions: Dict[str, MockPosition] = {}
        self._prices: Dict[str, float] = {
            "BTCUSDT": 65000.0,
            "ETHUSDT": 3500.0,
            "SOLUSDT": 150.0,
            "ADAUSDT": 0.45,
            "BTCUSD": 65000.0,
            "ETHUSD": 3500.0,
            "AAPL": 180.0,
            "TSLA": 240.0,
            "MSFT": 420.0,
            "GOOGL": 170.0,
        }
        self._order_counter = 0
        self._orders: Dict[str, dict] = {}  # broker_order_id -> order info

    def _latency(self) -> None:
        """Simulate network latency."""
        delay = random.randint(*self._delay_ms) / 1000.0
        time.sleep(delay)

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"MOCK-{self._order_counter:06d}"

    def _symbol_to_mock(self, symbol: str) -> str:
        """Normalize VoltaNode symbol to mock internal format."""
        # BTC-USD -> BTCUSDT or BTCUSD depending on broker type
        return symbol.replace("-", "").upper()

    def _get_mock_price(self, symbol: str) -> float:
        """Get current mock price, with small random wiggle."""
        key = self._symbol_to_mock(symbol)
        base = self._prices.get(key, 100.0)
        wiggle = random.uniform(-0.001, 0.001)
        return base * (1.0 + wiggle)

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """Apply 5 bps of slippage (adverse)."""
        slippage_pct = 5.0 / 10000.0
        if side == OrderSide.BUY:
            return price * (1.0 + slippage_pct)
        return price * (1.0 - slippage_pct)

    def connect(self, api_key: str, api_secret: str, **kwargs: Any) -> bool:
        self._latency()
        if not api_key or not api_secret:
            # Mock broker accepts empty keys for convenience, but warns
            pass
        self._api_key = api_key
        self._secret = api_secret
        self._connected = True
        return True

    def is_connected(self) -> bool:
        return self._connected

    def get_balance(self) -> Dict[str, float]:
        self._latency()
        return dict(self._balances)

    def get_price(self, symbol: str) -> float:
        self._latency()
        return self._get_mock_price(symbol)

    def place_order(self, order: Order) -> FillResult:
        if not self._connected:
            raise BrokerConnectionError("Mock broker not connected. Call connect() first.")
        self._latency()

        price = self._get_mock_price(order.symbol)
        filled_price = price
        filled_qty = 0.0

        if order.order_type == OrderType.MARKET:
            filled_price = self._apply_slippage(price, order.side)
            filled_qty = order.quantity
        elif order.order_type == OrderType.LIMIT and order.price is not None:
            if order.side == OrderSide.BUY and price <= order.price:
                filled_price = self._apply_slippage(min(price, order.price), order.side)
                filled_qty = order.quantity
            elif order.side == OrderSide.SELL and price >= order.price:
                filled_price = self._apply_slippage(max(price, order.price), order.side)
                filled_qty = order.quantity
            else:
                # Limit not crossed — simulate partial or no fill
                if random.random() < 0.3:
                    filled_qty = order.quantity * random.uniform(0.1, 0.5)
                    filled_price = self._apply_slippage(price, order.side)
                else:
                    raise BrokerConnectionError(f"Limit order not crossed: {order.price} vs {price}")
        else:
            raise BrokerConnectionError(f"Unsupported order type for mock broker: {order.order_type}")

        notional = filled_qty * filled_price
        fee = notional * 0.001  # 0.1% fee
        slippage = abs(filled_price - price)

        broker_order_id = self._next_order_id()
        self._orders[broker_order_id] = {
            "order": order,
            "filled_qty": filled_qty,
            "filled_price": filled_price,
        }

        # Update mock balances / positions
        self._update_state(order, filled_qty, filled_price, fee)

        return FillResult(
            order_id=order.id,
            symbol=order.symbol,
            filled_qty=filled_qty,
            filled_price=filled_price,
            fee=fee,
            slippage=slippage,
            timestamp=datetime.now(timezone.utc),
            side=order.side,
            realized_pnl=None,
        )

    def _update_state(self, order: Order, qty: float, price: float, fee: float) -> None:
        """Update mock balances and positions after a fill."""
        quote = "USDT" if "USDT" in order.symbol.upper() else "USD"
        notional = qty * price

        if order.side == OrderSide.BUY:
            self._balances[quote] = self._balances.get(quote, 0.0) - notional - fee
            sym = order.symbol.replace("-", "").upper().replace("USDT", "").replace("USD", "")
            pos = self._positions.get(sym)
            if pos:
                total_cost = pos.size * pos.entry_price + qty * price
                pos.size += qty
                pos.entry_price = total_cost / pos.size
            else:
                self._positions[sym] = MockPosition(symbol=sym, size=qty, entry_price=price, side="long")
        else:
            self._balances[quote] = self._balances.get(quote, 0.0) + notional - fee
            sym = order.symbol.replace("-", "").upper().replace("USDT", "").replace("USD", "")
            pos = self._positions.get(sym)
            if pos:
                if qty >= pos.size:
                    del self._positions[sym]
                else:
                    pos.size -= qty

    def get_positions(self) -> List[dict]:
        self._latency()
        return [
            {
                "symbol": p.symbol,
                "size": p.size,
                "entry_price": p.entry_price,
                "side": p.side,
            }
            for p in self._positions.values()
        ]

    def cancel_order(self, order_id: str) -> bool:
        self._latency()
        if order_id in self._orders:
            del self._orders[order_id]
            return True
        return False

    def get_account_info(self) -> dict:
        self._latency()
        return {
            "broker": self.name,
            "mock": True,
            "balances": self._balances,
            "position_count": len(self._positions),
            "order_count": len(self._orders),
        }

    def disconnect(self) -> None:
        self._connected = False

    # ── Demo entry point ──

    def demo(self) -> None:
        """Run a quick demo of the mock broker."""
        print("=== Mock Broker Demo ===")
        print(f"Connecting to {self.name} ...")
        self.connect("fake_key", "fake_secret")
        print(f"Connected: {self.is_connected()}")

        print(f"Balance: {self.get_balance()}")
        print(f"BTC price: {self.get_price('BTC-USD')}")
        print(f"ETH price: {self.get_price('ETH-USD')}")

        from bot.orders import Order
        buy = Order.market("BTC-USD", OrderSide.BUY, 0.1)
        fill = self.place_order(buy)
        print(f"Fill: {fill.filled_qty} @ {fill.filled_price:.2f} fee={fill.fee:.4f}")

        print(f"Balance after: {self.get_balance()}")
        print(f"Positions: {self.get_positions()}")
        print(f"Account info: {self.get_account_info()}")
        print("=== Demo Complete ===")


if __name__ == "__main__":
    broker = MockBroker()
    broker.demo()
