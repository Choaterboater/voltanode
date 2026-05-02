"""SQLAlchemy ORM models for persistent storage."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Account(Base):
    """Trading account."""
    __tablename__ = "accounts"

    id = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex[:16])
    name = mapped_column(String(64), default="Default Account")
    created_at = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(default=True)

    # Relationships
    trades = relationship("TradeRecord", back_populates="account", cascade="all, delete-orphan")
    orders = relationship("OrderRecord", back_populates="account", cascade="all, delete-orphan")
    snapshots = relationship("PortfolioSnapshot", back_populates="account", cascade="all, delete-orphan")
    positions = relationship("PositionRecord", back_populates="account", cascade="all, delete-orphan")


class OHLCVRecord(Base):
    """Historical OHLCV data."""
    __tablename__ = "ohlcv"

    id = mapped_column(Integer, primary_key=True)
    symbol = mapped_column(String(32), index=True)
    asset_class = mapped_column(String(16))
    timeframe = mapped_column(String(8))
    timestamp = mapped_column(DateTime, index=True)
    open = mapped_column(Float)
    high = mapped_column(Float)
    low = mapped_column(Float)
    close = mapped_column(Float)
    volume = mapped_column(Float)

    __table_args__ = (UniqueConstraint("symbol", "timeframe", "timestamp"),)


class PriceTick(Base):
    """Real-time price tick."""
    __tablename__ = "price_ticks"

    id = mapped_column(Integer, primary_key=True)
    symbol = mapped_column(String(32), index=True)
    price = mapped_column(Float)
    bid = mapped_column(Float, nullable=True)
    ask = mapped_column(Float, nullable=True)
    timestamp = mapped_column(DateTime, index=True)


class TradeRecord(Base):
    """Completed trade record."""
    __tablename__ = "trades"

    id = mapped_column(Integer, primary_key=True)
    account_id = mapped_column(String(32), ForeignKey("accounts.id"), index=True)
    order_id = mapped_column(String(36), index=True)
    strategy_id = mapped_column(String(32), index=True, nullable=True)
    symbol = mapped_column(String(32), index=True)
    side = mapped_column(String(8))  # "buy" | "sell"
    quantity = mapped_column(Float)
    price = mapped_column(Float)
    fee = mapped_column(Float, default=0.0)
    realized_pnl = mapped_column(Float, nullable=True)
    timestamp = mapped_column(DateTime, index=True)

    account = relationship("Account", back_populates="trades")


class OrderRecord(Base):
    """Order record."""
    __tablename__ = "orders"

    id = mapped_column(String(36), primary_key=True)
    account_id = mapped_column(String(32), ForeignKey("accounts.id"), index=True)
    strategy_id = mapped_column(String(32), index=True, nullable=True)
    symbol = mapped_column(String(32), index=True)
    side = mapped_column(String(8))
    order_type = mapped_column(String(16))
    quantity = mapped_column(Float)
    price = mapped_column(Float, nullable=True)
    stop_price = mapped_column(Float, nullable=True)
    filled_quantity = mapped_column(Float, default=0.0)
    avg_fill_price = mapped_column(Float, nullable=True)
    status = mapped_column(String(16), default="pending")
    fee = mapped_column(Float, default=0.0)
    created_at = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    account = relationship("Account", back_populates="orders")
    fills = relationship("OrderFill", back_populates="order", cascade="all, delete-orphan")


class OrderFill(Base):
    """Individual fill record for an order."""
    __tablename__ = "order_fills"

    id = mapped_column(Integer, primary_key=True)
    order_id = mapped_column(String(36), ForeignKey("orders.id"), index=True)
    filled_qty = mapped_column(Float)
    filled_price = mapped_column(Float)
    fee = mapped_column(Float)
    slippage = mapped_column(Float)
    timestamp = mapped_column(DateTime)

    order = relationship("OrderRecord", back_populates="fills")


class PortfolioSnapshot(Base):
    """Portfolio snapshot at a point in time."""
    __tablename__ = "portfolio_snapshots"

    id = mapped_column(Integer, primary_key=True)
    account_id = mapped_column(String(32), ForeignKey("accounts.id"), index=True)
    timestamp = mapped_column(DateTime, index=True)
    total_equity = mapped_column(Float)
    cash_balance = mapped_column(Float)
    unrealized_pnl = mapped_column(Float)
    realized_pnl = mapped_column(Float)
    positions_json = mapped_column(Text)

    account = relationship("Account", back_populates="snapshots")


class StrategyPerformance(Base):
    """Strategy performance metrics over time."""
    __tablename__ = "strategy_performance"

    id = mapped_column(Integer, primary_key=True)
    strategy_id = mapped_column(String(32), index=True)
    timestamp = mapped_column(DateTime, index=True)
    total_trades = mapped_column(Integer)
    win_rate = mapped_column(Float)
    profit_factor = mapped_column(Float)
    sharpe_ratio = mapped_column(Float, nullable=True)
    max_drawdown = mapped_column(Float)
    total_pnl = mapped_column(Float)


class PositionRecord(Base):
    """Position record."""
    __tablename__ = "positions"

    id = mapped_column(Integer, primary_key=True)
    account_id = mapped_column(String(32), ForeignKey("accounts.id"), index=True)
    symbol = mapped_column(String(32), index=True)
    side = mapped_column(String(8))
    size = mapped_column(Float)
    entry_price = mapped_column(Float)
    current_price = mapped_column(Float)
    unrealized_pnl = mapped_column(Float)
    realized_pnl = mapped_column(Float)
    opened_at = mapped_column(DateTime)
    closed_at = mapped_column(DateTime, nullable=True)
    status = mapped_column(String(16), default="open")

    account = relationship("Account", back_populates="positions")


def create_engine_instance(db_path: str = "sqlite:///data/bot.db") -> Any:
    """Create SQLAlchemy engine."""
    return create_engine(db_path, echo=False)


def create_session_factory(engine: Any) -> sessionmaker[Session]:
    """Create a session factory bound to the engine."""
    return sessionmaker(bind=engine)


def init_db(db_path: str = "sqlite:///data/bot.db") -> Any:
    """Initialize database by creating all tables.

    Args:
        db_path: Database path/URL.

    Returns:
        SQLAlchemy engine instance.
    """
    import os
    db_file = db_path.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(os.path.abspath(db_file)), exist_ok=True)
    engine = create_engine_instance(db_path)
    Base.metadata.create_all(engine)
    return engine
