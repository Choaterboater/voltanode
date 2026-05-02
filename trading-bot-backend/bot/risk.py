"""Risk management: position sizing, drawdown monitoring, and exposure limits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from bot.config import OrderSide, RiskConfig, SizingMethod
from bot.orders import Order
from bot.portfolio import Portfolio


@dataclass
class RiskCheckResult:
    """Result of a pre-trade risk check."""
    allowed: bool
    order: Order | None
    reason: str | None


@dataclass
class RiskAlert:
    """Risk alert notification."""
    level: str  # "warning" | "critical"
    rule: str
    message: str
    timestamp: datetime


class PositionSizer:
    """Static methods for position sizing calculations."""

    @staticmethod
    def fixed(amount: float) -> float:
        """Fixed quantity regardless of price or equity."""
        return amount

    @staticmethod
    def percentage_of_equity(equity: float, pct: float, price: float) -> float:
        """Size based on percentage of equity.

        e.g., 2% of $10,000 = $200 → $200 / $100 = 2 units.
        """
        if price <= 0:
            return 0.0
        return (equity * pct) / price

    @staticmethod
    def kelly_criterion(
        win_rate: float, avg_win: float, avg_loss: float
    ) -> float:
        """Kelly criterion fraction.

        f* = (p*b - q) / b, where b = avg_win/avg_loss.
        """
        if avg_loss <= 0 or win_rate <= 0:
            return 0.0
        b = avg_win / avg_loss
        q = 1.0 - win_rate
        kelly = (win_rate * b - q) / b
        return max(0.0, min(kelly, 1.0))  # Clamp to [0, 1]

    @staticmethod
    def volatility_based(
        equity: float,
        atr: float,
        risk_per_trade_pct: float,
        price: float,
    ) -> float:
        """ATR-based position sizing.

        Size = (equity * risk_pct) / (atr * price).
        """
        if atr <= 0 or price <= 0:
            return 0.0
        risk_amount = equity * risk_per_trade_pct
        return risk_amount / (atr * price)


class DrawdownMonitor:
    """Monitors portfolio drawdown and triggers alerts."""

    def __init__(self, max_drawdown_pct: float = 0.10) -> None:
        """Initialize drawdown monitor.

        Args:
            max_drawdown_pct: Maximum allowed drawdown as decimal.
        """
        self.max_drawdown_pct = max_drawdown_pct
        self._peak_equity: float = 0.0
        self._current_drawdown: float = 0.0
        self._breached: bool = False

    def update(self, equity: float) -> bool:
        """Update with current equity.

        Args:
            equity: Current portfolio equity.

        Returns:
            True if drawdown threshold is breached.
        """
        if equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            self._current_drawdown = (self._peak_equity - equity) / self._peak_equity
        else:
            self._current_drawdown = 0.0
        self._breached = self._current_drawdown > self.max_drawdown_pct
        return self._breached

    def is_breached(self) -> bool:
        """Check if max drawdown has been breached."""
        return self._breached

    def get_status(self) -> Dict[str, Any]:
        """Get current drawdown status."""
        return {
            "peak_equity": self._peak_equity,
            "current_drawdown_pct": self._current_drawdown * 100,
            "max_allowed_pct": self.max_drawdown_pct * 100,
            "breached": self._breached,
        }

    def reset(self) -> None:
        """Reset the monitor."""
        self._peak_equity = 0.0
        self._current_drawdown = 0.0
        self._breached = False


class ExposureMonitor:
    """Monitors portfolio exposure against limits."""

    def check(
        self,
        portfolio: Portfolio,
        limits: Dict[str, float],
    ) -> List[RiskAlert]:
        """Check portfolio against exposure limits.

        Args:
            portfolio: The portfolio to check.
            limits: Dict of limit_type -> max_value (e.g., {"max_position_size_pct": 0.20}).

        Returns:
            List of RiskAlert objects.
        """
        alerts: List[RiskAlert] = []
        now = datetime.now(timezone.utc)

        # Calculate total equity for percentage checks
        balances = portfolio.get_all_balances()
        total_balance = sum(balances.values()) if balances else 0.0
        total_position_value = sum(p.market_value for p in portfolio.get_all_positions())
        total_equity = total_balance + total_position_value
        if total_equity <= 0:
            total_equity = 1.0  # Avoid division by zero

        # Check position concentration
        max_pos_pct = limits.get("max_position_size_pct", 0.20)
        for pos in portfolio.get_all_positions():
            pos_pct = pos.market_value / total_equity
            if pos_pct > max_pos_pct:
                alerts.append(RiskAlert(
                    level="critical",
                    rule="max_position_size_pct",
                    message=f"Position {pos.symbol} is {pos_pct:.1%} of portfolio (limit: {max_pos_pct:.1%})",
                    timestamp=now,
                ))

        # Check per-asset exposure
        max_asset_pct = limits.get("max_exposure_per_asset_pct", 0.30)
        symbols = set(p.symbol for p in portfolio.get_all_positions())
        for symbol in symbols:
            exposure = portfolio.get_exposure(symbol)
            exposure_value = exposure * next(
                (p.current_price for p in portfolio.get_all_positions() if p.symbol == symbol), 0
            )
            asset_pct = exposure_value / total_equity
            if asset_pct > max_asset_pct:
                alerts.append(RiskAlert(
                    level="warning",
                    rule="max_exposure_per_asset_pct",
                    message=f"Exposure to {symbol} is {asset_pct:.1%} of portfolio (limit: {max_asset_pct:.1%})",
                    timestamp=now,
                ))

        return alerts


class RiskManager:
    """Central risk controller."""

    def __init__(self, config: RiskConfig) -> None:
        """Initialize risk manager.

        Args:
            config: Risk configuration.
        """
        self.config = config
        self.drawdown_monitor = DrawdownMonitor(config.max_drawdown_pct)
        self.exposure_monitor = ExposureMonitor()
        self._history: List[Dict[str, Any]] = []

    # ── Position Sizing ──

    def calculate_position_size(
        self,
        method: SizingMethod,
        portfolio: Portfolio,
        signal_strength: float,
        entry_price: float,
        stop_price: float | None = None,
    ) -> float:
        """Calculate position size based on method.

        Args:
            method: Sizing method enum.
            portfolio: Current portfolio.
            signal_strength: Signal confidence (0-1).
            entry_price: Entry price.
            stop_price: Stop loss price (for volatility-based sizing).

        Returns:
            Recommended position size.
        """
        # Get base equity (use first balance)
        balances = portfolio.get_all_balances()
        equity = sum(balances.values()) if balances else 10000.0

        if method == SizingMethod.FIXED:
            return PositionSizer.fixed(self.config.position_sizing_value)

        if method == SizingMethod.PERCENTAGE:
            size = PositionSizer.percentage_of_equity(
                equity, self.config.position_sizing_value, entry_price
            )
            return size * signal_strength

        if method == SizingMethod.KELLY:
            # Use default win rate and reward/risk for simplicity
            kelly = PositionSizer.kelly_criterion(
                win_rate=0.55, avg_win=entry_price * 0.06, avg_loss=entry_price * 0.02
            )
            return PositionSizer.percentage_of_equity(equity, kelly, entry_price)

        if method == SizingMethod.VOLATILITY:
            atr = stop_price or entry_price * 0.02
            return PositionSizer.volatility_based(
                equity, atr, self.config.position_sizing_value, entry_price
            )

        return 0.0

    # ── Pre-trade Checks ──

    def check_order(
        self,
        order: Order,
        portfolio: Portfolio,
    ) -> RiskCheckResult:
        """Check if an order violates risk rules.

        Args:
            order: The order to check.
            portfolio: The portfolio.

        Returns:
            RiskCheckResult with allowed flag.
        """
        # Check drawdown
        if self.drawdown_monitor.is_breached():
            return RiskCheckResult(
                allowed=False,
                order=None,
                reason="Max drawdown breached — trading halted",
            )

        # Check position size limit
        notional = order.quantity * (order.price or 1.0)
        balances = portfolio.get_all_balances()
        equity = sum(balances.values()) if balances else 10000.0
        max_notional = equity * self.config.max_position_size_pct

        if notional > max_notional:
            # Reduce order size in-place so caller's reference stays valid
            if order.price and order.price > 0:
                reduced_qty = max_notional / order.price
                order.quantity = reduced_qty
                return RiskCheckResult(
                    allowed=True,
                    order=order,
                    reason=f"Order size reduced from {order.quantity:.4f} to {reduced_qty:.4f} due to position limit",
                )
            return RiskCheckResult(
                allowed=False,
                order=None,
                reason="Order exceeds max position size",
            )

        return RiskCheckResult(allowed=True, order=order, reason=None)

    def check_portfolio_limits(self, portfolio: Portfolio) -> List[RiskAlert]:
        """Check aggregate exposure and drawdown.

        Args:
            portfolio: The portfolio.

        Returns:
            List of risk alerts.
        """
        alerts: List[RiskAlert] = []
        now = datetime.now(timezone.utc)

        # Check drawdown
        balances = portfolio.get_all_balances()
        equity = sum(balances.values()) if balances else 10000.0
        if self.drawdown_monitor.update(equity):
            alerts.append(
                RiskAlert(
                    level="critical",
                    rule="max_drawdown",
                    message=f"Drawdown breached: {self.drawdown_monitor.get_status()['current_drawdown_pct']:.1f}%",
                    timestamp=now,
                )
            )

        return alerts

    # ── Trailing Stops ──

    def update_trailing_stops(
        self,
        portfolio: Portfolio,
        current_prices: Dict[str, float],
    ) -> List[Order]:
        """Generate stop-loss orders for trailing stop logic.

        Args:
            portfolio: Current portfolio.
            current_prices: Symbol -> current price mapping.

        Returns:
            List of stop orders to submit.
        """
        stops: List[Order] = []
        for pos in portfolio.get_all_positions():
            price = current_prices.get(pos.symbol)
            if price is None:
                continue
            # Simple trailing stop: fixed percentage below/above entry
            if pos.side.value == "long":
                stop_price = pos.entry_price * (1.0 - self.config.default_stop_loss_pct)
                if price <= stop_price:
                    stops.append(
                        Order.market(
                            symbol=pos.symbol,
                            side=OrderSide.SELL,
                            quantity=pos.size,
                            account_id=portfolio.account_id,
                        )
                    )
            else:
                stop_price = pos.entry_price * (1.0 + self.config.default_stop_loss_pct)
                if price >= stop_price:
                    stops.append(
                        Order.market(
                            symbol=pos.symbol,
                            side=OrderSide.BUY,
                            quantity=pos.size,
                            account_id=portfolio.account_id,
                        )
                    )
        return stops

    def reset(self) -> None:
        """Reset risk manager state."""
        self.drawdown_monitor.reset()
        self._history.clear()
