"""CLI runner for offline strategy hyperopt.

Usage:
    python -m cli.hyperopt_runner --strategy macd --symbol BTC/USD \
        --asset-class crypto --trials 50 --objective sharpe

Same entry point the API uses; lets you run overnight studies without keeping
the backend up. Appends results to ``data/hyperopt_history.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from hyperopt import append_history, run_hyperopt


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Bayesian hyperopt on a strategy.")
    p.add_argument("--strategy", required=True,
                   help="Registry key (mean_reversion, macd, momentum, ...)")
    p.add_argument("--symbol", required=True, help="e.g. BTC/USD")
    p.add_argument("--asset-class", default="crypto",
                   choices=["crypto", "stock", "forex"])
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--trials", type=int, default=50)
    p.add_argument("--objective", default="sharpe",
                   choices=["sharpe", "sortino", "profit_factor", "total_return", "calmar"])
    p.add_argument("--initial-balance", type=float, default=100_000.0)
    p.add_argument("--quote-asset", default="USDT")
    p.add_argument("--fee-rate", type=float, default=0.001)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--no-short", action="store_true", help="Disable short-selling in backtest")
    p.add_argument("--timeout-sec", type=int, default=None)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--strategy-id", default=None,
                   help="If set, history row is tagged with this id (default: <strategy>_<symbol>)")
    p.add_argument("--no-history", action="store_true",
                   help="Don't append to data/hyperopt_history.jsonl")
    p.add_argument("--json", action="store_true",
                   help="Emit full result as JSON to stdout (default: human-readable)")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    fixed_config: Dict[str, Any] = {"symbols": [args.symbol]}

    print(
        f"Running hyperopt: strategy={args.strategy} symbol={args.symbol} "
        f"trials={args.trials} objective={args.objective}",
        file=sys.stderr,
    )
    result = run_hyperopt(
        strategy_type=args.strategy,
        symbol=args.symbol,
        asset_class=args.asset_class,
        timeframe=args.timeframe,
        n_trials=args.trials,
        objective=args.objective,
        fixed_config=fixed_config,
        initial_balance=args.initial_balance,
        quote_asset=args.quote_asset,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
        allow_short=not args.no_short,
        timeout_sec=args.timeout_sec,
        seed=args.seed,
    )

    if not args.no_history:
        sid = args.strategy_id or f"{result.strategy_type}_{args.symbol.replace('/', '')}"
        append_history(result, strategy_id=sid)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        import math as _math
        finite_trials = sum(
            1 for t in result.trial_history
            if t.get("value") is not None and _math.isfinite(t["value"])
        )
        print(f"\nstrategy:        {result.strategy_type}")
        print(f"symbol:          {result.symbol}")
        print(f"objective:       {result.objective}")
        print(f"trials:          {result.n_trials} requested, "
              f"{len(result.trial_history)} completed, {finite_trials} produced a valid value")
        print(f"duration:        {result.duration_sec:.1f}s")
        print(f"baseline_value:  {result.baseline_value:.4f}")
        print(f"best_value:      {result.best_value:.4f}")
        print(f"improvement:     {result.improvement_pct:+.1f}%")
        if result.best_params:
            print(f"best_params:")
            for k, v in result.best_params.items():
                print(f"    {k}: {v}")
        else:
            print("best_params:     (none — every trial rejected; "
                  "widen param_space, lengthen window, or lower min_trades)")

    return 0 if result.best_params else 1


if __name__ == "__main__":
    sys.exit(main())
