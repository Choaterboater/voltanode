"""Auto-disable supervisor: bench entry strategies with a proven negative edge.

The live account bled for a month through strategies whose record was already
damning after a handful of trades (momentum 0-for-6, the trailing-stop churn
0-for-30) because nothing ever acted on the evidence. This module closes the
loop: after every trade-memory refresh it computes ENTRY-attributed profit
factor per registered strategy and benches (``is_active = False``) any bot
that has proven it loses.

Rules (deliberately conservative):
- Evidence basis: closed round trips from TradeMemory (FIFO-reconstructed
  from fills.jsonl, entry-attributed, phantom-lot-guarded). Never
  ``BaseStrategy.get_metrics`` — those in-memory counters are wiped on every
  restart.
- Bench when ``n >= min_trades`` (default 10) AND ``pf < min_pf`` (0.7).
- Only ever touches ENTRY strategies that exist in the registered-strategy
  registry. Exit managers (sltp_manager / trailing_stop / partial_take_profit)
  and bookkeeping ids (broker_sync / manual / unknown) are hard-excluded —
  benching an exit manager would freeze stops.
- Never auto re-enables. A benched bot is re-enabled only by the operator
  (POST /strategies/{id}/toggle); the supervisor then waits for
  ``rebench_fresh_trades`` (default 5) NEW round trips before it may bench
  again, so a manual re-enable isn't instantly reverted on the same stale
  evidence.
- State (bench history + watermarks) persists to JSON so restarts don't
  forget what was benched on which evidence.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("volta.learning.supervisor")

#: Engine-level exit/bookkeeping ids that must never be evaluated or benched.
PROTECTED_IDS = {
    "sltp_manager",
    "trailing_stop",
    "partial_take_profit",
    "broker_sync",
    "manual",
    "manual_flatten",
    "unknown",
    "",
}

_STATE_PATH = Path("data") / "supervisor_state.json"


@dataclass
class StrategyRecord:
    """Entry-attributed performance for one registered strategy."""

    strategy_id: str
    n: int = 0
    wins: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0  # stored positive
    total_pnl: float = 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss <= 0:
            # No losses: infinite edge so far. Report a large finite number so
            # JSON consumers don't choke on Infinity.
            return 999.0 if self.gross_profit > 0 else 0.0
        return self.gross_profit / self.gross_loss

    @property
    def win_rate(self) -> float:
        return (self.wins / self.n * 100.0) if self.n else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "n": self.n,
            "profit_factor": round(self.profit_factor, 4),
            "win_rate": round(self.win_rate, 2),
            "total_pnl": round(self.total_pnl, 2),
        }


class StrategySupervisor:
    """Benches registered strategies whose entry-attributed PF proves no edge."""

    def __init__(
        self,
        min_trades: int = 10,
        min_pf: float = 0.7,
        rebench_fresh_trades: int = 5,
        state_path: Path | str = _STATE_PATH,
    ) -> None:
        self.min_trades = int(min_trades)
        self.min_pf = float(min_pf)
        self.rebench_fresh_trades = int(rebench_fresh_trades)
        self.state_path = Path(state_path)
        self._state: Dict[str, Dict[str, Any]] = self._load_state()

    # ── State persistence ──

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        try:
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            logger.warning("Could not read supervisor state: %s", exc)
        return {}

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(self._state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Could not persist supervisor state: %s", exc)

    # ── Evaluation ──

    @staticmethod
    def aggregate(records: List[Dict[str, Any]]) -> Dict[str, StrategyRecord]:
        """Fold TradeMemory round-trip dicts into per-strategy records."""
        out: Dict[str, StrategyRecord] = {}
        for r in records:
            sid = str(r.get("strategy") or "").strip()
            if not sid or sid in PROTECTED_IDS:
                continue
            try:
                pnl = float(r.get("pnl", 0) or 0)
            except (TypeError, ValueError):
                continue
            rec = out.setdefault(sid, StrategyRecord(strategy_id=sid))
            rec.n += 1
            rec.total_pnl += pnl
            if pnl > 0:
                rec.wins += 1
                rec.gross_profit += pnl
            else:
                rec.gross_loss += -pnl
        return out

    def run(
        self,
        records: List[Dict[str, Any]],
        registered: Dict[str, Any],
        persist: Callable[[], None],
        notify: Optional[Callable[[str, str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Evaluate and bench. Returns the list of bench actions taken.

        Args:
            records: TradeMemory round-trip dicts (entry-attributed).
            registered: the live ``_registered_strategies`` mapping
                (strategy_id -> strategy instance with ``is_active``).
            persist: callable that persists the registry (routes ``_persist``).
            notify: optional ``(level, message)`` alert sink.
        """
        actions: List[Dict[str, Any]] = []
        perf = self.aggregate(records)

        for sid, rec in perf.items():
            strategy = registered.get(sid)
            if strategy is None:
                continue  # engine-level id or already deleted — nothing to bench
            if sid in PROTECTED_IDS:
                continue
            if rec.n < self.min_trades or rec.profit_factor >= self.min_pf:
                continue

            prior = self._state.get(sid) or {}
            if not getattr(strategy, "is_active", True):
                # Already benched (by us or the operator) — refresh the
                # evidence snapshot but take no action.
                self._state[sid] = {
                    **prior,
                    "last_eval_n": rec.n,
                    "last_eval_pf": round(rec.profit_factor, 4),
                }
                continue
            # Operator re-enabled after a bench: require fresh evidence
            # (new round trips beyond the bench watermark) before re-benching.
            benched_n = int(prior.get("benched_at_n", 0) or 0)
            if benched_n and rec.n < benched_n + self.rebench_fresh_trades:
                continue

            reason = (
                f"entry-attributed PF {rec.profit_factor:.2f} < {self.min_pf} "
                f"over {rec.n} closed round trips (total {rec.total_pnl:+.2f})"
            )
            strategy.is_active = False
            self._state[sid] = {
                "benched_at": datetime.now(timezone.utc).isoformat(),
                "benched_at_n": rec.n,
                "bench_reason": reason,
                "last_eval_n": rec.n,
                "last_eval_pf": round(rec.profit_factor, 4),
            }
            actions.append({"strategy_id": sid, "reason": reason, **rec.to_dict()})
            logger.warning("Supervisor benched %s: %s", sid, reason)
            if notify is not None:
                try:
                    notify("warning", f"Supervisor benched {sid}: {reason}")
                except Exception:
                    pass

        if actions:
            try:
                persist()
            except Exception as exc:
                logger.warning("Registry persist after benching failed: %s", exc)
        self._save_state()
        return actions

    # ── Reporting (GET /learning/stats) ──

    def stats(
        self,
        records: List[Dict[str, Any]],
        registered: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Per-strategy entry-attributed performance + bench status."""
        perf = self.aggregate(records)
        rows: List[Dict[str, Any]] = []
        seen: set = set()
        for sid, rec in sorted(perf.items(), key=lambda kv: kv[1].total_pnl):
            strategy = registered.get(sid)
            state = self._state.get(sid) or {}
            rows.append(
                {
                    **rec.to_dict(),
                    "registered": strategy is not None,
                    "active": bool(getattr(strategy, "is_active", False)) if strategy is not None else None,
                    "bench_reason": state.get("bench_reason"),
                    "benched_at": state.get("benched_at"),
                }
            )
            seen.add(sid)
        # Registered bots with no closed round trips yet still show up, so the
        # UI can honestly say "no evidence yet" instead of omitting them.
        for sid, strategy in registered.items():
            if sid in seen or sid in PROTECTED_IDS:
                continue
            state = self._state.get(sid) or {}
            rows.append(
                {
                    "strategy_id": sid,
                    "n": 0,
                    "profit_factor": None,
                    "win_rate": None,
                    "total_pnl": 0.0,
                    "registered": True,
                    "active": bool(getattr(strategy, "is_active", False)),
                    "bench_reason": state.get("bench_reason"),
                    "benched_at": state.get("benched_at"),
                }
            )
        return rows
