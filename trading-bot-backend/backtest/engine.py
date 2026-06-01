"""Backtest runner with bar-by-bar execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.metrics import BacktestMetrics, TradeRecord
from bot.config import OrderSide, SizingMethod
from bot.orders import ExecutionSimulator, Order, OrderType
from bot.portfolio import Portfolio, PositionSide
from bot.risk import PositionSizer, RiskManager
from strategies.base import BaseStrategy, Signal, SignalType


@dataclass
class BacktestConfig:
    """Configuration for backtest run."""
    initial_balance: Dict[str, float]
    fee_rate: float = 0.001
    slippage_bps: float = 5.0
    allow_short: bool = True
    position_sizing: SizingMethod = SizingMethod.PERCENTAGE
    position_sizing_value: float = 0.02


@dataclass
class BacktestResult:
    """Result of a backtest run."""
    strategy_id: str
    equity_curve: pd.DataFrame
    trades: List[TradeRecord]
    metrics: BacktestMetrics
    config: BacktestConfig
    duration: timedelta

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "strategy_id": self.strategy_id,
            "equity_curve": self.equity_curve.to_dict("records"),
            "trades": [
                {
                    "timestamp": t.timestamp.isoformat(),
                    "realized_pnl": t.realized_pnl,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": t.price,
                }
                for t in self.trades
            ],
            "metrics": self.metrics.to_dict(),
            "config": {
                "initial_balance": self.config.initial_balance,
                "fee_rate": self.config.fee_rate,
                "slippage_bps": self.config.slippage_bps,
                "allow_short": self.config.allow_short,
            },
            "duration_seconds": self.duration.total_seconds(),
        }


class BacktestRunner:
    """Run strategies on historical data with realistic execution simulation."""

    def __init__(
        self,
        strategy: BaseStrategy,
        data: pd.DataFrame,
        config: BacktestConfig,
        initial_balance: Dict[str, float] | None = None,
    ) -> None:
        """Initialize backtest runner.

        Args:
            strategy: Strategy to backtest.
            data: OHLCV historical data.
            config: Backtest configuration.
            initial_balance: Initial balance (defaults to config value).
        """
        self.strategy = strategy
        self.data = data.copy()
        self.config = config
        self.initial_balance = initial_balance or config.initial_balance
        self.execution = ExecutionSimulator(
            fee_rate=config.fee_rate,
            slippage_model=getattr(config, "slippage_model", "fixed"),
            slippage_bps=config.slippage_bps,
            # Fixed seed by default so a backtest is reproducible run-to-run;
            # override via config.random_seed.
            seed=getattr(config, "random_seed", 42),
            impact_coeff_bps=getattr(config, "impact_coeff_bps", 0.0),
            impact_ref_notional=getattr(config, "impact_ref_notional", 10_000.0),
        )
        self._trades: List[TradeRecord] = []
        self._equity_curve: List[Dict[str, Any]] = []

    def run(self) -> BacktestResult:
        """Run backtest bar-by-bar.

        Returns:
            BacktestResult with full history.
        """
        start_time = datetime.now(timezone.utc)
        strategy = self.strategy
        strategy.reset()

        # Ensure data has required columns
        data = self.data.copy()
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(data.columns)
        if missing:
            col_map = {c.lower(): c for c in data.columns}
            for req in missing:
                if req in col_map:
                    data[req] = data[col_map[req]]

        # Ensure timestamp column
        if "timestamp" not in data.columns and data.index.name in ("timestamp", "date", "datetime"):
            data = data.reset_index()

        # Create portfolio
        quote_asset = list(self.initial_balance.keys())[0] if self.initial_balance else "USDT"
        portfolio = Portfolio("backtest", self.initial_balance)

        positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position state

        for i in range(1, len(data)):
            # Current bar (we use i, keeping data[i-1] for indicator warmup)
            current_bar = data.iloc[: i + 1].copy()
            current_price = float(data["close"].iloc[i])
            timestamp = data.iloc[i].get("timestamp", pd.Timestamp.now())

            # Update open positions with current price
            for symbol, pos in positions.items():
                if pos["side"] == "long":
                    pos["unrealized_pnl"] = (current_price - pos["entry_price"]) * pos["size"]
                else:
                    pos["unrealized_pnl"] = (pos["entry_price"] - current_price) * pos["size"]
                pos["current_price"] = current_price

            # Generate signal
            signal = strategy.generate_signal(current_bar, current_price)

            if signal.signal_type == SignalType.BUY:
                self._execute_signal(
                    signal, current_price, portfolio, positions, quote_asset
                )
            elif signal.signal_type == SignalType.SELL:
                self._execute_signal(
                    signal, current_price, portfolio, positions, quote_asset
                )

            # Record equity
            total_unrealized = sum(p["unrealized_pnl"] for p in positions.values())
            total_realized = sum(t.realized_pnl for t in self._trades)
            equity = sum(portfolio.get_all_balances().values()) + total_unrealized
            peak = max(
                (e["equity"] for e in self._equity_curve), default=equity
            )
            drawdown = ((peak - equity) / peak * 100) if peak > 0 else 0.0

            self._equity_curve.append(
                {
                    "timestamp": timestamp,
                    "equity": equity,
                    "drawdown": drawdown,
                    "realized_pnl": total_realized,
                    "unrealized_pnl": total_unrealized,
                }
            )

        equity_df = pd.DataFrame(self._equity_curve)
        if equity_df.empty:
            equity_df = pd.DataFrame(
                [{"timestamp": pd.Timestamp.now(), "equity": sum(self.initial_balance.values()), "drawdown": 0.0}]
            )

        duration = datetime.now(timezone.utc) - start_time

        metrics = BacktestMetrics(equity_df, self._trades)

        return BacktestResult(
            strategy_id=strategy.strategy_id,
            equity_curve=equity_df,
            trades=self._trades,
            metrics=metrics,
            config=self.config,
            duration=duration,
        )

    def _execute_signal(
        self,
        signal: Signal,
        current_price: float,
        portfolio: Portfolio,
        positions: Dict[str, Dict[str, Any]],
        quote_asset: str,
    ) -> None:
        """Execute a signal in backtest."""
        symbol = signal.symbol
        is_buy = signal.signal_type == SignalType.BUY

        # Position sizing
        equity = sum(portfolio.get_all_balances().values())
        if signal.suggested_size and signal.suggested_size > 0:
            size = signal.suggested_size
        else:
            size = PositionSizer.percentage_of_equity(
                equity, self.config.position_sizing_value, current_price
            )
        size = max(size, 0.0)

        if size == 0:
            return

        # Create order
        side = OrderSide.BUY if is_buy else OrderSide.SELL
        order = Order.market(symbol=symbol, side=side, quantity=size, account_id="backtest")

        # Execute
        fill = self.execution.execute(order, current_price)
        if fill:
            # Update positions and portfolio
            cost = fill.filled_qty * fill.filled_price + fill.fee

            if is_buy:
                portfolio.withdraw(quote_asset, cost)
                # Check if short exists to close
                if symbol in positions and positions[symbol]["side"] == "short":
                    pos = positions[symbol]
                    realized = (pos["entry_price"] - fill.filled_price) * min(fill.filled_qty, pos["size"])
                    if fill.filled_qty >= pos["size"]:
                        del positions[symbol]
                    else:
                        pos["size"] -= fill.filled_qty
                    self._trades.append(
                        TradeRecord(
                            timestamp=fill.timestamp,
                            realized_pnl=realized,
                            side="buy",
                            quantity=fill.filled_qty,
                            price=fill.filled_price,
                        )
                    )
                else:
                    # Open or add to long
                    if symbol in positions and positions[symbol]["side"] == "long":
                        pos = positions[symbol]
                        total_cost = pos["entry_price"] * pos["size"] + fill.filled_price * fill.filled_qty
                        pos["size"] += fill.filled_qty
                        pos["entry_price"] = total_cost / pos["size"]
                        pos["current_price"] = fill.filled_price
                    else:
                        positions[symbol] = {
                            "side": "long",
                            "size": fill.filled_qty,
                            "entry_price": fill.filled_price,
                            "current_price": fill.filled_price,
                            "unrealized_pnl": 0.0,
                        }
                    # Log the entry as a trade so total_trades reflects activity.
                    # Realized P&L is 0 for entries; closes will record their own.
                    self._trades.append(
                        TradeRecord(
                            timestamp=fill.timestamp,
                            realized_pnl=0.0,
                            side="buy",
                            quantity=fill.filled_qty,
                            price=fill.filled_price,
                        )
                    )
            else:
                # Sell
                portfolio.deposit(quote_asset, fill.filled_qty * fill.filled_price - fill.fee)
                if symbol in positions and positions[symbol]["side"] == "long":
                    pos = positions[symbol]
                    realized = (fill.filled_price - pos["entry_price"]) * min(fill.filled_qty, pos["size"])
                    if fill.filled_qty >= pos["size"]:
                        del positions[symbol]
                    else:
                        pos["size"] -= fill.filled_qty
                        remaining_cost = pos["entry_price"] * (pos["size"] + fill.filled_qty) - fill.filled_price * fill.filled_qty
                        pos["entry_price"] = remaining_cost / pos["size"] if pos["size"] > 0 else 0
                    self._trades.append(
                        TradeRecord(
                            timestamp=fill.timestamp,
                            realized_pnl=realized,
                            side="sell",
                            quantity=fill.filled_qty,
                            price=fill.filled_price,
                        )
                    )
                elif self.config.allow_short:
                    # Open or add to short
                    if symbol in positions and positions[symbol]["side"] == "short":
                        pos = positions[symbol]
                        total_cost = pos["entry_price"] * pos["size"] + fill.filled_price * fill.filled_qty
                        pos["size"] += fill.filled_qty
                        pos["entry_price"] = total_cost / pos["size"]
                        pos["current_price"] = fill.filled_price
                    else:
                        positions[symbol] = {
                            "side": "short",
                            "size": fill.filled_qty,
                            "entry_price": fill.filled_price,
                            "current_price": fill.filled_price,
                            "unrealized_pnl": 0.0,
                        }
                    # Log short entry as a trade for accurate total_trades count.
                    self._trades.append(
                        TradeRecord(
                            timestamp=fill.timestamp,
                            realized_pnl=0.0,
                            side="sell",
                            quantity=fill.filled_qty,
                            price=fill.filled_price,
                        )
                    )

    def walk_forward(
        self,
        data: pd.DataFrame,
        train_size: int,
        test_size: int,
        step_size: int | None = None,
    ) -> List[BacktestResult]:
        """Walk-forward analysis.

        Args:
            data: Full OHLCV data.
            train_size: Number of bars for training/warmup.
            test_size: Number of bars for testing.
            step_size: Step forward size. Defaults to test_size.

        Returns:
            List of BacktestResult for each window.
        """
        step = step_size or test_size
        results: List[BacktestResult] = []
        strategy = self.strategy

        for start in range(0, len(data) - train_size - test_size + 1, step):
            train_start = start
            test_start = start + train_size
            test_end = min(test_start + test_size, len(data))

            train_data = data.iloc[train_start:test_start].copy()
            test_data = data.iloc[test_start:test_end].copy()

            if len(test_data) < 5:
                continue

            # Reset strategy for each window
            strategy.reset()
            # Warm up on train data
            if len(train_data) > 0:
                _ = strategy.generate_signal(train_data, float(train_data["close"].iloc[-1]))

            # Run backtest on test data
            runner = BacktestRunner(
                strategy=strategy,
                data=test_data,
                config=self.config,
                initial_balance=self.initial_balance,
            )
            result = runner.run()
            results.append(result)

        return results


if __name__ == "__main__":
    # Demo backtest
    print("=== Backtest Runner Demo ===")
    
    # Create synthetic data
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.randn(100) * 2)
    df = pd.DataFrame({
        "timestamp": dates,
        "open": prices * 0.99,
        "high": prices * 1.02,
        "low": prices * 0.98,
        "close": prices,
        "volume": np.random.randint(1000, 10000, 100),
    })
    df.attrs["symbol"] = "TEST"

    from strategies.momentum import MomentumStrategy
    strategy = MomentumStrategy("demo_momentum", {"fast_ema": 5, "slow_ema": 10})

    config = BacktestConfig(
        initial_balance={"USDT": 10000.0},
        fee_rate=0.001,
        allow_short=True,
    )

    runner = BacktestRunner(strategy, df, config)
    result = runner.run()

    print(f"Strategy: {result.strategy_id}")
    print(f"Total Return: {result.metrics.total_return_pct:.2f}%")
    print(f"Sharpe Ratio: {result.metrics.sharpe_ratio:.4f}")
    print(f"Max Drawdown: {result.metrics.max_drawdown_pct:.2f}%")
    print(f"Win Rate: {result.metrics.win_rate:.1f}%")
    print(f"Total Trades: {len(result.trades)}")
    print("=== Demo Complete ===")
