"""Correlation-cluster haircut tests (analysis/correlation.py).

Pure clustering math + the per-cluster gross cap that stops auto-deploy from
opening N highly-correlated names as one concentrated bet.
"""

from __future__ import annotations

import numpy as np
import pytest

from analysis.correlation import (
    ClusterState,
    build_cluster_state,
    cached_returns,
    cluster_symbols,
    correlation_matrix,
    returns_from_closes,
    store_returns,
    _RETURNS_CACHE,
    _RETURNS_TS,
    _norm_key,
)


def _clear():
    _RETURNS_CACHE.clear()
    _RETURNS_TS.clear()


def _seed_correlated_universe():
    """BTC/ETH/SOL ~0.99 correlated; GLD independent."""
    _clear()
    rng = np.random.default_rng(0)
    base = rng.normal(0, 0.02, 120)
    store_returns("BTC", base + rng.normal(0, 0.0008, 120))
    store_returns("ETH", base + rng.normal(0, 0.0008, 120))
    store_returns("SOL", base + rng.normal(0, 0.0008, 120))
    store_returns("GLD", rng.normal(0, 0.02, 120))


def test_norm_key_strips_suffix_and_aliases():
    assert _norm_key("BTCUSD") == "BTC"
    assert _norm_key("ethusdt") == "ETH"
    assert _norm_key("bitcoin") == "BTC"
    assert _norm_key("AAPL") == "AAPL"


def test_returns_from_closes():
    r = returns_from_closes([100, 101, 102, 101])
    assert r.shape == (3,)
    assert np.isfinite(r).all()
    assert returns_from_closes([100]).size == 0


def test_correlated_symbols_cluster_together():
    _seed_correlated_universe()
    kept, mat = correlation_matrix(["BTC", "ETH", "SOL", "GLD"], min_obs=20)
    assert set(kept) == {"BTC", "ETH", "SOL", "GLD"}
    clusters = cluster_symbols(kept, mat, threshold=0.75)
    # BTC/ETH/SOL share one cluster; GLD is its own.
    assert clusters["BTC"] == clusters["ETH"] == clusters["SOL"]
    assert clusters["GLD"] != clusters["BTC"]


def test_cluster_gross_cap_haircuts_crowded_cluster():
    _seed_correlated_universe()
    # equity 100k, 40% per-cluster cap -> $40k per cluster.
    state = build_cluster_state(
        candidate_symbols=["ETH", "GLD"],
        held={"BTC": 30_000.0},     # BTC already fills most of its cluster
        equity=100_000.0,
        threshold=0.75,
        max_cluster_gross_pct=40.0,
    )
    # ETH shares BTC's cluster: only $10k room left of the $40k cap.
    assert state.haircut("ETH", 20_000.0) == pytest.approx(10_000.0)
    # GLD is uncorrelated: full $20k allowed.
    assert state.haircut("GLD", 20_000.0) == pytest.approx(20_000.0)
    # After adding ETH to fill the cluster, no room remains.
    state.add("ETH", 10_000.0)
    assert state.haircut("ETH", 5_000.0) == pytest.approx(0.0)


def test_haircut_failopen_when_no_cached_returns():
    _clear()  # nothing cached -> no cluster info
    state = build_cluster_state(["BTC", "ETH"], held={}, equity=100_000.0)
    # No correlation data => don't constrain (fail-open): full notional allowed.
    assert state.haircut("BTC", 50_000.0) == pytest.approx(50_000.0)


def test_cached_returns_staleness():
    _clear()
    store_returns("BTC", np.array([0.01, -0.02, 0.03]))
    assert cached_returns("BTC", max_age_s=900) is not None
    _RETURNS_TS["BTC"] = 0.0  # epoch -> very old
    assert cached_returns("BTC", max_age_s=900) is None
