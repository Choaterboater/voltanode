# Session handoff — 2026-05-15

Drop this into the new session as context: `Read D:\VoltaNode\docs\session-handoff-2026-05-15.md`.

## What shipped today (5 commits, all on local `main`, not yet pushed)

```
b3a54c6  fix(fred): retry+backoff on 5xx; single summary line instead of per-series WARN
8b31396  feat(scanner): freqtrade-style pairlist filters
555689b  feat(strategies): POST /strategies/refresh-universes + 12h collector cron
49ba99f  feat(ui): persistent "Restart backend" button + POST /settings/restart
1247525  feat(api): POST /trades/external/ingest — sibling-bot outcome ingest
```

Detail per commit:

### 1. `/trades/external/ingest` — sibling-bot outcome ingest (`1247525`)
- Endpoint: `POST /trades/external/ingest`, body shape locked with D:\Trade:
  `{source, symbol, side, qty, entry_price, exit_price, entry_ts, exit_ts, realized_pnl, strategy_tag, conviction_score}`
- Idempotent on `(source, symbol, entry_ts)` — replays return 200 `already_seen=true`.
- Storage: append-only JSONL at `trading-bot-backend/data/external_trades.jsonl`.
- Readback: `GET /trades/external/recent?source=tradingbot&limit=100`.
- **D:\Trade has been emitting daily at 21:15 UTC** with a ~13-row backlog that drained tonight. Going forward each new round-trip from their committee-gated trades flows here for advisor calibration.

### 2. Restart-backend button (`49ba99f`)
- Endpoint: `POST /settings/restart` — spawns a detached `cmd` helper that waits 2s (so HTTP response can complete), force-kills the parent PID, and starts a fresh backend in a new console.
- Windows-only (uses `DETACHED_PROCESS` flag).
- Frontend: `app/src/components/RestartBackendButton.tsx` — two-click confirm pattern (idle → amber confirm → spinner → green ✓), top-right of every page. Polls `/engine/status` until it returns 200.
- **`Layout.tsx` now always renders the header bar** so the button is reachable from pages that previously omitted it (Watchlist, Advisor, Squeeze, About).

### 3. Dynamic universe refresh (`555689b`)
- Endpoint: `POST /strategies/refresh-universes?dry_run=false` (also `dry_run=true` for preview).
- For each registered `auto_discovery` bot: replaces `config.symbols` with scanner top-N matching the bot's `asset_class`.
- For each registered `squeeze` bot: replaces with squeeze top-N.
- **Calls scanner/squeeze handlers directly as Python coroutines via `asyncio.gather`** — NOT HTTP loopback (that deadlocks single-worker async).
- Empty scan = no-op (never wipes a bot's universe to `[]`).
- Persists via `_persist()` → restart-safe.
- Does NOT touch momentum / macd / mean_reversion / news_sentiment / arbitrage bots — those have intentionally pinned symbols.
- Collector adds a 12h `universe_refresh` stream that fires this endpoint automatically. Tunable via `VOLTA_COLLECT_UNIVERSE_SEC`.
- **First apply today rotated the stock auto_discovery bot from 27 hardcoded mega-caps to 25 scanner top-N names.** First fill on the new universe: ONDS at 14:37 UTC.

### 4. Pairlist filters (`8b31396`)
- New module: `trading-bot-backend/advisor/pairlist.py`.
- Six composable filters (modeled on freqtrade): `VolumeFilter`, `AgeFilter`, `PriceFilter`, `SpreadFilter`, `VolatilityFilter`, `BlacklistFilter`.
- Wired into `GET /advisor/scanner` (9 new tunable Query params) AND `POST /strategies/refresh-universes` (matching defaults).
- Response now includes `filtered_count` and a `filtered[]` array so the operator sees *why* each symbol was dropped.
- Sub-$1 coins (TRX, DOGE, ADA, SHIB) now get gated automatically by `PriceFilter`. **The ADA loop we fought all session would be blocked upstream from now on.**
- **Known follow-up:** `PriceFilter` $1 floor is too aggressive for crypto. Make floor asset-class-aware, OR default `pl_min_price=0` when `asset_class=crypto`. Two-line change.

### 5. FRED retry+backoff (`b3a54c6`)
- `signals/fred.py` now retries up to 3 times on 5xx + ConnectionError + Timeout with 1s/2s/4s exponential backoff.
- 4xx fails fast (no retry on bad key/series).
- **Logging cleanup:** per-series failures moved to DEBUG. ONE INFO summary on partial success (`"fetched 9/11; missing T10Y2Y,DGS2"`). One WARNING on total failure only.
- Honest pivot note in commit message: original plan was full OpenBB-FRED swap (~4hr + 300MB dep). On inspection, 500s come from FRED's API itself — no library swap fixes them. Retry+backoff is the actual fix.

## Branches + remote state

| | SHA |
|---|---|
| Local `main` | `b3a54c6` |
| Worktree `claude/nervous-hertz-7f6087` | `b3a54c6` (identical) |
| `origin/main` (GitHub) | **stale** — 10 commits behind |

**Push command if you want today's work on GitHub:**
```
git push origin main
```
(No PR review process in this repo — direct push to main matches existing git log history.)

## Running services state

```
backend  127.0.0.1:8000   alpaca paper, live_mode=true, broker_connected=true
frontend 127.0.0.1:3001   restart button visible top-right of every page
collector                 12h universe-refresh stream added (not running unless user launched it)
```

Worktree path: `D:\VoltaNode\.claude\worktrees\nervous-hertz-7f6087`
Main repo:     `D:\VoltaNode`

**Vite gotcha (CLAUDE.md):** the frontend Vite is normally running from main repo at `D:\VoltaNode\app`, NOT the worktree. Edits in worktree won't appear on :3001 unless mirrored.

## Today's portfolio P&L

End-of-session snapshot:
- 19 positions
- Equity: $100,565
- Unrealized: -$472 (was +$552 mid-session — crypto pulled back)
- Realized today: +$118 (5 trades closed, net positive)

Bot ran correctly. Stops fired on BTC/ETH/SHIB/XRP/YFI as crypto dropped — exit discipline working as designed.

## Roadmap — phases 3+ (NEXT session priority)

User's request was to ship the freqtrade/OpenBB/OctoBot steal-list in order. Done so far: pairlist (phase 1), FRED hardening (phase 2 — pivoted away from OpenBB swap, see commit msg).

### Phase 3 — Hyperopt (~2 days, biggest single P&L lift remaining)

Strategies currently run on textbook defaults (RSI=14, MACD=12/26/9, etc.) from deploy day. **Bayesian parameter search via backtesting could meaningfully move expected Sharpe on the top-3 strategies (`mean_reversion`, `macd`, `momentum`).**

Sketch:
1. New module `trading-bot-backend/hyperopt/`
   - `engine.py` — runs N trials, uses `scikit-optimize` or `optuna`
   - `objective.py` — calls the existing backtest path, returns Sharpe / Sortino / profit factor
2. Each strategy declares its param space:
   - `strategies/mean_reversion.py` adds a `param_space() -> dict` returning `{"rsi_period": (5, 30), "threshold": (20, 40), ...}`
3. Endpoint `POST /strategies/{id}/hyperopt?n_trials=50&objective=sharpe` — kicks off, returns best params
4. Endpoint `POST /strategies/{id}/apply-hyperopt` — overwrites config with best params from the most recent run, persists, hot-reloads
5. CLI runner for batch offline optimization
6. `data/hyperopt_history.jsonl` for trial history

Estimated 2-3 days end-to-end. Worth its own session.

### Phase 4 — Port 3-5 named strategies (~4 hr each)

From `freqtrade-strategies` community repo, picks worth porting:
- **BBRSIPower** — Bollinger Band squeeze + RSI confluence
- **SwingHighToSky** — donchian breakout with SuperTrend filter
- **NostalgiaForInfinity** — well-known multi-condition system (large, but historically performant)

Each becomes a new file in `trading-bot-backend/strategies/`, matches our `BaseStrategy` interface, registers via `StrategyFactory`.

### Phase 5 — OctoBot evaluator chain pattern (~1 day)

OctoBot's signal-combining architecture: multiple technical evaluators emit weighted opinions, a chain aggregates. Similar to our LLM committee but for TA. Currently we just dump all signals into one composite score in `advisor/scanner.py`. Refactor into a chain of evaluators with explicit weights makes tuning + debugging cleaner. Worth doing AFTER hyperopt so we have more strategies for the chain to combine.

### Skipped from original list (revisit only on demand)

- CCXT / lumibot / TradingView-MCP / huseinzol05/Stock-Prediction-Models / HKUDS/AI-Trader — see today's earlier triage. Real options, not blocking growth.

## Known issues / follow-ups

| Severity | Issue | Where |
|---|---|---|
| Medium | `POST /settings/safety` doesn't propagate to running SafetyValidator. CLAUDE.md flagged it; verified twice today (`blocked_symbols` updates persist but don't load even after restart). | `api/routes/settings.py`, `bot/safety.py` |
| Medium | Squeeze screener returns 0 candidates most days under current filters. Squeeze bot has been trading a stale list (GRPN, DBI, SKLZ, CADL, STIM, OLMA, SOFI, HOOD, COIN, SMCI) for weeks. **Either loosen squeeze filters or accept that squeeze bot is dormant.** | `api/routes/advisor.py` `squeeze_screener` |
| Low | `PriceFilter` $1 floor in pairlist drops liquid crypto (DOGE, SHIB). Asset-class-aware default would be 2 lines. | `advisor/pairlist.py` |
| Low | Alpaca paper doesn't support ADA trading. Phantom ADA position will sit on broker side forever unless Alpaca support clears it. Pairlist `BlacklistFilter` should be set with ADA when scanning if it ever comes back into the universe. | Operational |
| Low | `POST /portfolio/{id}/flatten` orders bypass `/trades/` ledger. (CLAUDE.md) | `bot/engine.py` |

## Quick test commands the new session may want

```bash
# Health sweep
curl -s -o /dev/null -w "backend: %{http_code}\n" http://localhost:8000/engine/status
curl -s -o /dev/null -w "frontend: %{http_code}\n" http://localhost:3001/

# Today's endpoints — should all return 200
curl -s -o /dev/null -w "/trades/external/ingest: %{http_code}\n" -X POST http://localhost:8000/trades/external/ingest -H "Content-Type: application/json" -d '{"source":"healthcheck","symbol":"X","side":"BUY","qty":1,"entry_price":1,"exit_price":1,"entry_ts":"2099-01-01T00:00:00Z","exit_ts":"2099-01-01T00:00:00Z","realized_pnl":0}'
curl -s -o /dev/null -w "/strategies/refresh-universes (dry): %{http_code}\n" -X POST "http://localhost:8000/strategies/refresh-universes?dry_run=true" --max-time 180
curl -s -o /dev/null -w "/advisor/scanner with pairlist: %{http_code}\n" "http://localhost:8000/advisor/scanner?asset_class=crypto&top=5&enable_pairlist=true" --max-time 180

# Restart via button endpoint (note: actually restarts — use intentionally)
curl -s -X POST http://localhost:8000/settings/restart
```

## Cross-bot integration (D:\Trade ↔ VoltaNode)

| Direction | Status |
|---|---|
| D:\Trade → VoltaNode watchlist (capacity-blocked candidates) | ✅ Live since `f91613d` |
| VoltaNode → D:\Trade sentiment (per-symbol cache) | ✅ Live, D:\Trade reads `/news/sentiment/{symbol}` |
| D:\Trade → VoltaNode outcomes (realized round-trips for advisor calibration) | ✅ Live today (`1247525`) |
| VoltaNode advisor → calibration off D:\Trade outcomes | ⏳ Has data flowing in; consumer-side analysis not built yet |
