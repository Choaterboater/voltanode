"""Portfolio API routes."""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List

from api.models import DepositRequest, PortfolioResponse, PositionResponse
from bot.engine import PaperTradingEngine
from bot.portfolio import Portfolio

logger = logging.getLogger("volta.api.portfolio")

router = APIRouter()

# Global engine + equity-history references (set in main.py).
engine: PaperTradingEngine | None = None
_equity_history: Any | None = None


def set_engine(e: PaperTradingEngine) -> None:
    """Set the global engine reference."""
    global engine
    engine = e


def set_equity_history(store: Any) -> None:
    """Inject the EquityHistoryStore so /equity-history can serve points."""
    global _equity_history
    _equity_history = store


def _portfolio_to_response(portfolio: Portfolio) -> PortfolioResponse:
    """Convert Portfolio to response model."""
    positions = [
        PositionResponse(
            symbol=p.symbol,
            side=p.side.value,
            size=p.size,
            entry_price=p.entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl,
            market_value=p.market_value,
            stop_loss=p.stop_loss,
            take_profit=p.take_profit,
        )
        for p in portfolio.get_all_positions()
    ]
    total_balance = sum(portfolio.get_all_balances().values())
    total_position_value = sum(p.market_value for p in portfolio.get_all_positions())
    return PortfolioResponse(
        account_id=portfolio.account_id,
        balances=portfolio.get_all_balances(),
        positions=positions,
        total_equity=total_balance + total_position_value,
        unrealized_pnl=portfolio.total_unrealized_pnl,
        realized_pnl=portfolio.total_realized_pnl,
        timestamp=portfolio.snapshot().timestamp,
    )


def _live_broker_to_response(account_id: str, eng: Any) -> PortfolioResponse | None:
    """Build a PortfolioResponse from the connected live broker.

    Returns None if not in live mode or broker is unavailable.
    """
    if not getattr(eng, "live_mode", False):
        return None
    broker = getattr(eng, "broker", None)
    if broker is None or not broker.is_connected() or broker.name == "mock":
        return None

    try:
        balances = eng.get_broker_balance()  # Dict[str, float]
        raw_positions = eng.get_broker_positions()  # List[dict]
    except Exception as exc:
        logger.warning(f"Live broker fetch failed, falling back to simulated portfolio: {exc}")
        return None

    # Overlay engine's tick-loop prices over broker-reported current_price.
    # Alpaca paper position pricing lags noticeably; the engine fetches fresh
    # prices every tick (~5-15s) into _current_prices. Use those when newer.
    live_prices = getattr(eng, "_current_prices", {}) or {}

    positions: List[PositionResponse] = []
    for p in raw_positions:
        symbol = p.get("symbol", "")
        size = float(p.get("qty", p.get("size", 0)) or 0)
        entry = float(p.get("avg_entry_price", p.get("entry_price", 0)) or 0)
        broker_current = float(p.get("current_price", p.get("market_price", entry)) or entry)
        # Engine map keys are typically the bot's symbol — try a few variants.
        sym_upper = symbol.upper()
        canonical = sym_upper.replace("USD", "").replace("/", "").replace("-", "")
        live = (
            live_prices.get(symbol)
            or live_prices.get(sym_upper)
            or live_prices.get(canonical)
            or live_prices.get(sym_upper + "USD")
        )
        current = float(live) if live else broker_current
        side = (p.get("side") or ("long" if size >= 0 else "short")).lower()
        # Recompute mark-to-market with the fresher price.
        market_value = abs(size) * current
        if current and entry:
            sign = 1 if side == "long" else -1
            unrealized_pnl = sign * (current - entry) * abs(size)
        else:
            unrealized_pnl = float(p.get("unrealized_pl", p.get("unrealized_pnl", 0)) or 0)
        positions.append(
            PositionResponse(
                symbol=symbol,
                side=side,
                size=abs(size),
                entry_price=entry,
                current_price=current,
                unrealized_pnl=unrealized_pnl,
                market_value=market_value,
                stop_loss=None,
                take_profit=None,
            )
        )

    # Pick a canonical total_equity. Brokers like Alpaca expose overlapping
    # ledger fields (cash + equity + buying_power) where equity already
    # includes position market value, so summing them double-counts.
    # Preference order: explicit EQUITY/equity field, then cash + positions.
    total_position_value = sum(pos.market_value for pos in positions)
    if balances and any(k.upper() == "EQUITY" for k in balances):
        equity_key = next(k for k in balances if k.upper() == "EQUITY")
        total_equity = float(balances[equity_key])
    else:
        cash_keys = {"USD", "USDT", "CASH"}
        cash_total = sum(v for k, v in (balances or {}).items() if k.upper() in cash_keys)
        total_equity = cash_total + total_position_value

    unrealized = sum(pos.unrealized_pnl for pos in positions)

    from datetime import datetime, timezone
    return PortfolioResponse(
        account_id=account_id,
        balances=balances or {},
        positions=positions,
        total_equity=total_equity,
        unrealized_pnl=unrealized,
        realized_pnl=0.0,  # Broker-reported realized P&L not standardized across adapters
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/{account_id}")
async def get_portfolio(account_id: str) -> PortfolioResponse:
    """Get portfolio for an account.

    When live mode is enabled and a real broker is connected, returns the
    broker's actual balance/positions. Otherwise returns the simulated
    in-memory portfolio.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    live = _live_broker_to_response(account_id, engine)
    if live is not None:
        return live

    try:
        portfolio = engine.get_portfolio(account_id)
        return _portfolio_to_response(portfolio)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")


@router.post("/{account_id}/deposit")
async def deposit(account_id: str, request: DepositRequest) -> Dict[str, Any]:
    """Deposit virtual funds into an account."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    try:
        portfolio = engine.get_portfolio(account_id)
        portfolio.deposit(request.asset, request.amount)
        return {"account_id": account_id, "asset": request.asset, "amount": request.amount, "balance": portfolio.get_balance(request.asset)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")


@router.get("/{account_id}/positions")
async def get_positions(account_id: str) -> List[PositionResponse]:
    """Get open positions for an account."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    try:
        portfolio = engine.get_portfolio(account_id)
        return [
            PositionResponse(
                symbol=p.symbol,
                side=p.side.value,
                size=p.size,
                entry_price=p.entry_price,
                current_price=p.current_price,
                unrealized_pnl=p.unrealized_pnl,
                market_value=p.market_value,
                stop_loss=p.stop_loss,
                take_profit=p.take_profit,
            )
            for p in portfolio.get_all_positions()
        ]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")


@router.post("/{account_id}/flatten")
async def flatten_positions(
    account_id: str,
    symbols: str | None = None,
    confirm: bool = False,
) -> Dict[str, Any]:
    """Close one or more open positions via market sell.

    Pass ``symbols=RXT,AAPL`` (comma-separated) to flatten specific names, or
    omit ``symbols`` AND set ``confirm=true`` to flatten ALL open positions.
    Without either, the request errors so a typo can't accidentally close the
    whole book. Returns a per-symbol success / failure breakdown.

    Use this to clean up over-sized positions caused by duplicate same-side
    entries (now prevented by the ``BaseStrategy`` position-aware gate). Bots
    will re-enter cleanly on the next valid signal — single-lot this time.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    from datetime import datetime, timezone
    import uuid as _uuid
    from bot.orders import Order, OrderSide, OrderType, OrderStatus

    try:
        portfolio = engine.get_portfolio(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    all_positions = portfolio.get_all_positions()
    open_positions = [p for p in all_positions if getattr(p, "status", "") == "open" and p.size > 0]

    target_set: set[str] = set()
    if symbols:
        target_set = {s.strip().upper() for s in symbols.split(",") if s.strip()}
    elif not confirm:
        raise HTTPException(
            status_code=400,
            detail="Refusing to flatten ALL positions without ?confirm=true. "
                   "Pass ?symbols=RXT,AAPL for a targeted flatten or ?confirm=true to close everything.",
        )
    if target_set:
        candidates = [p for p in open_positions if p.symbol.upper() in target_set]
    else:
        candidates = list(open_positions)

    closed: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for pos in candidates:
        try:
            order = Order(
                id=str(_uuid.uuid4()),
                symbol=pos.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=float(pos.size),
                price=None,
                stop_price=None,
                created_at=datetime.now(timezone.utc),
                strategy_id="manual_flatten",
                account_id=account_id,
            )
            # In live mode the engine routes to broker on execute_order;
            # in paper mode it fills locally.
            try:
                fill = engine.execute_order(order)
            except TypeError:
                # Paper engine signature is (order, current_price)
                fill = engine.execute_order(order, getattr(pos, "current_price", 0.0) or 0.0)
            filled_qty = getattr(fill, "filled_qty", 0.0) if fill else 0.0
            status = order.status.value if hasattr(order.status, "value") else str(order.status)
            closed.append({
                "symbol": pos.symbol,
                "qty": filled_qty,
                "status": status,
                "order_id": order.id,
            })
        except Exception as exc:
            failed.append({"symbol": pos.symbol, "error": str(exc)[:200]})
            logger.warning("flatten %s failed: %s", pos.symbol, exc)

    return {
        "account_id": account_id,
        "requested": sorted(target_set) if target_set else "ALL",
        "closed": closed,
        "failed": failed,
        "remaining_positions": len(open_positions) - len(closed),
    }


@router.get("/{account_id}/snapshots")
async def get_snapshots(account_id: str) -> Dict[str, Any]:
    """Get portfolio snapshots (simplified)."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return {"account_id": account_id, "snapshots": []}


@router.get("/{account_id}/equity-history")
async def get_equity_history(account_id: str, range: str = "30D") -> Dict[str, Any]:
    """Return the persisted equity curve for an account.

    Range: '1H', '24H', '7D', '30D', or 'ALL'.
    """
    from datetime import datetime, timedelta, timezone
    from fastapi import Request
    import inspect
    # pull the EquityHistoryStore off app.state — engine is set per-request only;
    # we stash a module-level pointer when set_engine fires too.
    history = _equity_history
    if history is None:
        return {"account_id": account_id, "range": range, "points": []}

    delta_map = {
        "1H": timedelta(hours=1),
        "24H": timedelta(hours=24),
        "7D": timedelta(days=7),
        "30D": timedelta(days=30),
        "ALL": None,
    }
    delta = delta_map.get(range.upper(), timedelta(days=30))
    since = (datetime.now(timezone.utc) - delta) if delta is not None else None

    points = history.query(account_id, since=since)
    return {
        "account_id": account_id,
        "range": range,
        "points": [{"ts": ts.isoformat(), "equity": eq} for ts, eq in points],
    }
