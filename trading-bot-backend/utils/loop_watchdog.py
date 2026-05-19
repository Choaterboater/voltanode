"""Event-loop watchdog — detects + diagnoses wedges in real time.

Spawns a daemon thread that periodically schedules a tiny coroutine on
the FastAPI event loop and waits for it to complete. If completion takes
longer than ``stall_threshold_sec`` the loop is considered wedged and
the thread:

  1. Logs CRITICAL with the stall duration
  2. Dumps Python tracebacks for every active thread to a stall-log file
     (via ``faulthandler.dump_traceback``) so the operator can see what
     was blocking the loop at the moment of stall
  3. Optionally writes a wedge marker to ``data/wedge_alerts.jsonl``
     for the UI / monitoring to surface

The watchdog itself runs OUTSIDE the event loop (in a regular Python
thread), so it stays responsive even when the loop is fully blocked —
which is exactly when we need it most.

Usage:
    from utils.loop_watchdog import start_loop_watchdog
    # inside FastAPI lifespan, after the event loop is running:
    start_loop_watchdog()

It's idempotent — calling start_loop_watchdog() twice is a no-op (the
second call returns the existing watchdog).
"""

from __future__ import annotations

import asyncio
import faulthandler
import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("volta.watchdog")


_WEDGE_LOG = Path("data") / "wedge_alerts.jsonl"
_STALL_TRACE_DIR = Path("data") / "wedge_traces"

# Module-level singleton — second start_loop_watchdog() call is a no-op.
_watchdog_thread: Optional[threading.Thread] = None
_watchdog_stop: Optional[threading.Event] = None


def _record_wedge(stall_sec: float, trace_path: Optional[Path]) -> None:
    """Append a single-line wedge marker for monitoring + UI surfaces."""
    try:
        _WEDGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stall_sec": round(stall_sec, 2),
            "trace_path": str(trace_path) if trace_path else None,
        }
        with _WEDGE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception:
        pass


def _dump_stacks() -> Optional[Path]:
    """Dump tracebacks of every active thread to a timestamped file.

    Returns the path on success, None on failure. Uses ``faulthandler``
    which is specifically designed to work when the interpreter is in
    distress.
    """
    try:
        _STALL_TRACE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = _STALL_TRACE_DIR / f"stall-{ts}.txt"
        with path.open("w", encoding="utf-8") as fh:
            fh.write(f"# Event-loop wedge detected at {ts}\n")
            fh.write(f"# Python {sys.version}\n\n")
            faulthandler.dump_traceback(file=fh, all_threads=True)
        return path
    except Exception as exc:
        logger.error(f"watchdog: failed to dump stacks: {exc}")
        return None


def _watchdog_loop(
    loop: asyncio.AbstractEventLoop,
    interval_sec: float,
    stall_threshold_sec: float,
    stop_event: threading.Event,
) -> None:
    """Body of the watchdog thread.

    Every ``interval_sec`` we schedule a no-op coroutine on the loop and
    wait up to ``stall_threshold_sec`` for it to finish. If it doesn't,
    we declare a wedge, dump stacks, and continue running (we don't kill
    anything — the operator decides).
    """
    consecutive_stalls = 0
    while not stop_event.is_set():
        try:
            # Schedule the canary. asyncio.run_coroutine_threadsafe is the
            # designed-for-this-purpose bridge from sync threads into a
            # running event loop.
            future = asyncio.run_coroutine_threadsafe(
                _canary(), loop,
            )
            try:
                future.result(timeout=stall_threshold_sec)
                # Canary completed — loop is alive.
                if consecutive_stalls > 0:
                    logger.warning(
                        f"watchdog: event loop recovered after "
                        f"{consecutive_stalls} stall(s)"
                    )
                consecutive_stalls = 0
            except Exception:
                # Timeout or other failure → loop is wedged or near-wedged.
                consecutive_stalls += 1
                trace_path = _dump_stacks()
                logger.critical(
                    f"watchdog: event loop stalled "
                    f"{stall_threshold_sec}s+ (consecutive_stalls={consecutive_stalls}). "
                    f"Stack trace dumped to: {trace_path}"
                )
                _record_wedge(stall_threshold_sec, trace_path)
                # Cancel the future so it doesn't pile up if the loop recovers
                future.cancel()
        except Exception as exc:
            # Watchdog itself can never crash the app
            logger.error(f"watchdog: internal error (continuing): {exc}")
        # Sleep before next probe
        stop_event.wait(interval_sec)


async def _canary() -> None:
    """No-op coroutine the watchdog schedules every interval."""
    await asyncio.sleep(0)


def start_loop_watchdog(
    interval_sec: float = 30.0,
    stall_threshold_sec: float = 10.0,
) -> threading.Thread:
    """Start the watchdog. Idempotent.

    Args:
        interval_sec: How often to probe the loop. 30s is the default —
            often enough to catch stalls quickly, rarely enough to be
            noise-free.
        stall_threshold_sec: How long the canary may take before we
            declare a wedge. 10s is generous; a healthy loop responds
            to ``asyncio.sleep(0)`` in microseconds.

    Returns the watchdog thread (already started).
    """
    global _watchdog_thread, _watchdog_stop
    if _watchdog_thread is not None and _watchdog_thread.is_alive():
        return _watchdog_thread
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Caller invoked us outside a running event loop. Refuse rather
        # than start a watchdog with nothing to watch.
        logger.warning("watchdog: no running event loop; not starting")
        return None  # type: ignore[return-value]
    _watchdog_stop = threading.Event()
    _watchdog_thread = threading.Thread(
        target=_watchdog_loop,
        args=(loop, interval_sec, stall_threshold_sec, _watchdog_stop),
        name="volta-loop-watchdog",
        daemon=True,
    )
    _watchdog_thread.start()
    logger.info(
        f"watchdog: started (interval={interval_sec}s, "
        f"stall_threshold={stall_threshold_sec}s)"
    )
    return _watchdog_thread


def stop_loop_watchdog() -> None:
    """Signal the watchdog to stop. Mostly for tests."""
    global _watchdog_stop
    if _watchdog_stop is not None:
        _watchdog_stop.set()
