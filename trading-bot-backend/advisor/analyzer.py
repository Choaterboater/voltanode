"""Full symbol analysis orchestrator.

Orchestrates data fetching, indicator computation, signal generation,
price-target prediction, and recommendation synthesis into a single
``AnalysisResult``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from advisor.indicators import compute_all_indicators
from advisor.models import AnalysisResult, IndicatorReading, PriceTarget
from advisor.predictor import PricePredictor
from advisor.recommender import RecommendationEngine
from bot.config import AssetClass
from data.cache import DataCache
from data.fetcher import MarketData


class SymbolAnalyzer:
    """Analyses any stock or crypto symbol and produces a recommendation."""

    def __init__(self, market_data: MarketData | None = None) -> None:
        """Initialise the analyser.

        Args:
            market_data: Optional MarketData instance.  If None, a default
                one is created with a temporary cache.
        """
        if market_data is None:
            cache = DataCache(cache_dir="./data/cache")
            from bot.config import BotConfig

            market_data = MarketData(cache=cache, config=BotConfig())
        self.market_data = market_data
        self.predictor = PricePredictor()
        self.recommender = RecommendationEngine()

    async def analyze(
        self,
        symbol: str,
        asset_type: str = "crypto",
        lookback_days: int = 90,
        advanced: bool = False,
    ) -> AnalysisResult:
        """Run the full analysis pipeline.

        Args:
            symbol: Trading symbol (CoinGecko ID for crypto, Yahoo ticker for stocks).
            asset_type: ``"crypto"`` or ``"stock"``.
            lookback_days: Days of history to request.

        Returns:
            Complete ``AnalysisResult``.
        """
        # ── 1. Fetch OHLCV ──
        data = await self._fetch_data(symbol, asset_type, lookback_days)
        if data is None or data.empty:
            return self._error_result(symbol, asset_type, "Unable to fetch market data.")

        current_price = float(data["close"].iloc[-1])

        # ── 2. Compute all indicators ──
        indicators = compute_all_indicators(data)

        # ── 3. Generate readings ──
        readings = self._generate_readings(indicators, data, current_price)

        # ── 4. Recommendation ──
        reading_dicts = [
            {
                "name": r.name,
                "value": r.value,
                "signal": r.signal,
                "strength": r.strength,
                "description": r.description,
            }
            for r in readings
        ]
        verdict, confidence, summary = self.recommender.recommend(reading_dicts, data, current_price)

        # ── 5. Price targets ──
        # If we have an analyst median target (yfinance), pass it on the frame
        # so the predictor can anchor 1Y projection to consensus instead of
        # naively extrapolating recent CAGR.
        if asset_type == "stock":
            try:
                import yfinance as yf
                info = yf.Ticker(symbol).info or {}
                atm = info.get("targetMedianPrice") or info.get("targetMeanPrice")
                if atm:
                    data.attrs["analyst_target_median"] = float(atm)
            except Exception:
                pass
        targets = self.predictor.predict_targets(data, current_price)

        # ── 6. Risk & sizing ──
        risk_level, position_size, entry_zone, stop_loss, take_profit, time_horizon = self._risk_analysis(
            data, current_price, verdict, confidence, targets
        )

        # ── 7. Chart data ──
        chart_data = self._build_chart_data(data, indicators)

        # Display metadata — best-effort, never fatal.
        display_name, exchange, sector = await asyncio.to_thread(
            self._fetch_display_metadata, symbol, asset_type
        )

        result = AnalysisResult(
            symbol=symbol,
            current_price=round(current_price, 4),
            asset_type=asset_type,
            verdict=verdict,
            confidence=round(confidence, 1),
            summary=summary,
            indicators=readings,
            price_targets=targets,
            risk_level=risk_level,
            suggested_position_size=round(position_size, 3),
            entry_zone=entry_zone,
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            time_horizon=time_horizon,
            chart_data=chart_data,
            display_name=display_name,
            exchange=exchange,
            sector=sector,
        )

        # ── 8. Optional LLM commentary (Llama / OpenAI / Anthropic / OpenRouter) ──
        # Runs in a thread so the requests-based LLM clients don't block the
        # asyncio event loop. Failures are non-fatal — the deterministic
        # analysis is always returned even if the LLM call errors.
        # When advanced=True, force the OpenRouter provider regardless of env.
        try:
            from advisor.llm_advisor import generate_commentary
            commentary = await asyncio.to_thread(
                generate_commentary, result, "openrouter" if advanced else None
            )
            if commentary is not None:
                result.llm_commentary = commentary
        except Exception as exc:
            import logging as _log
            _log.getLogger("volta.advisor").warning(f"LLM commentary skipped: {exc}")

        return result

    def _fetch_display_metadata(self, symbol: str, asset_type: str) -> tuple[str, str, str]:
        """Return (display_name, exchange, sector). All fields best-effort.

        Stocks → yfinance Ticker.info
        Crypto → CoinGecko coin metadata cache
        """
        try:
            if asset_type == "stock":
                import yfinance as yf
                info = yf.Ticker(symbol).info or {}
                name = info.get("longName") or info.get("shortName") or symbol.upper()
                exchange = info.get("exchange") or info.get("fullExchangeName") or ""
                sector = info.get("sector") or ""
                return str(name), str(exchange), str(sector)
            else:
                # CoinGecko: derive a friendly display name from the id slug
                # without an extra API call (e.g. 'matic-network' -> 'Matic Network')
                # and let the ticker map fill in for short aliases.
                friendly = symbol.replace("-", " ").replace("_", " ").title()
                return friendly, "", ""
        except Exception:
            return symbol.upper(), "", ""

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    async def _fetch_data(
        self, symbol: str, asset_type: str, lookback_days: int
    ) -> pd.DataFrame | None:
        """Fetch OHLCV. Raises ValueError when the symbol can't be resolved.

        Previously fell back to deterministic synthetic data on miss, which
        silently served random prices for unknown tickers. That misleads
        users into thinking they're seeing real analysis, so we now surface
        the failure instead.
        """
        last_error: Exception | None = None
        try:
            if asset_type == "crypto":
                df = await self.market_data.get_crypto_ohlcv(symbol, days=lookback_days)
            else:
                # Map lookback days → yfinance period string. Must include the
                # current UI ranges (30/90/365) plus legacy values for callers
                # that pass arbitrary numbers.
                period_map = {
                    7: "5d", 14: "1mo", 28: "1mo", 30: "1mo",
                    60: "3mo", 90: "3mo", 180: "6mo",
                    365: "1y", 730: "2y",
                }
                period = period_map.get(lookback_days, "1y")
                df = self.market_data.get_stock_ohlcv(symbol, period=period)
            if df is not None and not df.empty:
                df = self._normalise_df(df)
                df.attrs["lookback_days"] = lookback_days
                return df
        except Exception as exc:
            last_error = exc

        suffix = f": {last_error}" if last_error else ""
        raise ValueError(
            f"Symbol '{symbol}' not found on the {asset_type} feed. "
            f"For crypto use a CoinGecko id (e.g. 'bitcoin') or a known ticker "
            f"(e.g. 'BTC'); for stocks use a Yahoo ticker (e.g. 'AAPL', 'CAT'){suffix}"
        )

    def _normalise_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure lower-case columns and numeric types."""
        df = df.copy()
        df.columns = [str(c).lower().strip() for c in df.columns]
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # Drop rows with missing core prices
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df.reset_index(drop=True)

    def _synthetic_data(self, symbol: str, periods: int = 90) -> pd.DataFrame:
        """Generate realistic synthetic OHLCV data.

        Uses a random-walk with trend and realistic volatility patterns
        so that technical indicators still produce meaningful signals.
        """
        np.random.seed(hash(symbol) % (2 ** 31))
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=periods, freq="D")

        # Base price from symbol hash (deterministic per symbol)
        base_price = 50 + (hash(symbol) % 10000) / 100

        # Generate returns with slight mean reversion and clustering
        returns = np.random.normal(0.0005, 0.02, periods)
        # Add some autocorrelation (trend persistence)
        for i in range(1, periods):
            returns[i] += 0.1 * returns[i - 1]
        # Add a modest trend component
        trend = np.linspace(0, 0.15, periods)
        returns += trend / periods

        closes = base_price * np.exp(np.cumsum(returns))

        # Build realistic OHLC from close
        intraday_vol = np.abs(np.random.normal(0, 0.015, periods))
        highs = closes * (1 + intraday_vol)
        lows = closes * (1 - intraday_vol * 0.8)
        opens = closes * (1 + np.random.normal(0, 0.005, periods))
        volumes = np.random.randint(1_000_000, 50_000_000, periods)

        df = pd.DataFrame({
            "timestamp": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })
        df.attrs["symbol"] = symbol
        df.attrs["lookback_days"] = periods
        return df

    # ------------------------------------------------------------------
    # Reading generation
    # ------------------------------------------------------------------

    def _generate_readings(
        self, indicators: Dict[str, Any], data: pd.DataFrame, current_price: float
    ) -> List[IndicatorReading]:
        """Turn raw indicator values into signal readings."""
        readings: List[IndicatorReading] = []

        # --- SMA ---
        if "sma_20" in indicators and "sma_50" in indicators:
            sma20 = indicators["sma_20"].iloc[-1]
            sma50 = indicators["sma_50"].iloc[-1]
            signal = "bullish" if current_price > sma20 > sma50 else "bearish" if current_price < sma20 < sma50 else "neutral"
            strength = 0.85 if current_price > sma20 > sma50 else 0.85 if current_price < sma20 < sma50 else 0.4
            desc = f"Price {round(current_price, 2)} vs SMA20 {round(sma20, 2)} and SMA50 {round(sma50, 2)}."
            readings.append(IndicatorReading("SMA 20/50", round(current_price / ((sma20 + sma50) / 2) - 1, 4) * 100, signal, strength, desc))

        # --- EMA ---
        if "ema_20" in indicators and "ema_50" in indicators:
            ema20 = indicators["ema_20"].iloc[-1]
            ema50 = indicators["ema_50"].iloc[-1]
            signal = "bullish" if ema20 > ema50 else "bearish" if ema20 < ema50 else "neutral"
            dist = abs(ema20 / ema50 - 1)
            strength = min(0.9, max(0.3, dist * 50))
            desc = f"EMA20 {round(ema20, 2)} {'above' if ema20 > ema50 else 'below'} EMA50 {round(ema50, 2)} — trend alignment."
            readings.append(IndicatorReading("EMA 20/50", round(ema20, 2), signal, strength, desc))

        # --- RSI ---
        if "rsi" in indicators:
            rsi = indicators["rsi"].iloc[-1]
            if pd.isna(rsi):
                rsi = 50.0
            signal = "bullish" if rsi < 30 else "bearish" if rsi > 70 else "neutral"
            strength = min(0.9, abs(rsi - 50) / 40)
            desc = f"RSI at {round(rsi, 1)} — {'oversold, potential bounce' if rsi < 30 else 'overbought, potential pullback' if rsi > 70 else 'neutral territory'}."
            readings.append(IndicatorReading("RSI (14)", round(rsi, 2), signal, strength, desc))

        # --- MACD ---
        if "macd" in indicators:
            macd = indicators["macd"]
            macd_val = macd["macd"].iloc[-1]
            signal_val = macd["signal"].iloc[-1]
            hist = macd["histogram"].iloc[-1]
            signal = "bullish" if macd_val > signal_val else "bearish"
            strength = min(0.9, abs(macd_val - signal_val) / (abs(macd["macd"]).mean() + 1e-9))
            desc = f"MACD {round(macd_val, 3)} vs Signal {round(signal_val, 3)} (hist {round(hist, 3)}) — {'bullish' if macd_val > signal_val else 'bearish'} crossover."
            readings.append(IndicatorReading("MACD", round(macd_val, 4), signal, strength, desc))

        # --- Bollinger ---
        if "bollinger" in indicators:
            bb = indicators["bollinger"]
            upper = bb["upper"].iloc[-1]
            lower = bb["lower"].iloc[-1]
            pct_b = bb["pct_b"].iloc[-1]
            if pd.isna(pct_b):
                pct_b = 0.5
            signal = "bearish" if pct_b > 0.9 else "bullish" if pct_b < 0.1 else "neutral"
            strength = abs(pct_b - 0.5) * 2
            desc = f"Price at {round(pct_b * 100, 1)}% of Bollinger range (upper {round(upper, 2)}, lower {round(lower, 2)})."
            readings.append(IndicatorReading("Bollinger Bands %B", round(pct_b, 4), signal, strength, desc))

        # --- VWAP ---
        if "vwap" in indicators:
            vwap = indicators["vwap"].iloc[-1]
            signal = "bullish" if current_price > vwap else "bearish"
            strength = min(0.8, abs(current_price / vwap - 1) * 10)
            desc = f"Price {round(current_price, 2)} {'above' if current_price > vwap else 'below'} VWAP {round(vwap, 2)} — {'institutional accumulation' if current_price > vwap else 'institutional distribution'}."
            readings.append(IndicatorReading("VWAP", round(vwap, 2), signal, strength, desc))

        # --- ATR ---
        if "atr" in indicators:
            atr = indicators["atr"].iloc[-1]
            atr_pct = atr / current_price if current_price > 0 else 0
            signal = "neutral"
            strength = 0.5
            regime = "low" if atr_pct < 0.015 else "moderate" if atr_pct < 0.04 else "high"
            desc = f"ATR {round(atr, 2)} ({round(atr_pct * 100, 2)}% of price) — {regime} volatility regime."
            readings.append(IndicatorReading("ATR (14)", round(atr, 4), signal, strength, desc))

        # --- ADX ---
        if "adx" in indicators:
            adx = indicators["adx"]
            adx_val = adx["adx"].iloc[-1]
            plus_di = adx["plus_di"].iloc[-1]
            minus_di = adx["minus_di"].iloc[-1]
            if pd.isna(adx_val):
                adx_val = 0
            trend_strength = "strong" if adx_val > 25 else "weak"
            signal = "bullish" if plus_di > minus_di else "bearish"
            strength = min(0.9, adx_val / 50)
            desc = f"ADX {round(adx_val, 1)} ({trend_strength} trend), +DI {round(plus_di, 1)} vs -DI {round(minus_di, 1)}."
            readings.append(IndicatorReading("ADX/DI", round(adx_val, 2), signal, strength, desc))

        # --- Supertrend ---
        if "supertrend" in indicators:
            st = indicators["supertrend"]
            direction = st["direction"].iloc[-1]
            st_val = st["supertrend"].iloc[-1]
            signal = "bullish" if direction == 1 else "bearish"
            strength = 0.85
            desc = f"Supertrend at {round(st_val, 2)} — {'bullish' if direction == 1 else 'bearish'} direction confirmed."
            readings.append(IndicatorReading("Supertrend", round(st_val, 2), signal, strength, desc))

        # --- Stochastic ---
        if "stochastic" in indicators:
            sto = indicators["stochastic"]
            k = sto["k"].iloc[-1]
            d = sto["d"].iloc[-1]
            if pd.isna(k):
                k = 50.0
            signal = "bullish" if k < 20 else "bearish" if k > 80 else "neutral"
            strength = min(0.85, abs(k - 50) / 50)
            desc = f"Stochastic %K {round(k, 1)}, %D {round(d, 1)} — {'oversold bounce' if k < 20 else 'overbought pullback' if k > 80 else 'neutral'}."
            readings.append(IndicatorReading("Stochastic", round(k, 2), signal, strength, desc))

        # --- Williams %R ---
        if "williams_r" in indicators:
            wr = indicators["williams_r"].iloc[-1]
            if pd.isna(wr):
                wr = -50.0
            signal = "bullish" if wr < -80 else "bearish" if wr > -20 else "neutral"
            strength = min(0.85, abs(wr + 50) / 50)
            desc = f"Williams %R at {round(wr, 1)} — {'oversold' if wr < -80 else 'overbought' if wr > -20 else 'mid-range'}."
            readings.append(IndicatorReading("Williams %R", round(wr, 2), signal, strength, desc))

        # --- CMF ---
        if "cmf" in indicators:
            cmf = indicators["cmf"].iloc[-1]
            if pd.isna(cmf):
                cmf = 0.0
            signal = "bullish" if cmf > 0.05 else "bearish" if cmf < -0.05 else "neutral"
            strength = min(0.8, abs(cmf) * 5)
            desc = f"Chaikin Money Flow {round(cmf, 3)} — {'accumulation' if cmf > 0.05 else 'distribution' if cmf < -0.05 else 'balanced flow'}."
            readings.append(IndicatorReading("CMF (20)", round(cmf, 4), signal, strength, desc))

        # --- OBV ---
        if "obv" in indicators:
            obv = indicators["obv"]
            obv_slope = (obv.iloc[-1] - obv.iloc[-10]) if len(obv) >= 10 else 0
            price_slope = data["close"].iloc[-1] - data["close"].iloc[-10] if len(data) >= 10 else 0
            signal = "bullish" if obv_slope > 0 and price_slope > 0 else "bearish" if obv_slope < 0 and price_slope < 0 else "neutral"
            strength = 0.7 if signal != "neutral" else 0.3
            desc = f"OBV trend {'confirming price' if (obv_slope > 0) == (price_slope > 0) else 'diverging from price'}."
            readings.append(IndicatorReading("OBV", float(obv.iloc[-1]), signal, strength, desc))

        # --- MFI ---
        if "mfi" in indicators:
            mfi = indicators["mfi"].iloc[-1]
            if pd.isna(mfi):
                mfi = 50.0
            signal = "bullish" if mfi < 20 else "bearish" if mfi > 80 else "neutral"
            strength = min(0.85, abs(mfi - 50) / 40)
            desc = f"Money Flow Index at {round(mfi, 1)} — {'oversold' if mfi < 20 else 'overbought' if mfi > 80 else 'neutral'}."
            readings.append(IndicatorReading("MFI (14)", round(mfi, 2), signal, strength, desc))

        # --- Ichimoku ---
        if "ichimoku" in indicators:
            ichi = indicators["ichimoku"]
            tenkan = ichi["tenkan"].iloc[-1]
            kijun = ichi["kijun"].iloc[-1]
            senkou_a = ichi["senkou_a"].iloc[-1]
            senkou_b = ichi["senkou_b"].iloc[-1]
            if pd.isna(tenkan) or pd.isna(kijun):
                pass
            else:
                signal = "bullish" if tenkan > kijun and current_price > max(senkou_a, senkou_b) else \
                         "bearish" if tenkan < kijun and current_price < min(senkou_a, senkou_b) else "neutral"
                strength = 0.85 if signal != "neutral" else 0.4
                desc = f"Ichimoku: TK {'bullish' if tenkan > kijun else 'bearish'} cross, price vs cloud {'above' if current_price > max(senkou_a, senkou_b) else 'below' if current_price < min(senkou_a, senkou_b) else 'inside'}."
                readings.append(IndicatorReading("Ichimoku Cloud", round(tenkan, 2), signal, strength, desc))

        # --- Elder Force Index ---
        if "efi" in indicators:
            efi = indicators["efi"].iloc[-1]
            if pd.isna(efi):
                efi = 0.0
            signal = "bullish" if efi > 0 else "bearish" if efi < 0 else "neutral"
            strength = min(0.7, abs(efi) / (abs(indicators["efi"]).mean() + 1))
            desc = f"Elder's Force Index {round(efi, 1)} — {'buying pressure' if efi > 0 else 'selling pressure' if efi < 0 else 'neutral'}."
            readings.append(IndicatorReading("Elder Force Index", round(efi, 2), signal, strength, desc))

        return readings

    # ------------------------------------------------------------------
    # Risk analysis
    # ------------------------------------------------------------------

    def _risk_analysis(
        self,
        data: pd.DataFrame,
        current_price: float,
        verdict: str,
        confidence: float,
        targets: List[PriceTarget],
    ) -> Tuple[str, float, Tuple[float, float], float, float, str]:
        """Derive risk level, position size, entry zone, stop, and take-profit."""
        from advisor.indicators import compute_atr

        atr = float(compute_atr(data, 14).iloc[-1])
        atr_pct = atr / current_price if current_price > 0 else 0

        # Risk level
        if atr_pct > 0.06:
            risk_level = "extreme"
        elif atr_pct > 0.035:
            risk_level = "high"
        elif atr_pct > 0.015:
            risk_level = "moderate"
        else:
            risk_level = "low"

        # Position sizing (volatility-adjusted Kelly-inspired)
        base_size = 0.05  # 5% base
        if risk_level == "low":
            base_size = 0.10
        elif risk_level == "moderate":
            base_size = 0.07
        elif risk_level == "high":
            base_size = 0.03
        else:
            base_size = 0.01

        # Scale by confidence
        position_size = base_size * (confidence / 100)
        position_size = max(0.01, min(0.20, position_size))

        # Stop loss and take profit
        is_buy = verdict in ("BUY", "STRONG_BUY")
        is_sell = verdict in ("SELL", "STRONG_SELL")
        
        if is_buy:
            stop_loss = current_price - 2 * atr
            take_profit = current_price + 3 * atr
        elif is_sell:
            stop_loss = current_price + 2 * atr
            take_profit = current_price - 3 * atr
        else:
            # HOLD — set symmetric bands for reference
            stop_loss = current_price - 2 * atr
            take_profit = current_price + 3 * atr

        # Entry zone: near current price ± ATR
        if is_buy:
            entry_low = max(current_price - atr, stop_loss * 0.98)
            entry_high = current_price + atr * 0.3
        elif is_sell:
            entry_low = current_price - atr * 0.3
            entry_high = min(current_price + atr, stop_loss * 1.02)
        else:
            entry_low = current_price - atr * 0.5
            entry_high = current_price + atr * 0.5

        # Time horizon based on user's selected lookback period.
        # Buckets line up with the UI's range buttons (1mo / 3mo / 1yr).
        lookback_days = getattr(data, 'attrs', {}).get('lookback_days', 90)
        if lookback_days <= 30:
            time_horizon = "short_term"
        elif lookback_days <= 90:
            time_horizon = "medium_term"
        else:
            time_horizon = "long_term"

        return risk_level, position_size, (float(entry_low), float(entry_high)), float(stop_loss), float(take_profit), time_horizon

    # ------------------------------------------------------------------
    # Chart data
    # ------------------------------------------------------------------

    def _build_chart_data(self, data: pd.DataFrame, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """Build serialisable chart data for frontend rendering."""
        timestamps = data["timestamp"].astype(str).tolist() if "timestamp" in data.columns else []
        if not timestamps:
            timestamps = [str(i) for i in range(len(data))]

        chart = {
            "timestamps": timestamps,
            "ohlcv": {
                "open": data["open"].tolist(),
                "high": data["high"].tolist(),
                "low": data["low"].tolist(),
                "close": data["close"].tolist(),
                "volume": data["volume"].tolist(),
            },
        }

        # Overlay series
        for key in ["sma_20", "sma_50", "ema_20", "ema_50", "vwap"]:
            if key in indicators:
                s = indicators[key]
                chart[key] = [round(v, 4) if not pd.isna(v) else None for v in s.tolist()]

        # Bollinger
        if "bollinger" in indicators:
            bb = indicators["bollinger"]
            chart["bb_upper"] = [round(v, 4) if not pd.isna(v) else None for v in bb["upper"].tolist()]
            chart["bb_lower"] = [round(v, 4) if not pd.isna(v) else None for v in bb["lower"].tolist()]

        # MACD
        if "macd" in indicators:
            macd = indicators["macd"]
            chart["macd"] = [round(v, 4) if not pd.isna(v) else None for v in macd["macd"].tolist()]
            chart["macd_signal"] = [round(v, 4) if not pd.isna(v) else None for v in macd["signal"].tolist()]
            chart["macd_hist"] = [round(v, 4) if not pd.isna(v) else None for v in macd["histogram"].tolist()]

        # RSI
        if "rsi" in indicators:
            chart["rsi"] = [round(v, 2) if not pd.isna(v) else None for v in indicators["rsi"].tolist()]

        # Supertrend
        if "supertrend" in indicators:
            st = indicators["supertrend"]
            chart["supertrend"] = [round(v, 4) if not pd.isna(v) else None for v in st["supertrend"].tolist()]

        # Ichimoku
        if "ichimoku" in indicators:
            ichi = indicators["ichimoku"]
            chart["tenkan"] = [round(v, 4) if not pd.isna(v) else None for v in ichi["tenkan"].tolist()]
            chart["kijun"] = [round(v, 4) if not pd.isna(v) else None for v in ichi["kijun"].tolist()]

        # ADX
        if "adx" in indicators:
            adx = indicators["adx"]
            chart["adx"] = [round(v, 2) if not pd.isna(v) else None for v in adx["adx"].tolist()]

        return chart

    # ------------------------------------------------------------------
    # Error result
    # ------------------------------------------------------------------

    def _error_result(self, symbol: str, asset_type: str, message: str) -> AnalysisResult:
        """Return a neutral result when analysis fails."""
        return AnalysisResult(
            symbol=symbol,
            current_price=0.0,
            asset_type=asset_type,
            verdict="HOLD",
            confidence=0.0,
            summary=message,
            indicators=[],
            price_targets=[],
            risk_level="high",
            suggested_position_size=0.0,
            entry_zone=(0.0, 0.0),
            stop_loss=0.0,
            take_profit=0.0,
            time_horizon="medium_term",
            chart_data={},
        )


# ------------------------------------------------------------------
# Demo
# ------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def _demo():
        analyser = SymbolAnalyzer()
        result = await analyser.analyze("bitcoin", asset_type="crypto", lookback_days=90)
        print(f"Symbol: {result.symbol}")
        print(f"Price: ${result.current_price:,.2f}")
        print(f"Verdict: {result.verdict} ({result.confidence}% confidence)")
        print(f"Risk: {result.risk_level}")
        print(f"Entry zone: {result.entry_zone}")
        print(f"Stop: {result.stop_loss}, Take-profit: {result.take_profit}")
        print(f"Indicators: {len(result.indicators)}")
        for r in result.indicators[:5]:
            print(f"  - {r.name}: {r.signal} (strength {r.strength:.2f})")
        print(f"Price targets: {len(result.price_targets)}")
        for t in result.price_targets[:5]:
            print(f"  - {t.label}: ${t.price:,.2f} (prob {t.probability:.0%})")
        print(f"\nSummary:\n{result.summary}")

    asyncio.run(_demo())
