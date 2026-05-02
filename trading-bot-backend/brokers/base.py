"""Abstract broker adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from bot.orders import FillResult, Order


class BrokerConnectionError(Exception):
    """Raised when broker connection fails."""
    pass


class BrokerAdapter(ABC):
    """Abstract base class for exchange/broker adapters.

    All real and simulated brokers must implement this interface so the
    engine can execute orders agnostically.
    """

    name: str = "base"

    @abstractmethod
    def connect(self, api_key: str, api_secret: str, **kwargs: Any) -> bool:
        """Connect to the broker using API credentials.

        Args:
            api_key: Broker API key.
            api_secret: Broker API secret.
            **kwargs: Extra connection parameters (e.g. testnet=True).

        Returns:
            True if connection succeeded.
        """
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if broker connection is alive."""
        ...

    @abstractmethod
    def get_balance(self) -> Dict[str, float]:
        """Return account balances {asset: free_balance}."""
        ...

    @abstractmethod
    def get_price(self, symbol: str) -> float:
        """Return current mid price for a symbol."""
        ...

    @abstractmethod
    def place_order(self, order: Order) -> FillResult:
        """Submit an order and return fill details.

        Raises:
            BrokerConnectionError: If not connected or order rejected.
        """
        ...

    @abstractmethod
    def get_positions(self) -> List[dict]:
        """Return open positions / holdings."""
        ...

    @abstractmethod
    def get_order(self, order_id: str, **kwargs: Any) -> dict:
        """Get order status by broker order ID.

        Returns a normalized dict with keys:
        - broker_order_id: str
        - status: str ("pending", "partial", "filled", "canceled", "rejected")
        - filled_qty: float
        - filled_price: float
        - symbol: str
        - side: str
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by broker order ID."""
        ...

    @abstractmethod
    def get_account_info(self) -> dict:
        """Return account metadata (permissions, limits, etc.)."""
        ...

    def disconnect(self) -> None:
        """Cleanly disconnect from the broker. Override if needed."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
