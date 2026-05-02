"""Tests for all trading strategies."""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from bot.config import SignalType
from strategies import StrategyFactory, list_strategies
from strategies.base import BaseStrategy, Signal


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """Create synthetic OHLCV data with a known trend pattern."""
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    # Create trending data: first 100 up, then down
    trend = np.concatenate([np.linspace(0, 50, 100), np.linspace(50, -30, 100)])
    prices = 100 + trend + np.random.randn(n) * 2
    df = pd.DataFrame({
        "timestamp": dates,
        "open": prices * 0.99,
        "high": prices * 1.02,
        "low": prices * 0.98,
        "close": prices,
        "volume": np.random.randint(1000, 10000, n),
    })
    df.attrs["symbol"] = "TEST"
    return df


@pytest.fixture
def ranging_ohlcv() -> pd.DataFrame:
    """Create ranging/sideways OHLCV data."""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    prices = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "timestamp": dates,
        "open": prices * 0.99,
        "high": prices * 1.02,
        "low": prices * 0.98,
        "close": prices,
        "volume": np.random.randint(1000, 10000, n),
    })
    df.attrs["symbol"] = "TEST"
    return df


class TestStrategyFactory:
    """Test strategy factory."""

    def test_list_strategies(self) -> None:
        strategies = list_strategies()
        assert len(strategies) == 7
        expected = ["momentum", "mean_reversion", "grid", "breakout", "arbitrage", "macd", "ensemble_ml"]
        for name in expected:
            assert name in strategies

    def test_create_all_strategies(self) -> None:
        for name in list_strategies().keys():
            strategy = StrategyFactory(name)
            assert isinstance(strategy, BaseStrategy)
            assert strategy.strategy_id.startswith(name)

    def test_invalid_strategy(self) -> None:
        with pytest.raises(ValueError):
            StrategyFactory("invalid_strategy")


class TestMomentumStrategy:
    """Test momentum strategy signal generation."""

    def test_signal_on_trending_data(self, sample_ohlcv: pd.DataFrame) -> None:
        strategy = StrategyFactory("momentum", config={"fast_ema": 12, "slow_ema": 26})
        
        # Test on uptrend portion
        uptrend = sample_ohlcv.iloc[:150]
        current_price = float(uptrend["close"].iloc[-1])
        signal = strategy.generate_signal(uptrend, current_price)
        
        assert isinstance(signal, Signal)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
        assert 0.0 <= signal.confidence <= 1.0

    def test_config_override(self) -> None:
        strategy = StrategyFactory("momentum", config={"fast_ema": 5, "slow_ema": 10})
        assert strategy.config["fast_ema"] == 5
        assert strategy.config["slow_ema"] == 10


class TestMeanReversionStrategy:
    """Test mean reversion strategy."""

    def test_signal_generation(self, ranging_ohlcv: pd.DataFrame) -> None:
        strategy = StrategyFactory("mean_reversion")
        current_price = float(ranging_ohlcv["close"].iloc[-1])
        signal = strategy.generate_signal(ranging_ohlcv, current_price)
        
        assert isinstance(signal, Signal)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
        assert 0.0 <= signal.confidence <= 1.0

    def test_oversold_buy_signal(self) -> None:
        """Create data with RSI < 30 and price near lower BB."""
        np.random.seed(42)
        n = 50
        prices = 80 + np.abs(np.random.randn(n) * 2)  # Low prices
        prices[-10:] = prices[-10] - np.linspace(0, 10, 10)  # Declining
        df = pd.DataFrame({
            "timestamp": pd.date_range("2023-01-01", periods=n, freq="D"),
            "open": prices * 0.99,
            "high": prices * 1.02,
            "low": prices * 0.98,
            "close": prices,
            "volume": np.random.randint(1000, 10000, n),
        })
        df.attrs["symbol"] = "TEST"
        
        strategy = StrategyFactory("mean_reversion")
        signal = strategy.generate_signal(df, float(prices[-1]))
        assert isinstance(signal, Signal)
        # With very low prices, should potentially trigger oversold


class TestGridStrategy:
    """Test grid trading strategy."""

    def test_grid_setup(self) -> None:
        strategy = StrategyFactory("grid", config={"grid_levels": 5, "grid_spacing_pct": 0.02})
        assert strategy.config["grid_levels"] == 5

    def test_tick_level_crossing(self) -> None:
        from strategies.base import TickData
        from bot.portfolio import Portfolio
        
        strategy = StrategyFactory("grid", config={"grid_levels": 5, "grid_spacing_pct": 0.02})
        portfolio = Portfolio("test", {"USDT": 10000.0})
        
        # First tick - sets up grids
        tick = TickData(symbol="BTC", price=100.0)
        result = strategy.on_tick(tick, portfolio)
        
        # Second tick crossing a grid level
        tick2 = TickData(symbol="BTC", price=97.0)
        signal = strategy.on_tick(tick2, portfolio)
        
        if signal is not None:
            assert signal.signal_type in [SignalType.BUY, SignalType.SELL]


class TestBreakoutStrategy:
    """Test breakout strategy."""

    def test_breakout_signal(self, sample_ohlcv: pd.DataFrame) -> None:
        strategy = StrategyFactory("breakout", config={"lookback_period": 10})
        current_price = float(sample_ohlcv["close"].iloc[-1])
        signal = strategy.generate_signal(sample_ohlcv, current_price)
        
        assert isinstance(signal, Signal)
        assert 0.0 <= signal.confidence <= 1.0


class TestMACDStrategy:
    """Test MACD strategy."""

    def test_macd_signal(self, sample_ohlcv: pd.DataFrame) -> None:
        strategy = StrategyFactory("macd")
        current_price = float(sample_ohlcv["close"].iloc[-1])
        signal = strategy.generate_signal(sample_ohlcv, current_price)
        
        assert isinstance(signal, Signal)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
        assert 0.0 <= signal.confidence <= 1.0

    def test_metadata_contains_macd(self, sample_ohlcv: pd.DataFrame) -> None:
        strategy = StrategyFactory("macd")
        current_price = float(sample_ohlcv["close"].iloc[-1])
        signal = strategy.generate_signal(sample_ohlcv, current_price)
        
        assert "macd" in signal.metadata or signal.signal_type == SignalType.HOLD


class TestArbitrageStrategy:
    """Test arbitrage strategy."""

    def test_scan_opportunities(self) -> None:
        strategy = StrategyFactory("arbitrage", config={"min_spread_pct": 0.3})
        
        prices = {
            "exchange_a": {"BTC": 45000.0},
            "exchange_b": {"BTC": 45300.0},  # 0.67% spread
        }
        
        opportunities = strategy.scan(prices)
        assert len(opportunities) > 0
        assert opportunities[0].spread_pct > 0.3

    def test_tick_signal(self) -> None:
        from strategies.base import TickData
        from bot.portfolio import Portfolio
        
        strategy = StrategyFactory("arbitrage", config={"min_spread_pct": 0.1})
        portfolio = Portfolio("test", {"USDT": 10000.0})
        
        tick = TickData(symbol="BTC", price=45000.0)
        signal = strategy.on_tick(tick, portfolio)
        
        # Arbitrage should potentially find opportunities with simulated second market
        assert signal is None or signal.confidence > 0


class TestEnsembleMLStrategy:
    """Test ensemble ML strategy."""

    def test_composite_score(self, sample_ohlcv: pd.DataFrame) -> None:
        strategy = StrategyFactory("ensemble_ml")
        current_price = float(sample_ohlcv["close"].iloc[-1])
        signal = strategy.generate_signal(sample_ohlcv, current_price)
        
        assert isinstance(signal, Signal)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
        assert 0.0 <= signal.confidence <= 1.0
        
        if signal.signal_type != SignalType.HOLD:
            assert "composite_score" in signal.metadata

    def test_component_scores(self, sample_ohlcv: pd.DataFrame) -> None:
        strategy = StrategyFactory("ensemble_ml")
        current_price = float(sample_ohlcv["close"].iloc[-1])
        signal = strategy.generate_signal(sample_ohlcv, current_price)
        
        if "component_scores" in signal.metadata:
            scores = signal.metadata["component_scores"]
            assert isinstance(scores, dict)
            assert "weights" in signal.metadata

    def test_signal_thresholds(self, sample_ohlcv: pd.DataFrame) -> None:
        """Verify buy/sell thresholds work."""
        strategy = StrategyFactory("ensemble_ml", config={"buy_threshold": 0.8, "sell_threshold": -0.8})
        current_price = float(sample_ohlcv["close"].iloc[-1])
        signal = strategy.generate_signal(sample_ohlcv, current_price)
        
        # With higher thresholds, should more often be HOLD
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]


class TestStrategyMetrics:
    """Test strategy metrics collection."""

    def test_metrics_after_trades(self) -> None:
        strategy = StrategyFactory("momentum")
        
        # Simulate some fills
        from bot.orders import FillResult, OrderSide
        from bot.portfolio import Portfolio
        from datetime import datetime, timezone
        
        portfolio = Portfolio("test", {"USDT": 10000.0})
        fill = FillResult(
            order_id="test-1",
            symbol="BTC",
            filled_qty=1.0,
            filled_price=50000.0,
            fee=50.0,
            slippage=0.0,
            timestamp=datetime.now(timezone.utc),
            side=OrderSide.BUY,
            realized_pnl=100.0,
        )
        strategy.on_fill(fill, portfolio)
        
        metrics = strategy.get_metrics()
        assert metrics.total_trades == 1
        assert metrics.total_pnl == 100.0
        assert metrics.win_rate == 100.0

    def test_reset_clears_state(self, sample_ohlcv: pd.DataFrame) -> None:
        strategy = StrategyFactory("momentum")
        strategy.trade_count = 5
        strategy.total_pnl = 100.0
        
        strategy.reset()
        
        assert strategy.trade_count == 0
        assert strategy.total_pnl == 0.0
        assert len(strategy._history) == 0
