"""CPCV + Deflated Sharpe Ratio promotion gate (Lopez de Prado).

Combinatorial Purged Cross-Validation with purge + embargo for honest
out-of-sample Sharpe, plus the Deflated Sharpe Ratio (DSR) to correct for the
multiple-testing selection bias of running N hyperopt trials and keeping the
best. This is the last guardrail before live capital: it blocks promoting a
config whose backtest edge is indistinguishable from noise once you account
for how many dials were spun and out-of-sample variance.

Pure numpy/pandas/stdlib — NO scipy (not a project dependency). The normal
CDF/PPF are closed-form (math.erf + Acklam rational approximation). The gate
reuses the existing BacktestRunner path read-only and runs ONLY on the
operator-initiated apply-hyperopt route — never on the live tick path.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ── Closed-form standard-normal CDF / PPF (no scipy) ──────────────────────

def _norm_cdf(x: float) -> float:
    """Standard-normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation).

    Accurate to ~1.15e-9 over (0,1). Clamps the open-interval ends.
    """
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


# ── CPCV fold generation ──────────────────────────────────────────────────

def cpcv_splits(
    n_samples: int,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo_pct: float = 0.01,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """(train_idx, test_idx) for every C(n_groups, n_test_groups) combo.

    Bars are partitioned into ``n_groups`` contiguous blocks. Each split holds
    out ``n_test_groups`` blocks as test; remaining bars are train MINUS a
    purge/embargo of ``ceil(n_samples*embargo_pct)`` bars adjacent to each test
    block (those would leak via indicator lookback / label overlap).
    """
    if n_samples < n_groups or n_groups < 2 or n_test_groups < 1 or n_test_groups >= n_groups:
        return []
    idx = np.arange(n_samples)
    bounds = np.array_split(idx, n_groups)
    embargo = int(math.ceil(n_samples * max(0.0, embargo_pct)))
    splits: List[Tuple[np.ndarray, np.ndarray]] = []
    for combo in combinations(range(n_groups), n_test_groups):
        test_idx = np.concatenate([bounds[g] for g in combo])
        test_set = set(test_idx.tolist())
        purge = set()
        for g in combo:
            lo, hi = int(bounds[g][0]), int(bounds[g][-1])
            for j in range(max(0, lo - embargo), min(n_samples, hi + 1 + embargo)):
                purge.add(j)
        train_idx = np.array([i for i in idx if i not in test_set and i not in purge])
        if train_idx.size == 0 or test_idx.size == 0:
            continue
        splits.append((train_idx, np.sort(test_idx)))
    return splits


# ── Deflated Sharpe Ratio (Lopez de Prado 2014) ───────────────────────────

def deflated_sharpe_ratio(
    observed_sr: float,
    sr_variance_across_trials: float,
    n_trials: int,
    n_returns: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """P(true SR > 0 | observed SR, N trials) in [0,1].

    Builds the expected-maximum-Sharpe benchmark SR0 from N independent trials,
    then the probabilistic Sharpe of ``observed_sr`` vs SR0, adjusting the SR
    estimator's standard error for non-normal returns (skew/kurtosis). A higher
    ``n_trials`` or ``sr_variance_across_trials`` raises SR0 → harder to pass.
    """
    if n_trials < 1 or n_returns < 2 or sr_variance_across_trials <= 0:
        return 0.0
    sigma_sr = math.sqrt(sr_variance_across_trials)
    emc = 0.5772156649015329  # Euler-Mascheroni
    n = max(n_trials, 2)
    sr0 = sigma_sr * (
        (1.0 - emc) * _norm_ppf(1.0 - 1.0 / n)
        + emc * _norm_ppf(1.0 - 1.0 / (n * math.e))
    )
    denom = math.sqrt(
        max(1e-12, 1.0 - skew * observed_sr + (kurtosis - 1.0) / 4.0 * observed_sr ** 2)
    )
    psr_arg = (observed_sr - sr0) * math.sqrt(n_returns - 1) / denom
    return float(_norm_cdf(psr_arg))


# ── Gate config + result ──────────────────────────────────────────────────

@dataclass
class PromotionGateConfig:
    enabled: bool = False           # OPT-IN. Absent block => disabled => no-op.
    n_groups: int = 6
    n_test_groups: int = 2
    embargo_pct: float = 0.01
    min_dsr: float = 0.5            # DSR is a probability; >0.5 == positive after deflation
    min_oos_sharpe: float = 0.0
    min_trades_per_fold: int = 3

    @classmethod
    def from_mapping(cls, m: Optional[Dict[str, Any]]) -> "PromotionGateConfig":
        m = m or {}
        return cls(
            enabled=bool(m.get("enabled", False)),
            n_groups=int(m.get("n_groups", 6)),
            n_test_groups=int(m.get("n_test_groups", 2)),
            embargo_pct=float(m.get("embargo_pct", 0.01)),
            min_dsr=float(m.get("min_dsr", 0.5)),
            min_oos_sharpe=float(m.get("min_oos_sharpe", 0.0)),
            min_trades_per_fold=int(m.get("min_trades_per_fold", 3)),
        )


@dataclass
class GateResult:
    passed: bool
    dsr: float
    mean_oos_sharpe: float
    n_folds: int
    n_trials: int
    n_returns: int
    fold_sharpes: List[float] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "dsr": round(self.dsr, 4),
            "mean_oos_sharpe": round(self.mean_oos_sharpe, 4),
            "n_folds": self.n_folds,
            "n_trials": self.n_trials,
            "n_returns": self.n_returns,
            "fold_sharpes": [round(s, 4) for s in self.fold_sharpes],
            "reason": self.reason,
        }


def _oos_sharpe_for_config(
    strategy_type: str,
    config: Dict[str, Any],
    df: pd.DataFrame,
    bt_config: Any,
    splits: List[Tuple[np.ndarray, np.ndarray]],
    min_trades: int = 3,
) -> List[float]:
    """Per-fold OOS Sharpe via the existing BacktestRunner on each test slice.

    Folds with < ``min_trades`` are scored 0.0 (no edge demonstrated) rather
    than dropped, so a config that only works in one regime is penalized.
    """
    # Lazy import to keep this module importable without the strategy/backtest
    # stack (e.g. for pure cpcv_splits/DSR unit tests).
    from backtest.engine import BacktestRunner
    from strategies import StrategyFactory

    out: List[float] = []
    sym = df.attrs.get("symbol", "")
    for _train_idx, test_idx in splits:
        fold_df = df.iloc[np.sort(test_idx)].reset_index(drop=True)
        fold_df.attrs["symbol"] = sym
        try:
            strat = StrategyFactory(strategy_type, config=dict(config))
            result = BacktestRunner(strat, fold_df, bt_config).run()
            m = result.metrics.to_dict()
            sr = float(m.get("sharpe_ratio", 0.0))
            if int(m.get("total_trades", 0)) < min_trades or not math.isfinite(sr):
                sr = 0.0
        except Exception:
            sr = 0.0
        out.append(sr)
    return out


def evaluate_promotion(
    strategy_type: str,
    candidate_config: Dict[str, Any],
    df: pd.DataFrame,
    bt_config: Any,
    n_trials: int,
    gate_cfg: PromotionGateConfig,
    trial_sharpes: Optional[List[float]] = None,
) -> GateResult:
    """CPCV-evaluate ``candidate_config`` and deflate by ``n_trials``.

    ``trial_sharpes`` (the per-trial Sharpe values from hyperopt, if available)
    gives a truer across-trial variance for DSR; otherwise the variance across
    CPCV folds is used as the proxy.
    """
    splits = cpcv_splits(len(df), gate_cfg.n_groups, gate_cfg.n_test_groups, gate_cfg.embargo_pct)
    fold_sr = _oos_sharpe_for_config(
        strategy_type, candidate_config, df, bt_config, splits,
        min_trades=gate_cfg.min_trades_per_fold,
    )
    arr = np.asarray(fold_sr, dtype=float)
    mean_sr = float(arr.mean()) if arr.size else 0.0
    if trial_sharpes:
        tarr = np.asarray([s for s in trial_sharpes if math.isfinite(s)], dtype=float)
        var_sr = float(tarr.var(ddof=1)) if tarr.size > 1 else 0.0
    else:
        var_sr = float(arr.var(ddof=1)) if arr.size > 1 else 0.0
    if var_sr <= 0:
        var_sr = (abs(mean_sr) + 1e-6) ** 2
    dsr = deflated_sharpe_ratio(
        observed_sr=mean_sr,
        sr_variance_across_trials=var_sr,
        n_trials=max(1, n_trials),
        n_returns=len(df),
    )
    passed = (dsr > gate_cfg.min_dsr) and (mean_sr > gate_cfg.min_oos_sharpe)
    reason = "" if passed else (
        f"DSR {dsr:.3f} <= {gate_cfg.min_dsr} or mean OOS Sharpe "
        f"{mean_sr:.3f} <= {gate_cfg.min_oos_sharpe}"
    )
    return GateResult(passed, dsr, mean_sr, len(splits), n_trials, len(df), fold_sr, reason)
