"""Data exporter for CSV and JSON output."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from analytics.records import (
    PortfolioSnapshotRepository,
    StrategyPerformanceRepository,
    TradeRepository,
)


class DataExporter:
    """Export database records to flat files."""

    def __init__(self, db_session: Session, output_dir: str = "./exports") -> None:
        """Initialize data exporter.

        Args:
            db_session: SQLAlchemy session.
            output_dir: Output directory for exports.
        """
        self.session = db_session
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.trade_repo = TradeRepository(db_session)
        self.snapshot_repo = PortfolioSnapshotRepository(db_session)
        self.perf_repo = StrategyPerformanceRepository(db_session)

    def export_trades(
        self,
        path: str | None = None,
        account_id: str | None = None,
        strategy_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> str:
        """Export trades to CSV.

        Args:
            path: Output file path. Defaults to auto-generated.
            account_id: Filter by account.
            strategy_id: Filter by strategy.
            start: Start date filter.
            end: End date filter.

        Returns:
            File path of exported CSV.
        """
        if path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = str(self.output_dir / f"trades_{ts}.csv")

        if account_id:
            trades = self.trade_repo.get_by_account(account_id, start, end)
        else:
            trades = self.trade_repo.get_all()

        if strategy_id:
            trades = [t for t in trades if t.strategy_id == strategy_id]

        data = [
            {
                "id": t.id,
                "account_id": t.account_id,
                "order_id": t.order_id,
                "strategy_id": t.strategy_id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "fee": t.fee,
                "realized_pnl": t.realized_pnl,
                "timestamp": t.timestamp,
            }
            for t in trades
        ]
        df = pd.DataFrame(data)
        df.to_csv(path, index=False)
        return str(path)

    def export_portfolio_snapshots(
        self, path: str | None = None, account_id: str | None = None
    ) -> str:
        """Export portfolio snapshots to CSV.

        Args:
            path: Output file path.
            account_id: Filter by account.

        Returns:
            File path.
        """
        if path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = str(self.output_dir / f"portfolio_snapshots_{ts}.csv")

        if account_id:
            start = datetime.min.replace(tzinfo=timezone.utc)
            end = datetime.max.replace(tzinfo=timezone.utc)
            snapshots = self.snapshot_repo.get_snapshots(account_id, start, end)
        else:
            # Get all - limited approach
            snapshots = self.session.query(self.snapshot_repo.session.query.__class__).all()

        data = [
            {
                "id": s.id,
                "account_id": s.account_id,
                "timestamp": s.timestamp,
                "total_equity": s.total_equity,
                "cash_balance": s.cash_balance,
                "unrealized_pnl": s.unrealized_pnl,
                "realized_pnl": s.realized_pnl,
            }
            for s in snapshots
        ]
        df = pd.DataFrame(data)
        df.to_csv(path, index=False)
        return str(path)

    def export_strategy_performance(
        self, path: str | None = None, strategy_id: str | None = None
    ) -> str:
        """Export strategy performance to CSV.

        Args:
            path: Output file path.
            strategy_id: Filter by strategy.

        Returns:
            File path.
        """
        if path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = str(self.output_dir / f"strategy_performance_{ts}.csv")

        if strategy_id:
            records = self.perf_repo.get_history(strategy_id)
        else:
            from data.storage import StrategyPerformance as SP
            records = self.session.query(SP).all()

        data = [
            {
                "id": r.id,
                "strategy_id": r.strategy_id,
                "timestamp": r.timestamp,
                "total_trades": r.total_trades,
                "win_rate": r.win_rate,
                "profit_factor": r.profit_factor,
                "sharpe_ratio": r.sharpe_ratio,
                "max_drawdown": r.max_drawdown,
                "total_pnl": r.total_pnl,
            }
            for r in records
        ]
        df = pd.DataFrame(data)
        df.to_csv(path, index=False)
        return str(path)

    def export_all(self, base_path: str | None = None) -> Dict[str, str]:
        """Export everything to CSV files.

        Args:
            base_path: Base output path. Defaults to output_dir.

        Returns:
            Dict mapping table name to file path.
        """
        out = Path(base_path) if base_path else self.output_dir
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        results = {}
        results["trades"] = self.export_trades(str(out / f"trades_{ts}.csv"))
        results["portfolio_snapshots"] = self.export_portfolio_snapshots(
            str(out / f"portfolio_snapshots_{ts}.csv")
        )
        results["strategy_performance"] = self.export_strategy_performance(
            str(out / f"strategy_performance_{ts}.csv")
        )
        return results

    def export_to_json(self, table_name: str, path: str) -> str:
        """Export a table to JSON.

        Args:
            table_name: Table name.
            path: Output file path.

        Returns:
            File path.
        """
        from data.storage import (
            TradeRecord,
            PortfolioSnapshot,
            StrategyPerformance,
        )

        model_map = {
            "trades": TradeRecord,
            "portfolio_snapshots": PortfolioSnapshot,
            "strategy_performance": StrategyPerformance,
        }

        if table_name not in model_map:
            raise ValueError(f"Unknown table: {table_name}")

        records = self.session.query(model_map[table_name]).all()
        data = []
        for r in records:
            row = {c.name: getattr(r, c.name) for c in r.__table__.columns}
            # Convert datetime to ISO format
            for key, val in row.items():
                if isinstance(val, datetime):
                    row[key] = val.isoformat()
            data.append(row)

        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        return str(path)
