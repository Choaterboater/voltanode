"""Abstract base strategy class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

from bot.config import SignalType
from bot.orders import FillResult, Order, OrderSide
from bot.portfolio import Portfolio


@dataclass
class Signal:
    """Trading signal emitted by a strategy."""
    strategy_id: str
    symbol: str
    signal_type: SignalType
    confidence: float  # 0.0 – 1.0
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    suggested_size: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None

    def to_order(self, account_id: str = "default") -> Order | None:
        """Convert signal to an Order if applicable."""
        if self.signal_type == SignalType.BUY:
            return Order.market(
                symbol=self.symbol,
                side=OrderSide.BUY,
                quantity=self.suggested_size or 0.0,
                account_id=account_id,
                strategy_id=self.strategy_id,
            )
        if self.signal_type == SignalType.SELL:
            return Order.market(
                symbol=self.symbol,
                side=OrderSide.SELL,
                quantity=self.suggested_size or 0.0,
                account_id=account_id,
                strategy_id=self.strategy_id,
            )
        return None


@dataclass
class StrategyMetrics:
    """Performance metrics for a strategy."""
    strategy_id: str
    total_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    sharpe_ratio: float | None
    max_drawdown: float
    current_streak: int
    total_pnl: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "avg_profit": self.avg_profit,
            "avg_loss": self.avg_loss,
            "profit_factor": self.profit_factor,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "current_streak": self.current_streak,
            "total_pnl": self.total_pnl,
        }


@dataclass
class TickData:
    """Price tick data for strategy on_tick."""
    symbol: str
    price: float
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    name: str = "base"
    DEFAULT_CONFIG: Dict[str, Any] = {}

    def __init__(self, strategy_id: str, config: Dict[str, Any]) -> None:
        """Initialize strategy.

        Args:
            strategy_id: Unique strategy identifier.
            config: Strategy-specific configuration.
        """
        self.strategy_id = strategy_id
        self.config = {**self.DEFAULT_CONFIG, **config}
        self.is_active = True
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_pnl = 0.0
        self._history: List[Signal] = []
        self._trades: List[Dict[str, Any]] = []

    # ── Required ──

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Analyze data and emit a trading signal.

        Args:
            data: OHLCV DataFrame up to current point.
            current_price: Current market price.

        Returns:
            Signal with confidence and metadata.
        """
        ...

    # ── Lifecycle ──

    def on_tick(self, tick: TickData, portfolio: Portfolio) -> Signal | None:
        """Called on every price tick.

        Default implementation fetches OHLCV and calls generate_signal.
        Override for tick-level strategies.
        """
        return None

    def on_fill(self, fill: FillResult, portfolio: Portfolio) -> None:
        """Callback when an order from this strategy is filled."""
        self.trade_count += 1
        if fill.realized_pnl is not None:
            self.total_pnl += fill.realized_pnl
            if fill.realized_pnl > 0:
                self.win_count += 1
            else:
                self.loss_count += 1
            self._trades.append(
                {
                    "pnl": fill.realized_pnl,
                    "price": fill.filled_price,
                    "timestamp": fill.timestamp,
                }
            )

    def on_init(self, market_data: Any) -> None:
        """Pre-load historical data, warm up indicators."""
        pass

    def on_stop(self) -> None:
        """Cleanup, persist state."""
        pass

    # ── Metrics ──

    def get_metrics(self) -> StrategyMetrics:
        """Return performance metrics for this strategy."""
        win_rate = self.win_count / max(1, self.trade_count) * 100
        profits = [t["pnl"] for t in self._trades if t["pnl"] > 0]
        losses = [t["pnl"] for t in self._trades if t["pnl"] <= 0]
        avg_profit = np.mean(profits) if profits else 0.0
        avg_loss = abs(np.mean(losses)) if losses else 0.0
        profit_factor = (
            sum(profits) / max(1e-9, abs(sum(losses)))
            if losses or profits
            else 0.0
        )
        # Simple drawdown calculation
        max_dd = 0.0
        peak = 0.0
        cum_pnl = 0.0
        for t in self._trades:
            cum_pnl += t["pnl"]
            peak = max(peak, cum_pnl)
            dd = peak - cum_pnl
            max_dd = max(max_dd, dd)

        return StrategyMetrics(
            strategy_id=self.strategy_id,
            total_trades=self.trade_count,
            win_rate=win_rate,
            avg_profit=avg_profit,
            avg_loss=-avg_loss,
            profit_factor=profit_factor,
            sharpe_ratio=None,
            max_drawdown=max_dd,
            current_streak=0,
            total_pnl=self.total_pnl,
        )

    def reset(self) -> None:
        """Reset internal state for backtesting or restart."""
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_pnl = 0.0
        self._history.clear()
        self._trades.clear()

    # ── Helpers ──

    def _record_signal(self, signal: Signal) -> None:
        """Record a generated signal in history."""
        self._history.append(signal)

    @staticmethod
    def _ensure_columns(data: pd.DataFrame) -> pd.DataFrame:
        """Ensure required OHLCV columns exist."""
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(data.columns)
        if missing:
            # Try case-insensitive match
            col_map = {c.lower(): c for c in data.columns}
            for req in missing:
                if req in col_map:
                    data[req] = data[col_map[req]]
        return data
