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


# ─── Dynamic universe refresh ─────────────────────────────────────────────
#
# Auto-discovery and squeeze bots get registered with a frozen universe at
# deploy time (DEFAULT_CRYPTO_UNIVERSE / DEFAULT_STOCK_UNIVERSE constants or
# the squeeze screener's then-top-10). That universe goes stale fast — the
# squeeze list especially turns over weekly. This endpoint refreshes their
# config.symbols in place from the live scanner + squeeze output and
# persists, so the next tick trades the fresh universe.
#
# Mean-reversion / macd / momentum / news_sentiment bots are NOT touched —
# those have intentionally pinned symbols (e.g. "trade BTC with MACD"); only
# the strategies whose whole point is universe-scanning get refreshed.

@router.post("/refresh-universes")
async def refresh_universes(
    crypto_top: int = 20,
    stock_top: int = 25,
    squeeze_top: int = 10,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Refresh symbol universes for auto_discovery and squeeze bots.

    Reads the live scanner (per asset class) and the squeeze screener, then
    updates each registered auto_discovery / squeeze bot's ``config.symbols``
    to the fresh top-N. Persists to disk.

    Pass ``dry_run=true`` to see what would change without applying.

    Empty scan results are a no-op — we never wipe a bot's universe to [].

    The scanner + squeeze handlers are called directly as Python coroutines
    here (not via HTTP loopback) so this endpoint doesn't deadlock the
    single-worker async server while waiting on itself.
    """
    # Local imports — pulling these at module import time would force every
    # request to load the advisor stack on app start.
    from api.routes.advisor import market_scanner, squeeze_screener

    async def _fetch_scanner(asset_class: str, top: int) -> List[str]:
        try:
            # All Query() defaults must be passed explicitly when calling
            # a FastAPI handler directly (not via HTTP).
            data = await market_scanner(
                asset_class=asset_class,
                top=top,
                min_score=0.0,
                limit_universe=50,
                symbols=None,
                direction=None,
                concurrency=5,
                crypto_days=60,
                stock_period="3mo",
                include_sp500=False,
                include_movers=True,
                # Pairlist filters — same defaults the scanner endpoint uses.
                enable_pairlist=True,
                min_quote_volume_usd=1_000_000.0,
                min_bars=30,
                pl_min_price=1.0,
                pl_max_price=0.0,
                max_spread_pct=0.08,
                min_atr_pct=0.005,
                max_atr_pct=0.15,
                blacklist=None,
            )
            results = (data.get("results") or [])[:top]
            return [row["symbol"] for row in results if row.get("symbol")]
        except Exception as exc:
            logger.warning(f"refresh: scanner({asset_class}) failed: {exc}")
            return []

    async def _fetch_squeeze(top: int) -> List[str]:
        try:
            data = await squeeze_screener(
                days_back=7,
                min_score=2.5,
                tier=None,
                extra_symbols=None,
                only_filings=False,
                min_market_cap=100_000_000,
                max_market_cap=5_000_000_000,
                max_float_shares=500_000_000,
                min_price=1.0,
                max_price=20.0,
                min_avg_daily_volume=100_000,
                sector_blocklist="utilities,reit",
                fetch_technical=True,
                concurrency=6,
                max_results=40,
            )
            cands = (data.get("candidates") or [])[:top]
            return [c["ticker"] for c in cands if c.get("ticker")]
        except Exception as exc:
            logger.warning(f"refresh: squeeze failed: {exc}")
            return []

    # Run the three scans concurrently — they hit different data sources
    # (CoinGecko / yfinance / SEC) so they parallelize cleanly.
    import asyncio
    crypto_universe, stock_universe, squeeze_universe = await asyncio.gather(
        _fetch_scanner("crypto", crypto_top),
        _fetch_scanner("stock", stock_top),
        _fetch_squeeze(squeeze_top),
    )

    updated: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for sid, strat in _registered_strategies.items():
        new_syms: List[str] | None = None
        if strat.name == "auto_discovery":
            asset_class = (strat.config or {}).get("asset_class", "crypto")
            new_syms = crypto_universe if asset_class == "crypto" else stock_universe
        elif strat.name == "squeeze":
            new_syms = squeeze_universe

        if new_syms is None:
            continue  # not a refreshable strategy type

        if not new_syms:
            skipped.append({"strategy_id": sid, "reason": "empty scan result"})
            continue

        old_syms = list((strat.config or {}).get("symbols") or [])
        if sorted(old_syms) == sorted(new_syms):
            skipped.append({"strategy_id": sid, "reason": "no change"})
            continue

        added = sorted(set(new_syms) - set(old_syms))
        removed = sorted(set(old_syms) - set(new_syms))

        if not dry_run:
            new_cfg = dict(strat.config or {})
            new_cfg["symbols"] = list(new_syms)
            strat.config = new_cfg

        updated.append({
            "strategy_id": sid,
            "strategy_type": strat.name,
            "added": added,
            "removed": removed,
            "new_size": len(new_syms),
        })

    if updated and not dry_run:
        _persist()

    return {
        "dry_run": dry_run,
        "crypto_universe_size": len(crypto_universe),
        "stock_universe_size": len(stock_universe),
        "squeeze_universe_size": len(squeeze_universe),
        "updated": updated,
        "skipped": skipped,
    }
