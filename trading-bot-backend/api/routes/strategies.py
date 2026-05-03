"""Strategy API routes."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List

from api.models import StrategyInfo, StrategyListResponse, StrategyRegisterRequest, StrategyToggleRequest
from strategies import StrategyFactory, list_strategies
from strategies.base import BaseStrategy
from bot.engine import PaperTradingEngine

logger = logging.getLogger("volta.api.strategies")

router = APIRouter()

engine: PaperTradingEngine | None = None
_registered_strategies: Dict[str, BaseStrategy] = {}

_PERSIST_PATH = Path("data") / "registered_strategies.json"


def _persist() -> None:
    """Write the current registered strategies to disk so they survive restarts."""
    try:
        _PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "strategy_id": sid,
                "strategy_type": s.name,
                "config": s.config,
                "is_active": s.is_active,
            }
            for sid, s in _registered_strategies.items()
        ]
        _PERSIST_PATH.write_text(json.dumps(payload, indent=2))
    except Exception as exc:
        logger.warning(f"Could not persist strategies: {exc}")


def restore_strategies(eng: PaperTradingEngine) -> int:
    """Re-instantiate registered strategies from the persistence file.

    Called once at app startup. Returns the number of strategies restored.
    """
    if not _PERSIST_PATH.exists():
        return 0
    try:
        data = json.loads(_PERSIST_PATH.read_text())
    except Exception as exc:
        logger.warning(f"Could not read persisted strategies: {exc}")
        return 0

    count = 0
    for entry in data:
        try:
            sid = entry["strategy_id"]
            strategy = StrategyFactory(
                entry["strategy_type"],
                strategy_id=sid,
                config=entry.get("config") or {},
            )
            strategy.is_active = bool(entry.get("is_active", True))
            _registered_strategies[sid] = strategy
            eng.register_strategy(strategy)
            count += 1
        except Exception as exc:
            logger.warning(f"Failed to restore strategy {entry.get('strategy_id')}: {exc}")
    if count:
        logger.info(f"Restored {count} strategies from {_PERSIST_PATH}")
    return count


def set_engine(e: PaperTradingEngine) -> None:
    global engine
    engine = e


@router.get("/")
async def list_all_strategies() -> StrategyListResponse:
    """List user-registered strategies (the bots the user has created).

    Built-in strategy templates are advertised via /strategies/available
    and should not appear in the active-bots list.
    """
    strategies = []
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


@router.get("/available")
async def list_available_strategy_types() -> StrategyListResponse:
    """List built-in strategy templates that can be registered."""
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
    return StrategyListResponse(strategies=strategies)


@router.post("/register")
async def register_strategy(request: StrategyRegisterRequest) -> Dict[str, Any]:
    """Register a new strategy. Accepts snake_case or PascalCase type names."""
    try:
        from strategies import _normalize_strategy_type
        resolved_type = _normalize_strategy_type(request.strategy_type)
        sid = f"{resolved_type}_{int(time.time() * 1000)}"
        strategy = StrategyFactory(resolved_type, strategy_id=sid, config=request.config or {})
        _registered_strategies[strategy.strategy_id] = strategy
        if engine is not None:
            engine.register_strategy(strategy)
        _persist()
        return {
            "strategy_id": strategy.strategy_id,
            "strategy_type": resolved_type,
            "status": "registered",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str, request: StrategyToggleRequest) -> Dict[str, Any]:
    """Toggle strategy active state."""
    if strategy_id in _registered_strategies:
        _registered_strategies[strategy_id].is_active = request.active
        _persist()
        return {"strategy_id": strategy_id, "active": request.active}
    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")


@router.get("/{strategy_id}/metrics")
async def get_strategy_metrics(strategy_id: str) -> Dict[str, Any]:
    """Get strategy performance metrics."""
    if strategy_id in _registered_strategies:
        metrics = _registered_strategies[strategy_id].get_metrics()
        return metrics.to_dict()
    raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
