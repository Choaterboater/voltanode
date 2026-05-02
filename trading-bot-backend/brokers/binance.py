"""Binance Spot broker adapter using `requests`.

Supports both mainnet and testnet.
Maps VoltaNode symbols (BTC-USD) to Binance format (BTCUSDT).
Handles Binance-specific rate limits and error codes.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from bot.config import OrderSide, OrderType
from bot.orders import FillResult, Order

from brokers.base import BrokerAdapter, BrokerConnectionError


class BinanceBroker(BrokerAdapter):
    """Binance Spot API adapter.

    Environment variables:
        VOLTANODE_BINANCE_TESTNET -- set to "true" to force testnet.
    """

    name = "binance"

    MAINNET_BASE = "https://api.binance.com"
    TESTNET_BASE = "https://testnet.binance.vision"

    def __init__(self, testnet: bool = True) -> None:
        self._testnet = testnet
        self._base_url = self.TESTNET_BASE if testnet else self.MAINNET_BASE
        self._api_key = ""
        self._api_secret = ""
        self._session = requests.Session()
        self._recv_window = 5000

    def connect(self, api_key: str, api_secret: str, **kwargs: Any) -> bool:
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip()
        if kwargs.get("testnet") is not None:
            self._testnet = bool(kwargs["testnet"])
            self._base_url = self.TESTNET_BASE if self._testnet else self.MAINNET_BASE

        if not self._api_key or not self._api_secret:
            raise BrokerConnectionError("Binance API key and secret are required.")

        self._session.headers.update({
            "X-MBX-APIKEY": self._api_key,
        })

        # Test connection with account info
        try:
            info = self.get_account_info()
            return info.get("canTrade", False) or info.get("makerCommission") is not None
        except Exception as exc:
            raise BrokerConnectionError(f"Binance connection failed: {exc}") from exc

    def is_connected(self) -> bool:
        try:
            self._request("GET", "/api/v3/ping")
            return True
        except Exception:
            return False

    def _signature(self, query_string: str) -> str:
        return hmac.new(
            self._api_secret.encode(),
            query_string.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _request(self, method: str, path: str, params: Optional[Dict] = None, signed: bool = False) -> Any:
        url = f"{self._base_url}{path}"
        params = params or {}

        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = self._recv_window
            query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            params["signature"] = self._signature(query)

        try:
            response = self._session.request(method, url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "code" in data and "msg" in data:
                if data["code"] < 0:
                    raise BrokerConnectionError(f"Binance API error {data['code']}: {data['msg']}")
            return data
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response else 0
            text = exc.response.text if exc.response else ""
            raise BrokerConnectionError(f"Binance HTTP {status}: {text}") from exc
        except requests.exceptions.RequestException as exc:
            raise BrokerConnectionError(f"Binance request failed: {exc}") from exc

    def get_balance(self) -> Dict[str, float]:
        data = self._request("GET", "/api/v3/account", signed=True)
        balances = {}
        for bal in data.get("balances", []):
            free = float(bal.get("free", 0))
            locked = float(bal.get("locked", 0))
            if free + locked > 0:
                balances[bal["asset"]] = free
        return balances

    def get_price(self, symbol: str) -> float:
        binance_symbol = self._to_binance_symbol(symbol)
        data = self._request("GET", "/api/v3/ticker/price", params={"symbol": binance_symbol})
        return float(data["price"])

    def place_order(self, order: Order) -> FillResult:
        if not self._api_key:
            raise BrokerConnectionError("Not connected. Call connect() first.")

        binance_symbol = self._to_binance_symbol(order.symbol)
        side_map = {OrderSide.BUY: "BUY", OrderSide.SELL: "SELL"}
        type_map = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.STOP_LOSS: "STOP_LOSS_LIMIT",
            OrderType.TAKE_PROFIT: "TAKE_PROFIT_LIMIT",
            OrderType.STOP_LIMIT: "STOP_LIMIT",
        }

        params: Dict[str, Any] = {
            "symbol": binance_symbol,
            "side": side_map[order.side],
            "type": type_map.get(order.order_type, "MARKET"),
            "quantity": order.quantity,
        }

        if order.order_type == OrderType.LIMIT and order.price is not None:
            params["price"] = order.price
            params["timeInForce"] = order.time_in_force or "GTC"
        elif order.order_type == OrderType.STOP_LOSS and order.stop_price is not None:
            params["stopPrice"] = order.stop_price
            params["timeInForce"] = "GTC"
        elif order.order_type == OrderType.STOP_LIMIT and order.price is not None and order.stop_price is not None:
            params["price"] = order.price
            params["stopPrice"] = order.stop_price
            params["timeInForce"] = "GTC"

        data = self._request("POST", "/api/v3/order", params=params, signed=True)

        # Binance returns order details; we synthesize a FillResult
        executed_qty = float(data.get("executedQty", 0))
        fills = data.get("fills", [])
        if fills:
            avg_price = sum(float(f["price"]) * float(f["qty"]) for f in fills) / executed_qty if executed_qty else 0
            fee = sum(float(f.get("commission", 0)) for f in fills)
        else:
            avg_price = float(data.get("price", 0) or 0)
            fee = 0.0

        # Handle both immediate fills and pending orders
        status = data.get("status")
        if status not in ("FILLED", "PARTIALLY_FILLED", "NEW", "PENDING_NEW"):
            raise BrokerConnectionError(
                f"Order rejected (status={status}). "
                f"Response: {data}"
            )

        broker_order_id = str(data.get("orderId", ""))

        # If order is pending, return zero fill — caller should poll
        if status in ("NEW", "PENDING_NEW"):
            return FillResult(
                order_id=order.id,
                symbol=order.symbol,
                filled_qty=0.0,
                filled_price=0.0,
                fee=0.0,
                slippage=0.0,
                timestamp=datetime.now(timezone.utc),
                side=order.side,
                realized_pnl=None,
                broker_order_id=broker_order_id,
            )

        slippage = abs(avg_price - float(data.get("price", avg_price) or avg_price))

        return FillResult(
            order_id=order.id,
            symbol=order.symbol,
            filled_qty=executed_qty,
            filled_price=avg_price,
            fee=fee,
            slippage=slippage,
            timestamp=datetime.now(timezone.utc),
            side=order.side,
            realized_pnl=None,
            broker_order_id=broker_order_id,
        )

    def get_positions(self) -> List[dict]:
        """Binance spot doesn't have traditional "positions".
        Return non-zero balances as holdings.
        """
        balances = self.get_balance()
        return [
            {"symbol": asset, "size": qty, "entry_price": 0.0, "side": "long"}
            for asset, qty in balances.items() if qty > 0 and asset not in ("USDT", "USD", "BUSD")
        ]

    def get_order(self, order_id: str, symbol: str | None = None) -> dict:
        """Get order status from Binance by broker order ID."""
        lookup_symbol = self._to_binance_symbol(symbol) if symbol else "BTCUSDT"
        data = self._request(
            "GET",
            "/api/v3/order",
            params={"symbol": lookup_symbol, "orderId": order_id},
            signed=True,
        )
        status_map = {
            "NEW": "pending",
            "PENDING_NEW": "pending",
            "PARTIALLY_FILLED": "partial",
            "FILLED": "filled",
            "CANCELED": "canceled",
            "REJECTED": "rejected",
        }
        return {
            "broker_order_id": str(data.get("orderId", order_id)),
            "status": status_map.get(data.get("status", ""), "pending"),
            "filled_qty": float(data.get("executedQty", 0)),
            "filled_price": float(data.get("price", 0) or 0),
            "symbol": symbol or "",
            "side": data.get("side", "").lower(),
        }

    def cancel_order(self, order_id: str, symbol: str | None = None) -> bool:
        # order_id here is the Binance orderId, not our internal uuid
        try:
            cancel_symbol = self._to_binance_symbol(symbol) if symbol else "BTCUSDT"
            self._request(
                "DELETE",
                "/api/v3/order",
                params={"symbol": cancel_symbol, "orderId": order_id},
                signed=True,
            )
            return True
        except BrokerConnectionError:
            return False

    def get_account_info(self) -> dict:
        return self._request("GET", "/api/v3/account", signed=True)

    def disconnect(self) -> None:
        self._session.close()

    @staticmethod
    def _to_binance_symbol(symbol: str) -> str:
        """Convert VoltaNode symbol (BTC-USD) to Binance format (BTCUSDT).

        If symbol already has no dash, return uppercased.
        """
        s = symbol.replace("-", "").upper()
        if s.endswith("USD") and not s.endswith("USDT") and not s.endswith("BUSD"):
            s += "T"  # default to USDT for spot
        return s
