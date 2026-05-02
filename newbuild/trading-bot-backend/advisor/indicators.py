"""Professional technical indicators — pure pandas/numpy implementations.

No external TA libraries (TA-Lib, ta, etc.) are used.  All calculations
are vectorised with pandas/numpy for production-grade performance.

Expected input DataFrame columns (lower-case):
    timestamp, open, high, low, close, volume
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def _get_close(data: pd.DataFrame) -> pd.Series:
    """Safely extract the close series."""
    return data["close"]


# ── Moving Averages ──

def compute_sma(data: pd.DataFrame, period: int = 20) -> pd.Series:
    """Simple Moving Average.

    Args:
        data: OHLCV DataFrame.
        period: Look-back window.

    Returns:
        SMA series aligned with input index.
    """
    return _get_close(data).rolling(window=period, min_periods=1).mean()


def compute_ema(data: pd.DataFrame, period: int = 20) -> pd.Series:
    """Exponential Moving Average.

    Uses the standard ``span=period`` definition (same as TradingView).

    Args:
        data: OHLCV DataFrame.
        period: EMA span.

    Returns:
        EMA series.
    """
    return _get_close(data).ewm(span=period, adjust=False, min_periods=1).mean()


# ── Momentum / Oscillators ──

def compute_rsi(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing).

    Args:
        data: OHLCV DataFrame.
        period: RSI look-back.

    Returns:
        RSI series (0-100).
    """
    close = _get_close(data)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def compute_macd(
    data: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> Dict[str, pd.Series]:
    """Moving Average Convergence Divergence.

    Args:
        data: OHLCV DataFrame.
        fast: Fast EMA span.
        slow: Slow EMA span.
        signal: Signal-line EMA span.

    Returns:
        Dict with keys ``macd``, ``signal``, ``histogram``.
    """
    close = _get_close(data)
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=1).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=1).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=1).mean()
    histogram = macd_line - signal_line
    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def compute_stochastic(
    data: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> Dict[str, pd.Series]:
    """Stochastic Oscillator (%K and %D).

    Args:
        data: OHLCV DataFrame.
        k_period: %K look-back.
        d_period: %D smoothing.

    Returns:
        Dict with keys ``k`` and ``d``.
    """
    low_min = data["low"].rolling(window=k_period, min_periods=1).min()
    high_max = data["high"].rolling(window=k_period, min_periods=1).max()
    k = 100 * (_get_close(data) - low_min) / (high_max - low_min).replace(0, np.nan)
    k = k.fillna(50.0)
    d = k.rolling(window=d_period, min_periods=1).mean()
    return {"k": k, "d": d}


def compute_williams_r(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Williams %R.

    Args:
        data: OHLCV DataFrame.
        period: Look-back window.

    Returns:
        Williams %R series (-100 to 0).
    """
    high_max = data["high"].rolling(window=period, min_periods=1).max()
    low_min = data["low"].rolling(window=period, min_periods=1).min()
    wr = -100 * (high_max - _get_close(data)) / (high_max - low_min).replace(0, np.nan)
    return wr.fillna(-50.0)


def compute_mfi(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Money Flow Index (volume-weighted RSI).

    Args:
        data: OHLCV DataFrame.
        period: Look-back window.

    Returns:
        MFI series (0-100).
    """
    typical = (data["high"] + data["low"] + data["close"]) / 3
    raw_money_flow = typical * data["volume"]
    delta = typical.diff()
    pos_flow = raw_money_flow.where(delta > 0, 0.0)
    neg_flow = raw_money_flow.where(delta < 0, 0.0)

    pos_sum = pos_flow.rolling(window=period, min_periods=1).sum()
    neg_sum = neg_flow.rolling(window=period, min_periods=1).sum()

    mfi = 100 - (100 / (1 + pos_sum / neg_sum.replace(0, np.nan)))
    return mfi.fillna(50.0)


# ── Volatility ──

def compute_bollinger_bands(
    data: pd.DataFrame, period: int = 20, std_dev: float = 2.0
) -> Dict[str, pd.Series]:
    """Bollinger Bands.

    Args:
        data: OHLCV DataFrame.
        period: SMA window.
        std_dev: Band multiplier.

    Returns:
        Dict with keys ``upper``, ``middle``, ``lower``, ``bandwidth``, ``pct_b``.
    """
    close = _get_close(data)
    middle = close.rolling(window=period, min_periods=1).mean()
    std = close.rolling(window=period, min_periods=1).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    bandwidth = (upper - lower) / middle.replace(0, np.nan)
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "bandwidth": bandwidth,
        "pct_b": pct_b,
    }


def compute_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's smoothing).

    Args:
        data: OHLCV DataFrame.
        period: ATR look-back.

    Returns:
        ATR series.
    """
    high = data["high"]
    low = data["low"]
    close = _get_close(data)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    return atr.fillna(tr.rolling(window=period, min_periods=1).mean())


# ── Trend Strength ──

def compute_adx(data: pd.DataFrame, period: int = 14) -> Dict[str, pd.Series]:
    """Average Directional Index (+DI, -DI, ADX).

    Args:
        data: OHLCV DataFrame.
        period: DI/ADX look-back.

    Returns:
        Dict with keys ``adx``, ``plus_di``, ``minus_di``.
    """
    high = data["high"]
    low = data["low"]
    close = _get_close(data)

    plus_dm = (high.diff() > low.diff().abs()) & (high.diff() > 0)
    minus_dm = (low.diff().abs() > high.diff()) & (low.diff() < 0)

    plus_dm_vals = high.diff().where(plus_dm, 0.0)
    minus_dm_vals = (-low.diff()).where(minus_dm, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_vals = tr.ewm(alpha=1 / period, min_periods=period).mean()

    plus_di = 100 * plus_dm_vals.ewm(alpha=1 / period, min_periods=period).mean() / atr_vals.replace(0, np.nan)
    minus_di = 100 * minus_dm_vals.ewm(alpha=1 / period, min_periods=period).mean() / atr_vals.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()

    return {
        "adx": adx.fillna(0),
        "plus_di": plus_di.fillna(0),
        "minus_di": minus_di.fillna(0),
    }


# ── Trend / Overlay ──

def compute_ichimoku(data: pd.DataFrame) -> Dict[str, pd.Series]:
    """Ichimoku Cloud.

    Returns:
        Dict with keys ``tenkan``, ``kijun``, ``senkou_a``, ``senkou_b``, ``chikou``.
    """
    high = data["high"]
    low = data["low"]
    close = _get_close(data)

    tenkan = (high.rolling(9, min_periods=1).max() + low.rolling(9, min_periods=1).min()) / 2
    kijun = (high.rolling(26, min_periods=1).max() + low.rolling(26, min_periods=1).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((high.rolling(52, min_periods=1).max() + low.rolling(52, min_periods=1).min()) / 2).shift(26)
    chikou = close.shift(-26)

    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "chikou": chikou,
    }


def compute_supertrend(
    data: pd.DataFrame, period: int = 10, multiplier: float = 3.0
) -> Dict[str, pd.Series]:
    """Supertrend indicator.

    Args:
        data: OHLCV DataFrame.
        period: ATR look-back for bands.
        multiplier: Band width multiplier.

    Returns:
        Dict with keys ``supertrend``, ``direction`` (1=bullish, -1=bearish),
        ``upper_band``, ``lower_band``.
    """
    high = data["high"]
    low = data["low"]
    close = _get_close(data)

    atr = compute_atr(data, period)

    upper_band = ((high + low) / 2) + (multiplier * atr)
    lower_band = ((high + low) / 2) - (multiplier * atr)

    supertrend = pd.Series(index=data.index, dtype=float)
    direction = pd.Series(index=data.index, dtype=int)

    # Initialise first valid value
    first_valid = atr.first_valid_index()
    if first_valid is None:
        first_valid = data.index[0]

    supertrend.iloc[0] = upper_band.iloc[0]
    direction.iloc[0] = 1

    for i in range(1, len(data)):
        prev_st = supertrend.iloc[i - 1]
        curr_close = close.iloc[i]

        if prev_st == upper_band.iloc[i - 1]:
            supertrend.iloc[i] = (
                upper_band.iloc[i]
                if curr_close > upper_band.iloc[i]
                else max(lower_band.iloc[i], prev_st)
            )
        else:
            supertrend.iloc[i] = (
                lower_band.iloc[i]
                if curr_close < lower_band.iloc[i]
                else min(upper_band.iloc[i], prev_st)
            )

        direction.iloc[i] = 1 if curr_close > supertrend.iloc[i] else -1

    return {
        "supertrend": supertrend,
        "direction": direction,
        "upper_band": upper_band,
        "lower_band": lower_band,
    }


# ── Volume ──

def compute_vwap(data: pd.DataFrame) -> pd.Series:
    """Volume-Weighted Average Price (cumulative, reset per session).

    For daily data this produces a single-session VWAP.  For intra-day
    data you would typically reset per trading session.

    Args:
        data: OHLCV DataFrame.

    Returns:
        VWAP series.
    """
    typical = (data["high"] + data["low"] + data["close"]) / 3
    cum_typ_vol = (typical * data["volume"]).cumsum()
    cum_vol = data["volume"].cumsum().replace(0, np.nan)
    return (cum_typ_vol / cum_vol).fillna(typical)


def compute_obv(data: pd.DataFrame) -> pd.Series:
    """On Balance Volume.

    Args:
        data: OHLCV DataFrame.

    Returns:
        OBV series.
    """
    close = _get_close(data)
    volume = data["volume"]
    obv = pd.Series(index=data.index, dtype=float)
    obv.iloc[0] = volume.iloc[0]
    for i in range(1, len(data)):
        if close.iloc[i] > close.iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] + volume.iloc[i]
        elif close.iloc[i] < close.iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] - volume.iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i - 1]
    return obv


def compute_cmf(data: pd.DataFrame, period: int = 20) -> pd.Series:
    """Chaikin Money Flow.

    Args:
        data: OHLCV DataFrame.
        period: Look-back window.

    Returns:
        CMF series.
    """
    typical = (data["high"] + data["low"] + data["close"]) / 3
    money_flow_volume = ((data["close"] - data["low"]) - (data["high"] - data["close"])) / (
        data["high"] - data["low"]
    ).replace(0, np.nan) * data["volume"]
    cmf = money_flow_volume.rolling(window=period, min_periods=1).sum() / data["volume"].rolling(
        window=period, min_periods=1
    ).sum().replace(0, np.nan)
    return cmf.fillna(0.0)


def compute_elder_force_index(data: pd.DataFrame, period: int = 13) -> pd.Series:
    """Elder's Force Index.

    Args:
        data: OHLCV DataFrame.
        period: EMA smoothing period.

    Returns:
        EFI series.
    """
    close = _get_close(data)
    efi = (close.diff() * data["volume"]).ewm(span=period, adjust=False, min_periods=1).mean()
    return efi.fillna(0.0)


# ── Support / Resistance ──

def compute_fibonacci_levels(data: pd.DataFrame) -> Dict[str, float]:
    """Fibonacci retracement levels from recent swing high/low.

    Uses the highest high and lowest low over the last 60 bars.

    Returns:
        Dict mapping level name (e.g. ``0.0``, ``0.236``) to price.
    """
    recent = data.tail(60)
    swing_high = recent["high"].max()
    swing_low = recent["low"].min()
    diff = swing_high - swing_low
    levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    return {f"{lvl}": swing_low + lvl * diff for lvl in levels}


def compute_pivot_points(data: pd.DataFrame) -> Dict[str, float]:
    """Classic pivot points from the most recent complete bar.

    Returns:
        Dict with keys ``PP``, ``R1``, ``R2``, ``R3``, ``S1``, ``S2``, ``S3``.
    """
    last = data.iloc[-1]
    high, low, close = last["high"], last["low"], last["close"]
    pp = (high + low + close) / 3
    r1 = 2 * pp - low
    r2 = pp + (high - low)
    r3 = high + 2 * (pp - low)
    s1 = 2 * pp - high
    s2 = pp - (high - low)
    s3 = low - 2 * (high - pp)
    return {"PP": pp, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}


# ── Helpers ──

def compute_all_indicators(data: pd.DataFrame) -> Dict[str, any]:
    """Compute every indicator in one call and return a flat dictionary.

    Useful for the analyzer that needs every metric at once.
    """
    if data is None or data.empty or len(data) < 5:
        return {}

    # Ensure lower-case columns
    data = data.copy()
    data.columns = [c.lower() for c in data.columns]

    return {
        "sma_20": compute_sma(data, 20),
        "sma_50": compute_sma(data, 50),
        "ema_20": compute_ema(data, 20),
        "ema_50": compute_ema(data, 50),
        "rsi": compute_rsi(data, 14),
        "macd": compute_macd(data, 12, 26, 9),
        "bollinger": compute_bollinger_bands(data, 20, 2.0),
        "vwap": compute_vwap(data),
        "atr": compute_atr(data, 14),
        "adx": compute_adx(data, 14),
        "ichimoku": compute_ichimoku(data),
        "supertrend": compute_supertrend(data, 10, 3.0),
        "fibonacci": compute_fibonacci_levels(data),
        "pivot_points": compute_pivot_points(data),
        "stochastic": compute_stochastic(data, 14, 3),
        "williams_r": compute_williams_r(data, 14),
        "cmf": compute_cmf(data, 20),
        "obv": compute_obv(data),
        "efi": compute_elder_force_index(data, 13),
        "mfi": compute_mfi(data, 14),
    }
