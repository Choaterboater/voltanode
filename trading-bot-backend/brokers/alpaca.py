"""Alpaca broker adapter for US equities.

Supports paper trading and live trading via Alpaca Markets API.
Uses `requests` to call the Alpaca REST API directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import logging
import time
import requests

logger = logging.getLogger("volta.brokers")

from bot.config import OrderSide, OrderType
from bot.orders import FillResult, Order

from brokers.base import BrokerAdapter, BrokerConnectionError


class AlpacaBroker(BrokerAdapter):
    """Alpaca Markets broker adapter.

    Paper trading endpoint: https://paper-api.alpaca.markets
    Live trading endpoint:  https://api.alpaca.markets
    """

    name = "alpaca"

    PAPER_BASE = "https://paper-api.alpaca.markets"
    LIVE_BASE = "https://api.alpaca.markets"

    DATA_PAPER = "https://data.alpaca.markets"
    DATA_LIVE = "https://data.alpaca.markets"

    # Common crypto assets supported by Alpaca (single-ticker form)
    _CRYPTO_TICKERS = {
        "BTC", "ETH", "LTC", "BCH", "LINK", "UNI", "AAVE", "SOL", "ADA", "DOT",
        "AVAX", "MATIC", "POL", "DOGE", "SHIB", "XRP", "ETC", "ALGO", "FIL", "XTZ",
        "TRX", "ATOM", "MANA", "SAND", "AXS", "GRT", "FTM", "ICP", "NEAR",
        "HBAR", "VET", "THETA", "EOS", "CHZ", "BAT", "ZIL", "DASH", "NEO",
        "LRC", "SKL", "CELO", "KNC", "SNX", "YFI", "BAL", "SUSHI", "1INCH",
        "BAND", "APT", "SUI", "SEI", "TIA", "DYM", "STRK", "WLD", "ARB", "OP",
        "IMX", "GALA", "BLUR", "PEPE", "BONK", "FLOKI", "JUP", "PYTH", "RNDR",
        "TAO", "ARKM", "PORTAL", "DEGEN", "POLY",
    }

    _CONN_CACHE_TTL = 30.0

    def __init__(self, paper: bool = True) -> None:
        self._paper = paper
        self._base_url = self.PAPER_BASE if paper else self.LIVE_BASE
        self._data_url = self.DATA_PAPER if paper else self.DATA_LIVE
        self._api_key = ""
        self._api_secret = ""
        self._session = requests.Session()
        self._conn_cache: tuple[bool, float] | None = None

    def connect(self, api_key: str, api_secret: str, **kwargs: Any) -> bool:
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip()
        if kwargs.get("paper") is not None:
            self._paper = bool(kwargs["paper"])
            self._base_url = self.PAPER_BASE if self._paper else self.LIVE_BASE
            self._data_url = self.DATA_PAPER if self._paper else self.DATA_LIVE

        if not self._api_key or not self._api_secret:
            raise BrokerConnectionError("Alpaca API key and secret are required.")

        self._session.headers.update({
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._api_secret,
            "Content-Type": "application/json",
        })

        try:
            account = self.get_account_info()
            return account.get("status") == "ACTIVE"
        except Exception as exc:
            raise BrokerConnectionError(f"Alpaca connection failed: {exc}") from exc

    def is_connected(self) -> bool:
        now = time.monotonic()
        if self._conn_cache is not None and now - self._conn_cache[1] < self._CONN_CACHE_TTL:
            return self._conn_cache[0]
        try:
            self._request("GET", "/v2/account")
            result = True
        except Exception:
            result = False
        self._conn_cache = (result, now)
        return result

    def _request(self, method: str, path: str, json: Any = None, params: Any = None) -> Any:
        url = f"{self._base_url}{path}"
        try:
            response = self._session.request(method, url, json=json, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "code" in data and "message" in data:
                raise BrokerConnectionError(f"Alpaca API error {data['code']}: {data['message']}")
            return data
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response else 0
            text = exc.response.text if exc.response else ""
            raise BrokerConnectionError(f"Alpaca HTTP {status}: {text}") from exc
        except requests.exceptions.RequestException as exc:
            raise BrokerConnectionError(f"Alpaca request failed: {exc}") from exc

    def get_balance(self) -> Dict[str, float]:
        account = self._request("GET", "/v2/account")
        return {
            "USD": float(account.get("cash", 0)),
            "EQUITY": float(account.get("equity", 0)),
            "BUYING_POWER": float(account.get("buying_power", 0)),
        }

    def _is_crypto_symbol(self, symbol: str) -> bool:
        """Detect if symbol is a crypto asset."""
        sym = symbol.upper()
        if "/" in sym or sym.endswith("-USD") or sym.endswith("USDT"):
            return True
        # Handle BTCUSD format (no dash/slash) — check base against known tickers
        if sym.endswith("USD") and not sym.endswith("USDT"):
            base = sym[:-3]
            if base in self._CRYPTO_TICKERS:
                return True
        base = sym.replace("-USD", "").replace("USDT", "").replace("/USD", "")
        return base in self._CRYPTO_TICKERS

    def _normalize_crypto_symbol(self, symbol: str) -> str:
        """Normalize crypto symbol to Alpaca format (BTC/USD)."""
        sym = symbol.upper()
        if "/USD" in sym:
            return sym
        if sym.endswith("-USD"):
            return sym.replace("-USD", "/USD")
        if sym.endswith("USDT"):
            return sym.replace("USDT", "/USD")
        if sym.endswith("USD") and not sym.endswith("USDT"):
            base = sym[:-3]
            if base in self._CRYPTO_TICKERS:
                return f"{base}/USD"
        return f"{sym}/USD"

    def get_price(self, symbol: str) -> float:
        """Get latest trade price for a stock or crypto symbol."""
        if self._is_crypto_symbol(symbol):
            norm = self._normalize_crypto_symbol(symbol)
            url = f"{self._data_url}/v1beta3/crypto/us/latest/trades"
            try:
                response = self._session.get(url, params={"symbols": norm}, timeout=10)
                response.raise_for_status()
                data = response.json()
                trade = data.get("trades", {}).get(norm, {})
                price = float(trade.get("p", 0))
                if price:
                    return price
                logger.warning(f"Alpaca crypto trade price empty for {norm} — response: {data}")
            except Exception as exc:
                logger.warning(f"Alpaca crypto trade fetch failed for {norm}: {exc}")
            # Fallback: use last quote midpoint
            url = f"{self._data_url}/v1beta3/crypto/us/latest/quotes"
            try:
                response = self._session.get(url, params={"symbols": norm}, timeout=10)
                response.raise_for_status()
                data = response.json()
                quote = data.get("quotes", {}).get(norm, {})
                bid = float(quote.get("bp", 0))
                ask = float(quote.get("ap", 0))
                if bid and ask:
                    return (bid + ask) / 2
                return bid or ask or 0.0
            except Exception as exc:
                logger.warning(f"Alpaca crypto quote fetch failed for {norm}: {exc}")
                return 0.0

        # Stock path
        url = f"{self._data_url}/v2/stocks/{symbol}/trades/latest"
        try:
            response = self._session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            trade = data.get("trade", {})
            return float(trade.get("p", 0))  # 'p' is price
        except Exception as exc:
            logger.warning(f"Alpaca stock trade fetch failed for {symbol}: {exc}")
            # Fallback: use last quote midpoint
            url = f"{self._data_url}/v2/stocks/{symbol}/quotes/latest"
            try:
                response = self._session.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                quote = data.get("quote", {})
                bid = float(quote.get("bp", 0))
                ask = float(quote.get("ap", 0))
                if bid and ask:
                    return (bid + ask) / 2
                return bid or ask or 0.0
            except Exception as exc2:
                logger.warning(f"Alpaca stock quote fetch failed for {symbol}: {exc2}")
                return 0.0

    def place_order(self, order: Order) -> FillResult:
        if not self._api_key:
            raise BrokerConnectionError("Not connected. Call connect() first.")

        side_map = {OrderSide.BUY: "buy", OrderSide.SELL: "sell"}
        type_map = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP_LOSS: "stop",
            OrderType.TAKE_PROFIT: "limit",
            OrderType.STOP_LIMIT: "stop_limit",
        }

        sym = order.symbol.upper()
        if self._is_crypto_symbol(sym):
            sym = self._normalize_crypto_symbol(sym)

        body = {
            "symbol": sym,
            "qty": str(order.quantity),
            "side": side_map[order.side],
            "type": type_map.get(order.order_type, "market"),
            "time_in_force": order.time_in_force.lower() if order.time_in_force else "day",
            "client_order_id": order.id,
        }

        if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and order.price is not None:
            body["limit_price"] = str(order.price)
        if order.order_type in (OrderType.STOP_LOSS, OrderType.STOP_LIMIT) and order.stop_price is not None:
            body["stop_price"] = str(order.stop_price)

        data = self._request("POST", "/v2/orders", json=body)

        # Alpaca returns the order object; handle both immediate and async fills
        status = data.get("status")
        accepted_statuses = ("filled", "partially_filled", "accepted", "new", "pending_new", "submitted")
        if status not in accepted_statuses:
            raise BrokerConnectionError(
                f"Alpaca order rejected (status={status}). "
                f"Response: {data.get('message', 'Unknown error')}"
            )

        filled_qty = float(data.get("filled_qty", 0))
        filled_price = float(data.get("filled_avg_price", 0) or data.get("price", 0) or 0)
        fee = 0.0  # Alpaca commission-free for equities
        slippage = 0.0

        broker_order_id = data.get("id", "")

        # If not yet filled, return zero fill — caller should poll
        if status in ("accepted", "new", "pending_new", "submitted"):
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
            broker_order_id=broker_order_id,
        )

    def get_positions(self) -> List[dict]:
        data = self._request("GET", "/v2/positions")
        return [
            {
                "symbol": p.get("symbol"),
                "size": float(p.get("qty", 0)),
                "entry_price": float(p.get("avg_entry_price", 0)),
                "side": "long" if float(p.get("qty", 0)) > 0 else "short",
            }
            for p in (data if isinstance(data, list) else [])
        ]

    def get_order(self, order_id: str) -> dict:
        """Get order status from Alpaca by broker order ID."""
        data = self._request("GET", f"/v2/orders/{order_id}")
        status_map = {
            "new": "pending",
            "accepted": "pending",
            "pending_new": "pending",
            "submitted": "pending",
            "partially_filled": "partial",
            "filled": "filled",
            "canceled": "canceled",
            "rejected": "rejected",
        }
        return {
            "broker_order_id": data.get("id", order_id),
            "status": status_map.get(data.get("status", "").lower(), "pending"),
            "filled_qty": float(data.get("filled_qty", 0)),
            "filled_price": float(data.get("filled_avg_price", 0) or data.get("price", 0) or 0),
            "symbol": data.get("symbol", ""),
            "side": data.get("side", ""),
        }

    def get_orders(self, status: str | None = None, limit: int = 50, **kwargs: Any) -> List[dict]:
        """List orders from Alpaca.

        Args:
            status: "open", "closed", or "all". Default "open".
            limit: Max results (1-500).
            **kwargs: Additional filters (after, until, symbols, etc.).

        Returns:
            List of normalized order dicts.
        """
        params: Dict[str, Any] = {"limit": min(limit, 500)}
        if status:
            params["status"] = status
        for key in ("after", "until", "direction", "symbols", "nested"):
            if key in kwargs:
                params[key] = kwargs[key]
        data = self._request("GET", "/v2/orders", params=params)
        status_map = {
            "new": "pending",
            "accepted": "pending",
            "pending_new": "pending",
            "submitted": "pending",
            "partially_filled": "partial",
            "filled": "filled",
            "canceled": "canceled",
            "rejected": "rejected",
        }
        return [
            {
                "broker_order_id": o.get("id", ""),
                "client_order_id": o.get("client_order_id", ""),
                "status": status_map.get(o.get("status", "").lower(), "pending"),
                "filled_qty": float(o.get("filled_qty", 0)),
                "filled_price": float(o.get("filled_avg_price", 0) or o.get("price", 0) or 0),
                "symbol": o.get("symbol", ""),
                "side": o.get("side", ""),
                "order_type": o.get("type", ""),
                "qty": o.get("qty", o.get("notional", "0")),
                "created_at": o.get("submitted_at", ""),
            }
            for o in (data if isinstance(data, list) else [])
        ]

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._request("DELETE", f"/v2/orders/{order_id}")
            return True
        except BrokerConnectionError:
            return False

    def close_position(self, symbol: str) -> dict:
        """Liquidate an open position for a symbol."""
        try:
            return self._request("DELETE", f"/v2/positions/{symbol}")
        except BrokerConnectionError as exc:
            return {"error": str(exc)}

    def get_account_info(self) -> dict:
        return self._request("GET", "/v2/account")

    def disconnect(self) -> None:
        self._conn_cache = None
        self._session.close()
