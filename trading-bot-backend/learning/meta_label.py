"""Meta-labeling (Lopez de Prado): does a primary strategy's signal have
*conditional* edge a secondary model can exploit?

The primary strategy decides the SIDE (when to BUY). The meta-labeler predicts
P(this BUY is correct) from features available at signal time, trained on
triple-barrier labels (did +TP hit before -SL within N bars?). If the model has
OOS skill (AUC > ~0.55 under purged CV), gating/sizing by it can extract edge
even when the unconditional edge is ~0. If AUC ≈ 0.5, the signal is noise and
meta-labeling can't help — honest either way.

Pure numpy/pandas + a lazy sklearn import (GradientBoosting). No live-path use.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ── features (computed from OHLCV up to the signal bar) ────────────────────

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


FEATURES = ["rsi", "macd_hist", "ema_ratio", "px_vs_ema50", "atr_pct", "rel_vol", "ret5", "ret10", "ret20"]


def feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Per-bar feature matrix (causal — each row uses only past/current data)."""
    c = df["close"].astype(float)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    out = pd.DataFrame(index=df.index)
    out["rsi"] = _rsi(c)
    out["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    out["ema_ratio"] = (ema12 / ema26 - 1.0)
    out["px_vs_ema50"] = (c / c.ewm(span=50, adjust=False).mean() - 1.0)
    out["atr_pct"] = (_atr(df) / c).fillna(0.0)
    vol = df["volume"].astype(float)
    out["rel_vol"] = (vol / vol.rolling(20).mean()).fillna(1.0)
    out["ret5"] = c.pct_change(5)
    out["ret10"] = c.pct_change(10)
    out["ret20"] = c.pct_change(20)
    return out.replace([np.inf, -np.inf], 0.0).fillna(0.0)


# ── triple-barrier labels ──────────────────────────────────────────────────

def triple_barrier_labels(df: pd.DataFrame, idxs: List[int], tp_pct: float, sl_pct: float, max_bars: int) -> List[int]:
    """For each signal bar i: 1 if +tp is hit before -sl within max_bars
    (using bar highs/lows), 0 if -sl first; on the time barrier, 1 iff the
    horizon close is above entry."""
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    close = df["close"].astype(float).to_numpy()
    n = len(close)
    labels: List[int] = []
    for i in idxs:
        entry = close[i]
        tp, sl = entry * (1 + tp_pct), entry * (1 - sl_pct)
        lab = None
        for j in range(i + 1, min(i + max_bars + 1, n)):
            if low[j] <= sl:
                lab = 0
                break
            if high[j] >= tp:
                lab = 1
                break
        if lab is None:
            end = min(i + max_bars, n - 1)
            lab = 1 if close[end] > entry else 0
        labels.append(lab)
    return labels


def build_meta_dataset(strategy, df: pd.DataFrame, tp_pct: float, sl_pct: float, max_bars: int,
                       warmup: int = 50) -> Tuple[pd.DataFrame, np.ndarray]:
    """Run the primary bar-by-bar, collect BUY-signal bars, attach features +
    triple-barrier labels. Returns (X, y)."""
    from bot.config import SignalType

    feats = feature_frame(df)
    buy_idx: List[int] = []
    strategy.reset()
    for i in range(warmup, len(df) - 1):
        sub = df.iloc[: i + 1].copy()
        sub.attrs["symbol"] = df.attrs.get("symbol", "")
        try:
            sig = strategy.generate_signal(sub, float(df["close"].iloc[i]))
        except Exception:
            continue
        if sig is not None and sig.signal_type == SignalType.BUY:
            buy_idx.append(i)
    if not buy_idx:
        return feats.iloc[0:0][FEATURES], np.array([])
    y = np.array(triple_barrier_labels(df, buy_idx, tp_pct, sl_pct, max_bars))
    X = feats.iloc[buy_idx][FEATURES].reset_index(drop=True)
    return X, y


# ── purged-CV evaluation ────────────────────────────────────────────────────

def meta_label_cv_auc(X: pd.DataFrame, y: np.ndarray, n_splits: int = 4, embargo: int = 5) -> Dict[str, Any]:
    """Mean out-of-sample AUC under contiguous K-fold with an embargo gap
    (signals are time-ordered; the embargo drops train rows adjacent to each
    test fold to curb leakage from the label horizon). AUC > ~0.55 ⇒ the model
    has skill on this signal. Returns {auc, n, base_rate, folds}."""
    n = len(y)
    base = float(y.mean()) if n else 0.0
    if n < 40 or len(np.unique(y)) < 2:
        return {"auc": float("nan"), "n": n, "base_rate": round(base, 3), "folds": 0, "note": "insufficient/degenerate data"}
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import roc_auc_score
    except Exception:
        return {"auc": float("nan"), "n": n, "base_rate": round(base, 3), "folds": 0, "note": "sklearn unavailable"}

    Xv = X.to_numpy()
    bounds = np.array_split(np.arange(n), n_splits)
    aucs: List[float] = []
    for fold in bounds:
        lo, hi = int(fold[0]), int(fold[-1])
        test_mask = np.zeros(n, dtype=bool)
        test_mask[lo:hi + 1] = True
        train_mask = ~test_mask
        train_mask[max(0, lo - embargo):lo] = False
        train_mask[hi + 1:hi + 1 + embargo] = False
        if train_mask.sum() < 20 or len(np.unique(y[train_mask])) < 2 or len(np.unique(y[test_mask])) < 2:
            continue
        clf = GradientBoostingClassifier(n_estimators=80, max_depth=2, learning_rate=0.05, random_state=0)
        clf.fit(Xv[train_mask], y[train_mask])
        proba = clf.predict_proba(Xv[test_mask])[:, 1]
        aucs.append(float(roc_auc_score(y[test_mask], proba)))
    if not aucs:
        return {"auc": float("nan"), "n": n, "base_rate": round(base, 3), "folds": 0, "note": "no valid folds"}
    return {"auc": round(float(np.mean(aucs)), 3), "n": n, "base_rate": round(base, 3), "folds": len(aucs)}
