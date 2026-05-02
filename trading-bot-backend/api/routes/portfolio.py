"""Portfolio API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List

from api.models import DepositRequest, PortfolioResponse, PositionResponse
from bot.engine import PaperTradingEngine
from bot.portfolio import Portfolio

router = APIRouter()

# Global engine reference (set in main.py)
engine: PaperTradingEngine | None = None


def set_engine(e: PaperTradingEngine) -> None:
    """Set the global engine reference."""
    global engine
    engine = e


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


@router.get("/{account_id}")
async def get_portfolio(account_id: str) -> PortfolioResponse:
    """Get portfolio for an account."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
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
            )
            for p in portfolio.get_all_positions()
        ]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")


@router.get("/{account_id}/snapshots")
async def get_snapshots(account_id: str) -> Dict[str, Any]:
    """Get portfolio snapshots (simplified)."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return {"account_id": account_id, "snapshots": []}
