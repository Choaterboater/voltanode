"""Funding-carry strategy + historical-funding data tests (no network)."""

from __future__ import annotations

import pandas as pd
import pytest

from bot.config import SignalType
from strategies.funding_carry import FundingCarryStrategy
import data.funding as fd


def _df(funding):
    df = pd.DataFrame({
        "open": [100, 101], "high": [101, 102], "low": [99, 100],
        "close": [100, 101], "volume": [1e3, 1e3], "funding_rate": [0.0, funding],
    })
    df.attrs["symbol"] = "BTC"
    return df


def test_funding_buy_on_crowded_short():
    sig = FundingCarryStrategy("f", {}).generate_signal(_df(-0.0005), 101.0)  # <= enter -0.0003
    assert sig.signal_type == SignalType.BUY
    assert sig.stop_loss and sig.take_profit and sig.suggested_size


def test_funding_sell_on_crowded_long():
    sig = FundingCarryStrategy("f", {}).generate_signal(_df(0.001), 101.0)  # >= exit 0.0005
    assert sig.signal_type == SignalType.SELL


def test_funding_hold_neutral():
    sig = FundingCarryStrategy("f", {}).generate_signal(_df(0.0001), 101.0)
    assert sig.signal_type == SignalType.HOLD


def test_funding_hold_when_no_data():
    fd._CACHE.clear(); fd._CACHE_TS.clear()
    df = pd.DataFrame({"open": [100, 101], "high": [101, 102], "low": [99, 100], "close": [100, 101], "volume": [1e3, 1e3]})
    df.attrs["symbol"] = "DOGE"
    sig = FundingCarryStrategy("f", {}).generate_signal(df, 101.0)
    assert sig.signal_type == SignalType.HOLD


def test_daily_funding_aggregation(monkeypatch):
    monkeypatch.setattr(fd, "fetch_funding_history", lambda *a, **k: [
        (1735689600000, 0.0001),  # 2025-01-01 00:00 UTC
        (1735718400000, 0.0002),  # 2025-01-01 08:00 UTC (same day)
        (1735776000000, -0.0001),  # 2025-01-02 00:00 UTC
    ])
    dm = fd.daily_funding("BTC")
    assert round(dm["2025-01-01"], 6) == 0.0003   # summed daily carry
    assert round(dm["2025-01-02"], 6) == -0.0001


def test_attach_funding_to_ohlcv(monkeypatch):
    monkeypatch.setattr(fd, "daily_funding", lambda *a, **k: {"2025-01-01": 0.0005, "2025-01-02": -0.0002})
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]), "close": [100, 101, 102]})
    out = fd.attach_funding_to_ohlcv(df, "BTC")
    assert "funding_rate" in out.columns
    assert round(float(out["funding_rate"].iloc[0]), 6) == 0.0005
    assert round(float(out["funding_rate"].iloc[2]), 6) == -0.0002  # day3 absent -> ffill from day2
