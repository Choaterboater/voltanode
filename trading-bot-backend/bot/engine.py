"""Paper trading engine — core orchestrator."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from bot.config import BotConfig, OrderSide
from bot.orders import ExecutionSimulator, FillResult, Order, OrderStatus, OrderType
from bot.portfolio import Portfolio, Position, PositionSide
from bot.risk import RiskAlert, RiskCheckResult, RiskManager

# Live trading imports
from brokers.base import BrokerAdapter, BrokerConnectionError
from safety.kill_switch import KillSwitch, KillSwitchError
from safety.daily_tracker import DailyPnlTracker
from safety.limits import SafetyValidator, SafetyValidationError
from safety.notifier import SafetyNotifier


@dataclass
class TickData:
    """Price tick data."""
    symbol: str
    price: float
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Trade:
    """Recorded trade."""
    id: str
    order_id: str
    strategy_id: str | None
    symbol: str
    side: str
    quantity: float
    price: float
    fee: float
    realized_pnl: float | None
    timestamp: datetime


class PaperTradingEngine:
    """Core paper trading engine with multi-account support."""

    def __init__(
        self,
        config: BotConfig,
        market_data: Any | None = None,
        risk_manager: RiskManager | None = None,
        db_session: Any | None = None,
    ) -> None:
        """Initialize the paper trading engine.

        Args:
            config: Bot configuration.
            market_data: Market data service (optional).
            risk_manager: Risk manager instance (optional).
            db_session: Database session (optional).
        """
        self.config = config
        self.market_data = market_data
        self.risk_manager = risk_manager or RiskManager(config.risk)
        self.db_session = db_session
        self.execution = ExecutionSimulator(
            fee_rate=config.risk.fee_rate,
            slippage_model=config.risk.slippage_model,
            slippage_bps=config.risk.slippage_bps,
        )

        self._portfolios: Dict[str, Portfolio] = {}
        self._strategies: Dict[str, List[Any]] = {}  # account_id -> strategies
        self._orders: Dict[str, Dict[str, Order]] = {}  # account_id -> {order_id: Order}
        self._fills: List[FillResult] = []
        self._trades: List[Trade] = []
        self._running: bool = False
        self._current_prices: Dict[str, float] = {}

        # Initialize default account
        default_balance = config.backtest.default_initial_balance if config.backtest else {"USDT": 10000.0}
        self._portfolios["default"] = Portfolio("default", default_balance)
        self._orders["default"] = {}
        self._strategies["default"] = []

    # ── Lifecycle ──

    def register_strategy(self, strategy: Any, account_id: str = "default") -> None:
        """Attach a strategy to an account.

        Args:
            strategy: Strategy instance.
            account_id: Account to attach to.
        """
        if account_id not in self._strategies:
            self._strategies[account_id] = []
        self._strategies[account_id].append(strategy)

    def create_account(self, account_id: str, initial_balance: Dict[str, float]) -> Portfolio:
        """Create a new account with initial balance.

        Args:
            account_id: Unique account identifier.
            initial_balance: Initial balance mapping.

        Returns:
            The new Portfolio.
        """
        self._portfolios[account_id] = Portfolio(account_id, initial_balance)
        self._orders[account_id] = {}
        self._strategies[account_id] = []
        return self._portfolios[account_id]

    def start(self) -> None:
        """Begin the tick loop (blocking in sync mode)."""
        self._running = True

    def stop(self) -> None:
        """Gracefully stop the tick loop."""
        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if engine is running."""
        return self._running

    def reset(self, account_id: str | None = None) -> None:
        """Reset all state (or single account).

        Args:
            account_id: Optional account to reset. If None, reset all.
        """
        if account_id is None:
            default_balance = self.config.backtest.default_initial_balance if self.config.backtest else {"USDT": 10000.0}
            self._portfolios = {"default": Portfolio("default", default_balance)}
            self._orders = {"default": {}}
            self._strategies = {"default": []}
            self._fills.clear()
            self._trades.clear()
            self._current_prices.clear()
            self.risk_manager.reset()
        else:
            if account_id in self._portfolios:
                old_balance = self._portfolios[account_id].get_all_balances()
                self._portfolios[account_id] = Portfolio(account_id, old_balance)
                self._orders[account_id] = {}

    # ── Order Handling ──

    def submit_order(self, order: Order, account_id: str = "default") -> str:
        """Submit an order.

        Args:
            order: The order to submit.
            account_id: Target account.

        Returns:
            Order ID.
        """
        if account_id not in self._orders:
            self._orders[account_id] = {}
        self._orders[account_id][order.id] = order
        return order.id

    def cancel_order(self, order_id: str, account_id: str = "default") -> bool:
        """Cancel a pending order.

        Args:
            order_id: Order ID to cancel.
            account_id: Account ID.

        Returns:
            True if cancelled successfully.
        """
        orders = self._orders.get(account_id, {})
        if order_id in orders:
            order = orders[order_id]
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELED
                return True
        return False

    def get_order_status(self, order_id: str, account_id: str = "default") -> OrderStatus | None:
        """Return status of an order."""
        orders = self._orders.get(account_id, {})
        order = orders.get(order_id)
        return order.status if order else None

    def get_orders(self, account_id: str = "default") -> List[Order]:
        """Get all orders for an account."""
        return list(self._orders.get(account_id, {}).values())

    def get_pending_orders(self, account_id: str = "default") -> List[Order]:
        """Get pending orders for an account."""
        return [o for o in self.get_orders(account_id) if o.status == OrderStatus.PENDING]

    def _get_quote_asset(self, symbol: str) -> str:
        """Derive quote asset from symbol (e.g. BTC/USD -> USD, BTCUSDT -> USDT)."""
        sym = symbol.upper()
        if "/USD" in sym or sym.endswith("-USD"):
            return "USD"
        if sym.endswith("USDT"):
            return "USDT"
        return "USD"

    def execute_order(self, order: Order, current_price: float) -> FillResult | None:
        """Simulate order execution.

        Args:
            order: The order to execute.
            current_price: Current market price.

        Returns:
            FillResult if filled, None otherwise.
        """
        portfolio = self._portfolios.get(order.account_id)
        if portfolio is None:
            return None

        # Balance sufficiency check
        quote_asset = self._get_quote_asset(order.symbol)
        order_cost = order.quantity * current_price
        if order.side == OrderSide.BUY:
            if portfolio.get_balance(quote_asset) < order_cost:
                order.status = OrderStatus.REJECTED
                return None
        elif order.side == OrderSide.SELL:
            pos = portfolio.get_position(order.symbol)
            if pos is None or pos.size < order.quantity:
                order.status = OrderStatus.REJECTED
                return None

        # Risk check
        risk_result = self.risk_manager.check_order(order, portfolio)
        if not risk_result.allowed:
            order.status = OrderStatus.REJECTED
            return None

        fill = self.execution.execute(order, current_price)
        if fill:
            order.filled_quantity += fill.filled_qty
            order.avg_fill_price = (
                (order.avg_fill_price or 0.0) * (order.filled_quantity - fill.filled_qty)
                + fill.filled_price * fill.filled_qty
            ) / order.filled_quantity if order.filled_quantity > 0 else fill.filled_price
            order.fee += fill.fee
            order.status = OrderStatus.FILLED

            self._fills.append(fill)
            self._update_portfolio_on_fill(order, fill, portfolio)
            self.on_fill(fill)
        return fill

    def _update_portfolio_on_fill(
        self, order: Order, fill: FillResult, portfolio: Portfolio
    ) -> None:
        """Update portfolio state after a fill."""
        symbol = order.symbol
        is_buy = order.side == OrderSide.BUY
        is_sell = order.side == OrderSide.SELL

        # Update cash balance (derive quote asset from symbol)
        quote_asset = self._get_quote_asset(order.symbol)
        cost = fill.filled_qty * fill.filled_price + fill.fee

        if is_buy:
            portfolio.withdraw(quote_asset, cost)
            # Open or increase long position
            pos = portfolio.get_position(symbol)
            if pos and pos.side.value == "long":
                # Average up
                total_cost = pos.cost_basis + fill.filled_qty * fill.filled_price
                total_size = pos.size + fill.filled_qty
                pos.entry_price = total_cost / total_size
                pos.size = total_size
                pos.update_price(fill.filled_price)
            elif pos and pos.side.value == "short":
                # Reduce short
                if fill.filled_qty >= pos.size:
                    _, realized_pnl = portfolio.close_position(symbol, fill.filled_price)
                    fill.realized_pnl = realized_pnl
                else:
                    pos.size -= fill.filled_qty
                    pos.update_price(fill.filled_price)
            else:
                portfolio.open_position(symbol, PositionSide.LONG, fill.filled_qty, fill.filled_price)
        elif is_sell:
            portfolio.deposit(quote_asset, fill.filled_qty * fill.filled_price - fill.fee)
            pos = portfolio.get_position(symbol)
            if pos and pos.side.value == "long":
                if fill.filled_qty >= pos.size:
                    _, realized_pnl = portfolio.close_position(symbol, fill.filled_price)
                    fill.realized_pnl = realized_pnl
                else:
                    pos.size -= fill.filled_qty
                    pos.entry_price = (pos.cost_basis - fill.filled_qty * fill.filled_price) / pos.size
                    pos.update_price(fill.filled_price)
            elif pos and pos.side.value == "short":
                # Increase short
                total_cost = pos.cost_basis + fill.filled_qty * fill.filled_price
                total_size = pos.size + fill.filled_qty
                pos.entry_price = total_cost / total_size
                pos.size = total_size
                pos.update_price(fill.filled_price)
            else:
                # Open short
                portfolio.open_position(symbol, PositionSide.SHORT, fill.filled_qty, fill.filled_price)

        portfolio.record_trade(
            symbol=symbol,
            side=order.side.value,
            quantity=fill.filled_qty,
            price=fill.filled_price,
            fee=fill.fee,
            realized_pnl=fill.realized_pnl,
        )

        # Record Trade object
        self._trades.append(
            Trade(
                id=str(uuid.uuid4()),
                order_id=fill.order_id,
                strategy_id=order.strategy_id,
                symbol=symbol,
                side=order.side.value,
                quantity=fill.filled_qty,
                price=fill.filled_price,
                fee=fill.fee,
                realized_pnl=fill.realized_pnl,
                timestamp=fill.timestamp,
            )
        )

    # ── Portfolio ──

    def get_portfolio(self, account_id: str = "default") -> Portfolio:
        """Return current portfolio for an account."""
        return self._portfolios[account_id]

    def get_all_portfolios(self) -> Dict[str, Portfolio]:
        """Return all account portfolios."""
        return dict(self._portfolios)

    # ── Events ──

    def on_tick(self, tick: TickData) -> None:
        """Process a price tick.

        Args:
            tick: Price tick data.
        """
        self._current_prices[tick.symbol] = tick.price

        # Update all portfolios with new price
        for portfolio in self._portfolios.values():
            portfolio.update_position_price(tick.symbol, tick.price)

        # Notify registered strategies of tick
        for account_id, strategies in self._strategies.items():
            for strategy in strategies:
                if hasattr(strategy, "on_tick"):
                    portfolio = self._portfolios.get(account_id)
                    signal = strategy.on_tick(tick, portfolio)
                    if signal is not None and hasattr(signal, "to_order"):
                        order = signal.to_order(account_id)
                        if order is not None:
                            self.submit_order(order, account_id)
                            # Auto-execute market orders immediately
                            if order.order_type.value == "market" and tick.price:
                                self.execute_order(order, tick.price)

        # Check pending orders for fills
        for account_id, orders in self._orders.items():
            for order in list(orders.values()):
                if order.status == OrderStatus.PENDING and order.symbol == tick.symbol:
                    self.execute_order(order, tick.price)

        # Check trailing stops
        for portfolio in self._portfolios.values():
            stops = self.risk_manager.update_trailing_stops(
                portfolio, self._current_prices
            )
            for stop_order in stops:
                self.submit_order(stop_order, stop_order.account_id)

        # Risk alerts
        for portfolio in self._portfolios.values():
            alerts = self.risk_manager.check_portfolio_limits(portfolio)
            for alert in alerts:
                pass  # Could log or emit events

    def on_fill(self, fill: FillResult) -> None:
        """Callback when an order is filled."""
        # Find the account_id for this fill by looking up the order
        account_id = "default"
        for acc_id, orders in self._orders.items():
            if fill.order_id in orders:
                account_id = acc_id
                break
        portfolio = self._portfolios.get(account_id, self._portfolios.get("default"))
        # Notify strategies
        for strategies in self._strategies.values():
            for strategy in strategies:
                if hasattr(strategy, "on_fill"):
                    strategy.on_fill(fill, portfolio)

    # ── Queries ──

    def get_open_positions(self, account_id: str = "default") -> List[Position]:
        """Get open positions for an account."""
        return self._portfolios[account_id].get_all_positions()

    def get_trade_history(self, account_id: str | None = None) -> List[Trade]:
        """Get trade history.

        Args:
            account_id: Optional account filter.

        Returns:
            List of Trade objects.
        """
        if account_id:
            return [t for t in self._trades if t.order_id in self._orders.get(account_id, {})]
        return list(self._trades)

    def get_current_price(self, symbol: str) -> float | None:
        """Get the last known price for a symbol."""
        return self._current_prices.get(symbol)

    def get_fills(self) -> List[FillResult]:
        """Get all fill results."""
        return list(self._fills)

    def get_risk_alerts(self) -> List[RiskAlert]:
        """Get current risk alerts for all portfolios."""
        alerts: List[RiskAlert] = []
        for portfolio in self._portfolios.values():
            alerts.extend(self.risk_manager.check_portfolio_limits(portfolio))
        return alerts


class LiveTradingEngine(PaperTradingEngine):
    """Live trading engine with real broker execution and hard safety rails.

    Inherits paper-trading portfolio tracking while sending orders to a real
    broker adapter. Enforces:
      - Kill switch (hard halt)
      - Daily P&L tracker (auto-reset at midnight)
      - Safety validator (position size, exposure, rate limits, symbol lists)
      - Broker connectivity checks
    """

    def __init__(
        self,
        config: BotConfig,
        broker: BrokerAdapter,
        notifier: SafetyNotifier | None = None,
    ) -> None:
        """Initialize live trading engine.

        Args:
            config: Bot configuration.
            broker: Broker adapter instance (connected externally or lazily).
            notifier: Optional safety notifier for alerts.
        """
        super().__init__(config)
        self.broker = broker
        self.live_mode = True
        self.kill_switch = KillSwitch()
        self.daily_tracker = DailyPnlTracker()
        self.safety_validator = SafetyValidator()

        if notifier is None:
            # Build notifier from safety config
            email_cfg = {}
            if config.safety.smtp_host:
                email_cfg = {
                    "smtp_host": config.safety.smtp_host,
                    "smtp_port": config.safety.smtp_port,
                    "smtp_user": config.safety.smtp_user,
                    "smtp_password": config.safety.smtp_password_encrypted,
                    "email_from": config.safety.alert_email_from,
                    "email_to": config.safety.alert_email_to,
                }
            notifier = SafetyNotifier(
                webhook_url=config.safety.webhook_url or None,
                webhook_headers=config.safety.webhook_headers or None,
                email_config=email_cfg if email_cfg else None,
            )
        self.notifier = notifier

    def execute_order(
        self, order: Order, current_price: float | None = None
    ) -> FillResult:
        """Execute an order via the real broker with full safety checks.

        Args:
            order: The order to execute.
            current_price: Optional price hint (broker usually provides real price).

        Returns:
            FillResult from the broker.

        Raises:
            KillSwitchError: If kill switch is active.
            BrokerConnectionError: If broker is not connected.
            SafetyValidationError: If order violates safety limits.
        """
        # 1. Hard kill switch check
        self.kill_switch.check()

        # 2. Broker connectivity
        if not self.broker.is_connected():
            if self.config.safety.kill_switch_on_disconnect:
                self.kill_switch.activate("Broker disconnected")
                self.notifier.alert("critical", "Kill switch activated: broker disconnected")
            raise BrokerConnectionError("Broker disconnected")

        # 3. Get portfolio for safety checks
        portfolio = self.get_portfolio(order.account_id)

        # 4. Safety validation
        self.safety_validator.validate_order(
            order,
            portfolio,
            self.config,
            self.daily_tracker.daily_pnl,
        )

        # 5. Execute via broker
        fill = self.broker.place_order(order)

        # 6. Record fill
        self.daily_tracker.record(fill)
        self._fills.append(fill)
        self._update_portfolio_on_fill(order, fill, portfolio)
        self.on_fill(fill)

        # 7. Post-fill safety check (daily loss limit)
        self._check_safety_after_fill()

        return fill

    def _check_safety_after_fill(self) -> None:
        """Check safety limits after a fill and activate kill switch if needed."""
        max_loss = getattr(self.config.safety, "max_daily_loss_pct", 5.0)
        if self.daily_tracker.daily_pnl < -max_loss:
            self.kill_switch.activate(f"Daily loss limit exceeded: {self.daily_tracker.daily_pnl:.2f}%")
            self.notifier.alert(
                "critical",
                f"Kill switch activated: daily loss {self.daily_tracker.daily_pnl:.2f}% exceeds limit {max_loss}%",
            )

    def get_live_status(self) -> dict:
        """Return comprehensive live trading status."""
        return {
            "live_mode": self.live_mode,
            "broker_connected": self.broker.is_connected(),
            "broker_name": self.broker.name,
            "kill_switch": self.kill_switch.status(),
            "daily_tracker": self.daily_tracker.get_status(),
            "safety": self.safety_validator.get_status(),
        }

    def get_broker_balance(self) -> Dict[str, float]:
        """Fetch live balance from broker."""
        if not self.broker.is_connected():
            raise BrokerConnectionError("Broker not connected")
        return self.broker.get_balance()

    def get_broker_positions(self) -> List[dict]:
        """Fetch live positions from broker."""
        if not self.broker.is_connected():
            raise BrokerConnectionError("Broker not connected")
        return self.broker.get_positions()


if __name__ == "__main__":
    # Demo script
    print("=== Paper Trading Engine Demo ===")
    config = BotConfig()
    engine = PaperTradingEngine(config)
    engine.start()

    # Submit a buy order
    order = Order.market("BTC", OrderSide.BUY, 0.5, account_id="default")
    engine.submit_order(order)
    print(f"Submitted order: {order.id}")

    # Simulate a price tick
    engine.on_tick(TickData(symbol="BTC", price=45000.0))
    print(f"Order status after tick: {engine.get_order_status(order.id)}")

    portfolio = engine.get_portfolio("default")
    print(f"Portfolio balance: {portfolio.get_all_balances()}")
    print(f"Open positions: {[p.symbol for p in portfolio.get_all_positions()]}")
    print(f"Trade history: {len(portfolio.get_trade_history())} trades")
    print("=== Demo Complete ===")

    # Live engine demo
    print("\n=== Live Trading Engine Demo (Mock Broker) ===")
    from brokers.registry import get_broker
    broker = get_broker("mock")
    broker.connect("demo_key", "demo_secret")
    live = LiveTradingEngine(config, broker)
    live.start()

    buy = Order.market("BTC-USD", OrderSide.BUY, 0.1)
    fill = live.execute_order(buy)
    print(f"Live fill: {fill.filled_qty} @ {fill.filled_price:.2f}")
    print(f"Live status: {live.get_live_status()}")
    print("=== Live Demo Complete ===")
