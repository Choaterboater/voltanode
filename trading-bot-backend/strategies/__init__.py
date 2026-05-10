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
from strategies.news_sentiment import NewsSentimentStrategy
from strategies.multi_coin import MultiCoinMomentumStrategy
from strategies.simple_trend import SimpleTrendStrategy
from strategies.auto_discovery import AutoDiscoveryStrategy
from strategies.squeeze import SqueezeStrategy


# Strategy registry
STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "grid": GridStrategy,
    "breakout": BreakoutStrategy,
    "arbitrage": ArbitrageStrategy,
    "macd": MACDStrategy,
    "ensemble_ml": EnsembleMLStrategy,
    "news_sentiment": NewsSentimentStrategy,
    "multi_coin": MultiCoinMomentumStrategy,
    "simple_trend": SimpleTrendStrategy,
    "auto_discovery": AutoDiscoveryStrategy,
    "squeeze": SqueezeStrategy,
}


def _normalize_strategy_type(name: str) -> str:
    """Map UI-style names ('Momentum', 'MeanReversion', 'EnsembleML', 'MACD')
    to the snake_case registry keys used internally."""
    import re
    raw = (name or "").strip()
    if raw in STRATEGY_REGISTRY:
        return raw
    lowered = raw.lower()
    if lowered in STRATEGY_REGISTRY:
        return lowered
    # CamelCase/PascalCase → snake_case, handling acronym runs.
    # "MyName" -> "my_name", "EnsembleML" -> "ensemble_ml", "MACDX" -> "macdx"
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", raw)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    snake = s2.lower()
    if snake in STRATEGY_REGISTRY:
        return snake
    return raw


def StrategyFactory(
    strategy_type: str,
    strategy_id: str | None = None,
    config: Dict[str, Any] | None = None,
) -> BaseStrategy:
    """Factory function to create a strategy instance by type name.

    Accepts either snake_case registry keys ("momentum", "mean_reversion") or
    PascalCase UI labels ("Momentum", "MeanReversion", "EnsembleML").

    Args:
        strategy_type: Strategy type name.
        strategy_id: Unique strategy identifier. Defaults to a generated ID.
        config: Strategy-specific configuration.

    Returns:
        Strategy instance.

    Raises:
        ValueError: If strategy type cannot be resolved against the registry.
    """
    resolved = _normalize_strategy_type(strategy_type)
    if resolved not in STRATEGY_REGISTRY:
        raise ValueError(
            f"Unknown strategy type: {strategy_type}. "
            f"Available: {list(STRATEGY_REGISTRY.keys())}"
        )
    strategy_class = STRATEGY_REGISTRY[resolved]
    sid = strategy_id or f"{resolved}_{id(strategy_class)}"
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
    "NewsSentimentStrategy",
    "AutoDiscoveryStrategy",
    "SqueezeStrategy",
    "StrategyFactory",
    "list_strategies",
    "STRATEGY_REGISTRY",
]
