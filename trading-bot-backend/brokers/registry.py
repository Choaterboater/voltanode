"""Broker factory registry."""

from __future__ import annotations

from typing import Dict, Type

from brokers.base import BrokerAdapter
from brokers.binance import BinanceBroker
from brokers.alpaca import AlpacaBroker
from brokers.mock import MockBroker


BROKERS: Dict[str, Type[BrokerAdapter]] = {
    "binance": BinanceBroker,
    "alpaca": AlpacaBroker,
    "mock": MockBroker,
}


def get_broker(name: str) -> BrokerAdapter:
    """Instantiate a broker adapter by name.

    Args:
        name: One of "binance", "alpaca", "mock".

    Returns:
        Fresh BrokerAdapter instance.

    Raises:
        KeyError: If broker name is not registered.
    """
    broker_cls = BROKERS[name.lower()]
    return broker_cls()


def list_brokers() -> Dict[str, str]:
    """Return a mapping of broker names to descriptions."""
    return {
        "binance": "Binance Spot (testnet/live)",
        "alpaca": "Alpaca Markets (paper/live US equities)",
        "mock": "Mock broker for testing (no API keys)",
    }
