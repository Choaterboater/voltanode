"""Bayesian hyperopt engine for trading strategies.

Wraps Optuna over the existing ``BacktestRunner``. The whole point of this
module is: vary ``strategy.config`` via ``param_space()``, run the same
backtest path the rest of the system already uses, and return the best
config. No new execution logic — we only twist the dials.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import optuna
import pandas as pd
from optuna.pruners import MedianPruner
from optuna.samplers import TPESampler

from backtest.engine import BacktestConfig
from hyperopt.objective import baseline_value, make_objective
from strategies import STRATEGY_REGISTRY, _normalize_strategy_type

logger = logging.getLogger("volta.hyperopt")

# Optuna spams INFO with one log per trial. We're running 50–200 trials at a
# time — surface only warnings unless the operator turns it back up.
optuna.logging.set_verbosity(optuna.logging.WARNING)


@dataclass
class HyperoptResult:
    """Outcome of a single hyperopt study."""
    strategy_type: str
    symbol: str
    objective: str
    n_trials: int
    best_params: Dict[str, Any]
    best_value: float
    baseline_value: float
    duration_sec: float
    trial_history: List[Dict[str, Any]] = field(default_factory=list)
    completed_at: str = ""  # ISO-8601, set by run_hyperopt

    @property
    def improvement_pct(self) -> float:
        """Best vs. baseline as a percent. Handles baseline<=0 gracefully."""
        if not math.isfinite(self.baseline_value):
            return float("inf") if self.best_value > 0 else 0.0
        if abs(self.baseline_value) < 1e-9:
            return float("inf") if self.best_value > 0 else 0.0
        return (self.best_value - self.baseline_value) / abs(self.baseline_value) * 100.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["improvement_pct"] = self.improvement_pct
        return d


async def _fetch_ohlcv(
    symbol: str,
    asset_class: str,
    timeframe: str,
) -> pd.DataFrame:
    """Fetch historical OHLCV once for the study. Mirrors the loader the
    /backtest/run route uses (api/routes/backtest.py)."""
    from bot.config import AssetClass, BotConfig
    from data.cache import DataCache
    from data.fetcher import MarketData

    # MarketData.get_ohlcv takes the AssetClass enum, not a string. Coerce
    # so callers can pass "crypto"/"stock"/"forex" verbatim.
    if isinstance(asset_class, AssetClass):
        ac = asset_class
    else:
        try:
            ac = AssetClass(str(asset_class).lower())
        except ValueError as exc:
            raise ValueError(
                f"Unsupported asset_class {asset_class!r}; "
                f"expected one of {[a.value for a in AssetClass]}"
            ) from exc

    cache = DataCache()
    market_data = MarketData(cache=cache, config=BotConfig())
    df = await market_data.get_ohlcv(symbol, ac, timeframe)
    if df is None or df.empty:
        raise RuntimeError(f"No OHLCV returned for {symbol} ({ac.value}, {timeframe})")
    df.attrs["symbol"] = symbol
    return df


def run_hyperopt(
    strategy_type: str,
    symbol: str,
    asset_class: str,
    timeframe: str = "1h",
    n_trials: int = 50,
    objective: str = "sharpe",
    fixed_config: Dict[str, Any] | None = None,
    initial_balance: float = 100_000.0,
    quote_asset: str = "USDT",
    fee_rate: float = 0.001,
    slippage_bps: float = 5.0,
    allow_short: bool = True,
    timeout_sec: Optional[int] = None,
    seed: int = 42,
    df: Optional[pd.DataFrame] = None,
) -> HyperoptResult:
    """Run a Bayesian hyperopt study against the existing backtest path.

    Args:
        strategy_type: Registry key (e.g. "mean_reversion", "macd", "momentum").
        symbol: Asset symbol the backtest runs on (single-symbol studies only).
        asset_class: "crypto" | "stock" | "forex" — fed to ``MarketData.get_ohlcv``.
        timeframe: Bar interval (e.g. "1h", "1d").
        n_trials: Number of Optuna trials.
        objective: "sharpe" | "sortino" | "profit_factor" | "total_return" | "calmar".
        fixed_config: Non-tuned strategy config keys merged into every trial
            (e.g. symbol-scoping like ``{"symbols": ["BTC/USD"]}``).
        initial_balance: Starting cash in quote_asset.
        quote_asset: Currency code for initial_balance.
        fee_rate, slippage_bps, allow_short: Backtest execution config.
        timeout_sec: Optional wall-clock cap on the whole study.
        seed: TPE sampler seed for reproducibility.
        df: Pre-fetched OHLCV. If None, the function fetches it via
            ``MarketData.get_ohlcv``. Tests pass a pre-built DataFrame.

    Returns:
        ``HyperoptResult`` with best params, best value, baseline value,
        and per-trial history.
    """
    from datetime import datetime, timezone

    resolved = _normalize_strategy_type(strategy_type)
    if resolved not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy type: {strategy_type}")
    if not STRATEGY_REGISTRY[resolved].param_space():
        raise ValueError(f"Strategy {resolved!r} has no param_space — opts out of hyperopt")

    if df is None:
        try:
            df = asyncio.run(_fetch_ohlcv(symbol, asset_class, timeframe))
        except RuntimeError as exc:
            # Already inside an event loop (e.g. called from FastAPI without
            # asyncio.to_thread). The caller is responsible for fetching df
            # and passing it in; signal the misuse loudly.
            if "asyncio.run() cannot be called" in str(exc):
                raise RuntimeError(
                    "run_hyperopt cannot fetch OHLCV from inside a running event loop. "
                    "Pass df= explicitly or call via asyncio.to_thread."
                ) from exc
            raise

    bt_config = BacktestConfig(
        initial_balance={quote_asset: float(initial_balance)},
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        allow_short=allow_short,
    )

    base_val = baseline_value(resolved, df, bt_config, objective, fixed_config)
    obj_fn = make_objective(resolved, df, bt_config, objective, fixed_config)

    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=seed),
        pruner=MedianPruner(n_warmup_steps=5),
    )

    start = time.time()
    study.optimize(obj_fn, n_trials=n_trials, timeout=timeout_sec, gc_after_trial=True)
    duration = time.time() - start

    history: List[Dict[str, Any]] = []
    for t in study.trials:
        if t.state.name != "COMPLETE":
            continue
        history.append({
            "number": t.number,
            "params": t.params,
            "value": t.value if (t.value is not None and math.isfinite(t.value)) else None,
            "total_trades": t.user_attrs.get("total_trades"),
            "duration_sec": t.duration.total_seconds() if t.duration else None,
        })

    if study.best_trial is None or study.best_value is None or not math.isfinite(study.best_value):
        # Every trial was rejected (min-trades / constraint violations).
        best_params: Dict[str, Any] = {}
        best_value = float("-inf")
        logger.warning(
            f"hyperopt({resolved}, {symbol}): no valid trials in {n_trials} attempts"
        )
    else:
        best_params = dict(study.best_trial.params)
        best_value = float(study.best_value)

    return HyperoptResult(
        strategy_type=resolved,
        symbol=symbol,
        objective=objective,
        n_trials=n_trials,
        best_params=best_params,
        best_value=best_value,
        baseline_value=float(base_val),
        duration_sec=duration,
        trial_history=history,
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
