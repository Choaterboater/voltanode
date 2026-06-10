"""Strategy API routes."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict, List

from api.models import StrategyInfo, StrategyListResponse, StrategyRegisterRequest, StrategyToggleRequest
from strategies import STRATEGY_REGISTRY, StrategyFactory, list_strategies
from strategies.base import BaseStrategy
from bot.engine import PaperTradingEngine
from bot.orders import Order
from bot.config import OrderSide
from bot.portfolio import symbols_equivalent
from safety.limits import compute_portfolio_equity

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
                # Supervisor bench flag (entries-only veto; exits keep flowing).
                "entries_disabled": bool(getattr(s, "entries_disabled", False)),
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
            strategy.entries_disabled = bool(entry.get("entries_disabled", False))
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
        strategy = _registered_strategies[strategy_id]
        strategy.is_active = request.active
        if request.active:
            # An explicit operator re-enable also clears a supervisor bench —
            # the rebench watermark in learning/supervisor.py then demands
            # fresh round trips before it may bench again.
            strategy.entries_disabled = False
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
                limit_universe=30,
                symbols=None,
                direction=None,
                concurrency=10,
                crypto_days=30,
                stock_period="3mo",
                include_sp500=False,
                include_movers=True,
                fast=True,
                nocache=True,
                # Pairlist filters — same defaults the scanner endpoint uses.
                enable_pairlist=True,
                min_quote_volume_usd=1_000_000.0,
                min_bars=30,
                # Asset-class-aware: 0 for crypto (keep DOGE/SHIB/TRX),
                # $1 for stocks (drop penny stocks).
                pl_min_price=0.0 if asset_class == "crypto" else 1.0,
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
                fetch_technical=False,
                concurrency=8,
                max_results=40,
                max_candidates=60,
                nocache=True,
            )
            # squeeze_screener returns rows under "results", not "candidates",
            # keyed by "ticker". The older "candidates" key never existed —
            # _fetch_squeeze was silently returning [] every refresh, leaving
            # the squeeze bot stuck on its deploy-day hardcoded universe for
            # weeks while the screener was happily surfacing 20-30 fresh
            # setups per day.
            rows = (data.get("results") or [])[:top]
            return [r["ticker"] for r in rows if r.get("ticker")]
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


# ─── Capital deployment allocator ─────────────────────────────────────────

def _cash_balance(portfolio: Any, broker_balances: Dict[str, float] | None = None) -> float:
    if broker_balances:
        cash = sum(
            float(v)
            for k, v in broker_balances.items()
            if str(k).upper() in {"USD", "USDT", "CASH"}
        )
        if cash > 0:
            return cash
    balances = portfolio.get_all_balances()
    return sum(
        float(v)
        for k, v in (balances or {}).items()
        if str(k).upper() in {"USD", "USDT", "CASH"}
    )


def _mark_price(symbol: str) -> float:
    prices = getattr(engine, "_current_prices", {}) if engine is not None else {}
    try:
        from bot.portfolio import lookup_price
        price = lookup_price(prices or {}, symbol)
        if price and price > 0:
            return float(price)
    except Exception:
        pass
    broker = getattr(engine, "broker", None) if engine is not None else None
    if broker is not None and getattr(broker, "is_connected", lambda: False)():
        try:
            price = float(broker.get_price(symbol) or 0)
            if price > 0:
                return price
        except Exception:
            pass
    return 0.0


def _exposure_notional(portfolio: Any, broker_positions: List[Dict[str, Any]] | None = None) -> float:
    if broker_positions:
        exposure = 0.0
        for pos in broker_positions:
            symbol = str(pos.get("symbol", ""))
            size = abs(float(pos.get("qty", pos.get("size", 0)) or 0))
            price = _mark_price(symbol) or float(pos.get("current_price", pos.get("entry_price", 0)) or 0)
            exposure += size * price
        if exposure > 0:
            return exposure
    return sum(
        abs(float(getattr(p, "market_value", 0) or 0))
        for p in portfolio.get_all_positions()
        if getattr(p, "status", "") == "open"
    )


def _has_real_position(
    portfolio: Any,
    symbol: str,
    broker_positions: List[Dict[str, Any]] | None = None,
) -> bool:
    for pos in broker_positions or []:
        psym = str(pos.get("symbol", ""))
        if not symbols_equivalent(psym, symbol):
            continue
        size = abs(float(pos.get("qty", pos.get("size", 0)) or 0))
        if size >= 1e-6:
            return True
    for pos in portfolio.get_all_positions():
        if getattr(pos, "status", "") != "open":
            continue
        if not symbols_equivalent(getattr(pos, "symbol", ""), symbol):
            continue
        size = float(getattr(pos, "size", 0) or 0)
        market_value = abs(float(getattr(pos, "market_value", 0) or 0))
        if size >= 1e-6 and market_value >= 1.0:
            return True
    return False


_SHARE_CLASS_GROUPS = (
    frozenset({"GOOG", "GOOGL"}),
    frozenset({"BRK.A", "BRK.B", "BRKA", "BRKB"}),
)


def _share_class_root(symbol: str) -> str:
    """Normalize share-class variants to a common root for dedupe."""
    sym = symbol.upper()
    for group in _SHARE_CLASS_GROUPS:
        if sym in group:
            return min(group)
    return sym


def _held_share_class_roots(
    portfolio: Any,
    broker_positions: List[Dict[str, Any]] | None,
) -> set[str]:
    roots: set[str] = set()
    for pos in broker_positions or []:
        sym = str(pos.get("symbol", "")).upper()
        size = abs(float(pos.get("qty", pos.get("size", 0)) or 0))
        if sym and size >= 1e-6:
            roots.add(_share_class_root(sym))
    for pos in portfolio.get_all_positions():
        if getattr(pos, "status", "") != "open":
            continue
        sym = str(getattr(pos, "symbol", "")).upper()
        size = float(getattr(pos, "size", 0) or 0)
        if sym and size >= 1e-6:
            roots.add(_share_class_root(sym))
    return roots


def _round_stop_price(price: float) -> float:
    ax = abs(price)
    if ax < 1e-4:
        return round(price, 10)
    if ax < 0.01:
        return round(price, 8)
    if ax < 1:
        return round(price, 6)
    return round(price, 4)


def _attach_allocator_stops(
    pos: Any,
    *,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> None:
    """Set downside/upside targets on a freshly opened allocator position."""
    entry = float(getattr(pos, "entry_price", 0) or 0)
    if entry <= 0:
        return
    is_long = getattr(getattr(pos, "side", None), "value", str(getattr(pos, "side", "long"))).lower() == "long"
    if is_long:
        if not getattr(pos, "stop_loss", None):
            pos.stop_loss = _round_stop_price(entry * (1.0 - stop_loss_pct))
        if not getattr(pos, "take_profit", None):
            pos.take_profit = _round_stop_price(entry * (1.0 + take_profit_pct))
    else:
        if not getattr(pos, "stop_loss", None):
            pos.stop_loss = _round_stop_price(entry * (1.0 + stop_loss_pct))
        if not getattr(pos, "take_profit", None):
            pos.take_profit = _round_stop_price(entry * (1.0 - take_profit_pct))


def _open_position_count(
    portfolio: Any,
    broker_positions: List[Dict[str, Any]] | None,
) -> int:
    seen: set[str] = set()
    for pos in broker_positions or []:
        sym = str(pos.get("symbol", "")).upper()
        size = abs(float(pos.get("qty", pos.get("size", 0)) or 0))
        if sym and size >= 1e-6:
            seen.add(sym)
    for pos in portfolio.get_all_positions():
        if getattr(pos, "status", "") != "open":
            continue
        sym = str(getattr(pos, "symbol", "")).upper()
        size = float(getattr(pos, "size", 0) or 0)
        mv = abs(float(getattr(pos, "market_value", 0) or 0))
        if sym and size >= 1e-6 and mv >= 1.0:
            seen.add(sym)
    return len(seen)


def _merge_deploy_candidates(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge scanner/squeeze/long-term candidates into one ranked list."""
    merged: Dict[str, Dict[str, Any]] = {}
    for group in groups:
        source = str(group.get("source", "unknown"))
        weight = float(group.get("weight", 1.0))
        for raw in group.get("rows") or []:
            symbol = str(raw.get("symbol", raw.get("ticker", ""))).upper()
            price = float(raw.get("current_price", raw.get("price", 0)) or 0)
            score = float(raw.get("score", 0) or 0)
            if not symbol or price <= 0 or score <= 0:
                continue
            item = merged.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "current_price": price,
                    "score": 0.0,
                    "sources": [],
                    "source_scores": {},
                },
            )
            item["current_price"] = item["current_price"] or price
            item["score"] += score * weight
            item["sources"].append(source)
            item["source_scores"][source] = round(score, 2)

    ranked = list(merged.values())
    for item in ranked:
        # Reward multi-source confirmation without letting duplicates dominate.
        confirmation_bonus = min(15.0, 5.0 * max(0, len(set(item["sources"])) - 1))
        item["score"] = round(item["score"] + confirmation_bonus, 2)
        item["sources"] = sorted(set(item["sources"]))
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked


async def _deployment_candidates(
    asset: str,
    max_positions: int,
    score_floor: float,
    nocache: bool,
) -> Dict[str, Any]:
    """Build allocator candidates from multiple independent opportunity sources."""
    from api.routes.advisor import long_term_screener, market_scanner, squeeze_screener

    scanner_fast = asset == "crypto"

    async def _scanner() -> Dict[str, Any]:
        return await market_scanner(
            asset_class=asset,
            top=max(30 if asset == "stock" else 20, max_positions * 8),
            min_score=0.0,
            limit_universe=30 if asset == "crypto" else 80,
            symbols=None,
            direction="long",
            concurrency=12 if asset == "crypto" else 10,
            crypto_days=30,
            stock_period="3mo",
            include_sp500=False,
            include_movers=True,
            fast=scanner_fast,
            nocache=nocache,
            enable_pairlist=True,
            min_quote_volume_usd=1_000_000.0,
            min_bars=30,
            pl_min_price=0.0 if asset == "crypto" else 1.0,
            pl_max_price=0.0,
            max_spread_pct=0.08,
            min_atr_pct=0.005,
            max_atr_pct=0.15,
            blacklist="NEAR,TRX" if asset == "crypto" else None,
        )

    async def _long_term() -> Dict[str, Any]:
        return await long_term_screener(
            asset_class=asset,
            top=max(20, max_positions * 6),
            min_score=0.0,
            limit_universe=40 if asset == "stock" else 25,
            symbols=None,
            concurrency=6,
            stock_period="2y",
            crypto_days=730,
            weight_fundamentals=0.35 if asset == "stock" else 0.10,
            weight_trend=0.45,
            weight_low_volatility=0.20 if asset == "stock" else 0.45,
            sector=None,
            max_price=None,
            min_price=1.0 if asset == "stock" else None,
            nocache=nocache,
        )

    tasks = [_scanner(), _long_term()]
    if asset == "stock":
        tasks.append(
            squeeze_screener(
                days_back=7,
                min_score=0.0,
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
                fetch_technical=False,
                concurrency=8,
                max_results=40,
                max_candidates=80,
                nocache=nocache,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    groups: List[Dict[str, Any]] = []
    source_meta: Dict[str, Any] = {}

    scanner = results[0]
    if isinstance(scanner, dict):
        groups.append({"source": "scanner", "weight": 1.0, "rows": scanner.get("results", [])})
        source_meta["scanner"] = {"elapsed_ms": scanner.get("elapsed_ms"), "count": len(scanner.get("results", []) or [])}
    else:
        source_meta["scanner"] = {"error": str(scanner)[:200]}

    long_term = results[1]
    if isinstance(long_term, dict):
        groups.append({"source": "long_term", "weight": 0.45, "rows": long_term.get("results", [])})
        source_meta["long_term"] = {"elapsed_ms": long_term.get("elapsed_ms"), "count": len(long_term.get("results", []) or [])}
    else:
        source_meta["long_term"] = {"error": str(long_term)[:200]}

    if asset == "stock" and len(results) > 2:
        squeeze = results[2]
        if isinstance(squeeze, dict):
            rows = []
            for row in squeeze.get("results", []) or []:
                rows.append({
                    "symbol": row.get("ticker"),
                    "score": float(row.get("score", 0) or 0) * 10.0,
                    "current_price": row.get("current_price", row.get("price", 0)),
                })
            groups.append({"source": "squeeze", "weight": 0.75, "rows": rows})
            source_meta["squeeze"] = {"elapsed_ms": squeeze.get("elapsed_ms"), "count": len(rows)}
        else:
            source_meta["squeeze"] = {"error": str(squeeze)[:200]}

    candidates = [
        c for c in _merge_deploy_candidates(groups)
        if float(c.get("score", 0) or 0) >= score_floor
    ]
    return {"candidates": candidates, "sources": source_meta}


async def execute_capital_deploy(
    *,
    target_exposure_pct: float | None = None,
    max_cash_pct: float | None = None,
    min_cash_reserve_pct: float | None = None,
    position_pct: float | None = None,
    max_new_positions: int | None = None,
    asset_class: str | None = None,
    min_score: float | None = None,
    dry_run: bool = False,
    nocache: bool = False,
) -> Dict[str, Any]:
    """Deploy idle capital into ranked scanner candidates (shared by API + scheduler)."""
    if engine is None:
        raise RuntimeError("Engine not initialized")

    config = getattr(engine, "config", None)
    alloc_cfg = getattr(config, "capital_deployment", None)
    target = float(target_exposure_pct if target_exposure_pct is not None else getattr(alloc_cfg, "target_exposure_pct", 95.0))
    cash_ceiling = float(max_cash_pct if max_cash_pct is not None else getattr(alloc_cfg, "max_cash_pct", 20.0))
    min_floor = float(min_cash_reserve_pct if min_cash_reserve_pct is not None else getattr(alloc_cfg, "min_cash_reserve_pct", 5.0))
    per_position = float(position_pct if position_pct is not None else getattr(alloc_cfg, "position_pct", 5.0))
    max_positions = int(max_new_positions if max_new_positions is not None else getattr(alloc_cfg, "max_new_positions_per_cycle", 6))
    score_floor = float(min_score if min_score is not None else getattr(alloc_cfg, "min_score", 45.0))
    min_sources = int(getattr(alloc_cfg, "min_source_count", 2) or 2)
    max_open = int(getattr(alloc_cfg, "max_open_positions", 28) or 28)
    stop_pct = float(getattr(alloc_cfg, "initial_stop_loss_pct", 0.07) or 0.07)
    tp_pct = float(getattr(alloc_cfg, "initial_take_profit_pct", 0.20) or 0.20)
    asset = str(asset_class or getattr(alloc_cfg, "asset_class", "crypto")).lower()
    min_notional = float(getattr(alloc_cfg, "min_order_notional", 25.0))

    if asset not in {"crypto", "stock"}:
        raise ValueError("asset_class must be 'crypto' or 'stock'")
    if max_positions <= 0:
        raise ValueError("max_new_positions must be positive")
    if not (0 < per_position <= 20):
        raise ValueError("position_pct must be between 0 and 20")
    if not (0 <= min_floor < 100):
        raise ValueError("min_cash_reserve_pct must be between 0 and 100")
    if not (0 <= cash_ceiling < 100):
        raise ValueError("max_cash_pct must be between 0 and 100")
    if min_floor > cash_ceiling:
        raise ValueError("min_cash_reserve_pct cannot exceed max_cash_pct")
    if not (0 < target <= 300):
        raise ValueError("target_exposure_pct must be between 0 and 300")

    portfolio = engine.get_portfolio("default")
    broker_balances: Dict[str, float] | None = None
    broker_positions: List[Dict[str, Any]] = []
    if getattr(engine, "live_mode", False):
        try:
            broker_balances = engine.get_broker_balance()
        except Exception:
            broker_balances = None
        try:
            broker_positions = engine.get_broker_positions()
        except Exception:
            broker_positions = []

    equity = compute_portfolio_equity(portfolio, broker_balances)
    cash = _cash_balance(portfolio, broker_balances)
    exposure = _exposure_notional(portfolio, broker_positions)
    current_exposure_pct = (exposure / equity) * 100.0 if equity > 0 else 0.0
    current_cash_pct = (cash / equity) * 100.0 if equity > 0 else 0.0
    max_deployed_by_floor = equity * max(0.0, (100.0 - min_floor) / 100.0)
    target_deployed = equity * (target / 100.0)
    deploy_room = max(0.0, min(target_deployed, max_deployed_by_floor) - exposure)
    cash_room = max(0.0, cash - equity * (min_floor / 100.0))
    budget = min(deploy_room, cash_room)

    if budget < min_notional:
        return {
            "dry_run": dry_run,
            "deployed": [],
            "skipped": [{"reason": "no_budget", "budget": round(budget, 2)}],
            "equity": round(equity, 2),
            "cash": round(cash, 2),
            "exposure": round(exposure, 2),
            "exposure_pct": round(current_exposure_pct, 2),
            "cash_pct": round(current_cash_pct, 2),
            "target_exposure_pct": target,
            "max_cash_pct": cash_ceiling,
            "min_cash_reserve_pct": min_floor,
            "available_budget": round(budget, 2),
        }

    candidate_payload = await _deployment_candidates(asset, max_positions, score_floor, nocache)
    candidates = candidate_payload["candidates"]
    held_roots = _held_share_class_roots(portfolio, broker_positions)
    open_count = _open_position_count(portfolio, broker_positions)

    deployed: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    remaining = budget
    per_position_notional = equity * (per_position / 100.0)

    for row in candidates:
        if len(deployed) >= max_positions or remaining < min_notional:
            break
        if open_count + len(deployed) >= max_open:
            skipped.append({"reason": "max_open_positions", "limit": max_open})
            break
        symbol = str(row.get("symbol", "")).upper()
        sources = row.get("sources") or []
        if len(set(sources)) < min_sources:
            skipped.append({"symbol": symbol, "reason": "insufficient_sources", "sources": sources})
            continue
        if _share_class_root(symbol) in held_roots:
            skipped.append({"symbol": symbol, "reason": "share_class_held"})
            continue
        price = float(row.get("current_price") or 0)
        if not symbol or price <= 0:
            skipped.append({"symbol": symbol, "reason": "missing_price"})
            continue
        if _has_real_position(portfolio, symbol, broker_positions):
            skipped.append({"symbol": symbol, "reason": "already_held"})
            continue
        notional = min(per_position_notional, remaining)
        if notional < min_notional:
            skipped.append({"symbol": symbol, "reason": "below_min_notional", "notional": round(notional, 2)})
            continue

        qty = notional / price
        order = Order.market(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=qty,
            account_id="default",
            strategy_id="capital_allocator",
        )
        item: Dict[str, Any] = {
            "symbol": symbol,
            "score": row.get("score"),
            "sources": row.get("sources", []),
            "source_scores": row.get("source_scores", {}),
            "price": price,
            "notional": round(notional, 2),
            "quantity": qty,
        }
        if not dry_run:
            fill = engine.execute_order(order, current_price=price)
            status = order.status.value if hasattr(order.status, "value") else str(order.status)
            filled_qty = float(getattr(fill, "filled_qty", 0) or 0) if fill else 0.0
            if status in {"rejected", "canceled"}:
                skipped.append({
                    "symbol": symbol,
                    "reason": "broker_rejected",
                    "status": status,
                    "score": row.get("score"),
                })
                continue
            item.update({
                "order_id": order.id,
                "status": status,
                "filled_qty": filled_qty,
            })
            if filled_qty > 0:
                pos = portfolio.get_position(symbol)
                if pos is not None:
                    _attach_allocator_stops(pos, stop_loss_pct=stop_pct, take_profit_pct=tp_pct)
        deployed.append(item)
        held_roots.add(_share_class_root(symbol))
        remaining -= notional

    return {
        "dry_run": dry_run,
        "asset_class": asset,
        "deployed": deployed,
        "skipped": skipped[:20],
        "sources": candidate_payload.get("sources", {}),
        "candidate_count": len(candidates),
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "exposure": round(exposure, 2),
        "exposure_pct": round(current_exposure_pct, 2),
        "cash_pct": round(current_cash_pct, 2),
        "target_exposure_pct": target,
        "max_cash_pct": cash_ceiling,
        "min_cash_reserve_pct": min_floor,
        "available_budget": round(budget, 2),
        "remaining_budget": round(max(0.0, remaining), 2),
    }


@router.post("/capital-deploy")
async def capital_deploy(
    target_exposure_pct: float | None = None,
    max_cash_pct: float | None = None,
    min_cash_reserve_pct: float | None = None,
    position_pct: float | None = None,
    max_new_positions: int | None = None,
    asset_class: str | None = None,
    min_score: float | None = None,
    dry_run: bool = False,
    nocache: bool = False,
) -> Dict[str, Any]:
    """Deploy idle paper capital into top scanner candidates up to a target exposure.

    ``max_cash_pct`` is a soft ceiling — deploy when cash is above it.
    ``min_cash_reserve_pct`` is the hard floor — may deploy below the ceiling
    down to this level when candidates and target exposure allow.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    try:
        return await execute_capital_deploy(
            target_exposure_pct=target_exposure_pct,
            max_cash_pct=max_cash_pct,
            min_cash_reserve_pct=min_cash_reserve_pct,
            position_pct=position_pct,
            max_new_positions=max_new_positions,
            asset_class=asset_class,
            min_score=min_score,
            dry_run=dry_run,
            nocache=nocache,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── Hyperopt ──────────────────────────────────────────────────────────────
#
# Strategies ship with textbook defaults (RSI=14, MACD=12/26/9, ...) frozen
# at deploy day. These endpoints run Bayesian parameter search over the
# existing backtest path and let the operator apply the winning config to a
# live bot. See ``hyperopt/`` for the engine and ``strategies/*.py`` for
# per-strategy ``param_space()``.

def _first_symbol(strat: BaseStrategy) -> str | None:
    """Pick a representative symbol for a single-symbol hyperopt run."""
    syms = strat.configured_symbols()
    if syms:
        return syms[0]
    cfg = strat.config or {}
    for key in ("symbol", "default_symbol"):
        v = cfg.get(key)
        if v:
            return str(v)
    return None


@router.get("/{strategy_id}/hyperopt/space")
async def get_param_space(strategy_id: str) -> Dict[str, Any]:
    """Return the strategy's tunable parameter ranges. Lets the UI render
    sliders / preview a study before kicking one off."""
    strat = _registered_strategies.get(strategy_id)
    if strat is None:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
    cls = STRATEGY_REGISTRY.get(strat.name)
    space = cls.param_space() if cls else {}
    return {
        "strategy_id": strategy_id,
        "strategy_type": strat.name,
        "supports_hyperopt": bool(space),
        "param_space": space,
        "current_config": {k: strat.config.get(k) for k in space.keys()},
    }


@router.post("/{strategy_id}/hyperopt")
async def hyperopt_strategy(
    strategy_id: str,
    n_trials: int = 50,
    objective: str = "sharpe",
    symbol: str | None = None,
    asset_class: str = "crypto",
    timeframe: str = "1h",
    timeout_sec: int | None = 600,
) -> Dict[str, Any]:
    """Run a Bayesian hyperopt study against the strategy's backtest path.

    Does NOT mutate the strategy. The winning params are stashed in
    ``data/hyperopt_history.jsonl``; call ``POST /apply-hyperopt`` to merge
    them into the live config.

    The study runs inside ``asyncio.to_thread`` so it doesn't block the
    single-worker async server while the backtest loop chews through bars.
    """
    strat = _registered_strategies.get(strategy_id)
    if strat is None:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
    cls = STRATEGY_REGISTRY.get(strat.name)
    if cls is None or not cls.param_space():
        raise HTTPException(
            status_code=400,
            detail=f"{strat.name} does not support hyperopt (no param_space)",
        )

    sym = symbol or _first_symbol(strat)
    if not sym:
        raise HTTPException(
            status_code=400,
            detail="No symbol provided and strategy has no configured symbol",
        )

    # Pull modules inside the handler so import-time failures (e.g. optuna
    # missing) don't take the whole API down on startup.
    from hyperopt import append_history, run_hyperopt
    from hyperopt.engine import _fetch_ohlcv

    try:
        df = await _fetch_ohlcv(sym, asset_class, timeframe)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OHLCV fetch failed: {exc}")

    fixed_config = {"symbols": [sym]}

    def _run():
        return run_hyperopt(
            strategy_type=strat.name,
            symbol=sym,
            asset_class=asset_class,
            timeframe=timeframe,
            n_trials=n_trials,
            objective=objective,
            fixed_config=fixed_config,
            timeout_sec=timeout_sec,
            df=df,
        )

    try:
        result = await asyncio.to_thread(_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Hyperopt failed: {exc}")

    append_history(result, strategy_id=strategy_id)

    return {
        "strategy_id": strategy_id,
        "strategy_type": result.strategy_type,
        "symbol": result.symbol,
        "objective": result.objective,
        "n_trials": result.n_trials,
        "valid_trials": len(result.trial_history),
        "best_params": result.best_params,
        "best_value": result.best_value,
        "baseline_value": result.baseline_value,
        "improvement_pct": result.improvement_pct,
        "duration_sec": result.duration_sec,
    }


@router.post("/{strategy_id}/apply-hyperopt")
async def apply_hyperopt(strategy_id: str, request: Request, force: bool = False) -> Dict[str, Any]:
    """Merge the most-recent hyperopt best_params into the strategy's config
    and persist. The bot picks up the new params on its next tick — no
    restart needed (config is read every ``on_tick``).

    When ``config.promotion_gate.enabled`` (default ON since 2026-06-09), the
    candidate params must first clear a CPCV + Deflated-Sharpe-Ratio gate
    (positive after deflating by the number of hyperopt trials) or the apply is
    blocked (422). ``force=true`` overrides the gate (logged for audit)."""
    strat = _registered_strategies.get(strategy_id)
    if strat is None:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

    from hyperopt import latest_for_strategy

    row = latest_for_strategy(strategy_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No hyperopt history for this strategy; run POST /hyperopt first",
        )
    best_params = row.get("best_params") or {}
    if not best_params:
        raise HTTPException(
            status_code=400,
            detail="Most-recent hyperopt run produced no valid params (all trials rejected)",
        )

    # ── CPCV + DSR promotion gate (default ON; force=true overrides) ─────
    # Read the LIVE config (loaded from config.yaml into app.state.config); a
    # bare BotConfig() would ignore the YAML and leave the gate un-enableable.
    gate_payload: Dict[str, Any] | None = None
    from bot.config import BotConfig
    cfg = getattr(request.app.state, "config", None) or BotConfig()
    gate_dict = cfg.promotion_gate.model_dump() if getattr(cfg, "promotion_gate", None) else {}
    if gate_dict.get("enabled") and not force:
        try:
            from backtest.validation import PromotionGateConfig, evaluate_promotion
            from backtest.engine import BacktestConfig
            from hyperopt.engine import _fetch_ohlcv

            sym = row.get("symbol") or _first_symbol(strat)
            if not sym:
                raise HTTPException(
                    status_code=400,
                    detail="Promotion gate enabled but strategy has no symbol to validate on",
                )
            asset_class = row.get("asset_class", "crypto")
            timeframe = row.get("timeframe", "1h")
            df = await _fetch_ohlcv(sym, asset_class, timeframe)
            bt_config = BacktestConfig(
                initial_balance={"USDT": 100_000.0},
                fee_rate=cfg.risk.fee_rate,
                crypto_fee_rate=getattr(cfg.risk, "crypto_fee_rate", 0.0025),
                slippage_bps=cfg.risk.slippage_bps,
                allow_short=False,
            )
            gate_cfg = PromotionGateConfig.from_mapping(gate_dict)
            # Carry asset_class so the gate's backtest charges the CRYPTO taker
            # fee (not the equity rate) for crypto bots — best_params hold only
            # EMA knobs and single-symbol configs don't default asset_class, so
            # without this the gate under-prices fees, inflates DSR, and passes
            # curve-fit configs it should reject (review 2026-06-09).
            merged_candidate = {**(strat.config or {}), **best_params, "asset_class": asset_class}
            trial_sharpes = None
            if row.get("objective") == "sharpe":
                trial_sharpes = [
                    t.get("value") for t in (row.get("trial_history") or [])
                    if isinstance(t, dict) and t.get("value") is not None
                ]
            gate = await asyncio.to_thread(
                evaluate_promotion,
                strat.name, merged_candidate, df, bt_config,
                int(row.get("n_trials", 50)), gate_cfg, trial_sharpes,
            )
            gate_payload = gate.to_dict()
            if not gate.passed:
                raise HTTPException(
                    status_code=422,
                    detail={"message": "Config failed CPCV/DSR promotion gate", "gate": gate_payload},
                )
        except HTTPException:
            raise
        except (RuntimeError, ValueError) as exc:
            # Transient validation-data fetch/availability failure — fail closed
            # but with a retryable status, not a generic 500 (the gate is
            # default-on now, so this path is reached on every apply).
            raise HTTPException(
                status_code=503,
                detail=f"Promotion gate could not fetch validation data ({exc}); retry or apply with force=true",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Promotion gate evaluation failed: {exc}")

    old = {k: strat.config.get(k) for k in best_params.keys()}
    new_cfg = dict(strat.config or {})
    new_cfg.update(best_params)
    strat.config = new_cfg
    _persist()

    return {
        "strategy_id": strategy_id,
        "applied_params": best_params,
        "previous_params": old,
        "objective": row.get("objective"),
        "best_value": row.get("best_value"),
        "baseline_value": row.get("baseline_value"),
        "gate": gate_payload,
        "forced": bool(force and gate_dict.get("enabled")),
    }


@router.get("/{strategy_id}/hyperopt/history")
async def hyperopt_history(strategy_id: str, limit: int = 10) -> Dict[str, Any]:
    """Return the most-recent hyperopt rows for this strategy, newest first."""
    from hyperopt import read_all
    rows = [r for r in read_all() if r.get("strategy_id") == strategy_id]
    rows.reverse()
    return {"strategy_id": strategy_id, "count": len(rows), "rows": rows[:limit]}
