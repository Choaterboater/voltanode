"""Kronos forecast strategy — EXPERIMENTAL.

Wraps the open-source Kronos foundation model (github.com/shiyu-coder/Kronos,
MIT) which forecasts future OHLCV candles. We turn an N-bar forecast into a
BUY / SELL / HOLD: if the model's predicted close `pred_len` bars out implies a
return above a threshold, go long; below the negative threshold, exit/short.

DESIGN NOTES
------------
- Heavy deps (``torch`` and the Kronos ``model`` package) are imported LAZILY,
  and every failure path returns HOLD. Importing this module on a box without a
  GPU / model download therefore never breaks the engine — the strategy simply
  stays flat. This lets it sit in the registry while we validate it.
- This is unproven. A forecaster is not edge until it survives a cost-aware,
  out-of-sample backtest. Validate with ``scripts/kronos_backtest.py`` BEFORE
  enabling it live. Keep it disabled in config until then.

SETUP (local, where Hugging Face is reachable)::

    pip install torch transformers huggingface_hub einops
    git clone https://github.com/shiyu-coder/Kronos
    export PYTHONPATH="$PYTHONPATH:/path/to/Kronos"   # exposes the `model` package

The model weights download from the HF Hub on first use (cached thereafter).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd

from bot.config import SignalType
from strategies.base import BaseStrategy, Signal


# Process-wide cache: one (tokenizer, model, predictor) per model name, shared
# across every symbol/bot so we don't reload a 100M-param model per strategy.
_PREDICTOR_CACHE: Dict[Tuple[str, str, int, str], Any] = {}
_LOAD_FAILED: Dict[Tuple[str, str, int, str], str] = {}


def _load_predictor(
    model_name: str, tokenizer_name: str, max_context: int, device: str
) -> Optional[Any]:
    """Lazily load + cache a KronosPredictor. Returns None on any failure."""
    key = (model_name, tokenizer_name, max_context, device)
    if key in _PREDICTOR_CACHE:
        return _PREDICTOR_CACHE[key]
    if key in _LOAD_FAILED:
        return None
    try:
        # Imported here so module import never requires torch / the Kronos repo.
        from model import Kronos, KronosTokenizer, KronosPredictor  # type: ignore

        tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
        model = Kronos.from_pretrained(model_name)
        predictor = KronosPredictor(
            model, tokenizer, device=device, max_context=max_context
        )
        _PREDICTOR_CACHE[key] = predictor
        return predictor
    except Exception as exc:  # noqa: BLE001 — fail safe, never crash the engine
        _LOAD_FAILED[key] = f"{type(exc).__name__}: {exc}"
        return None


class KronosForecastStrategy(BaseStrategy):
    """Trade on the Kronos model's N-bar OHLCV forecast (experimental)."""

    name = "kronos_forecast"
    SUPPORTS_MULTI_SYMBOL = True
    DEFAULT_CONFIG: Dict[str, Any] = {
        "model_name": "NeoQuasar/Kronos-small",
        "tokenizer_name": "NeoQuasar/Kronos-Tokenizer-base",
        "device": "cpu",          # set "cuda:0" where a GPU is available
        "max_context": 512,
        "lookback": 400,          # bars fed to the model (<= max_context)
        "pred_len": 12,           # bars to forecast ahead
        # Expected forecast return over the horizon needed to act. Net of the
        # ~0.1% fee + slippage, so keep it comfortably above round-trip cost.
        "buy_threshold": 0.008,
        "sell_threshold": 0.008,
        # Kronos sampling controls (probabilistic decoder).
        "T": 1.0,
        "top_p": 0.9,
        "sample_count": 1,
        "position_pct": 0.03,
        "stop_loss_pct": 0.05,    # mirror the engine's tightened default
        "take_profit_pct": 0.12,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Per-symbol latch: only emit once per bar (on_tick fires every ~5s).
        self._last_signal_bar: Dict[str, Any] = {}

    def _hold(self, symbol: str, **meta: Any) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            signal_type=SignalType.HOLD,
            confidence=0.0,
            timestamp=pd.Timestamp.now(),
            metadata=meta or None,
        )

    def _future_timestamps(self, idx: pd.Index, pred_len: int) -> pd.Series:
        """Extend the last timestamp by the median bar delta, pred_len times."""
        ts = pd.to_datetime(pd.Series(idx))
        if len(ts) >= 2:
            delta = ts.diff().dropna().median()
        else:
            delta = pd.Timedelta(hours=1)
        last = ts.iloc[-1]
        return pd.Series([last + delta * (i + 1) for i in range(pred_len)])

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        data = self._ensure_columns(data)
        cfg = self.config
        symbol = data.attrs.get("symbol", "unknown")

        lookback = int(cfg["lookback"])
        pred_len = int(cfg["pred_len"])
        if len(data) < min(lookback, 128) + 1 or current_price <= 0:
            return self._hold(symbol, trigger="warmup")

        # Per-bar latch.
        latest_bar = self._bar_key(data.index[-1] if len(data.index) else None)
        if latest_bar is not None and self._last_signal_bar.get(symbol) == latest_bar:
            return self._hold(symbol, trigger="already_fired_this_bar")

        predictor = _load_predictor(
            cfg["model_name"], cfg["tokenizer_name"],
            int(cfg["max_context"]), str(cfg["device"]),
        )
        if predictor is None:
            # Model unavailable (no torch / no download / load error) -> flat.
            key = (cfg["model_name"], cfg["tokenizer_name"],
                   int(cfg["max_context"]), str(cfg["device"]))
            return self._hold(symbol, trigger="model_unavailable",
                              error=_LOAD_FAILED.get(key))

        window = data.iloc[-lookback:]
        cols = [c for c in ("open", "high", "low", "close", "volume", "amount")
                if c in window.columns]
        x_df = window[cols].reset_index(drop=True)
        x_timestamp = pd.to_datetime(pd.Series(window.index))
        y_timestamp = self._future_timestamps(window.index, pred_len)

        try:
            pred_df = predictor.predict(
                df=x_df,
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=pred_len,
                T=float(cfg["T"]),
                top_p=float(cfg["top_p"]),
                sample_count=int(cfg["sample_count"]),
            )
        except Exception as exc:  # noqa: BLE001
            return self._hold(symbol, trigger="predict_error",
                              error=f"{type(exc).__name__}: {exc}")

        if pred_df is None or "close" not in pred_df or len(pred_df) == 0:
            return self._hold(symbol, trigger="empty_forecast")

        pred_close = float(pred_df["close"].iloc[-1])
        exp_return = (pred_close / current_price) - 1.0
        buy_thr = float(cfg["buy_threshold"])
        sell_thr = float(cfg["sell_threshold"])

        self._last_signal_bar[symbol] = latest_bar
        meta = {
            "trigger": "kronos_forecast",
            "expected_return": round(exp_return, 5),
            "pred_close": round(pred_close, 6),
            "current_price": round(current_price, 6),
            "horizon_bars": pred_len,
        }

        if exp_return >= buy_thr:
            confidence = min(1.0, 0.5 + min(exp_return / (buy_thr * 4), 0.5))
            sig = Signal(
                strategy_id=self.strategy_id, symbol=symbol,
                signal_type=SignalType.BUY, confidence=confidence,
                timestamp=pd.Timestamp.now(), metadata=meta,
                suggested_size=self._size_from_equity_pct(
                    current_price, default_pct=float(cfg["position_pct"])),
                stop_loss=current_price * (1.0 - float(cfg["stop_loss_pct"])),
                take_profit=current_price * (1.0 + float(cfg["take_profit_pct"])),
            )
            self._record_signal(sig)
            return sig

        if exp_return <= -sell_thr:
            confidence = min(1.0, 0.5 + min(abs(exp_return) / (sell_thr * 4), 0.5))
            sig = Signal(
                strategy_id=self.strategy_id, symbol=symbol,
                signal_type=SignalType.SELL, confidence=confidence,
                timestamp=pd.Timestamp.now(), metadata=meta,
            )
            self._record_signal(sig)
            return sig

        return self._hold(symbol, **meta)
