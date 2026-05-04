"""Stock screeners — ranked picks based on quantitative formulas.

Each screener implements ``run(universe: list[str]) -> list[ScreenerPick]``.
The first one is Greenblatt's Magic Formula. The pattern can be cloned
for Piotroski F-Score, Twin Momentum, Lynch Growth, etc.
"""

from screeners.magic_formula import (
    MagicFormulaScreener,
    ScreenerPick,
    DEFAULT_UNIVERSE,
)

__all__ = ["MagicFormulaScreener", "ScreenerPick", "DEFAULT_UNIVERSE"]
