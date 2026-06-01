"""Safety validators — position size, exposure, symbol lists, rate limits.

Enforces hard limits before an order reaches the broker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from bot.config import OrderSide
from bot.orders import FillResult, Order
from bot.portfolio import Portfolio, lookup_price


class SafetyValidationError(Exception):
    """Raised when an order violates safety rules."""
    pass


@dataclass
class SafetyConfig:
    """Runtime safety configuration (mirrors config.SafetyConfig)."""
    max_daily_loss_pct: float = 5.0
    max_position_size_pct: float = 20.0
    max_exposure_pct: float = 300.0
    require_confirmation: bool = True
    kill_switch_on_disconnect: bool = True
    max_orders_per_minute: int = 300
    allowed_symbols: List[str] = field(default_factory=list)
    blocked_symbols: List[str] = field(default_factory=list)


def compute_portfolio_equity(
    portfolio: Portfolio,
    broker_balances: Optional[Dict[str, float]] = None,
) -> float:
    """Canonical total equity for exposure / position-size % checks.

    Mirrors ``api/routes/portfolio.py`` and ``strategies/base.py``: prefer
    broker-reported EQUITY when available, else cash keys + position MV.
    Using ``sum(balances.values())`` alone breaks live mode — the engine
    keeps a small seed cash balance while broker-synced positions carry
    most of the book, which made exposure look 800%+ and blocked every BUY.
    """
    if broker_balances:
        for key, val in broker_balances.items():
            if str(key).upper() == "EQUITY" and val and float(val) > 0:
                return float(val)
    balances = portfolio.get_all_balances()
    positions = portfolio.get_all_positions()
    if balances and any(str(k).upper() == "EQUITY" for k in balances):
        eq_key = next(k for k in balances if str(k).upper() == "EQUITY")
        eq = float(balances[eq_key])
        if eq > 0:
            return eq
    cash_keys = {"USD", "USDT", "CASH"}
    cash = sum(
        float(v) for k, v in (balances or {}).items() if str(k).upper() in cash_keys
    )
    mv = sum(float(getattr(p, "market_value", 0) or 0) for p in positions)
    total = cash + mv
    return total if total > 0 else 1.0


def _coerce_safety_config(config: Any | None) -> SafetyConfig:
    """Normalize Pydantic ``bot.config.SafetyConfig`` or dataclass into runtime config."""
    if config is None:
        return SafetyConfig()
    if isinstance(config, SafetyConfig):
        return config
    return SafetyConfig(
        max_daily_loss_pct=float(getattr(config, "max_daily_loss_pct", 5.0)),
        max_position_size_pct=float(getattr(config, "max_position_size_pct", 20.0)),
        max_exposure_pct=float(getattr(config, "max_exposure_pct", 300.0)),
        require_confirmation=bool(getattr(config, "require_confirmation", True)),
        kill_switch_on_disconnect=bool(getattr(config, "kill_switch_on_disconnect", True)),
        max_orders_per_minute=int(getattr(config, "max_orders_per_minute", 300)),
        allowed_symbols=list(getattr(config, "allowed_symbols", []) or []),
        blocked_symbols=list(getattr(config, "blocked_symbols", []) or []),
    )


class RateLimiter:
    """Simple sliding-window rate limiter for orders per minute."""

    def __init__(self, max_per_minute: int = 10) -> None:
        self.max_per_minute = max_per_minute
        self._timestamps: List[float] = []

    def check(self) -> bool:
        """Return True if within rate limit, False if exceeded."""
        now = time.time()
        cutoff = now - 60.0
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self.max_per_minute:
            return False
        self._timestamps.append(now)
        return True

    def get_remaining(self) -> int:
        now = time.time()
        cutoff = now - 60.0
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        return max(0, self.max_per_minute - len(self._timestamps))


class SafetyValidator:
    """Validates orders against safety limits before execution.

    Checks:
        1. Symbol whitelist/blacklist
        2. Max position size (% of portfolio)
        3. Max total exposure (% of portfolio)
        4. Rate limit (orders per minute)
        5. Daily loss limit (soft check — engine has hard check)
    """

    def __init__(self, config: Any | None = None) -> None:
        self.config = _coerce_safety_config(config)
        self.rate_limiter = RateLimiter(self.config.max_orders_per_minute)

    def validate_order(
        self,
        order: Order,
        portfolio: Portfolio,
        config: Any | None = None,
        daily_pnl: float = 0.0,
        broker_balances: Optional[Dict[str, float]] = None,
        current_price: float | None = None,
    ) -> None:
        """Validate an order. Raises SafetyValidationError if rejected.

        Args:
            order: The order to validate.
            portfolio: Current portfolio state.
            config: Optional config override (from BotConfig).
            daily_pnl: Current day's realized P&L.
            broker_balances: Optional broker cash/equity payload.
            current_price: Live mark used to validate market orders.

        Raises:
            SafetyValidationError: If any rule is violated.
        """
        cfg = self.config
        if config is not None:
            # Try to read from BotConfig nested objects
            if hasattr(config, "safety"):
                safety = config.safety
                cfg = SafetyConfig(
                    max_daily_loss_pct=getattr(safety, "max_daily_loss_pct", cfg.max_daily_loss_pct),
                    max_position_size_pct=getattr(safety, "max_position_size_pct", cfg.max_position_size_pct),
                    max_exposure_pct=getattr(safety, "max_exposure_pct", cfg.max_exposure_pct),
                    max_orders_per_minute=getattr(safety, "max_orders_per_minute", cfg.max_orders_per_minute),
                    allowed_symbols=list(getattr(safety, "allowed_symbols", cfg.allowed_symbols)),
                    blocked_symbols=list(getattr(safety, "blocked_symbols", cfg.blocked_symbols)),
                )

        # 1. Symbol whitelist/blacklist
        symbol_upper = order.symbol.upper()
        if cfg.blocked_symbols and symbol_upper in [s.upper() for s in cfg.blocked_symbols]:
            raise SafetyValidationError(f"Symbol '{order.symbol}' is blocked.")
        if cfg.allowed_symbols and symbol_upper not in [s.upper() for s in cfg.allowed_symbols]:
            raise SafetyValidationError(f"Symbol '{order.symbol}' not in allowed list.")

        # 2. Rate limit
        if not self.rate_limiter.check():
            raise SafetyValidationError(
                f"Rate limit exceeded: max {cfg.max_orders_per_minute} orders/minute."
            )

        # 3. Position size check — use canonical equity (cash + positions or broker EQUITY)
        total_equity = compute_portfolio_equity(portfolio, broker_balances)
        # Market orders do not carry a limit price. Validate them against the
        # live tick mark; otherwise a fresh BUY with no existing position has
        # notional=0 and silently bypasses position/exposure checks.
        price = order.price or current_price
        if not price or price <= 0:
            try:
                price = lookup_price(portfolio, order.symbol) or 0
            except Exception:
                price = 0
        _side_val = getattr(order.side, "value", str(order.side)).lower()
        if _side_val != "sell" and (not price or price <= 0):
            raise SafetyValidationError(
                f"No market price available to validate BUY for {order.symbol}."
            )
        order_notional = order.quantity * price if price > 0 else 0
        # Skip position-size cap on SELL orders — they're closing exposure,
        # not opening it. Without this, an already-oversized position (ETH
        # at 28% when cap is 20%) can't be trimmed because the trim itself
        # would temporarily look like "opening a 28% position." Same logic
        # as the exposure check below; mirror it here.
        if _side_val != "sell" and order_notional > 0:
            position_size_pct = (order_notional / total_equity) * 100.0 if total_equity > 0 else 0.0
            if position_size_pct > cfg.max_position_size_pct:
                raise SafetyValidationError(
                    f"Position size {position_size_pct:.2f}% exceeds limit {cfg.max_position_size_pct}%."
                )

        # 4. Exposure check
        # SELL orders close (or reduce) a long position — they DECREASE
        # exposure rather than add to it. The original check added
        # ``order_notional`` regardless of side, which made it impossible to
        # flatten a position once total exposure was already over the limit
        # (a deadlock — the very orders that would bring you back under cap
        # were rejected for being over cap).
        current_exposure = sum(
            p.market_value for p in portfolio.get_all_positions()
        )
        side_val = getattr(order.side, "value", str(order.side)).lower()
        if side_val == "sell":
            # Closing exposure: cap by zero so we don't go negative on
            # weird state, but never reject a SELL on exposure grounds.
            new_exposure = max(0.0, current_exposure - order_notional)
        else:
            new_exposure = current_exposure + order_notional
        exposure_pct = (new_exposure / total_equity) * 100.0 if total_equity > 0 else 0.0
        if side_val != "sell" and exposure_pct > cfg.max_exposure_pct:
            raise SafetyValidationError(
                f"Exposure {exposure_pct:.2f}% exceeds limit {cfg.max_exposure_pct}%."
            )

        # 5. Soft daily loss check (engine has the hard check after fill).
        # ``daily_pnl`` arrives in DOLLARS (realized P&L from DailyPnlTracker);
        # ``max_daily_loss_pct`` is a PERCENT. Comparing them directly tripped
        # at a $5 loss (or never, depending on account size). Convert the loss
        # to a percent of equity first.
        if daily_pnl < 0 and total_equity > 0:
            daily_loss_pct = (-daily_pnl / total_equity) * 100.0
            if daily_loss_pct > cfg.max_daily_loss_pct:
                raise SafetyValidationError(
                    f"Daily loss {daily_loss_pct:.2f}% exceeds limit {cfg.max_daily_loss_pct}%."
                )

    def get_status(self) -> dict:
        """Return validator status."""
        return {
            "max_daily_loss_pct": self.config.max_daily_loss_pct,
            "max_position_size_pct": self.config.max_position_size_pct,
            "max_exposure_pct": self.config.max_exposure_pct,
            "max_orders_per_minute": self.config.max_orders_per_minute,
            "allowed_symbols": self.config.allowed_symbols,
            "blocked_symbols": self.config.blocked_symbols,
            "orders_remaining_this_minute": self.rate_limiter.get_remaining(),
        }
