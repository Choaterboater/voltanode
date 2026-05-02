"""Performance report generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from analytics.records import TradeRepository, PortfolioSnapshotRepository
from bot.portfolio import Portfolio


@dataclass
class DailyReport:
    """Daily performance report."""
    date: date
    starting_equity: float
    ending_equity: float
    realized_pnl: float
    unrealized_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    top_gainer: str | None
    top_loser: str | None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "starting_equity": self.starting_equity,
            "ending_equity": self.ending_equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "top_gainer": self.top_gainer,
            "top_loser": self.top_loser,
        }


@dataclass
class StrategyReport:
    """Strategy lifetime performance report."""
    strategy_id: str
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float | None
    max_drawdown: float
    equity_curve: List[tuple[datetime, float]]
    trades: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "equity_curve": [(t.isoformat(), e) for t, e in self.equity_curve],
            "trades": self.trades,
        }


@dataclass
class PortfolioReport:
    """Portfolio summary report."""
    account_id: str
    timestamp: datetime
    balances: Dict[str, float]
    positions: List[Dict[str, Any]]
    total_equity: float
    unrealized_pnl: float
    realized_pnl: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "timestamp": self.timestamp.isoformat(),
            "balances": self.balances,
            "positions": self.positions,
            "total_equity": self.total_equity,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
        }


class ReportGenerator:
    """Generate human-readable and machine-readable reports."""

    def __init__(self, db_session: Session) -> None:
        """Initialize report generator.

        Args:
            db_session: SQLAlchemy session.
        """
        self.session = db_session
        self.trade_repo = TradeRepository(db_session)
        self.snapshot_repo = PortfolioSnapshotRepository(db_session)

    def generate_daily_report(
        self, date: date, account_id: str = "default"
    ) -> DailyReport:
        """Generate a daily report.

        Args:
            date: Report date.
            account_id: Account ID.

        Returns:
            DailyReport.
        """
        start = datetime.combine(date, datetime.min.time().replace(tzinfo=timezone.utc))
        end = start + timedelta(days=1)

        trades = self.trade_repo.get_by_account(account_id, start, end)
        snapshots = self.snapshot_repo.get_snapshots(account_id, start, end)

        realized_pnl = sum(t.realized_pnl or 0.0 for t in trades)
        win_count = sum(1 for t in trades if (t.realized_pnl or 0) > 0)
        loss_count = sum(1 for t in trades if (t.realized_pnl or 0) < 0)

        top_gainer = None
        top_loser = None
        if trades:
            by_pnl = sorted(trades, key=lambda t: t.realized_pnl or 0, reverse=True)
            top_gainer = by_pnl[0].symbol if by_pnl[0].realized_pnl and by_pnl[0].realized_pnl > 0 else None
            top_loser = by_pnl[-1].symbol if by_pnl[-1].realized_pnl and by_pnl[-1].realized_pnl < 0 else None

        starting_equity = snapshots[0].total_equity if snapshots else 0.0
        ending_equity = snapshots[-1].total_equity if snapshots else 0.0
        unrealized_pnl = snapshots[-1].unrealized_pnl if snapshots else 0.0

        return DailyReport(
            date=date,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            trade_count=len(trades),
            win_count=win_count,
            loss_count=loss_count,
            top_gainer=top_gainer,
            top_loser=top_loser,
        )

    def generate_strategy_report(self, strategy_id: str) -> StrategyReport:
        """Generate strategy lifetime report.

        Args:
            strategy_id: Strategy ID.

        Returns:
            StrategyReport.
        """
        trades = self.trade_repo.get_by_strategy(strategy_id)
        total_trades = len(trades)
        win_rate = sum(1 for t in trades if (t.realized_pnl or 0) > 0) / max(1, total_trades) * 100
        profits = sum(t.realized_pnl for t in trades if (t.realized_pnl or 0) > 0)
        losses = abs(sum(t.realized_pnl for t in trades if (t.realized_pnl or 0) < 0))
        profit_factor = profits / max(1e-9, losses)

        trade_dicts = [
            {
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "realized_pnl": t.realized_pnl,
                "timestamp": t.timestamp.isoformat(),
            }
            for t in trades
        ]

        return StrategyReport(
            strategy_id=strategy_id,
            total_trades=total_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=None,
            max_drawdown=0.0,
            equity_curve=[],
            trades=trade_dicts,
        )

    def generate_portfolio_report(self, portfolio: Portfolio) -> PortfolioReport:
        """Generate portfolio summary report.

        Args:
            portfolio: Portfolio instance.

        Returns:
            PortfolioReport.
        """
        return PortfolioReport(
            account_id=portfolio.account_id,
            timestamp=datetime.now(timezone.utc),
            balances=portfolio.get_all_balances(),
            positions=[p.to_dict() for p in portfolio.get_all_positions()],
            total_equity=0.0,  # Requires external prices
            unrealized_pnl=portfolio.total_unrealized_pnl,
            realized_pnl=portfolio.total_realized_pnl,
        )
