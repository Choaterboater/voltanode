"""Correlation-cluster haircut for the capital allocator.

Pure return-correlation math + a module-level returns cache. The auto-deploy
allocator opens up to N positions, each capped per-symbol — but nothing caps
*correlation*: in a risk-on tape it can deploy 8 high-beta alts that move ~0.9
with BTC, which is really one concentrated BTC-beta bet the per-symbol cap
never sees. This module clusters the candidate + held universe by return
correlation and caps gross exposure per cluster.

NO trading behavior changes until ``capital_deployment.correlation_haircut``
is enabled. The cache is filled by a background refresher (see
``api/main.py:_run_correlation_loop``) so the deploy path does ZERO network
I/O — it reads ``cached_returns`` only, exactly like ``data/funding.py``.
Self-contained: no bot.* imports, fully unit-testable.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("volta.correlation")

# Cache keyed by the UPPER bare ticker (BTC, not BTCUSD/bitcoin). Values are
# the trailing daily log-return series + insert timestamp.
_RETURNS_CACHE: Dict[str, np.ndarray] = {}
_RETURNS_TS: Dict[str, float] = {}
_RETURNS_TTL_S = 6 * 3600.0  # 6h: daily-bar correlations don't move fast.

DEFAULT_CORR_THRESHOLD = 0.75        # |corr| >= this => same cluster
DEFAULT_MIN_OBS = 20                 # need >= N overlapping returns to trust a corr
DEFAULT_MAX_CLUSTER_GROSS_PCT = 40.0  # cap gross exposure per cluster (% equity)

_CG_ALIASES = {
    "BITCOIN": "BTC", "ETHEREUM": "ETH", "SOLANA": "SOL", "CARDANO": "ADA",
    "RIPPLE": "XRP", "DOGECOIN": "DOGE", "POLKADOT": "DOT", "CHAINLINK": "LINK",
    "AVALANCHE-2": "AVAX", "MATIC-NETWORK": "MATIC", "LITECOIN": "LTC",
}


def _norm_key(symbol: str) -> str:
    """Bare upper ticker for cache keys (BTCUSD / bitcoin -> BTC)."""
    s = str(symbol).strip().upper()
    s = _CG_ALIASES.get(s, s)
    for suf in ("USDT", "USD"):
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def returns_from_closes(closes) -> np.ndarray:
    """Daily log returns from a close-price array/Series. Pure."""
    arr = np.asarray(closes, dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    if arr.size < 2:
        return np.empty(0, dtype=float)
    return np.diff(np.log(arr))


def store_returns(symbol: str, returns: np.ndarray) -> None:
    """Insert/replace a symbol's trailing return series in the cache (no I/O)."""
    key = _norm_key(symbol)
    arr = np.asarray(returns, dtype=float)
    _RETURNS_CACHE[key] = arr[np.isfinite(arr)]
    _RETURNS_TS[key] = time.time()


def store_closes(symbol: str, closes) -> None:
    """Convenience: compute log returns from closes and cache them."""
    store_returns(symbol, returns_from_closes(closes))


def cached_returns(symbol: str, max_age_s: float = _RETURNS_TTL_S) -> Optional[np.ndarray]:
    """Read a symbol's cached returns with ZERO I/O. None if missing/stale."""
    key = _norm_key(symbol)
    ts = _RETURNS_TS.get(key)
    if ts is None or (time.time() - ts) > max_age_s:
        return None
    return _RETURNS_CACHE.get(key)


def correlation_matrix(
    symbols: List[str], *, min_obs: int = DEFAULT_MIN_OBS,
) -> Tuple[List[str], np.ndarray]:
    """Pairwise Pearson correlation over cached returns. Pure (reads cache).

    Aligns each pair on its trailing overlap (tail-aligned). Symbols with no
    cached series are dropped. Pairs with < ``min_obs`` overlap get corr 0.0
    (treated as uncorrelated -> own cluster, the safe default). Returns
    (kept_symbols, NxN matrix with 1.0 diagonal).
    """
    series: Dict[str, np.ndarray] = {}
    for s in symbols:
        r = cached_returns(s)
        if r is not None and r.size >= 2:
            series[_norm_key(s)] = r  # dedupes by bare ticker
    kept = list(series.keys())
    n = len(kept)
    mat = np.eye(n, dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = series[kept[i]], series[kept[j]]
            m = min(a.size, b.size)
            if m < min_obs:
                c = 0.0
            else:
                av, bv = a[-m:], b[-m:]
                if np.std(av) == 0 or np.std(bv) == 0:
                    c = 0.0
                else:
                    c = float(np.corrcoef(av, bv)[0, 1])
                    if not np.isfinite(c):
                        c = 0.0
            mat[i, j] = mat[j, i] = c
    return kept, mat


def cluster_symbols(
    symbols: List[str], matrix: np.ndarray, *, threshold: float = DEFAULT_CORR_THRESHOLD,
) -> Dict[str, int]:
    """Single-linkage threshold clustering (union-find). No matrix inversion.

    Two symbols join one cluster when |corr| >= threshold. Returns
    {bare_symbol -> dense cluster_id}.
    """
    n = len(symbols)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if abs(matrix[i, j]) >= threshold:
                parent[find(i)] = find(j)

    root_to_id: Dict[int, int] = {}
    out: Dict[str, int] = {}
    for idx, sym in enumerate(symbols):
        root = find(idx)
        if root not in root_to_id:
            root_to_id[root] = len(root_to_id)
        out[sym] = root_to_id[root]
    return out


@dataclass
class ClusterState:
    """Running gross exposure ($) per correlation cluster during a deploy cycle."""
    symbol_cluster: Dict[str, int]               # bare-ticker -> cluster id
    max_gross_per_cluster: float = 0.0           # dollars
    gross_by_cluster: Dict[int, float] = field(default_factory=dict)

    def cluster_of(self, symbol: str) -> Optional[int]:
        return self.symbol_cluster.get(_norm_key(symbol))

    def room_for(self, symbol: str) -> float:
        """Remaining gross-$ budget in this symbol's cluster (inf if unknown)."""
        cid = self.cluster_of(symbol)
        if cid is None or self.max_gross_per_cluster <= 0:
            return float("inf")  # no cluster info => don't constrain (fail-open)
        used = self.gross_by_cluster.get(cid, 0.0)
        return max(0.0, self.max_gross_per_cluster - used)

    def add(self, symbol: str, notional: float) -> None:
        cid = self.cluster_of(symbol)
        if cid is None:
            return
        self.gross_by_cluster[cid] = self.gross_by_cluster.get(cid, 0.0) + max(0.0, notional)

    def haircut(self, symbol: str, proposed_notional: float) -> float:
        """Allowed notional after the cluster cap (does NOT mutate; caller adds)."""
        if proposed_notional <= 0:
            return 0.0
        return min(proposed_notional, self.room_for(symbol))


def build_cluster_state(
    candidate_symbols: List[str],
    held: Optional[Dict[str, float]] = None,
    equity: float = 0.0,
    *,
    threshold: float = DEFAULT_CORR_THRESHOLD,
    max_cluster_gross_pct: float = DEFAULT_MAX_CLUSTER_GROSS_PCT,
    min_obs: int = DEFAULT_MIN_OBS,
) -> ClusterState:
    """Cluster candidate + held symbols and seed each cluster's gross with the
    market value already held there. Reads the cache only (zero I/O).

    ``held`` maps symbol -> current market value ($). ``equity`` sets the
    per-cluster gross cap (``equity * max_cluster_gross_pct/100``).
    """
    held = held or {}
    universe = list(dict.fromkeys([*candidate_symbols, *held.keys()]))
    kept, mat = correlation_matrix(universe, min_obs=min_obs)
    clusters = cluster_symbols(kept, mat, threshold=threshold)
    state = ClusterState(
        symbol_cluster=clusters,
        max_gross_per_cluster=max(0.0, equity * max_cluster_gross_pct / 100.0),
    )
    for sym, mv in held.items():
        state.add(sym, abs(float(mv or 0.0)))
    return state
