"""Order API routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict, List

from api.models import OrderRequest, OrderResponse
from bot.engine import PaperTradingEngine, LiveTradingEngine
from bot.orders import Order, OrderStatus, OrderType
from bot.config import OrderSide, AssetClass


def _detect_asset_class(symbol: str) -> AssetClass:
    """Heuristic to detect asset class from symbol."""
    sym = symbol.upper()
    # Crypto indicators: slash pair, -USD suffix, USDT suffix, or common crypto tickers
    if "/" in sym or sym.endswith("-USD") or sym.endswith("USDT"):
        return AssetClass.CRYPTO
    crypto_tickers = {
        "BTC", "ETH", "SOL", "ADA", "XRP", "DOT", "LINK", "AVAX", "MATIC",
        "DOGE", "SHIB", "LTC", "BCH", "UNI", "ETC", "ALGO", "FIL", "ATOM",
        "MANA", "SAND", "AXS", "GRT", "FTM", "ICP", "NEAR", "HBAR", "VET",
        "XTZ", "TRX", "THETA", "EOS", "AAVE", "CHZ", "BAT", "ZIL", "DASH",
        "NEO", "LRC", "SKL", "CELO", "KNC", "SNX", "YFI", "BAL", "SUSHI",
        "1INCH", "BAND", "APT", "SUI", "SEI", "TIA", "DYM", "STRK", "WLD",
        "ARB", "OP", "IMX", "GALA", "BLUR", "PEPE", "BONK", "FLOKI", "JUP",
        "PYTH", "RNDR", "TAO", "ARKM", "PORTAL", "DEGEN",
    }
    if sym in crypto_tickers:
        return AssetClass.CRYPTO
    return AssetClass.STOCK

router = APIRouter()

engine: PaperTradingEngine | None = None


def set_engine(e: PaperTradingEngine) -> None:
    global engine
    engine = e


def _is_live_mode() -> bool:
    """Check if the current engine is in live mode."""
    return isinstance(engine, LiveTradingEngine) and getattr(engine, "live_mode", False)


@router.get("/")
async def list_orders(account_id: str = "default") -> List[Dict[str, Any]]:
    """List all orders for an account."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    orders = engine.get_orders(account_id)
    return [
        {
            "id": o.id,
            "symbol": o.symbol,
            "side": o.side.value,
            "order_type": o.order_type.value,
            "quantity": o.quantity,
            "price": o.price,
            "stop_price": o.stop_price,
            "status": o.status.value,
            "created_at": o.created_at.isoformat() if hasattr(o.created_at, 'isoformat') else str(o.created_at),
            "strategy_id": o.strategy_id,
            "account_id": o.account_id,
        }
        for o in orders
    ]


@router.post("/")
async def place_order(request: Request, body: OrderRequest) -> OrderResponse:
    """Place a new order (paper or live depending on engine mode)."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    order = Order(
        id=str(uuid.uuid4()),
        symbol=body.symbol,
        side=body.side,
        order_type=body.order_type,
        quantity=body.quantity,
        price=body.price,
        stop_price=body.stop_price,
        created_at=datetime.now(timezone.utc),
        strategy_id=body.strategy_id,
        account_id=body.account_id,
    )

    # Live mode: route directly to broker
    if _is_live_mode():
        try:
            fill = engine.execute_order(order)
            # Reflect the order's final status — engine may have set REJECTED
            # via the sell-guard or per-strategy debounce path, in which case
            # filled_qty is 0 and the response should NOT say "pending".
            if order.status == OrderStatus.REJECTED:
                status = "rejected"
            elif fill.filled_qty >= order.quantity:
                status = "filled"
            elif fill.filled_qty > 0:
                status = "partial"
            else:
                status = "pending"
            return OrderResponse(
                order_id=order.id,
                status=status,
                filled_qty=fill.filled_qty,
                avg_fill_price=fill.filled_price,
                fee=fill.fee,
                created_at=order.created_at,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # Paper mode: submit to engine
    order_id = engine.submit_order(order, body.account_id)

    # Try to execute immediately for market orders
    if body.order_type == OrderType.MARKET and engine.market_data:
        try:
            asset_class = body.asset_class or _detect_asset_class(body.symbol)
            price = await engine.market_data.get_price(body.symbol, asset_class)
            fill = engine.execute_order(order, price)
            if fill:
                return OrderResponse(
                    order_id=order_id,
                    status="filled",
                    filled_qty=fill.filled_qty,
                    avg_fill_price=fill.filled_price,
                    fee=fill.fee,
                    created_at=order.created_at,
                )
        except Exception:
            pass

    return OrderResponse(
        order_id=order_id,
        status="pending",
        filled_qty=0.0,
        fee=0.0,
        created_at=order.created_at,
    )


@router.post("/{order_id}/cancel")
async def cancel_order(order_id: str, account_id: str = "default") -> Dict[str, Any]:
    """Cancel a pending order."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    success = engine.cancel_order(order_id, account_id)
    if not success:
        raise HTTPException(status_code=400, detail="Order not found or already filled/cancelled")
    return {"order_id": order_id, "status": "cancelled"}
