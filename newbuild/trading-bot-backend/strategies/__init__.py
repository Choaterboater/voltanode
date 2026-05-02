"""Strategy package with factory for loading strategies by name."""

from __future__ import annotations

from typing import Any, Dict, Type

from strategies.base import BaseStrategy, Signal, SignalType, StrategyMetrics
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.grid import GridStrategy
from strategies.breakout import BreakoutStrategy
from strategies.arbitrage import ArbitrageStrategy
from strategies.macd import MACDStrategy
from strategies.ensemble_ml import EnsembleMLStrategy


# Strategy registry
STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "grid": GridStrategy,
    "breakout": BreakoutStrategy,
    "arbitrage": ArbitrageStrategy,
    "macd": MACDStrategy,
    "ensemble_ml": EnsembleMLStrategy,
}


def StrategyFactory(
    strategy_type: str,
    strategy_id: str | None = None,
    config: Dict[str, Any] | None = None,
) -> BaseStrategy:
    """Factory function to create a strategy instance by type name.

    Args:
        strategy_type: Strategy type name (e.g., "momentum", "macd").
        strategy_id: Unique strategy identifier. Defaults to a generated ID.
        config: Strategy-specific configuration.

    Returns:
        Strategy instance.

    Raises:
        ValueError: If strategy type is not found in registry.
    """
    if strategy_type not in STRATEGY_REGISTRY:
        raise ValueError(
            f"Unknown strategy type: {strategy_type}. "
            f"Available: {list(STRATEGY_REGISTRY.keys())}"
        )
    strategy_class = STRATEGY_REGISTRY[strategy_type]
    sid = strategy_id or f"{strategy_type}_{id(strategy_class)}"
    return strategy_class(sid, config or {})


def list_strategies() -> Dict[str, Dict[str, Any]]:
    """List all available strategy types with their default configs.

    Returns:
        Dict mapping strategy name to default config.
    """
    return {
        name: {
            "class": cls.__name__,
            "default_config": cls.DEFAULT_CONFIG,
        }
        for name, cls in STRATEGY_REGISTRY.items()
    }


__all__ = [
    "BaseStrategy",
    "Signal",
    "SignalType",
    "StrategyMetrics",
    "MomentumStrategy",
    "MeanReversionStrategy",
    "GridStrategy",
    "BreakoutStrategy",
    "ArbitrageStrategy",
    "MACDStrategy",
    "EnsembleMLStrategy",
    "StrategyFactory",
    "list_strategies",
    "STRATEGY_REGISTRY",
]
