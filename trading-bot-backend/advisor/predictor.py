"""Price prediction engine — multi-method target generation.

Predicts realistic price targets using ATR channels, Fibonacci extensions,
pivot-point support/resistance, Bollinger Band projections, and Ichimoku
cloud projections.  Combines them with confidence weighting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

from advisor.indicators import (
    compute_atr,
    compute_bollinger_bands,
    compute_fibonacci_levels,
    compute_ichimoku,
    compute_pivot_points,
)

from advisor.models import PriceTarget


@dataclass
class _RawTarget:
    label: str
    price: float
    probability: float
    rationale: str


class PricePredictor:
    """Predicts price targets using multiple technical methods."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_targets(self, data: pd.DataFrame, current_price: float, lookback_days: int = 90) -> List["PriceTarget"]:
        """Generate price targets from all methods.

        Args:
            data: OHLCV DataFrame.
            current_price: Last known price.
            lookback_days: Days of history used — enables forward projections for longer horizons.

        Returns:
            List of PriceTarget objects: forward projections first, then technical levels.
        """
        # Forward projections shown first so they're prominent
        forward = self._forward_projections(data, current_price, lookback_days)

        technical: List[_RawTarget] = []
        technical.extend(self._atr_targets(data, current_price))
        technical.extend(self._fibonacci_targets(data, current_price))
        technical.extend(self._pivot_targets(data, current_price))
        technical.extend(self._bollinger_targets(data, current_price))
        technical.extend(self._ichimoku_targets(data, current_price))

        # Deduplicate technical targets (within 0.5%)
        unique_tech: List[_RawTarget] = []
        for t in sorted(technical, key=lambda x: x.probability, reverse=True):
            if not any(
                (t.price == u.price == 0)
                or (u.price != 0 and abs(t.price / u.price - 1) < 0.005)
                for u in unique_tech
            ):
                unique_tech.append(t)

        combined = forward + unique_tech[:8]
        return [
            PriceTarget(
                label=t.label,
                price=round(t.price, 4),
                probability=round(t.probability, 2),
                rationale=t.rationale,
            )
            for t in combined
        ]

    # ------------------------------------------------------------------
    # Method implementations
    # ------------------------------------------------------------------

    def _atr_targets(self, data: pd.DataFrame, current_price: float) -> List[_RawTarget]:
        """ATR-based stop-loss and take-profit channels."""
        atr = compute_atr(data, 14).iloc[-1]
        vol_regime = self._volatility_regime(data)

        targets = []
        # 1× ATR (moderate, high probability)
        targets.append(
            _RawTarget(
                label="ATR Support (1×)",
                price=current_price - atr,
                probability=0.72,
                rationale=f"1× ATR support at {round(current_price - atr, 2)} based on 14-day volatility ({round(atr, 2)}).",
            )
        )
        targets.append(
            _RawTarget(
                label="ATR Resistance (1×)",
                price=current_price + atr,
                probability=0.68,
                rationale=f"1× ATR resistance at {round(current_price + atr, 2)} — typical daily range.",
            )
        )
        # 2× ATR (aggressive, lower probability)
        targets.append(
            _RawTarget(
                label="Deep Support (2× ATR)",
                price=current_price - 2 * atr,
                probability=0.55,
                rationale=f"2× ATR deep support at {round(current_price - 2 * atr, 2)} — rare but significant reversal zone.",
            )
        )
        targets.append(
            _RawTarget(
                label="Strong Resistance (2× ATR)",
                price=current_price + 2 * atr,
                probability=0.50,
                rationale=f"2× ATR extended target at {round(current_price + 2 * atr, 2)} — requires sustained momentum.",
            )
        )
        return targets

    def _fibonacci_targets(self, data: pd.DataFrame, current_price: float) -> List[_RawTarget]:
        """Fibonacci extension / retracement targets."""
        fib = compute_fibonacci_levels(data)
        recent = data.tail(60)
        swing_high = recent["high"].max()
        swing_low = recent["low"].min()
        diff = swing_high - swing_low

        targets = []
        # Use extension levels beyond 1.0 for upside, below 0.0 for downside
        extension_levels = {
            "Fib 1.272 Extension": 1.272,
            "Fib 1.618 Extension": 1.618,
            "Fib 0.0 Retracement (Swing Low)": 0.0,
        }
        for label, ratio in extension_levels.items():
            if ratio <= 1.0:
                price = swing_low + ratio * diff
                prob = 0.60 if ratio == 0.0 else 0.45
            else:
                price = swing_high + (ratio - 1.0) * diff
                prob = 0.50 if ratio == 1.272 else 0.40

            targets.append(
                _RawTarget(
                    label=label,
                    price=price,
                    probability=prob,
                    rationale=f"Fibonacci {label.split()[1]} level from recent swing ({round(swing_low, 2)}–{round(swing_high, 2)}).",
                )
            )

        # Key retracement levels as support / resistance
        for lvl_name, lvl_val in [("0.618", 0.618), ("0.382", 0.382)]:
            price = swing_low + lvl_val * diff
            dist_pct = abs(price / current_price - 1)
            if dist_pct > 0.01:  # only include if not basically current price
                targets.append(
                    _RawTarget(
                        label=f"Fib {lvl_name} Retracement",
                        price=price,
                        probability=0.62 if lvl_name == "0.618" else 0.58,
                        rationale=f"Key Fibonacci {lvl_name} retracement level at {round(price, 2)} — high-confluence zone.",
                    )
                )
        return targets

    def _pivot_targets(self, data: pd.DataFrame, current_price: float) -> List[_RawTarget]:
        """Classic pivot-point support / resistance."""
        pivots = compute_pivot_points(data)
        targets = []
        mapping = [
            ("R3", "Pivot R3 — extreme resistance", 0.35),
            ("R2", "Pivot R2 — strong resistance", 0.55),
            ("R1", "Pivot R1 — initial resistance", 0.70),
            ("S1", "Pivot S1 — initial support", 0.70),
            ("S2", "Pivot S2 — strong support", 0.55),
            ("S3", "Pivot S3 — extreme support", 0.35),
        ]
        for key, desc, prob in mapping:
            price = pivots[key]
            # Only include if reasonably close (within 3× current move potential)
            if price > 0 and abs(price / current_price - 1) < 0.30:
                targets.append(
                    _RawTarget(
                        label=f"Pivot {key}",
                        price=price,
                        probability=prob,
                        rationale=f"{desc} calculated from last bar HLC at {round(price, 2)}.",
                    )
                )
        return targets

    def _bollinger_targets(self, data: pd.DataFrame, current_price: float) -> List[_RawTarget]:
        """Bollinger Band projected targets."""
        bb = compute_bollinger_bands(data, 20, 2.0)
        upper = bb["upper"].iloc[-1]
        lower = bb["lower"].iloc[-1]
        middle = bb["middle"].iloc[-1]
        bandwidth_series = bb["bandwidth"]
        bandwidth = bandwidth_series.iloc[-1]

        targets = []
        # Band squeeze -> breakout scenario
        avg_bandwidth = bandwidth_series.rolling(50, min_periods=1).mean().iloc[-1]
        squeeze = bandwidth < avg_bandwidth * 0.8 if not pd.isna(avg_bandwidth) else False

        targets.append(
            _RawTarget(
                label="BB Upper (2σ)",
                price=upper,
                probability=0.60 if not squeeze else 0.75,
                rationale=f"Upper Bollinger Band at {round(upper, 2)} — mean-reversion resistance." +
                          (" Band squeeze detected — higher breakout probability." if squeeze else ""),
            )
        )
        targets.append(
            _RawTarget(
                label="BB Lower (2σ)",
                price=lower,
                probability=0.60 if not squeeze else 0.75,
                rationale=f"Lower Bollinger Band at {round(lower, 2)} — mean-reversion support." +
                          (" Band squeeze detected — higher breakdown probability." if squeeze else ""),
            )
        )
        # Middle as equilibrium
        targets.append(
            _RawTarget(
                label="BB Middle (20 SMA)",
                price=middle,
                probability=0.65,
                rationale=f"20-period SMA equilibrium at {round(middle, 2)} — reversion target.",
            )
        )
        return targets

    def _ichimoku_targets(self, data: pd.DataFrame, current_price: float) -> List[_RawTarget]:
        """Ichimoku cloud projection targets."""
        ichi = compute_ichimoku(data)
        senkou_a = ichi["senkou_a"].iloc[-1]
        senkou_b = ichi["senkou_b"].iloc[-1]
        kijun = ichi["kijun"].iloc[-1]

        targets = []
        if not pd.isna(senkou_a) and senkou_a > 0:
            targets.append(
                _RawTarget(
                    label="Senkou Span A (Cloud)",
                    price=senkou_a,
                    probability=0.58,
                    rationale=f"Leading span A at {round(senkou_a, 2)} — first cloud boundary, momentum proxy.",
                )
            )
        if not pd.isna(senkou_b) and senkou_b > 0:
            targets.append(
                _RawTarget(
                    label="Senkou Span B (Cloud)",
                    price=senkou_b,
                    probability=0.55,
                    rationale=f"Leading span B at {round(senkou_b, 2)} — stronger cloud boundary, long-term equilibrium.",
                )
            )
        if not pd.isna(kijun) and kijun > 0:
            targets.append(
                _RawTarget(
                    label="Kijun-sen (Base Line)",
                    price=kijun,
                    probability=0.62,
                    rationale=f"Kijun-sen (26-period equilibrium) at {round(kijun, 2)} — key support/resistance.",
                )
            )
        return targets

    def _forward_projections(self, data: pd.DataFrame, current_price: float, lookback_days: int) -> List[_RawTarget]:
        """1Y and 3Y forward price projections.

        Anchors the 1Y centerpoint to the analyst-consensus target when one is
        available on the dataframe (set via ``df.attrs['analyst_target_median']``);
        otherwise blends log-linear regression with realised CAGR and mean-reverts
        toward a long-run baseline. Also forces bull > current and bear < current
        so a "bear case" is never higher than today's price (the previous bug).
        """
        if len(data) < 30 or current_price <= 0:
            return []

        close = data["close"].values.astype(float)
        n = len(close)

        # Log-linear regression trend
        t = np.arange(n, dtype=float)
        log_prices = np.log(np.maximum(close, 1e-10))
        coeffs = np.polyfit(t, log_prices, 1)
        daily_log_growth = coeffs[0]
        regression_annual = np.exp(daily_log_growth * 252) - 1

        # CAGR from actual start→end
        period_years = max(n / 252, 0.05)
        cagr = (close[-1] / max(close[0], 1e-10)) ** (1.0 / period_years) - 1

        # Blend regression and CAGR, then mean-revert toward a long-run baseline.
        # Pure extrapolation of a hot recent year produces absurd 3Y numbers.
        RAW_BLEND = (regression_annual + cagr) / 2.0
        LONG_RUN_BASELINE = 0.10        # ~10%/yr long-run equity expectation
        MEAN_REVERT_WEIGHT = 0.55       # tilt 55% toward baseline so a hot 1y rally
                                        # doesn't drag the projection to the moon
        blended_rate = RAW_BLEND * (1 - MEAN_REVERT_WEIGHT) + LONG_RUN_BASELINE * MEAN_REVERT_WEIGHT
        # Tighter hard cap: keeps projections in plausible single-stock annual ranges.
        # Even the best companies rarely sustain >25%/yr; even disasters rarely
        # below -30%/yr without going to zero (which we model separately).
        blended_rate = float(np.clip(blended_rate, -0.30, 0.25))

        # Annualised historical volatility
        log_returns = np.diff(log_prices)
        annual_vol = float(np.std(log_returns) * np.sqrt(252)) if len(log_returns) > 1 else 0.30
        annual_vol = min(annual_vol, 0.80)  # cap projection vol at 80%

        # If an analyst median target is on the frame, use it as the 1Y centerpoint.
        attrs = getattr(data, "attrs", {}) or {}
        analyst_target_1y: float = 0.0
        try:
            atm = attrs.get("analyst_target_median")
            if atm is not None and atm > 0:
                analyst_target_1y = float(atm)
        except (TypeError, ValueError):
            analyst_target_1y = 0.0

        targets: List[_RawTarget] = []

        horizons = []
        if n >= 90:
            horizons.append((1, 0.55))
        if n >= 252:
            horizons.append((3, 0.45))

        data_years = round(n / 252, 1)
        cagr_pct = blended_rate * 100
        vol_pct = annual_vol * 100

        for years, base_prob in horizons:
            # Centerpoint: analyst consensus for 1Y when available, otherwise model.
            if years == 1 and analyst_target_1y > 0:
                base = analyst_target_1y
                base_source = "analyst median target"
            else:
                base = current_price * ((1 + blended_rate) ** years)
                base_source = f"blended CAGR {cagr_pct:+.1f}%/yr"

            # Bands are sigma-spreads relative to the centerpoint, not compounded
            # off the rate. Square-root-of-time scaling keeps multi-year bands sane.
            band_sigma = annual_vol * 0.75 * np.sqrt(years)
            bull = base * (1 + band_sigma)
            bear = base * (1 - band_sigma)

            # Sanity rails: a "bull case" should be > current price, a "bear case" < current.
            # When the centerpoint sits near current price and σ is small, the bands
            # can violate this — clamp them so the labels stay meaningful.
            if bull < current_price * 1.05:
                bull = current_price * 1.05
            if bear > current_price * 0.95:
                bear = current_price * 0.95

            base = max(base, current_price * 0.05)
            bull = max(bull, current_price * 0.05)
            bear = max(bear, current_price * 0.05)

            pct = (base / current_price - 1) * 100

            targets.append(_RawTarget(
                label=f"{years}Y Projection",
                price=base,
                probability=base_prob,
                rationale=(
                    f"{years}-year projection: {'+' if pct >= 0 else ''}{pct:.1f}% "
                    f"({base_source}, vol {vol_pct:.1f}%/yr). "
                    f"Based on {data_years}Y of history. Confidence bar = direction strength, not price certainty."
                ),
            ))
            targets.append(_RawTarget(
                label=f"{years}Y Bull Case",
                price=bull,
                probability=round(base_prob * 0.70, 2),
                rationale=(
                    f"{years}-year bull scenario (+0.75σ over {years}y): "
                    f"{(bull / current_price - 1) * 100:+.1f}% from current price."
                ),
            ))
            targets.append(_RawTarget(
                label=f"{years}Y Bear Case",
                price=bear,
                probability=round(base_prob * 0.70, 2),
                rationale=(
                    f"{years}-year bear scenario (−0.75σ over {years}y): "
                    f"{(bear / current_price - 1) * 100:+.1f}% from current price."
                ),
            ))

        return targets

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _volatility_regime(self, data: pd.DataFrame) -> str:
        """Classify volatility as low / moderate / high."""
        atr = compute_atr(data, 14)
        close = data["close"]
        atr_pct = (atr / close).iloc[-30:].mean()
        if pd.isna(atr_pct):
            return "moderate"
        if atr_pct < 0.015:
            return "low"
        if atr_pct < 0.04:
            return "moderate"
        return "high"
