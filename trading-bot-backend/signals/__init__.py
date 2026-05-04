"""External signal sources for bot decision-making.

Each module exposes a small, cached fetcher for one external feed:
  - fear_greed: alternative.me crypto Fear & Greed Index (no key)
  - fred:       Federal Reserve Economic Data (VIX, Fed funds, 10y, CPI)
  - finnhub:    earnings calendar, insider trades, congressional trades

These are read-only signals. Strategies can pull them via the engine's
``signal_context`` to gate entries (e.g. "no new longs when VIX > 30").
"""

from signals.fear_greed import FearGreedSignal, fetch_fear_greed

__all__ = ["FearGreedSignal", "fetch_fear_greed"]
