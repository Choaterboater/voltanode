"""Optuna objective factory for strategy hyperopt."""

from __future__ import annotations

import math
from typing import Any, Callable, Dict

import optuna
import pandas as pd

from backtest.engine import BacktestConfig, BacktestRunner
from strategies import STRATEGY_REGISTRY, StrategyFactory, _normalize_strategy_type


MIN_TRADES_FOR_VALID_TRIAL = 5

# Metric extractors keyed on the user-facing objective name. Each takes a
# BacktestMetrics-shaped dict and returns a float to maximize.
_OBJECTIVE_KEYS = {
    "sharpe": "sharpe_ratio",
    "sortino": "sortino_ratio",
    "profit_factor": "profit_factor",
    "total_return": "total_return_pct",
    "calmar": "calmar_ratio",
}


def _suggest_param(trial: optuna.Trial, name: str, spec: Dict[str, Any]) -> Any:
    """Map a param_space spec to the right trial.suggest_* call."""
    ptype = spec.get("type", "float")
    if ptype == "int":
        return trial.suggest_int(name, int(spec["low"]), int(spec["high"]),
                                  step=int(spec.get("step", 1)))
    if ptype == "float":
        step = spec.get("step")
        log = bool(spec.get("log", False))
        if step is not None and not log:
            return trial.suggest_float(name, float(spec["low"]), float(spec["high"]),
                                        step=float(step))
        return trial.suggest_float(name, float(spec["low"]), float(spec["high"]), log=log)
    if ptype == "categorical":
        return trial.suggest_categorical(name, spec["choices"])
    raise ValueError(f"Unknown param_space type {ptype!r} for {name!r}")


def _violates_constraints(strategy_type: str, params: Dict[str, Any]) -> bool:
    """Return True for param combinations the strategy can't run.

    These are constraints Optuna's sampler doesn't know about — easier to
    short-circuit here than build a constrained sampler.
    """
    if strategy_type == "macd":
        if params.get("fast", 0) >= params.get("slow", 1):
            return True
    if strategy_type == "momentum":
        if params.get("fast_ema", 0) >= params.get("slow_ema", 1):
            return True
    return False


def make_objective(
    strategy_type: str,
    df: pd.DataFrame,
    bt_config: BacktestConfig,
    objective: str,
    fixed_config: Dict[str, Any] | None = None,
    min_trades: int = MIN_TRADES_FOR_VALID_TRIAL,
) -> Callable[[optuna.Trial], float]:
    """Build a callable Optuna objective for the given strategy type.

    Args:
        strategy_type: Registry key or PascalCase strategy name.
        df: OHLCV DataFrame fetched ONCE before the study (shared across trials).
        bt_config: Backtest config (fees, slippage, initial balance, sizing).
        objective: One of _OBJECTIVE_KEYS.
        fixed_config: Non-tuned config keys (e.g. {"symbols": ["BTC/USD"]}).
        min_trades: Trials producing fewer than this many trades are rejected.

    Returns:
        ``func(trial) -> float`` for ``study.optimize``.
    """
    resolved = _normalize_strategy_type(strategy_type)
    if resolved not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy type: {strategy_type}")
    strategy_cls = STRATEGY_REGISTRY[resolved]
    space = strategy_cls.param_space()
    if not space:
        raise ValueError(f"Strategy {resolved!r} has no param_space — opts out of hyperopt")
    if objective not in _OBJECTIVE_KEYS:
        raise ValueError(
            f"Unknown objective {objective!r}. Choose from {sorted(_OBJECTIVE_KEYS)}"
        )
    metric_key = _OBJECTIVE_KEYS[objective]
    fixed = dict(fixed_config or {})

    def _objective(trial: optuna.Trial) -> float:
        params = {name: _suggest_param(trial, name, spec) for name, spec in space.items()}
        if _violates_constraints(resolved, params):
            return -math.inf
        merged = {**fixed, **params}
        try:
            strategy = StrategyFactory(resolved, config=merged)
            runner = BacktestRunner(strategy, df, bt_config)
            result = runner.run()
        except Exception:
            return -math.inf

        metrics = result.metrics.to_dict()
        total_trades = int(metrics.get("total_trades", 0))
        if total_trades < min_trades:
            return -math.inf
        value = float(metrics.get(metric_key, 0.0))
        # Cap pathological profit_factor=inf so Optuna can compare trials.
        if not math.isfinite(value):
            return -math.inf
        # Stash diagnostics on the trial for later inspection.
        trial.set_user_attr("total_trades", total_trades)
        trial.set_user_attr("sharpe_ratio", metrics.get("sharpe_ratio"))
        trial.set_user_attr("total_return_pct", metrics.get("total_return_pct"))
        trial.set_user_attr("max_drawdown_pct", metrics.get("max_drawdown_pct"))
        return value

    return _objective


def baseline_value(
    strategy_type: str,
    df: pd.DataFrame,
    bt_config: BacktestConfig,
    objective: str,
    fixed_config: Dict[str, Any] | None = None,
) -> float:
    """Run one backtest with DEFAULT_CONFIG, return the same metric the study
    optimizes. Lets the caller report "Sharpe 0.4 → 0.91" against the operator's
    current production config."""
    resolved = _normalize_strategy_type(strategy_type)
    if resolved not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy type: {strategy_type}")
    if objective not in _OBJECTIVE_KEYS:
        raise ValueError(f"Unknown objective {objective!r}")
    metric_key = _OBJECTIVE_KEYS[objective]
    strategy = StrategyFactory(resolved, config=dict(fixed_config or {}))
    runner = BacktestRunner(strategy, df, bt_config)
    try:
        result = runner.run()
    except Exception:
        return float("-inf")
    metrics = result.metrics.to_dict()
    val = float(metrics.get(metric_key, 0.0))
    return val if math.isfinite(val) else float("-inf")
