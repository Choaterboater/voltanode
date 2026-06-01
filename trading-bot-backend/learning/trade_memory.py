"""Trade memory — the learning loop for the paper-trading lab.

Captures every CLOSED round-trip with context + a plain-English lesson, so the
system (and the operator) can learn from mistakes over time instead of repeating
them. Three views of the same data:

* **Structured JSONL** (`data/trade_memory.jsonl`) — the queryable source of truth.
* **Obsidian vault** (`data/vault/`) — human-readable, linked markdown notes
  (one per trade) + a rolling `_dashboard.md`. Open the folder in Obsidian and
  the [[wikilinks]] build a graph by symbol / strategy / outcome.
* **Recall** (`recall`, `stats`, `worst_setups`) — retrieval for an LLM advisor
  or a pre-trade gate ("last 5 times you ran this setup you lost").

Pure stdlib, no heavy deps. The vector-RAG upgrade (embed lessons, semantic
recall) drops into `recall()` later; v1 uses structured + tag retrieval, which
is plenty for a single account's history.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("volta.learning")


def _parse_ts(s: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s))
    except Exception:
        return None


def _hold_bucket(minutes: float) -> str:
    if minutes < 60:
        return "intraday-fast"      # < 1h
    if minutes < 24 * 60:
        return "intraday"           # < 1d
    if minutes < 7 * 24 * 60:
        return "swing"              # < 1w
    return "position"               # >= 1w


@dataclass
class TradeMemoryRecord:
    """One closed long round-trip + its lesson."""
    id: str
    symbol: str
    strategy: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    pnl_pct: float
    holding_minutes: float
    outcome: str               # "win" | "loss" | "scratch"
    exit_reason: str
    tags: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)   # regime/signals/news if available
    lesson: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _outcome(pnl_pct: float) -> str:
    if pnl_pct > 0.1:
        return "win"
    if pnl_pct < -0.1:
        return "loss"
    return "scratch"


class TradeMemory:
    """Append-only trade memory with Obsidian export + recall."""

    def __init__(self, memory_path: str = "data/trade_memory.jsonl", vault_dir: str = "data/vault") -> None:
        self.memory_path = Path(memory_path)
        self.vault_dir = Path(vault_dir)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        (self.vault_dir / "trades").mkdir(parents=True, exist_ok=True)

    # ── write ──────────────────────────────────────────────────────────────

    def record(self, rec: TradeMemoryRecord, write_note: bool = True) -> None:
        with self.memory_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec.to_dict()) + "\n")
        if write_note:
            self._write_note(rec)

    def _write_note(self, rec: TradeMemoryRecord) -> None:
        date = (rec.exit_time or "")[:10]
        slug = f"{date}-{rec.symbol}-{rec.strategy}-{rec.id[:8]}".replace("/", "_")
        sign = "+" if rec.pnl >= 0 else ""
        body = (
            f"---\n"
            f"id: {rec.id}\n"
            f"symbol: {rec.symbol}\n"
            f"strategy: {rec.strategy}\n"
            f"outcome: {rec.outcome}\n"
            f"pnl: {round(rec.pnl, 4)}\n"
            f"pnl_pct: {round(rec.pnl_pct, 3)}\n"
            f"held_minutes: {round(rec.holding_minutes, 1)}\n"
            f"exit_reason: {rec.exit_reason}\n"
            f"date: {date}\n"
            f"tags: [{', '.join('trade/' + t for t in rec.tags)}]\n"
            f"---\n\n"
            f"# {rec.symbol} · {rec.strategy} — {rec.outcome.upper()} {sign}{round(rec.pnl_pct, 2)}%\n\n"
            f"- **Entry:** ${rec.entry_price:.4f} @ {rec.entry_time}\n"
            f"- **Exit:** ${rec.exit_price:.4f} @ {rec.exit_time} ({rec.exit_reason})\n"
            f"- **Qty:** {rec.qty:g} · **P&L:** {sign}${round(rec.pnl, 2)} ({sign}{round(rec.pnl_pct, 2)}%)\n"
            f"- **Held:** {round(rec.holding_minutes, 1)} min ({_hold_bucket(rec.holding_minutes)})\n\n"
        )
        if rec.context:
            body += "## Context at entry\n" + "\n".join(f"- {k}: {v}" for k, v in rec.context.items()) + "\n\n"
        body += f"## Lesson\n{rec.lesson or '_(pending reflection)_'}\n\n"
        body += f"Related: [[{rec.symbol}]] · [[{rec.strategy}]] · [[{rec.outcome}s]]\n"
        try:
            (self.vault_dir / "trades" / f"{slug}.md").write_text(body, encoding="utf-8")
        except OSError as exc:
            logger.warning(f"vault note write failed: {exc}")

    # ── read / recall ───────────────────────────────────────────────────────

    def all(self) -> List[Dict[str, Any]]:
        if not self.memory_path.exists():
            return []
        out = []
        for line in self.memory_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out

    def recall(
        self,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        outcome: Optional[str] = None,
        k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Most-recent matching trades (newest first). The retrieval hook a
        pre-trade gate / LLM advisor calls before acting."""
        rows = self.all()
        def match(r: Dict[str, Any]) -> bool:
            if symbol and str(r.get("symbol", "")).upper() != symbol.upper():
                return False
            if strategy and r.get("strategy") != strategy:
                return False
            if outcome and r.get("outcome") != outcome:
                return False
            return True
        rows = [r for r in rows if match(r)]
        rows.sort(key=lambda r: r.get("exit_time", ""), reverse=True)
        return rows[:k]

    def stats(self) -> Dict[str, Any]:
        """Aggregate win-rate / avg-P&L overall and per (strategy, symbol)."""
        rows = self.all()
        def agg(group: List[Dict[str, Any]]) -> Dict[str, Any]:
            n = len(group)
            wins = sum(1 for r in group if r.get("outcome") == "win")
            total_pnl = sum(float(r.get("pnl", 0.0)) for r in group)
            avg_pct = sum(float(r.get("pnl_pct", 0.0)) for r in group) / n if n else 0.0
            return {
                "trades": n,
                "win_rate": round(wins / n * 100, 1) if n else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_pnl_pct": round(avg_pct, 3),
            }
        by_setup: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            by_setup[f"{r.get('strategy','?')}/{r.get('symbol','?')}"].append(r)
        return {
            "overall": agg(rows),
            "by_setup": {k: agg(v) for k, v in sorted(by_setup.items())},
        }

    def worst_setups(self, min_trades: int = 2, n: int = 5) -> List[Tuple[str, Dict[str, Any]]]:
        """The setups bleeding the most — the actionable 'stop doing this' list."""
        by = self.stats()["by_setup"]
        ranked = [(k, v) for k, v in by.items() if v["trades"] >= min_trades]
        ranked.sort(key=lambda kv: (kv[1]["avg_pnl_pct"], kv[1]["win_rate"]))
        return ranked[:n]

    # ── reflection (rule-based v1; LLM hook documented) ──────────────────────

    def reflect(self, rec: TradeMemoryRecord, setup_stats: Optional[Dict[str, Any]] = None) -> str:
        """Plain-English lesson. v1 is rule-based + the setup's running record;
        swap in an LLM call (OpenRouter chain) here for sharper reflections."""
        verb = "WON" if rec.outcome == "win" else ("LOST" if rec.outcome == "loss" else "scratched")
        bits = [
            f"{verb} {'+' if rec.pnl_pct >= 0 else ''}{round(rec.pnl_pct, 2)}% on {rec.symbol} "
            f"via {rec.strategy}, held {round(rec.holding_minutes)}m, exit={rec.exit_reason}."
        ]
        if setup_stats and setup_stats.get("trades", 0) >= 2:
            bits.append(
                f"This setup's record: {setup_stats['trades']} trades, "
                f"{setup_stats['win_rate']}% win, avg {setup_stats['avg_pnl_pct']}%."
            )
            if setup_stats["avg_pnl_pct"] < 0:
                bits.append("Pattern is net-negative — candidate to disable or rework.")
        if rec.outcome == "loss" and rec.holding_minutes < 60:
            bits.append("Fast loss — entry likely premature / into chop; consider stricter entry filter.")
        return " ".join(bits)

    def write_dashboard(self) -> None:
        """Roll up the lab's progress + worst setups into vault/_dashboard.md."""
        s = self.stats()
        o = s["overall"]
        lines = [
            "# Trade Lab — Dashboard\n",
            f"_Generated from {o['trades']} closed round-trips._\n",
            "## Overall",
            f"- Trades: **{o['trades']}** · Win rate: **{o['win_rate']}%** · "
            f"Total P&L: **${o['total_pnl']}** · Avg/trade: **{o['avg_pnl_pct']}%**\n",
            "## Worst setups (stop-doing candidates)",
        ]
        for name, v in self.worst_setups():
            lines.append(f"- `{name}` — {v['trades']} trades, {v['win_rate']}% win, avg {v['avg_pnl_pct']}%, ${v['total_pnl']}")
        lines.append("\n## All setups")
        for name, v in s["by_setup"].items():
            lines.append(f"- `{name}` — {v['trades']} trades, {v['win_rate']}% win, avg {v['avg_pnl_pct']}%, ${v['total_pnl']}")
        try:
            (self.vault_dir / "_dashboard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.warning(f"dashboard write failed: {exc}")

    # ── backfill from fills.jsonl (FIFO round-trip reconstruction) ───────────

    def backfill_from_fills(self, fills_path: str = "data/fills.jsonl") -> int:
        """Reconstruct closed long round-trips from the append-only fills log by
        FIFO-matching SELLs against prior BUYs per symbol. Returns count recorded.
        Unmatched SELLs (pre-existing positions / shorts) are skipped — no entry
        context to learn from."""
        path = Path(fills_path)
        if not path.exists():
            return 0
        # Rebuild semantics: backfill reconstructs the FULL history from the
        # append-only fills log, so clear prior reconstructed records first.
        # This keeps it idempotent — safe to re-run / schedule without dupes.
        try:
            if self.memory_path.exists():
                self.memory_path.write_text("", encoding="utf-8")
            for _old in (self.vault_dir / "trades").glob("*.md"):
                _old.unlink()
        except OSError:
            pass
        fills = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                fills.append(json.loads(line))
            except Exception:
                continue
        fills.sort(key=lambda f: str(f.get("timestamp", "")))

        open_lots: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)
        records: List[TradeMemoryRecord] = []
        seq = 0
        for f in fills:
            sym = str(f.get("symbol", "")).upper()
            side = str(f.get("side", "")).lower()
            qty = float(f.get("filled_qty", 0) or 0)
            price = float(f.get("filled_price", 0) or 0)
            fee = float(f.get("fee", 0) or 0)
            ts = f.get("timestamp", "")
            if qty <= 0 or price <= 0:
                continue
            if side == "buy":
                open_lots[sym].append({"qty": qty, "price": price, "ts": ts, "fee": fee,
                                       "strategy": f.get("strategy_id") or "unknown"})
            elif side == "sell":
                remaining = qty
                lots = open_lots[sym]
                while remaining > 1e-12 and lots:
                    lot = lots[0]
                    matched = min(remaining, lot["qty"])
                    entry_t, exit_t = _parse_ts(lot["ts"]), _parse_ts(ts)
                    hold_min = ((exit_t - entry_t).total_seconds() / 60.0) if entry_t and exit_t else 0.0
                    pnl = (price - lot["price"]) * matched - (fee * matched / qty if qty else 0)
                    cost = lot["price"] * matched
                    pnl_pct = (pnl / cost * 100.0) if cost else 0.0
                    seq += 1
                    rec = TradeMemoryRecord(
                        id=f"{f.get('order_id','x')}-{seq}",
                        symbol=sym,
                        strategy=str(f.get("strategy_id") or lot["strategy"] or "unknown"),
                        entry_time=str(lot["ts"]), exit_time=str(ts),
                        entry_price=lot["price"], exit_price=price, qty=matched,
                        pnl=pnl, pnl_pct=pnl_pct, holding_minutes=hold_min,
                        outcome=_outcome(pnl_pct),
                        exit_reason=_exit_reason(str(f.get("strategy_id") or "")),
                        tags=[sym, str(f.get("strategy_id") or lot["strategy"] or "unknown"),
                              _outcome(pnl_pct), _hold_bucket(hold_min)],
                    )
                    records.append(rec)
                    lot["qty"] -= matched
                    remaining -= matched
                    if lot["qty"] <= 1e-12:
                        lots.popleft()

        # Compute per-setup stats first so each lesson can cite the running record.
        from_records_setup: Dict[str, List[TradeMemoryRecord]] = defaultdict(list)
        for r in records:
            from_records_setup[f"{r.strategy}/{r.symbol}"].append(r)
        count = 0
        for r in records:
            grp = from_records_setup[f"{r.strategy}/{r.symbol}"]
            n = len(grp)
            wins = sum(1 for x in grp if x.outcome == "win")
            setup_stats = {
                "trades": n,
                "win_rate": round(wins / n * 100, 1) if n else 0.0,
                "avg_pnl_pct": round(sum(x.pnl_pct for x in grp) / n, 3) if n else 0.0,
            }
            r.lesson = self.reflect(r, setup_stats)
            self.record(r)
            count += 1
        self.write_dashboard()
        return count


def _exit_reason(strategy_id: str) -> str:
    sid = (strategy_id or "").lower()
    if "partial_take_profit" in sid or "take_profit" in sid:
        return "take_profit"
    if "trailing_stop" in sid or "stop" in sid:
        return "stop"
    if not sid or sid == "unknown":
        return "manual/unknown"
    return "strategy_exit"
