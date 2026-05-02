"""Tests for the paper trading engine."""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from bot.config import BotConfig, OrderSide, PositionSide
from bot.engine import PaperTradingEngine, TickData
from bot.orders import ExecutionSimulator, Order, OrderType
from bot.portfolio import Portfolio, Position
from bot.risk import DrawdownMonitor, PositionSizer, RiskManager, RiskConfig


@pytest.fixture
def config() -> BotConfig:
    return BotConfig()


@pytest.fixture
def engine(config: BotConfig) -> PaperTradingEngine:
    return PaperTradingEngine(config)


class TestOrderExecution:
    """Test order execution and fill simulation."""

    def test_market_order_fill(self, engine: PaperTradingEngine) -> None:
        """Submit market order, verify fill at current price."""
        order = Order.market("BTC", OrderSide.BUY, 0.1, account_id="default")
        engine.submit_order(order)
        
        engine.on_tick(TickData(symbol="BTC", price=50000.0))
        
        assert order.is_filled
        assert order.filled_quantity > 0
        assert order.status.value == "filled"
        
        portfolio = engine.get_portfolio("default")
        assert len(portfolio.get_all_positions()) == 1
        pos = portfolio.get_position("BTC")
        assert pos is not None
        assert pos.side == PositionSide.LONG
        assert pos.size == 0.1

    def test_limit_order_fill(self, engine: PaperTradingEngine) -> None:
        """Submit limit buy below price, verify fill when price drops."""
        order = Order.limit("ETH", OrderSide.BUY, 0.5, price=3000.0, account_id="default")
        engine.submit_order(order)
        
        # Price above limit - should not fill
        engine.on_tick(TickData(symbol="ETH", price=3100.0))
        assert not order.is_filled
        
        # Price at limit - should fill
        engine.on_tick(TickData(symbol="ETH", price=3000.0))
        assert order.is_filled

    def test_portfolio_pnl(self, engine: PaperTradingEngine) -> None:
        """Test P&L calculation after buy and sell."""
        # Buy at 100
        buy_order = Order.market("TEST", OrderSide.BUY, 10.0, account_id="default")
        engine.submit_order(buy_order)
        engine.on_tick(TickData(symbol="TEST", price=100.0))
        
        portfolio = engine.get_portfolio("default")
        pos = portfolio.get_position("TEST")
        assert pos is not None
        assert abs(pos.unrealized_pnl) < 0.01  # Near-zero after entry (slippage may apply)
        
        # Price goes to 110
        engine.on_tick(TickData(symbol="TEST", price=110.0))
        pos = portfolio.get_position("TEST")
        # Allow for slippage on entry: expected ~100 but may be slightly less
        assert abs(pos.unrealized_pnl - 100.0) < 5.0

    def test_short_position_pnl(self, engine: PaperTradingEngine) -> None:
        """Test that selling without a position is rejected (prevents infinite money bug)."""
        sell_order = Order.market("TEST", OrderSide.SELL, 5.0, account_id="default")
        engine.submit_order(sell_order)
        engine.on_tick(TickData(symbol="TEST", price=100.0))
        
        # Order should be rejected since we don't own TEST
        assert sell_order.status.value == "rejected"
        
        # Now buy first, then sell to close
        buy_order = Order.market("TEST", OrderSide.BUY, 5.0, account_id="default")
        engine.submit_order(buy_order)
        engine.on_tick(TickData(symbol="TEST", price=100.0))
        
        portfolio = engine.get_portfolio("default")
        pos = portfolio.get_position("TEST")
        assert pos is not None
        assert pos.side == PositionSide.LONG
        
        # Sell to close
        close_order = Order.market("TEST", OrderSide.SELL, 5.0, account_id="default")
        engine.submit_order(close_order)
        engine.on_tick(TickData(symbol="TEST", price=110.0))
        assert close_order.is_filled
        # Position should be closed
        assert portfolio.get_position("TEST") is None

    def test_execution_simulator(self) -> None:
        """Test slippage and fee calculation."""
        sim = ExecutionSimulator(fee_rate=0.001, slippage_bps=10.0)
        
        # Buy slippage: price should be higher
        slippage_price = sim.apply_slippage(100.0, OrderSide.BUY)
        assert slippage_price > 100.0
        
        # Sell slippage: price should be lower
        slippage_price = sim.apply_slippage(100.0, OrderSide.SELL)
        assert slippage_price < 100.0
        
        # Fee calculation
        fee = sim.calculate_fee(10000.0)
        assert fee == 10.0


class TestPortfolio:
    """Test portfolio management."""

    def test_deposit_withdraw(self) -> None:
        """Test deposit and withdraw operations."""
        portfolio = Portfolio("test", {"USDT": 10000.0})
        
        portfolio.deposit("USDT", 5000.0)
        assert portfolio.get_balance("USDT") == 15000.0
        
        success = portfolio.withdraw("USDT", 2000.0)
        assert success
        assert portfolio.get_balance("USDT") == 13000.0
        
        failure = portfolio.withdraw("USDT", 50000.0)
        assert not failure

    def test_position_open_close(self) -> None:
        """Test opening and closing positions."""
        portfolio = Portfolio("test", {"USDT": 10000.0})
        
        pos = portfolio.open_position("BTC", PositionSide.LONG, 1.0, 50000.0)
        assert pos.symbol == "BTC"
        assert pos.size == 1.0
        assert pos.entry_price == 50000.0
        
        pos.update_price(55000.0)
        assert pos.unrealized_pnl == 5000.0
        
        closed_pos, realized_pnl = portfolio.close_position("BTC", 55000.0)
        assert realized_pnl == 5000.0
        assert portfolio.get_position("BTC") is None

    def test_multi_asset_balances(self) -> None:
        """Test multiple asset balances."""
        portfolio = Portfolio("test", {"USDT": 5000.0, "BTC": 0.5})
        
        assert portfolio.get_balance("USDT") == 5000.0
        assert portfolio.get_balance("BTC") == 0.5
        assert portfolio.get_balance("ETH") == 0.0


class TestRiskManager:
    """Test risk management."""

    def test_drawdown_monitor(self) -> None:
        """Test drawdown monitoring."""
        monitor = DrawdownMonitor(max_drawdown_pct=0.10)
        
        monitor.update(10000.0)
        assert not monitor.is_breached()
        
        monitor.update(9500.0)  # 5% drawdown
        assert not monitor.is_breached()
        
        monitor.update(8900.0)  # 11% drawdown
        assert monitor.is_breached()

    def test_position_sizer(self) -> None:
        """Test position sizing methods."""
        # Fixed
        assert PositionSizer.fixed(1.5) == 1.5
        
        # Percentage
        size = PositionSizer.percentage_of_equity(10000.0, 0.02, 100.0)
        assert size == 2.0  # 2% of $10k = $200 / $100 = 2 units
        
        # Kelly
        kelly = PositionSizer.kelly_criterion(0.55, 100.0, 50.0)
        assert 0 <= kelly <= 1.0
        
        # Volatility-based
        size = PositionSizer.volatility_based(10000.0, 5.0, 0.02, 100.0)
        assert size > 0

    def test_risk_order_check(self) -> None:
        """Test risk manager order validation."""
        risk_config = RiskConfig(max_position_size_pct=0.20)
        risk = RiskManager(risk_config)
        portfolio = Portfolio("test", {"USDT": 10000.0})
        
        # Small order should pass
        order = Order.market("BTC", OrderSide.BUY, 0.01, account_id="test")
        result = risk.check_order(order, portfolio)
        assert result.allowed


class TestEngine:
    """Test engine orchestration."""

    def test_multi_account_isolation(self, config: BotConfig) -> None:
        """Test that accounts are isolated."""
        engine = PaperTradingEngine(config)
        engine.create_account("acct1", {"USDT": 5000.0})
        engine.create_account("acct2", {"USDT": 10000.0})
        
        assert engine.get_portfolio("acct1").get_balance("USDT") == 5000.0
        assert engine.get_portfolio("acct2").get_balance("USDT") == 10000.0

    def test_reset(self, engine: PaperTradingEngine) -> None:
        """Test engine reset."""
        order = Order.market("BTC", OrderSide.BUY, 0.1)
        engine.submit_order(order)
        engine.on_tick(TickData(symbol="BTC", price=50000.0))
        
        assert len(engine.get_trade_history()) > 0
        
        engine.reset("default")
        assert len(engine.get_trade_history("default")) == 0
        assert len(engine.get_open_positions("default")) == 0

    def test_cancel_order(self, engine: PaperTradingEngine) -> None:
        """Test order cancellation."""
        order = Order.limit("ETH", OrderSide.BUY, 1.0, price=2000.0)
        engine.submit_order(order)
        
        assert engine.cancel_order(order.id)
        from bot.orders import OrderStatus
        assert engine.get_order_status(order.id) == OrderStatus.CANCELED
