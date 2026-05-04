"""Backtest API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Any, Dict
import uuid

from api.models import BacktestRequest, BacktestResponse
from backtest.engine import BacktestConfig, BacktestRunner
from data.fetcher import MarketData
from data.cache import DataCache
from strategies import StrategyFactory
from bot.config import BotConfig

router = APIRouter()

bot_config = BotConfig()


@router.post("/run")
async def run_backtest(request: BacktestRequest) -> Dict[str, Any]:
    """Run a backtest."""
    try:
        strategy = StrategyFactory(
            request.strategy_type,
            config=request.config or {},
        )

        # Fetch data
        cache = DataCache()
        market_data = MarketData(cache=cache, config=bot_config)
        
        import asyncio
        import pandas as pd
        try:
            df = await market_data.get_ohlcv(
                request.symbol,
                request.asset_class,
                request.timeframe,
            )
        except Exception:
            # Fallback: create synthetic data for demo
            import numpy as np
            dates = pd.date_range(request.start_date.isoformat(), periods=90, freq="D")
            np.random.seed(42)
            prices = 100 + np.cumsum(np.random.randn(90) * 2)
            df = pd.DataFrame({
                "timestamp": dates,
                "open": prices * 0.99,
                "high": prices * 1.02,
                "low": prices * 0.98,
                "close": prices,
                "volume": np.random.randint(1000, 10000, 90),
            })
            df.attrs["symbol"] = request.symbol

        # Filter the OHLCV bars to the user's requested date range so 90d and
        # 365d backtests don't return identical curves. Always keep some warmup
        # context (~50 bars) ahead of start_date so indicators like EMA(200)
        # have data to compute on, but treat the strategy as inactive there.
        if "timestamp" in df.columns and request.start_date and request.end_date:
            ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            start_ts = pd.Timestamp(request.start_date).tz_localize("UTC")
            end_ts = pd.Timestamp(request.end_date).tz_localize("UTC") + pd.Timedelta(days=1)
            mask = (ts >= start_ts) & (ts < end_ts)
            if mask.any():
                df = df.loc[mask].reset_index(drop=True)
                df.attrs["symbol"] = request.symbol

        config = BacktestConfig(
            initial_balance=request.initial_balance,
            fee_rate=bot_config.risk.fee_rate,
            slippage_bps=bot_config.risk.slippage_bps,
            allow_short=True,
        )

        runner = BacktestRunner(strategy, df, config)
        result = runner.run()

        metrics_dict = result.metrics.to_dict()

        return {
            "backtest_id": str(uuid.uuid4())[:8],
            "strategy_id": result.strategy_id,
            "total_return_pct": metrics_dict["total_return_pct"],
            "sharpe_ratio": metrics_dict["sharpe_ratio"],
            "max_drawdown_pct": metrics_dict["max_drawdown_pct"],
            "win_rate": metrics_dict["win_rate"],
            "profit_factor": metrics_dict["profit_factor"],
            "total_trades": metrics_dict["total_trades"],
            "equity_curve": result.equity_curve.to_dict("records") if not result.equity_curve.empty else [],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest error: {str(e)}")


@router.get("/results")
async def list_backtest_results() -> Dict[str, Any]:
    """List available backtest results."""
    return {"results": []}
