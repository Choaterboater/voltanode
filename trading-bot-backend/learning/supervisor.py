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
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("volta.learning.supervisor")


def _protective_ids() -> frozenset:
    """The engine's protective exit ids — single source of truth."""
    try:
        from bot.engine import LiveTradingEngine

        return LiveTradingEngine._PROTECTIVE_STRATEGY_IDS
    except Exception:
        return frozenset({"sltp_manager", "partial_take_profit", "trailing_stop"})


#: Exit/bookkeeping ids that must never be evaluated or benched. Protective
#: ids come from the engine's kill-switch exemption set so the two lists
#: cannot drift apart.
PROTECTED_IDS = frozenset(
    {"broker_sync", "manual", "manual_flatten", "unknown", ""}
) | _protective_ids()

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
        cohort_bench: bool = True,
        state_path: Path | str = _STATE_PATH,
    ) -> None:
        self.min_trades = int(min_trades)
        self.min_pf = float(min_pf)
        self.rebench_fresh_trades = int(rebench_fresh_trades)
        # Cohort guard: bench a whole strategy_type family whose COMBINED
        # entry-attributed record proves no edge, even when each instance has
        # too few round trips to trip the per-strategy rule. Closes the blind
        # spot that let 5 sub-min_trades news_sentiment bots bleed -$1,910
        # uncaught. Set False to restore strict per-strategy benching only.
        self.cohort_bench = bool(cohort_bench)
        self.state_path = Path(state_path)
        self._state: Dict[str, Dict[str, Any]] = self._load_state()

    @staticmethod
    def _cohort_key(strategy_id: str) -> str:
        """Strategy-type family for a registry id (``<type>_<timestamp>``).

        Ids follow ``{strategy_type}_{epoch_ms}`` and the type itself may
        contain underscores (news_sentiment, mean_reversion, auto_discovery),
        so split off only the trailing timestamp segment.
        """
        return str(strategy_id).rsplit("_", 1)[0] or str(strategy_id)

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
        """Atomic write (tmp + replace): a torn state file would silently
        reset bench watermarks and let a freshly re-enabled bot be instantly
        re-benched on stale evidence."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
            os.replace(tmp, self.state_path)
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
        dirty = False

        for sid, rec in perf.items():
            strategy = registered.get(sid)
            if strategy is None:
                continue  # engine-level id or already deleted — nothing to bench
            if sid in PROTECTED_IDS:
                continue

            prior = self._state.get(sid) or {}
            benched_n = int(prior.get("benched_at_n", 0) or 0)
            # TradeMemory is wiped + rebuilt from fills.jsonl every cycle, so
            # n can SHRINK (log rotation / restore). Re-anchor the watermark
            # downward or the rebench guard goes unreachable.
            if benched_n and rec.n < benched_n:
                prior["benched_at_n"] = benched_n = rec.n
                self._state[sid] = prior
                dirty = True

            if rec.n < self.min_trades or rec.profit_factor >= self.min_pf:
                continue
            if getattr(strategy, "entries_disabled", False) or not getattr(strategy, "is_active", True):
                # Already benched (by us) or fully off (operator) — nothing to do.
                continue
            # Operator re-enabled after a bench: require fresh evidence
            # (new round trips beyond the bench watermark) before re-benching.
            if benched_n and rec.n < benched_n + self.rebench_fresh_trades:
                continue

            reason = (
                f"entry-attributed PF {rec.profit_factor:.2f} < {self.min_pf} "
                f"over {rec.n} closed round trips (total {rec.total_pnl:+.2f})"
            )
            # Entries-only veto — NEVER is_active=False: the engine skips
            # on_tick entirely for inactive strategies, which would disarm
            # the agentic exits (score-decay / trend-flip SELLs) on the
            # benched bot's open positions and leave only blunt hard stops.
            strategy.entries_disabled = True
            self._state[sid] = {
                "benched_at": datetime.now(timezone.utc).isoformat(),
                "benched_at_n": rec.n,
                "bench_reason": reason,
                "last_eval_n": rec.n,
                "last_eval_pf": round(rec.profit_factor, 4),
            }
            dirty = True
            actions.append({"strategy_id": sid, "reason": reason, **rec.to_dict()})
            logger.warning("Supervisor benched %s: %s", sid, reason)
            if notify is not None:
                try:
                    notify("warning", f"Supervisor benched {sid}: {reason}")
                except Exception:
                    pass

        # ── Cohort guard ──
        # A strategy_type FAMILY whose COMBINED entry-attributed record proves
        # no edge gets benched even when each instance is below min_trades on
        # its own (the news_sentiment blind spot: 5 bots at n=1-4, 0% win,
        # -$1,910 combined, none individually benchable). Entries-only veto,
        # same watermark/protection rules as the per-strategy pass.
        if self.cohort_bench:
            cohorts: Dict[str, StrategyRecord] = {}
            members: Dict[str, List[str]] = {}
            for sid, rec in perf.items():
                if registered.get(sid) is None or sid in PROTECTED_IDS:
                    continue
                ckey = self._cohort_key(sid)
                crec = cohorts.setdefault(ckey, StrategyRecord(strategy_id=f"<cohort:{ckey}>"))
                crec.n += rec.n
                crec.wins += rec.wins
                crec.gross_profit += rec.gross_profit
                crec.gross_loss += rec.gross_loss
                crec.total_pnl += rec.total_pnl
                members.setdefault(ckey, []).append(sid)

            for ckey, crec in cohorts.items():
                sids = members.get(ckey, [])
                # Single-instance "cohorts" add nothing over the per-strategy
                # pass; skip them so this can only bench on FAMILY evidence.
                if len(sids) < 2:
                    continue
                if crec.n < self.min_trades or crec.profit_factor >= self.min_pf:
                    continue
                for sid in sids:
                    strategy = registered.get(sid)
                    if strategy is None or sid in PROTECTED_IDS:
                        continue
                    if getattr(strategy, "entries_disabled", False) or not getattr(strategy, "is_active", True):
                        continue
                    rec = perf.get(sid)
                    # Never drag down an instance that has individually earned
                    # its keep (enough trips AND PF above the floor).
                    if rec is not None and rec.n >= self.min_trades and rec.profit_factor >= self.min_pf:
                        continue
                    # Respect the rebench watermark: an operator re-enable needs
                    # fresh round trips before the cohort may re-bench it.
                    prior = self._state.get(sid) or {}
                    benched_n = int(prior.get("benched_at_n", 0) or 0)
                    this_n = rec.n if rec is not None else 0
                    if benched_n and this_n < benched_n + self.rebench_fresh_trades:
                        continue
                    reason = (
                        f"cohort '{ckey}' entry-attributed PF {crec.profit_factor:.2f} "
                        f"< {self.min_pf} over {crec.n} combined round trips across "
                        f"{len(sids)} instances"
                    )
                    strategy.entries_disabled = True
                    self._state[sid] = {
                        "benched_at": datetime.now(timezone.utc).isoformat(),
                        "benched_at_n": this_n,
                        "bench_reason": reason,
                        "last_eval_n": this_n,
                        "last_eval_pf": round(rec.profit_factor, 4) if rec is not None else None,
                    }
                    dirty = True
                    row = rec.to_dict() if rec is not None else {"strategy_id": sid, "n": this_n}
                    actions.append({"strategy_id": sid, "reason": reason, **row})
                    logger.warning("Supervisor cohort-benched %s: %s", sid, reason)
                    if notify is not None:
                        try:
                            notify("warning", f"Supervisor cohort-benched {sid}: {reason}")
                        except Exception:
                            pass

        if actions:
            try:
                persist()
            except Exception as exc:
                logger.warning("Registry persist after benching failed: %s", exc)
        if dirty:
            self._save_state()
        return actions

    # ── Reporting (GET /learning/stats) ──

    def stats(
        self,
        records: List[Dict[str, Any]],
        registered: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Per-strategy entry-attributed performance + bench status.

        One row per strategy that has either closed round trips or a registry
        entry — registered bots with no evidence yet still show up (n=0,
        PF None) so the UI can honestly say "no evidence" instead of omitting
        exactly the newly enabled bots the operator most needs to watch.
        """
        perf = self.aggregate(records)
        ids = (set(perf) | set(registered)) - set(PROTECTED_IDS)

        def _row(sid: str) -> Dict[str, Any]:
            rec = perf.get(sid)
            strategy = registered.get(sid)
            state = self._state.get(sid) or {}
            base = (
                rec.to_dict()
                if rec is not None
                else {"strategy_id": sid, "n": 0, "profit_factor": None,
                      "win_rate": None, "total_pnl": 0.0}
            )
            return {
                **base,
                "registered": strategy is not None,
                "active": bool(getattr(strategy, "is_active", False)) if strategy is not None else None,
                "entries_disabled": bool(getattr(strategy, "entries_disabled", False)) if strategy is not None else None,
                "bench_reason": state.get("bench_reason"),
                "benched_at": state.get("benched_at"),
            }

        return sorted(
            (_row(sid) for sid in ids),
            key=lambda r: (r["total_pnl"], r["strategy_id"]),
        )
