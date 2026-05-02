"""Repository classes for CRUD operations on database records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from data.storage import (
    PortfolioSnapshot,
    PositionRecord,
    StrategyPerformance,
    TradeRecord,
)
from bot.portfolio import Portfolio


class TradeRepository:
    """CRUD for trade records."""

    def __init__(self, session: Session) -> None:
        """Initialize trade repository.

        Args:
            session: SQLAlchemy session.
        """
        self.session = session

    def create(self, record: Dict[str, Any]) -> int:
        """Create a trade record.

        Args:
            record: Trade record dictionary.

        Returns:
            Record ID.
        """
        trade = TradeRecord(**record)
        self.session.add(trade)
        self.session.commit()
        return trade.id

    def get_by_strategy(self, strategy_id: str, limit: int = 100) -> List[TradeRecord]:
        """Get trades by strategy.

        Args:
            strategy_id: Strategy ID.
            limit: Maximum records.

        Returns:
            List of TradeRecord.
        """
        return (
            self.session.query(TradeRecord)
            .filter(TradeRecord.strategy_id == strategy_id)
            .order_by(TradeRecord.timestamp.desc())
            .limit(limit)
            .all()
        )

    def get_by_account(
        self,
        account_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> List[TradeRecord]:
        """Get trades by account and date range.

        Args:
            account_id: Account ID.
            start: Start datetime.
            end: End datetime.

        Returns:
            List of TradeRecord.
        """
        query = self.session.query(TradeRecord).filter(TradeRecord.account_id == account_id)
        if start:
            query = query.filter(TradeRecord.timestamp >= start)
        if end:
            query = query.filter(TradeRecord.timestamp <= end)
        return query.order_by(TradeRecord.timestamp.desc()).all()

    def get_all(self, limit: int = 1000) -> List[TradeRecord]:
        """Get all trades.

        Args:
            limit: Maximum records.

        Returns:
            List of TradeRecord.
        """
        return (
            self.session.query(TradeRecord)
            .order_by(TradeRecord.timestamp.desc())
            .limit(limit)
            .all()
        )


class PortfolioSnapshotRepository:
    """CRUD for portfolio snapshots."""

    def __init__(self, session: Session) -> None:
        """Initialize snapshot repository.

        Args:
            session: SQLAlchemy session.
        """
        self.session = session

    def create_snapshot(self, portfolio: Portfolio, timestamp: datetime | None = None) -> int:
        """Create a portfolio snapshot.

        Args:
            portfolio: Portfolio to snapshot.
            timestamp: Optional timestamp.

        Returns:
            Snapshot ID.
        """
        ts = timestamp or datetime.now(timezone.utc)
        positions = [p.to_dict() for p in portfolio.get_all_positions()]
        snapshot = PortfolioSnapshot(
            account_id=portfolio.account_id,
            timestamp=ts,
            total_equity=0.0,
            cash_balance=sum(portfolio.get_all_balances().values()),
            unrealized_pnl=portfolio.total_unrealized_pnl,
            realized_pnl=portfolio.total_realized_pnl,
            positions_json=str(positions),
        )
        self.session.add(snapshot)
        self.session.commit()
        return snapshot.id

    def get_snapshots(
        self, account_id: str, start: datetime, end: datetime
    ) -> List[PortfolioSnapshot]:
        """Get snapshots for an account in a date range.

        Args:
            account_id: Account ID.
            start: Start datetime.
            end: End datetime.

        Returns:
            List of PortfolioSnapshot.
        """
        return (
            self.session.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.account_id == account_id)
            .filter(PortfolioSnapshot.timestamp >= start)
            .filter(PortfolioSnapshot.timestamp <= end)
            .order_by(PortfolioSnapshot.timestamp)
            .all()
        )

    def get_latest(self, account_id: str) -> PortfolioSnapshot | None:
        """Get latest snapshot for an account.

        Args:
            account_id: Account ID.

        Returns:
            Latest PortfolioSnapshot or None.
        """
        return (
            self.session.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.account_id == account_id)
            .order_by(PortfolioSnapshot.timestamp.desc())
            .first()
        )


class StrategyPerformanceRepository:
    """Persist strategy metrics over time."""

    def __init__(self, session: Session) -> None:
        """Initialize strategy performance repository.

        Args:
            session: SQLAlchemy session.
        """
        self.session = session

    def record(
        self, strategy_id: str, metrics: Dict[str, Any], timestamp: datetime | None = None
    ) -> int:
        """Record strategy performance.

        Args:
            strategy_id: Strategy ID.
            metrics: Metrics dictionary.
            timestamp: Optional timestamp.

        Returns:
            Record ID.
        """
        ts = timestamp or datetime.now(timezone.utc)
        record = StrategyPerformance(
            strategy_id=strategy_id,
            timestamp=ts,
            total_trades=metrics.get("total_trades", 0),
            win_rate=metrics.get("win_rate", 0.0),
            profit_factor=metrics.get("profit_factor", 0.0),
            sharpe_ratio=metrics.get("sharpe_ratio"),
            max_drawdown=metrics.get("max_drawdown", 0.0),
            total_pnl=metrics.get("total_pnl", 0.0),
        )
        self.session.add(record)
        self.session.commit()
        return record.id

    def get_history(self, strategy_id: str) -> List[StrategyPerformance]:
        """Get performance history for a strategy.

        Args:
            strategy_id: Strategy ID.

        Returns:
            List of StrategyPerformance records.
        """
        return (
            self.session.query(StrategyPerformance)
            .filter(StrategyPerformance.strategy_id == strategy_id)
            .order_by(StrategyPerformance.timestamp)
            .all()
        )
