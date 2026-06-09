#!/usr/bin/env python
"""Kronos edge check — does the Kronos forecast actually make money here?

Runs KronosForecastStrategy through the project's BacktestRunner (real fees +
slippage + intra-bar stop/TP) on one symbol, then prints expectancy / profit
factor / Sharpe and compares to buy-and-hold. The point is a yes/no on edge
BEFORE any live wiring.

Run from trading-bot-backend/ ::

    # Offline: feed your own OHLCV CSV (timestamp,open,high,low,close,volume)
    python scripts/kronos_backtest.py --csv data/BTCUSD_1h.csv --symbol BTC

    # Or pull via the project fetcher (needs network/keys)
    python scripts/kronos_backtest.py --symbol BTC --asset-class crypto --days 365

Prereqs (where Hugging Face is reachable)::

    pip install torch transformers huggingface_hub einops
    git clone https://github.com/shiyu-coder/Kronos
    export PYTHONPATH="$PYTHONPATH:/path/to/Kronos"

If the Kronos model can't load, the strategy stays flat and you'll get 0 trades
(a clear signal the model wiring isn't set up yet, not a result).
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

# Make the package importable when run as a script from trading-bot-backend/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestConfig, BacktestRunner  # noqa: E402
from strategies.kronos_forecast import KronosForecastStrategy, _LOAD_FAILED  # noqa: E402


def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = next((c for c in ("timestamp", "date", "datetime", "time") if c in df.columns), None)
    if ts_col:
        df["timestamp"] = pd.to_datetime(df[ts_col])
        df = df.set_index("timestamp")
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"CSV missing columns: {missing}. Have: {list(df.columns)}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df


def _load_via_fetcher(symbol: str, asset_class: str, days: int, timeframe: str) -> pd.DataFrame:
    import asyncio
    from data.fetcher import MarketData

    md = MarketData()
    if asset_class == "crypto":
        df = asyncio.run(md.get_crypto_ohlcv(symbol, days=days))
    else:
        df = md.get_stock_ohlcv(symbol, period=f"{max(days, 1)}d", interval=timeframe)
    if df is None or len(df) == 0:
        raise SystemExit(f"No data returned for {symbol} ({asset_class}).")
    df.columns = [c.lower() for c in df.columns]
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest the Kronos forecast strategy.")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--csv", help="OHLCV CSV path (offline). Overrides fetcher.")
    ap.add_argument("--asset-class", default="crypto", choices=["crypto", "stock"])
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--pred-len", type=int, default=12)
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--buy-threshold", type=float, default=0.008)
    ap.add_argument("--sell-threshold", type=float, default=0.008)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    ap.add_argument("--balance", type=float, default=10_000.0)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    data = _load_csv(args.csv) if args.csv else _load_via_fetcher(
        args.symbol, args.asset_class, args.days, args.timeframe)
    data.attrs["symbol"] = args.symbol.upper()
    print(f"Loaded {len(data)} bars for {args.symbol.upper()} "
          f"({data.index[0]} -> {data.index[-1]})" if len(data) else "no data")

    strategy = KronosForecastStrategy(
        strategy_id=f"kronos_{args.symbol.lower()}",
        config={
            "symbol": args.symbol.upper(),
            "pred_len": args.pred_len,
            "lookback": args.lookback,
            "buy_threshold": args.buy_threshold,
            "sell_threshold": args.sell_threshold,
            "device": args.device,
        },
    )

    quote = "USDT" if args.asset_class == "crypto" else "USD"
    cfg = BacktestConfig(
        initial_balance={quote: args.balance},
        fee_rate=args.fee,
        slippage_bps=args.slippage_bps,
        allow_short=False,
    )
    result = BacktestRunner(strategy, data, cfg).run()
    m = result.metrics.to_dict() if hasattr(result.metrics, "to_dict") else dict(result.metrics)

    # Buy-and-hold benchmark over the same window, net of one round-trip fee.
    bh_ret = (float(data["close"].iloc[-1]) / float(data["close"].iloc[0]) - 1.0) - 2 * args.fee
    strat_ret = float(m.get("total_pnl", 0.0)) / args.balance
    pf = m.get("profit_factor")

    print("\n================ KRONOS BACKTEST ================")
    print(f" symbol            : {args.symbol.upper()} ({args.asset_class}, tf~{args.timeframe})")
    print(f" trades            : {m.get('total_trades')}")
    print(f" win rate          : {(m.get('win_rate') or 0)*100:.1f}%")
    print(f" profit factor     : {pf}")
    print(f" sharpe            : {m.get('sharpe_ratio')}")
    print(f" max drawdown      : {(m.get('max_drawdown') or 0)*100:.1f}%")
    print(f" total P&L         : ${m.get('total_pnl', 0):,.2f}  ({strat_ret*100:+.2f}%)")
    print(f" buy & hold (net)  : {bh_ret*100:+.2f}%")
    print("-------------------------------------------------")

    if not m.get("total_trades"):
        key = ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base", 512, args.device)
        why = _LOAD_FAILED.get(key)
        print(" VERDICT: NO TRADES — model likely not loaded.")
        if why:
            print(f"          load error: {why}")
            print("          install torch + Kronos repo (see header) and retry.")
    elif (pf or 0) > 1.0 and strat_ret > bh_ret:
        print(" VERDICT: EDGE — beats buy & hold AND profit factor > 1. Worth a closer look.")
    else:
        print(" VERDICT: NO EDGE — does not beat buy & hold net of costs. Do NOT deploy.")
    print("=================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
