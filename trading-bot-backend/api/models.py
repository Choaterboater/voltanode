"""Pydantic request and response models for the API."""

from __future__ import annotations

from datetime import datetime, date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from bot.config import AssetClass, OrderSide, OrderType


# ── Portfolio ──

class PositionResponse(BaseModel):
    """Position response model."""
    symbol: str
    side: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    market_value: float
    stop_loss: float | None = None
    take_profit: float | None = None


class PortfolioResponse(BaseModel):
    """Portfolio response model."""
    account_id: str
    balances: Dict[str, float]
    positions: List[PositionResponse]
    total_equity: float
    unrealized_pnl: float
    realized_pnl: float
    timestamp: datetime
    source: str = "paper"  # "paper" (local ledger) | "alpaca" | "binance" | other broker name
    broker_connected: bool = False


class DepositRequest(BaseModel):
    """Deposit request model."""
    asset: str
    amount: float


# ── Orders ──

class OrderRequest(BaseModel):
    """Order request model."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    account_id: str = "default"
    strategy_id: str | None = None
    asset_class: AssetClass | None = None


class OrderResponse(BaseModel):
    """Order response model."""
    order_id: str
    status: str
    filled_qty: float
    avg_fill_price: float | None = None
    fee: float
    created_at: datetime


# ── Strategies ──

class StrategyInfo(BaseModel):
    """Strategy info model."""
    strategy_id: str
    strategy_type: str
    is_active: bool
    config: Dict[str, Any]
    metrics: Dict[str, Any] | None = None


class StrategyListResponse(BaseModel):
    """Strategy list response."""
    strategies: List[StrategyInfo]


class StrategyToggleRequest(BaseModel):
    """Strategy toggle request."""
    strategy_id: str
    active: bool


class StrategyRegisterRequest(BaseModel):
    """Strategy registration request."""
    strategy_type: str
    config: Dict[str, Any] | None = None


# ── Backtest ──

class BacktestRequest(BaseModel):
    """Backtest request model."""
    strategy_type: str
    symbol: str
    asset_class: AssetClass = AssetClass.CRYPTO
    start_date: date
    end_date: date
    timeframe: str = "1d"
    initial_balance: Dict[str, float] = Field(default_factory=lambda: {"USDT": 10000.0})
    config: Dict[str, Any] | None = None


class BacktestResponse(BaseModel):
    """Backtest response model."""
    backtest_id: str
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int
    equity_curve_url: str | None = None
    trades_csv_url: str | None = None


# ── Market ──

class PriceResponse(BaseModel):
    """Price response model."""
    symbol: str
    price: float
    bid: float | None = None
    ask: float | None = None
    timestamp: datetime


class OHLCVBar(BaseModel):
    """Single OHLCV bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVResponse(BaseModel):
    """OHLCV response model."""
    symbol: str
    timeframe: str
    data: List[OHLCVBar]


# ── Engine ──

class EngineStatusResponse(BaseModel):
    """Engine status response."""
    running: bool
    account_count: int
    strategy_count: int
    tick_interval: float


# ── Reports ──

class DailyReportResponse(BaseModel):
    """Daily report response."""
    date: str
    starting_equity: float
    ending_equity: float
    realized_pnl: float
    unrealized_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    top_gainer: str | None = None
    top_loser: str | None = None
