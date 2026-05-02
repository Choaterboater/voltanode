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
from bot.portfolio import Portfolio


class SafetyValidationError(Exception):
    """Raised when an order violates safety rules."""
    pass


@dataclass
class SafetyConfig:
    """Runtime safety configuration (mirrors config.SafetyConfig)."""
    max_daily_loss_pct: float = 5.0
    max_position_size_pct: float = 20.0
    max_exposure_pct: float = 50.0
    require_confirmation: bool = True
    kill_switch_on_disconnect: bool = True
    max_orders_per_minute: int = 10
    allowed_symbols: List[str] = field(default_factory=list)
    blocked_symbols: List[str] = field(default_factory=list)


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

    def __init__(self, config: Optional[SafetyConfig] = None) -> None:
        self.config = config or SafetyConfig()
        self.rate_limiter = RateLimiter(self.config.max_orders_per_minute)

    def validate_order(
        self,
        order: Order,
        portfolio: Portfolio,
        config: Any | None = None,
        daily_pnl: float = 0.0,
    ) -> None:
        """Validate an order. Raises SafetyValidationError if rejected.

        Args:
            order: The order to validate.
            portfolio: Current portfolio state.
            config: Optional config override (from BotConfig).
            daily_pnl: Current day's realized P&L.

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

        # 3. Position size check
        # Portfolio doesn't have total_equity as property; compute from balances
        total_equity = sum(portfolio.get_all_balances().values()) or 1.0
        # For price, we can't ask portfolio directly — use order price or fallback
        price = order.price or 1.0
        order_notional = order.quantity * price
        position_size_pct = (order_notional / total_equity) * 100.0 if total_equity > 0 else 0.0
        if position_size_pct > cfg.max_position_size_pct:
            raise SafetyValidationError(
                f"Position size {position_size_pct:.2f}% exceeds limit {cfg.max_position_size_pct}%."
            )

        # 4. Exposure check
        current_exposure = sum(
            p.market_value for p in portfolio.get_all_positions()
        )
        new_exposure = current_exposure + order_notional
        exposure_pct = (new_exposure / total_equity) * 100.0 if total_equity > 0 else 0.0
        if exposure_pct > cfg.max_exposure_pct:
            raise SafetyValidationError(
                f"Exposure {exposure_pct:.2f}% exceeds limit {cfg.max_exposure_pct}%."
            )

        # 5. Soft daily loss check (engine has the hard check after fill)
        if daily_pnl < -cfg.max_daily_loss_pct:
            raise SafetyValidationError(
                f"Daily loss {daily_pnl:.2f}% already exceeds limit {cfg.max_daily_loss_pct}%."
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
