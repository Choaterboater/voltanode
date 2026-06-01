"""Meta-labeling primitives: triple-barrier labels, features, purged-CV AUC."""

from __future__ import annotations

import numpy as np
import pandas as pd

from learning.meta_label import FEATURES, feature_frame, meta_label_cv_auc, triple_barrier_labels


def _ohlc(closes):
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "open": c, "high": c * 1.001, "low": c * 0.999, "close": c,
        "volume": np.full(len(c), 1000.0),
    })


def test_triple_barrier_win_and_loss():
    up = _ohlc([100, 102, 104, 106, 108])     # high reaches +5% (105) before any -5%
    assert triple_barrier_labels(up, [0], 0.05, 0.05, 4) == [1]
    dn = _ohlc([100, 98, 96, 94, 92])          # low reaches -5% (95) first
    assert triple_barrier_labels(dn, [0], 0.05, 0.05, 4) == [0]


def test_feature_frame_clean():
    df = _ohlc(list(range(100, 170)))
    f = feature_frame(df)
    assert list(f.columns) == FEATURES
    assert np.isfinite(f.to_numpy()).all()   # no NaN/inf


def test_cv_auc_detects_learnable_signal():
    rng = np.random.default_rng(0)
    n = 240
    y = rng.integers(0, 2, n)
    X = pd.DataFrame({f: rng.normal(size=n) for f in FEATURES})
    X["rsi"] = y * 8 + rng.normal(0, 1, n)    # rsi strongly predicts y
    r = meta_label_cv_auc(X, y, n_splits=4, embargo=2)
    assert r["auc"] > 0.75                    # model finds the conditional edge


def test_cv_auc_insufficient_data():
    X = pd.DataFrame({f: [0.0] * 12 for f in FEATURES})
    r = meta_label_cv_auc(X, np.array([0, 1] * 6))
    assert r["folds"] == 0                    # n<40 -> reported, not faked
