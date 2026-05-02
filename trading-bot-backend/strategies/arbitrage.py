"""Arbitrage strategy scanning cross-exchange price divergence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal, TickData
from bot.portfolio import Portfolio


@dataclass
class ArbitrageOpportunity:
    """Represents an arbitrage opportunity."""
    symbol: str
    buy_market: str
    sell_market: str
    buy_price: float
    sell_price: float
    spread_pct: float
    profit_after_fees: float


class ArbitrageStrategy(BaseStrategy):
    """Cross-market price arbitrage scanner."""

    name = "arbitrage"
    DEFAULT_CONFIG = {
        "min_spread_pct": 0.5,
        "markets": ["coingecko", "simulated"],
        "fee_adjusted": True,
    }

    def __init__(self, strategy_id: str, config: Dict[str, Any]) -> None:
        super().__init__(strategy_id, config)
        self._market_prices: Dict[str, Dict[str, float]] = {}  # market -> {symbol: price}
        self._simulated_prices: Dict[str, float] = {}

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """Arbitrage uses on_tick primarily."""
        symbol = data.attrs.get("symbol", "unknown")
        return Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=SignalType.HOLD,
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
        )

    def on_tick(self, tick: TickData, portfolio: Portfolio) -> Signal | None:
        """Compare prices across simulated markets."""
        symbol = tick.symbol
        market_a_price = tick.price

        # Simulate a second market with slight offset
        offset = 0.005  # 0.5% typical spread
        market_b_price = market_a_price * (1 + (hash(symbol) % 100 - 50) / 10000)

        # Store prices
        self._market_prices["market_a"] = {symbol: market_a_price}
        self._market_prices["market_b"] = {symbol: market_b_price}

        # Calculate spread
        high_price = max(market_a_price, market_b_price)
        low_price = min(market_a_price, market_b_price)
        spread_pct = (high_price - low_price) / low_price * 100

        min_spread = self.config["min_spread_pct"]
        fee_rate = 0.001

        if self.config.get("fee_adjusted", True):
            profit_after_fees = spread_pct - (2 * fee_rate * 100)
        else:
            profit_after_fees = spread_pct

        if spread_pct >= min_spread and profit_after_fees > 0:
            buy_market = "market_a" if market_a_price == low_price else "market_b"
            sell_market = "market_a" if market_a_price == high_price else "market_b"

            signal = Signal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=min(1.0, spread_pct / 2.0),
                timestamp=pd.Timestamp.now(),
                metadata={
                    "arbitrage": True,
                    "buy_market": buy_market,
                    "sell_market": sell_market,
                    "buy_price": low_price,
                    "sell_price": high_price,
                    "spread_pct": spread_pct,
                    "profit_after_fees": profit_after_fees,
                },
                suggested_size=0.0,
            )
            self._record_signal(signal)
            return signal

        return None

    def scan(self, prices_by_market: Dict[str, Dict[str, float]]) -> List[ArbitrageOpportunity]:
        """Scan for arbitrage opportunities across markets.

        Args:
            prices_by_market: Dict of market_name -> {symbol: price}.

        Returns:
            List of arbitrage opportunities.
        """
        opportunities: List[ArbitrageOpportunity] = []
        min_spread = self.config["min_spread_pct"]
        fee_rate = 0.001

        symbols = set()
        for market_prices in prices_by_market.values():
            symbols.update(market_prices.keys())

        for symbol in symbols:
            prices = {}
            for market, market_prices in prices_by_market.items():
                if symbol in market_prices:
                    prices[market] = market_prices[symbol]

            if len(prices) < 2:
                continue

            buy_market = min(prices, key=prices.get)
            sell_market = max(prices, key=prices.get)
            buy_price = prices[buy_market]
            sell_price = prices[sell_market]
            spread_pct = (sell_price - buy_price) / buy_price * 100
            profit = spread_pct - (2 * fee_rate * 100) if self.config.get("fee_adjusted", True) else spread_pct

            if spread_pct >= min_spread and profit > 0:
                opportunities.append(
                    ArbitrageOpportunity(
                        symbol=symbol,
                        buy_market=buy_market,
                        sell_market=sell_market,
                        buy_price=buy_price,
                        sell_price=sell_price,
                        spread_pct=spread_pct,
                        profit_after_fees=profit,
                    )
                )

        return opportunities

    def reset(self) -> None:
        super().reset()
        self._market_prices.clear()
        self._simulated_prices.clear()
