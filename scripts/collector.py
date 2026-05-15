"""VoltaNode background collector.

Polls the VoltaNode API on a schedule and writes structured JSONL files
to ``data/collector/`` for offline analysis, backtest replay, and
historical sentiment lookup.

Streams + cadences::

    news_sentiment      every 15 min   held positions
    watchlist_news      every 30 min   watchlist symbols
    squeeze_snapshots   every 60 min   squeeze screener output
    macro_signals       every 30 min   FRED series + fear/greed
    advisor_analyses    every  4 hr    top 10 held positions

The collector runs as its own process; restart-safe with no shared
state. Append-only writes mean any crash just resumes from the next
schedule tick. Free-tier OpenRouter rate limits are respected by
throttling per-symbol calls and capping advisor sweeps at 10 names.

Usage::

    python -u scripts/collector.py

(``-u`` keeps stdout unbuffered so ``start.bat`` shows live progress.)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests

API_BASE = os.environ.get("VOLTA_API_BASE", "http://localhost:8000")
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "collector"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Cadence per stream in seconds. Tunable via env, e.g. VOLTA_COLLECT_NEWS_SEC=300
INTERVALS = {
    "news":           int(os.environ.get("VOLTA_COLLECT_NEWS_SEC",            15 * 60)),
    "watchlist_news": int(os.environ.get("VOLTA_COLLECT_WATCHLIST_NEWS_SEC",  30 * 60)),
    "squeeze":        int(os.environ.get("VOLTA_COLLECT_SQUEEZE_SEC",         60 * 60)),
    "macro":          int(os.environ.get("VOLTA_COLLECT_MACRO_SEC",           30 * 60)),
    "advisor":        int(os.environ.get("VOLTA_COLLECT_ADVISOR_SEC",       4 * 60 * 60)),
    "universe":       int(os.environ.get("VOLTA_COLLECT_UNIVERSE_SEC",     12 * 60 * 60)),
}

# Per-call inter-symbol pause so we don't hammer the LLM provider's rate
# limit. The Hybrid sentiment path is mostly VADER + occasional LLM, so
# this is generous; advisor calls are heavy so they get more.
SLEEP_BETWEEN_NEWS = float(os.environ.get("VOLTA_COLLECT_NEWS_PAUSE", 2.0))
SLEEP_BETWEEN_ADVISOR = float(os.environ.get("VOLTA_COLLECT_ADVISOR_PAUSE", 5.0))

# Cap how many symbols we batch into a single advisor sweep so a single
# tick can't blow through the free-tier minute budget.
ADVISOR_MAX_PER_RUN = int(os.environ.get("VOLTA_COLLECT_ADVISOR_CAP", 10))
WATCHLIST_MAX_PER_RUN = int(os.environ.get("VOLTA_COLLECT_WATCHLIST_CAP", 40))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s collector %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("collector")


# ─── JSONL helpers ───

def append_jsonl(filename: str, payload: Dict[str, Any]) -> None:
    """Append one row to a JSONL file with an automatic ts field."""
    p = DATA_DIR / filename
    row = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


# ─── API wrappers ───

def _get(path: str, params: Dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    r = requests.get(f"{API_BASE}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_held_symbols() -> List[str]:
    """Symbols we currently hold (skipping dust below $1 market value)."""
    try:
        data = _get("/portfolio/default", timeout=10)
        return [
            p["symbol"]
            for p in data.get("positions", [])
            if (p.get("market_value") or 0) >= 1.0
        ]
    except Exception as e:
        log.warning(f"get_held_symbols failed: {e}")
        return []


def get_watchlist_symbols() -> List[str]:
    """Watchlist symbols (manual + bot-promoted)."""
    try:
        data = _get("/watchlist/", timeout=10)
        if isinstance(data, list):
            return [item.get("symbol") for item in data if item.get("symbol")]
        return []
    except Exception as e:
        log.warning(f"get_watchlist_symbols failed: {e}")
        return []


# ─── Stream collectors ───

def collect_news(symbols: List[str], stream_label: str) -> None:
    """Snapshot per-symbol sentiment via /news/trending (which actively
    fetches + scores) and filter to the symbols we care about.

    We pull the full trending snapshot once per cycle and slice it down
    to the symbols we hold/watchlist, rather than hitting per-symbol
    endpoints. /news/trending does the real fetch/scoring work and the
    response covers the whole universe in one call.
    """
    if not symbols:
        log.info(f"{stream_label}: no symbols, skipping")
        return
    wanted = {s.upper() for s in symbols}
    try:
        # /news/trending returns ALL symbols it has scored in the window.
        trending = _get("/news/trending", params={"hours": 24, "min_articles": 1}, timeout=30)
    except Exception as e:
        log.warning(f"{stream_label}: trending fetch failed: {e}")
        return
    if not isinstance(trending, list):
        log.warning(f"{stream_label}: unexpected trending shape: {type(trending)}")
        return
    written = 0
    for row in trending:
        sym = (row.get("symbol") or "").upper()
        if sym not in wanted:
            continue
        append_jsonl("news_sentiment.jsonl", {
            "stream": stream_label,
            "symbol": sym,
            "summary": {
                "avg_compound": row.get("avg_compound"),
                "article_count": row.get("article_count"),
                "sentiment_label": row.get("sentiment_label"),
            },
            "trending": row.get("trending"),
            "latest_headlines": row.get("latest_headlines") or [],
            "updated_at": row.get("updated_at"),
        })
        written += 1
    log.info(f"{stream_label}: wrote {written}/{len(symbols)} sentiment rows (trending universe = {len(trending)})")


def collect_squeeze() -> None:
    """Squeeze screener snapshot — full candidate list with all 7 factors."""
    try:
        data = _get(
            "/advisor/squeeze",
            params={"days_back": 7, "max_price": 20},
            timeout=120,
        )
        candidates = data.get("candidates") or []
        # Trim each candidate to the fields useful for time-series analysis.
        slim = []
        for c in candidates[:80]:
            slim.append({
                "ticker": c.get("ticker"),
                "score": c.get("score"),
                "tier": c.get("tier"),
                "current_price": c.get("current_price"),
                "day_pct_change": c.get("day_pct_change"),
                "short_pct_of_float": c.get("short_pct_of_float"),
                "days_to_cover": c.get("days_to_cover"),
                "float_shares": c.get("float_shares"),
                "off_exchange_short_pct": c.get("off_exchange_short_pct"),
                "earnings_qoq_growth": c.get("earnings_qoq_growth"),
                "market_cap": c.get("market_cap"),
                "sector": c.get("sector"),
                "thirteen_d": c.get("thirteen_d"),
                "technical_score": c.get("technical_score"),
            })
        append_jsonl("squeeze_snapshots.jsonl", {
            "candidates_count": len(candidates),
            "filings_scanned": data.get("filings_scanned"),
            "structural_filter_passed": data.get("structural_filter_passed"),
            "candidates": slim,
        })
        log.info(f"squeeze: {len(candidates)} candidates")
    except Exception as e:
        log.warning(f"squeeze failed: {e}")


def collect_macro() -> None:
    """FRED + Fear & Greed snapshot for the macro tape."""
    try:
        data = _get("/signals/", timeout=20)
        slim = {
            "fear_greed": data.get("fear_greed"),
            "macro_series": (data.get("macro") or {}).get("series", {}),
            "providers": data.get("providers"),
        }
        append_jsonl("macro_signals.jsonl", slim)
        n_series = len(slim["macro_series"])
        fg = (slim.get("fear_greed") or {}).get("value")
        log.info(f"macro: {n_series} series  fear&greed={fg}")
    except Exception as e:
        log.warning(f"macro failed: {e}")


# Crypto bare-form mapping. The advisor endpoint expects bare tickers
# without USD suffix for crypto and the raw ticker for stocks. Our
# portfolio stores crypto as XYZUSD, so strip the suffix here.
_CRYPTO_BASES = {
    "BTC","ETH","SOL","BNB","XRP","ADA","DOGE","AVAX","SHIB","LTC","BCH",
    "UNI","AAVE","MATIC","MKR","SUSHI","YFI","LINK","DOT","TRX","XLM",
}


def _advisor_args(symbol: str) -> tuple[str, str]:
    s = symbol.upper()
    for suf in ("USDT", "USD"):
        if s.endswith(suf):
            base = s[: -len(suf)]
            if base in _CRYPTO_BASES:
                return base, "crypto"
    return s, "stock"


def collect_advisor(symbols: List[str]) -> None:
    """Heavy LLM-backed Advisor analysis for top-N held positions."""
    if not symbols:
        log.info("advisor: no symbols, skipping")
        return
    subset = symbols[:ADVISOR_MAX_PER_RUN]
    written = 0
    for sym in subset:
        bare, asset = _advisor_args(sym)
        try:
            data = _get(
                "/advisor/analyze",
                params={"symbol": bare, "asset_type": asset, "lookback_days": 90},
                timeout=60,
            )
            append_jsonl("advisor_analyses.jsonl", {
                "symbol": sym,
                "asset_type": asset,
                "verdict": data.get("verdict"),
                "confidence": data.get("confidence"),
                "current_price": data.get("current_price"),
                "time_horizon": data.get("time_horizon"),
                # Slim per-indicator + per-target to keep file small
                "indicators": [
                    {"name": i.get("name"), "signal": i.get("signal"), "strength": i.get("strength")}
                    for i in (data.get("indicators") or [])
                ],
                "price_targets": [
                    {"label": t.get("label"), "price": t.get("price"), "probability": t.get("probability")}
                    for t in (data.get("price_targets") or [])
                ],
            })
            written += 1
        except Exception as e:
            log.warning(f"advisor {sym}: {e}")
        time.sleep(SLEEP_BETWEEN_ADVISOR)
    log.info(f"advisor: wrote {written}/{len(subset)} analyses")


def refresh_universes() -> None:
    """Refresh auto_discovery + squeeze bot universes from live scanner.

    Bots get registered with frozen symbol lists at deploy time. Without a
    periodic refresh they trade stale rosters (the squeeze list in particular
    turns over weekly). This calls the backend's /strategies/refresh-universes
    endpoint and logs what changed.
    """
    try:
        r = requests.post(f"{API_BASE}/strategies/refresh-universes", timeout=300)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning(f"universe: refresh failed: {e}")
        return

    updated = data.get("updated", [])
    skipped = data.get("skipped", [])
    append_jsonl("universe_refresh.jsonl", data)
    if updated:
        for u in updated:
            log.info(
                f"universe: {u['strategy_type']} {u['strategy_id'][:24]} → "
                f"+{len(u['added'])}/-{len(u['removed'])} (size={u['new_size']})"
            )
    log.info(
        f"universe: refreshed crypto={data.get('crypto_universe_size')} "
        f"stock={data.get('stock_universe_size')} squeeze={data.get('squeeze_universe_size')}; "
        f"{len(updated)} updated, {len(skipped)} skipped"
    )


# ─── Dispatcher ───

def stream_due(stream: str, last_run: float, now: float) -> bool:
    return (now - last_run) >= INTERVALS[stream]


def main() -> int:
    log.info(f"collector starting — output: {DATA_DIR}")
    log.info(
        f"intervals (min): news={INTERVALS['news']//60} "
        f"wl_news={INTERVALS['watchlist_news']//60} "
        f"squeeze={INTERVALS['squeeze']//60} "
        f"macro={INTERVALS['macro']//60} "
        f"advisor={INTERVALS['advisor']//60} "
        f"universe={INTERVALS['universe']//60}"
    )

    # Probe API once so users see a clear error if backend is down
    try:
        _get("/engine/status", timeout=5)
    except Exception as e:
        log.error(f"backend not reachable at {API_BASE} — {e}")
        log.error("will keep retrying every 60s; start the backend with start.bat")

    last_run: Dict[str, float] = {k: 0.0 for k in INTERVALS}

    try:
        while True:
            now = time.time()
            ran_any = False
            for stream in INTERVALS:
                if not stream_due(stream, last_run[stream], now):
                    continue
                last_run[stream] = now
                ran_any = True
                try:
                    if stream == "news":
                        collect_news(get_held_symbols(), "news")
                    elif stream == "watchlist_news":
                        collect_news(get_watchlist_symbols()[:WATCHLIST_MAX_PER_RUN], "watchlist_news")
                    elif stream == "squeeze":
                        collect_squeeze()
                    elif stream == "macro":
                        collect_macro()
                    elif stream == "advisor":
                        collect_advisor(get_held_symbols())
                    elif stream == "universe":
                        refresh_universes()
                except Exception as e:
                    log.exception(f"{stream} stream crashed: {e}")
            if not ran_any:
                pass  # quiet idle
            # Re-check every 30s. All cadences are >= 15 min so this is fine.
            time.sleep(30)
    except KeyboardInterrupt:
        log.info("collector stopped (Ctrl-C)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
