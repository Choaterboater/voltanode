"""Backtest performance metrics calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List

import numpy as np
import pandas as pd


@dataclass
class TradeRecord:
    """Simplified trade record for metrics calculation.

    ``is_entry`` marks position-opening fills (which carry realized_pnl=0).
    Win-rate and per-trade averages must denominate over CLOSING round-trips
    only — counting entries as zero-P&L "trades" otherwise crushes win-rate
    toward 0 (a profitable momentum bot with 8 entries / 1 close showed 0%).
    """
    timestamp: pd.Timestamp
    realized_pnl: float
    side: str
    quantity: float
    price: float
    is_entry: bool = False


class BacktestMetrics:
    """Comprehensive backtest performance metrics."""

    def __init__(self, equity_curve: pd.DataFrame, trades: List[TradeRecord]) -> None:
        """Initialize metrics from equity curve and trades.

        Args:
            equity_curve: DataFrame with columns [timestamp, equity, drawdown].
            trades: List of completed trades.
        """
        self._equity_curve = equity_curve
        self._trades = trades
        self._returns = equity_curve["equity"].pct_change().dropna() if "equity" in equity_curve.columns else pd.Series()

    @property
    def total_return_pct(self) -> float:
        """Total return percentage."""
        if self._equity_curve.empty:
            return 0.0
        start = self._equity_curve["equity"].iloc[0]
        end = self._equity_curve["equity"].iloc[-1]
        if start == 0:
            return 0.0
        return (end - start) / start * 100

    @property
    def sharpe_ratio(self) -> float:
        """Annualized Sharpe ratio."""
        if len(self._returns) < 2 or self._returns.std() == 0:
            return 0.0
        # Annualized (assuming daily data)
        return float(self._returns.mean() / self._returns.std() * np.sqrt(252))

    @property
    def sortino_ratio(self) -> float:
        """Annualized Sortino ratio."""
        downside = self._returns[self._returns < 0]
        if len(downside) < 1 or downside.std() == 0:
            return 0.0
        return float(self._returns.mean() / downside.std() * np.sqrt(252))

    @property
    def max_drawdown_pct(self) -> float:
        """Maximum drawdown percentage."""
        if "drawdown" in self._equity_curve.columns:
            return float(self._equity_curve["drawdown"].max())
        equity = self._equity_curve["equity"]
        peak = equity.cummax()
        drawdown = ((peak - equity) / peak * 100)
        return float(drawdown.max())

    @property
    def max_drawdown_duration(self) -> timedelta:
        """Maximum drawdown duration."""
        if self._equity_curve.empty:
            return timedelta(0)
        equity = self._equity_curve["equity"]
        peak = equity.cummax()
        in_drawdown = equity < peak
        max_duration = timedelta(0)
        current_start = None
        for i, is_dd in enumerate(in_drawdown):
            if is_dd and current_start is None:
                current_start = i
            elif not is_dd and current_start is not None:
                duration = self._equity_curve.index[i] - self._equity_curve.index[current_start]
                # Index may be RangeIndex (int) or DatetimeIndex (timedelta).
                if not isinstance(duration, timedelta):
                    duration = timedelta(days=int(duration))
                if duration > max_duration:
                    max_duration = duration
                current_start = None
        return max_duration

    @property
    def _closes(self) -> List["TradeRecord"]:
        """Closing round-trips only (exclude zero-P&L position-opening entries)."""
        return [t for t in self._trades if not getattr(t, "is_entry", False)]

    @property
    def win_rate(self) -> float:
        """Percentage of winning CLOSED round-trips (entries excluded)."""
        closes = self._closes
        if not closes:
            return 0.0
        wins = sum(1 for t in closes if t.realized_pnl > 0)
        return wins / len(closes) * 100

    @property
    def profit_factor(self) -> float:
        """Profit factor: gross profit / gross loss."""
        profits = sum(t.realized_pnl for t in self._trades if t.realized_pnl > 0)
        losses = abs(sum(t.realized_pnl for t in self._trades if t.realized_pnl < 0))
        if losses == 0:
            return float("inf") if profits > 0 else 0.0
        return profits / losses

    @property
    def avg_trade_return(self) -> float:
        """Average realized P&L per CLOSED round-trip (entries excluded)."""
        closes = self._closes
        if not closes:
            return 0.0
        return sum(t.realized_pnl for t in closes) / len(closes)

    @property
    def avg_win(self) -> float:
        """Average winning trade."""
        wins = [t.realized_pnl for t in self._trades if t.realized_pnl > 0]
        return np.mean(wins) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        """Average losing trade."""
        losses = [t.realized_pnl for t in self._trades if t.realized_pnl < 0]
        return abs(np.mean(losses)) if losses else 0.0

    @property
    def payoff_ratio(self) -> float:
        """Payoff ratio: avg win / avg loss."""
        if self.avg_loss == 0:
            return float("inf") if self.avg_win > 0 else 0.0
        return self.avg_win / self.avg_loss

    @property
    def calmar_ratio(self) -> float:
        """Calmar ratio: annualized return / max drawdown."""
        mdd = self.max_drawdown_pct
        if mdd == 0:
            return 0.0
        # Simple annualization based on data length
        days = len(self._equity_curve)
        years = max(days / 252, 0.01)
        annual_return = self.total_return_pct / years
        return annual_return / mdd

    @property
    def trades_per_month(self) -> float:
        """Average trades per month."""
        if not self._trades or self._equity_curve.empty:
            return 0.0
        days = len(self._equity_curve)
        months = max(days / 21, 0.01)
        return len(self._trades) / months

    def to_dict(self) -> Dict[str, Any]:
        """Export all metrics as a dictionary."""
        return {
            "total_return_pct": round(self.total_return_pct, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_drawdown_duration_days": self.max_drawdown_duration.days,
            "win_rate": round(self.win_rate, 2),
            "profit_factor": round(self.profit_factor, 4),
            "avg_trade_return": round(self.avg_trade_return, 4),
            "avg_win": round(self.avg_win, 4),
            "avg_loss": round(self.avg_loss, 4),
            "payoff_ratio": round(self.payoff_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "trades_per_month": round(self.trades_per_month, 2),
            "total_trades": len(self._trades),
            "closed_trades": len(self._closes),
        }


def calculate_sharpe(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Calculate Sharpe ratio from a returns series.

    Args:
        returns: Series of period returns.
        risk_free_rate: Risk-free rate (annualized).

    Returns:
        Sharpe ratio.
    """
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    excess = returns - risk_free_rate / 252  # Daily adjustment
    return float(excess.mean() / excess.std() * np.sqrt(252))


def calculate_max_drawdown(equity: pd.Series) -> tuple[float, int, int]:
    """Calculate maximum drawdown.

    Args:
        equity: Equity curve series.

    Returns:
        Tuple of (max_drawdown_pct, peak_index, trough_index).
    """
    peak = equity.cummax()
    drawdown = (peak - equity) / peak
    max_dd_idx = drawdown.idxmax()
    max_dd = float(drawdown.max())
    peak_idx = equity.loc[:max_dd_idx].idxmax() if len(equity) > 0 else 0
    return max_dd * 100, peak_idx, max_dd_idx


def calculate_win_rate(trades: List[TradeRecord]) -> float:
    """Calculate win rate from trades.

    Args:
        trades: List of trade records.

    Returns:
        Win rate as percentage (rounded to 2 decimal places).
    """
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.realized_pnl > 0)
    return round(wins / len(trades) * 100, 2)


def calculate_profit_factor(trades: List[TradeRecord]) -> float:
    """Calculate profit factor.

    Args:
        trades: List of trade records.

    Returns:
        Profit factor.
    """
    profits = sum(t.realized_pnl for t in trades if t.realized_pnl > 0)
    losses = abs(sum(t.realized_pnl for t in trades if t.realized_pnl < 0))
    if losses == 0:
        return float("inf") if profits > 0 else 0.0
    return profits / losses
