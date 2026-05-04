"""Persistent append-only equity curve store, one JSONL file per account."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import List, Tuple

logger = logging.getLogger("volta.equity_history")


class EquityHistoryStore:
    """Append-only equity snapshots persisted as JSON Lines.

    One file per account at ``<root>/<account_id>.jsonl``. Each line is
    ``{"ts": <iso8601>, "equity": <float>}``. Ordered chronologically because
    callers always append.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._last_ts: dict[str, datetime] = {}

    def _path(self, account_id: str) -> Path:
        safe = account_id.replace("/", "_").replace("\\", "_")
        return self.root / f"{safe}.jsonl"

    def append(self, account_id: str, equity: float, timestamp: datetime | None = None) -> None:
        ts = timestamp or datetime.now(timezone.utc)
        line = json.dumps({"ts": ts.isoformat(), "equity": float(equity)}) + "\n"
        with self._lock:
            try:
                with self._path(account_id).open("a", encoding="utf-8") as f:
                    f.write(line)
                self._last_ts[account_id] = ts
            except OSError as exc:
                logger.warning(f"Equity snapshot write failed for {account_id}: {exc}")

    def append_throttled(
        self, account_id: str, equity: float, min_gap_seconds: float = 60.0
    ) -> bool:
        """Append only if at least ``min_gap_seconds`` have passed since the last point.

        Returns True if a point was written.
        """
        now = datetime.now(timezone.utc)
        last = self._last_ts.get(account_id)
        if last is not None and (now - last).total_seconds() < min_gap_seconds:
            return False
        self.append(account_id, equity, now)
        return True

    def query(
        self, account_id: str, since: datetime | None = None
    ) -> List[Tuple[datetime, float]]:
        """Return points ``(timestamp, equity)`` recorded at or after ``since``."""
        path = self._path(account_id)
        if not path.exists():
            return []
        points: List[Tuple[datetime, float]] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                        ts = datetime.fromisoformat(rec["ts"])
                    except (ValueError, KeyError):
                        continue
                    if since is not None and ts < since:
                        continue
                    points.append((ts, float(rec["equity"])))
        except OSError as exc:
            logger.warning(f"Equity snapshot read failed for {account_id}: {exc}")
        return points
