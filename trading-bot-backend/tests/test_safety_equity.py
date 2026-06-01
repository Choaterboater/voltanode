"""Safety validator equity basis — live portfolio with synced positions."""

from __future__ import annotations

import pytest

from bot.config import OrderSide
from bot.orders import Order
from bot.portfolio import Portfolio, PositionSide
from safety.limits import (
    SafetyConfig,
    SafetyValidationError,
    SafetyValidator,
    compute_portfolio_equity,
)


def test_compute_portfolio_equity_includes_position_market_value() -> None:
    """Seed cash alone must not undercount equity when positions are synced."""
    portfolio = Portfolio("default", {"USDT": 10_000.0})
    portfolio.open_position("BTC", PositionSide.LONG, 1.0, 50_000.0)
    pos = portfolio.get_position("BTC")
    assert pos is not None
    pos.update_price(50_000.0)

    equity = compute_portfolio_equity(portfolio)
    assert equity >= 55_000.0
    assert equity > 10_000.0


def test_cash_only_sum_overstates_exposure_vs_canonical_equity() -> None:
    """Document the live-sync bug: cash-only denominator falsely blocks BUYs."""
    portfolio = Portfolio("default", {"USDT": 10_000.0})
    portfolio.open_position("BTC", PositionSide.LONG, 1.0, 50_000.0)
    pos = portfolio.get_position("BTC")
    assert pos is not None
    pos.update_price(50_000.0)

    order_notional = 30.0
    broken_equity = sum(portfolio.get_all_balances().values())
    canonical = compute_portfolio_equity(portfolio)
    assert broken_equity == 10_000.0
    assert canonical >= 55_000.0

    broken_exposure_pct = (pos.market_value + order_notional) / broken_equity * 100.0
    fixed_exposure_pct = (pos.market_value + order_notional) / canonical * 100.0
    assert broken_exposure_pct > 300.0
    assert fixed_exposure_pct < 300.0


def test_safety_allows_buy_when_exposure_under_cap() -> None:
    portfolio = Portfolio("default", {"USDT": 10_000.0})
    portfolio.open_position("BTC", PositionSide.LONG, 1.0, 50_000.0)
    pos = portfolio.get_position("BTC")
    assert pos is not None
    pos.update_price(50_000.0)

    validator = SafetyValidator(
        SafetyConfig(max_exposure_pct=300.0, max_position_size_pct=20.0)
    )
    order = Order.limit("ETH", OrderSide.BUY, 0.01, price=3_000.0)
    validator.validate_order(order, portfolio)


def test_broker_equity_override_used_for_validation() -> None:
    portfolio = Portfolio("default", {"USDT": 1_000.0})
    portfolio.open_position("BTC", PositionSide.LONG, 2.0, 40_000.0)
    pos = portfolio.get_position("BTC")
    assert pos is not None
    pos.update_price(40_000.0)

    validator = SafetyValidator(SafetyConfig(max_exposure_pct=300.0, max_position_size_pct=25.0))
    order = Order.limit("SOL", OrderSide.BUY, 0.5, price=150.0)
    validator.validate_order(
        order,
        portfolio,
        broker_balances={"EQUITY": 100_000.0, "USD": 1_000.0},
    )


def test_market_buy_uses_current_price_for_position_cap() -> None:
    """A market BUY without order.price must still be checked by notional."""
    portfolio = Portfolio("default", {"USDT": 100_000.0})
    validator = SafetyValidator(
        SafetyConfig(max_exposure_pct=300.0, max_position_size_pct=20.0)
    )
    order = Order.market("BTC", OrderSide.BUY, 1.0)

    with pytest.raises(SafetyValidationError, match="Position size"):
        validator.validate_order(order, portfolio, current_price=50_000.0)


def test_market_buy_without_price_is_rejected_not_skipped() -> None:
    portfolio = Portfolio("default", {"USDT": 100_000.0})
    validator = SafetyValidator(
        SafetyConfig(max_exposure_pct=300.0, max_position_size_pct=20.0)
    )
    order = Order.market("BTC", OrderSide.BUY, 0.1)

    with pytest.raises(SafetyValidationError, match="No market price"):
        validator.validate_order(order, portfolio)
