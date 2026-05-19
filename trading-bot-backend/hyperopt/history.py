"""Append-only JSONL store of completed hyperopt studies.

One row per ``run_hyperopt`` call. Per-trial detail lives inside
``HyperoptResult.trial_history``; we keep the full result in the row so
``apply-hyperopt`` can read back the most-recent best_params without
re-running the study.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from hyperopt.engine import HyperoptResult

logger = logging.getLogger("volta.hyperopt.history")

HISTORY_PATH = Path("data") / "hyperopt_history.jsonl"


def append_history(
    result: HyperoptResult,
    strategy_id: str,
    path: Path | None = None,
) -> None:
    """Append one row to the history file. Best-effort — never raises."""
    p = path or HISTORY_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        row = result.to_dict()
        row["strategy_id"] = strategy_id
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as exc:
        logger.warning(f"Could not append hyperopt history: {exc}")


def read_all(path: Path | None = None) -> List[Dict[str, Any]]:
    """Read every history row in order written. Returns [] if no file."""
    p = path or HISTORY_PATH
    if not p.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception as exc:
        logger.warning(f"Could not read hyperopt history: {exc}")
    return rows


def latest_for_strategy(
    strategy_id: str,
    path: Path | None = None,
) -> Optional[Dict[str, Any]]:
    """Return the most-recent history row for ``strategy_id``, or None."""
    rows = read_all(path)
    for row in reversed(rows):
        if row.get("strategy_id") == strategy_id:
            return row
    return None
