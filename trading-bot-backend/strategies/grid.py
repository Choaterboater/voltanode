"""Grid trading strategy for ranging markets."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal, TickData
from bot.portfolio import Portfolio


class GridStrategy(BaseStrategy):
    """Grid trading strategy that places buy orders below price and sell orders above."""

    name = "grid"
    DEFAULT_CONFIG = {
        "grid_levels": 10,
        "grid_spacing_pct": 0.01,
        "upper_price": None,
        "lower_price": None,
        "quantity_per_grid": 0.01,
    }

    def __init__(self, strategy_id: str, config: Dict[str, Any]) -> None:
        super().__init__(strategy_id, config)
        self._grid_prices: list[float] = []
        self._last_price: float | None = None
        self._filled_grids: Dict[float, str] = {}  # grid_price -> side that filled

    def _setup_grids(self, center_price: float) -> None:
        """Setup grid levels around center price."""
        spacing = self.config["grid_spacing_pct"]
        levels = self.config["grid_levels"]

        upper = self.config.get("upper_price")
        lower = self.config.get("lower_price")

        if upper is None:
            upper = center_price * (1 + spacing * levels / 2)
        if lower is None:
            lower = center_price * (1 - spacing * levels / 2)

        self._grid_prices = []
        for i in range(levels + 1):
            price = lower + (upper - lower) * i / levels
            self._grid_prices.append(round(price, 8))

        self._last_price = center_price

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Grid strategy primarily uses on_tick for execution."""
        symbol = data.attrs.get("symbol", "unknown")
        return Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=SignalType.HOLD,
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
        )

    def on_tick(self, tick: TickData, portfolio: Portfolio) -> Signal | None:
        """Monitor price against grid levels.

        When price crosses a grid level, generate opposite-side order for next grid.
        """
        current_price = tick.price
        symbol = tick.symbol

        if not self._grid_prices or self._last_price is None:
            self._setup_grids(current_price)
            self._last_price = current_price
            return None

        # Find which grid levels were crossed
        crossed_grid: float | None = None
        crossed_direction: str | None = None

        for grid_price in self._grid_prices:
            if self._last_price < grid_price <= current_price:
                # Price moved up through grid
                crossed_grid = grid_price
                crossed_direction = "up"
            elif self._last_price > grid_price >= current_price:
                # Price moved down through grid
                crossed_grid = grid_price
                crossed_direction = "down"

        self._last_price = current_price

        if crossed_grid is None:
            return None

        qty = self.config["quantity_per_grid"]

        # If price moved up through grid, sell at that level
        if crossed_direction == "up":
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=0.7,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "grid_price": crossed_grid,
                    "direction": crossed_direction,
                    "strategy": "grid",
                },
                suggested_size=qty,
            )
            self._record_signal(signal)
            return signal

        # If price moved down through grid, buy at that level
        if crossed_direction == "down":
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=0.7,
                timestamp=pd.Timestamp.now(),
                metadata={
                    "grid_price": crossed_grid,
                    "direction": crossed_direction,
                    "strategy": "grid",
                },
                suggested_size=qty,
            )
            self._record_signal(signal)
            return signal

        return None

    def reset(self) -> None:
        """Reset grid state."""
        super().reset()
        self._grid_prices.clear()
        self._last_price = None
        self._filled_grids.clear()
