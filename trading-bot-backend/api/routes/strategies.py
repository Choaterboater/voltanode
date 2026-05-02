"""Strategy API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List

from api.models import StrategyInfo, StrategyListResponse, StrategyRegisterRequest, StrategyToggleRequest
from strategies import StrategyFactory, list_strategies
from strategies.base import BaseStrategy
from bot.engine import PaperTradingEngine

router = APIRouter()

engine: PaperTradingEngine | None = None
_registered_strategies: Dict[str, BaseStrategy] = {}


def set_engine(e: PaperTradingEngine) -> None:
    global engine
    engine = e


@router.get("/")
async def list_all_strategies() -> StrategyListResponse:
    """List all available strategy types."""
    available = list_strategies()
    strategies = []
    for name, info in available.items():
        strategies.append(
            StrategyInfo(
                strategy_id=name,
                strategy_type=info["class"],
                is_active=False,
                config=info["default_config"],
            )
        )
    # Add registered strategies
    for sid, strat in _registered_strategies.items():
        strategies.append(
            StrategyInfo(
                strategy_id=sid,
                strategy_type=strat.name,
                is_active=strat.is_active,
                config=strat.config,
                metrics=strat.get_metrics().to_dict() if strat.trade_count > 0 else None,
            )
        )
    return StrategyListResponse(strategies=strategies)


@router.post("/register")
async def register_strategy(request: StrategyRegisterRequest) -> Dict[str, Any]:
    """Register a new strategy."""
    try:
        strategy = StrategyFactory(request.strategy_type, config=request.config or {})
        _registered_strategies[strategy.strategy_id] = strategy
        if engine is not None:
            engine.register_strategy(strategy)
        return {
            "strategy_id": strategy.strategy_id,
            "strategy_type": request.strategy_type,
            "status": "registered",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str, request: StrategyToggleRequest) -> Dict[str, Any]:
    """Toggle strategy active state."""
    if strategy_id in _registered_strategies:
        _registered_strategies[strategy_id].is_active = request.active
        return {"strategy_id": strategy_id, "active": request.active}
    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")


@router.get("/{strategy_id}/metrics")
async def get_strategy_metrics(strategy_id: str) -> Dict[str, Any]:
    """Get strategy performance metrics."""
    if strategy_id in _registered_strategies:
        metrics = _registered_strategies[strategy_id].get_metrics()
        return metrics.to_dict()
    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
