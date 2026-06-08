"""Tests for the paper trading engine."""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from bot.config import BotConfig, OrderSide, PositionSide
from bot.engine import PaperTradingEngine, TickData
from bot.orders import ExecutionSimulator, Order, OrderType
from bot.portfolio import Portfolio, Position, lookup_price, symbol_lookup_keys, symbols_equivalent
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
        # Market-order risk checks now use the live mark and clamp to the
        # default 20% max-position cap instead of treating BTC as $1.
        assert pos.size == pytest.approx(0.08)

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
        # Profit manager takes a 40% partial at +8%, then lets the rest run.
        assert pos.size == pytest.approx(6.0)
        assert abs(pos.unrealized_pnl - 60.0) < 5.0

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

        # Market orders must be checked against the live mark, not a $1 fallback.
        large = Order.market("BTC", OrderSide.BUY, 1.0, account_id="test")
        result = risk.check_order(large, portfolio, current_price=50000.0)
        assert result.allowed
        assert large.quantity == pytest.approx(0.04)


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


class TestSymbolNormalization:
    """Bare vs suffixed symbol keys must resolve consistently."""

    def test_symbol_lookup_keys_bare_and_suffixed(self) -> None:
        assert "BTC" in symbol_lookup_keys("BTCUSD")
        assert "BTCUSD" in symbol_lookup_keys("BTC")

    def test_symbols_equivalent(self) -> None:
        assert symbols_equivalent("BTC", "BTCUSD")
        assert not symbols_equivalent("BTC", "ETH")

    def test_lookup_price_across_aliases(self) -> None:
        prices = {"BTC": 75000.0}
        assert lookup_price(prices, "BTCUSD") == 75000.0

    def test_managed_stop_sees_bare_tick_price(self, config: BotConfig) -> None:
        """Managed stops on BTCUSD positions must fire on BTC ticks."""
        engine = PaperTradingEngine(config)
        portfolio = engine.get_portfolio("default")
        portfolio._positions["BTCUSD"] = Position(
            symbol="BTCUSD",
            side=PositionSide.LONG,
            size=0.1,
            entry_price=100000.0,
            current_price=75000.0,
            stop_loss=80000.0,
        )
        engine.on_tick(TickData(symbol="BTC", price=75000.0))
        trailing = [
            o for o in engine.get_orders()
            if o.strategy_id == "sltp_manager" and o.symbol == "BTCUSD"
        ]
        assert trailing, "expected managed stop order on BTCUSD position"


class TestProfitAwareExits:
    """Profit manager should improve win-rate behavior."""

    def test_partial_take_profit_sells_only_part_of_winner(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        portfolio = engine.get_portfolio("default")
        portfolio.open_position("TEST", PositionSide.LONG, 100.0, 100.0, stop_loss=92.0, take_profit=108.0)

        engine.on_tick(TickData(symbol="TEST", price=108.0))

        pos = portfolio.get_position("TEST")
        assert pos is not None
        assert pos.status == "open"
        assert pos.size == pytest.approx(60.0)
        assert pos.partial_profit_taken is True
        assert pos.take_profit is None
        assert any(o.strategy_id == "partial_take_profit" for o in engine.get_orders())

    def test_breakeven_and_delayed_trailing_stop(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        portfolio = engine.get_portfolio("default")
        portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0, stop_loss=92.0, take_profit=130.0)

        engine.on_tick(TickData(symbol="TEST", price=104.0))
        pos = portfolio.get_position("TEST")
        assert pos is not None
        assert pos.stop_loss == pytest.approx(100.2)

        engine.on_tick(TickData(symbol="TEST", price=110.0))
        assert pos.high_water_price == pytest.approx(110.0)
        assert pos.stop_loss == pytest.approx(105.6)

    def test_no_synthetic_two_percent_trailing_stop(self, config: BotConfig) -> None:
        engine = PaperTradingEngine(config)
        portfolio = engine.get_portfolio("default")
        portfolio.open_position("TEST", PositionSide.LONG, 10.0, 100.0)

        engine.on_tick(TickData(symbol="TEST", price=97.0))

        assert not [
            o for o in engine.get_orders()
            if o.strategy_id == "trailing_stop" and o.symbol == "TEST"
        ]

    def test_default_stop_cuts_loss_at_five_percent(self, config: BotConfig) -> None:
        """A long with no explicit stop is cut at -5% (tightened from -8%).

        Asymmetry fix: partial profit is rung at +8%, so the default stop must
        sit inside that band or the avg loss dwarfs the avg win (the 0.58
        profit factor that sank realized P&L). -4% must NOT close; -5% must.
        """
        # -4%: inside the 5% default stop, position stays open.
        e1 = PaperTradingEngine(config)
        p1 = e1.get_portfolio("default")
        p1.open_position("TEST", PositionSide.LONG, 10.0, 100.0)
        e1.on_tick(TickData(symbol="TEST", price=96.0))
        pos = p1.get_position("TEST")
        assert pos is not None and pos.status == "open"
        assert not [o for o in e1.get_orders() if o.strategy_id == "sltp_manager"]

        # -5%: hits the default stop -> full close via sltp_manager.
        e2 = PaperTradingEngine(config)
        p2 = e2.get_portfolio("default")
        p2.open_position("TEST", PositionSide.LONG, 10.0, 100.0)
        e2.on_tick(TickData(symbol="TEST", price=95.0))
        assert [
            o for o in e2.get_orders()
            if o.strategy_id == "sltp_manager" and o.symbol == "TEST"
        ], "expected the default 5% stop to close the position"
