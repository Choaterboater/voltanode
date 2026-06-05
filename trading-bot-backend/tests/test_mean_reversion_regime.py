"""Regime gate on MeanReversionStrategy: don't buy dips in a downtrend."""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import SignalType
from strategies.mean_reversion import MeanReversionStrategy


def _downtrend_oversold(n: int = 130) -> pd.DataFrame:
    """A long, steady decline ending in a sharp drop -> RSI oversold + price
    at/under the lower Bollinger band, and well below the 100-EMA."""
    closes = list(np.linspace(300.0, 160.0, n - 3)) + [156.0, 151.0, 146.0]
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {"open": closes, "high": [c * 1.001 for c in closes],
         "low": [c * 0.999 for c in closes], "close": closes,
         "volume": [1_000.0] * n},
        index=idx,
    )
    df.attrs["symbol"] = "TEST"
    return df


def test_gate_off_buys_the_dip() -> None:
    df = _downtrend_oversold()
    s = MeanReversionStrategy("mr_off", {**MeanReversionStrategy.DEFAULT_CONFIG, "trend_filter_ema": 0})
    sig = s.generate_signal(df, float(df["close"].iloc[-1]))
    assert sig.signal_type == SignalType.BUY  # oversold + lower-band touch, no regime filter


def test_gate_on_blocks_dip_in_downtrend() -> None:
    df = _downtrend_oversold()
    s = MeanReversionStrategy("mr_on", {**MeanReversionStrategy.DEFAULT_CONFIG, "trend_filter_ema": 100})
    sig = s.generate_signal(df, float(df["close"].iloc[-1]))
    assert sig.signal_type == SignalType.HOLD
    assert sig.metadata.get("trigger") == "regime_downtrend_skip"
