"""Central _apply_regime_gate: veto BUYs below the trend EMA (downtrend)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import SignalType
from strategies.base import Signal
from strategies.simple_trend import SimpleTrendStrategy


def _df(start: float, end: float, n: int = 130) -> pd.DataFrame:
    closes = list(np.linspace(start, end, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"open": closes, "high": [c * 1.001 for c in closes],
         "low": [c * 0.999 for c in closes], "close": closes,
         "volume": [1000.0] * n},
        index=idx,
    )


def _buy(s: SimpleTrendStrategy) -> Signal:
    return Signal(strategy_id=s.strategy_id, symbol="TEST", signal_type=SignalType.BUY,
                  confidence=0.8, timestamp=pd.Timestamp.now(), suggested_size=1.0)


def test_blocks_buy_in_downtrend() -> None:
    s = SimpleTrendStrategy("st", {**SimpleTrendStrategy.DEFAULT_CONFIG})  # gate on by default
    out = s._apply_regime_gate(_buy(s), _df(300.0, 150.0))  # price far below EMA100
    assert out.signal_type == SignalType.HOLD
    assert out.metadata.get("trigger") == "regime_gate"


def test_allows_buy_in_uptrend() -> None:
    s = SimpleTrendStrategy("st", {**SimpleTrendStrategy.DEFAULT_CONFIG})
    out = s._apply_regime_gate(_buy(s), _df(150.0, 300.0))  # price above EMA100
    assert out.signal_type == SignalType.BUY


def test_disabled_when_no_config() -> None:
    s = SimpleTrendStrategy("st", {"regime_gate": {"enabled": False}})
    out = s._apply_regime_gate(_buy(s), _df(300.0, 150.0))
    assert out.signal_type == SignalType.BUY  # gate off -> unchanged
