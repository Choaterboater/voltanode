# VoltaNode

AI-powered paper trading platform. React + Vite + Tailwind frontend, FastAPI backend, Alpaca for execution. Two halves of the repo:

- `app/` — frontend
- `trading-bot-backend/` — backend

## Run commands

```bash
# Backend  (from repo root)
cd trading-bot-backend && python run.py --mode api --host 127.0.0.1 --port 8000

# Frontend
cd app && npm run dev          # serves http://localhost:3002

# One-click
./start.bat                    # spins up backend + frontend
./stop.bat
```

Type-check the frontend: `cd app && npx tsc --noEmit`.

## Worktrees & Vite — important gotcha

The harness sometimes operates from `.claude/worktrees/<name>/`. **Vite is normally running from the main repo at `D:\VoltaNode\app`, not the worktree.** Edits made inside a worktree won't appear on `:3002` until you either:

1. Restart Vite from the worktree, or
2. Mirror the edit into `D:\VoltaNode\app\src\...`, or
3. Fast-forward main to the feature branch (`git merge --ff-only <branch>`)

Verify which directory Vite is serving with:

```bash
powershell -Command "(Get-CimInstance Win32_Process -Filter 'Name=\"node.exe\"').CommandLine"
```

The worktree's `app/` has no `node_modules` by default. Don't `npm install` there — it duplicates ~1GB.

## Backend endpoints — quick reference

Base: `http://localhost:8000`

- `GET /engine/status` — `{running, account_count}`. `account_count: 0` ⇒ engine `__init__` broke.
- `GET /portfolio/default` — full snapshot. `source: "alpaca"` = broker, `"paper"` = local sim.
- `GET /portfolio/default/stats?range=1H|24H|7D|30D|ALL` — equity curve, Sharpe, drawdown, win rate.
- `GET /settings/live-mode` — `{live_mode, broker_name, broker_connected, confirmation_required}`.
- `GET /settings/safety-status` — current safety limits + kill switch + daily tracker.
- `POST /settings/safety` — update safety limits (persists YAML + pushes live `SafetyValidator` when engine is live).
- `POST /settings/kill-switch` body `{"action":"deactivate"}` — clear a latched kill switch.
- `POST /portfolio/{id}/flatten?symbols=SOL,BTC&trim_pct=0.4` — trim or close positions. `trim_pct=1.0` = full close, `0.4` = close 40%, keep 60%.
- `POST /strategies/auto-deploy?max_positions=N` — run the 12-coin scan + bot deploy.
- `GET /trades/?limit=200` — newest-first (reversed from append-only engine history).
- `GET /advisor/scanner` — RSI + breakout + relative-volume composite scorer.
- `GET /advisor/squeeze` — 7-factor squeeze screener (SI%, float, DTC, off-ex short, etc.).
- `GET /watchlist/`, `POST /watchlist/`, `DELETE /watchlist/{symbol}` — persistent watchlist.

## Safety limits — operator defaults

The backend ships with conservative defaults that **are not what we run in paper mode**. On a fresh start the engine boots with:

| limit | default | paper-mode value |
|---|---|---|
| `max_exposure_pct` | 50.0 | 150–300 |
| `max_position_size_pct` | 20.0 | 20 (keep) |
| `max_orders_per_minute` | 10 | 60–300 |
| `max_daily_loss_pct` | 5.0 | 5 (keep) |

Symptom of the defaults biting: bots stop trading because every BUY would push total exposure past 50%. Diagnose with `GET /settings/safety-status` + compute current `sum(|market_value|)/total_equity` from `/portfolio/default`.

## Engine gating logic — why bots may be idle

A BUY signal can be silently rejected at multiple layers:

1. **`max_exposure_pct`** — total long+short MV / equity > cap → reject (most common).
2. **`max_position_size_pct`** — this single symbol > cap → reject.
3. **`max_orders_per_minute`** — rate limit (`orders_remaining_this_minute` in `/settings/safety-status`).
4. **Position-aware BUY gate** (in `strategies/base.py:BaseStrategy.on_tick`) — if portfolio already holds the symbol, BUY signal downgrades to HOLD. Stops the "every restart adds another BUY" bug.
5. **Same-side dedup** — multiple bots firing BUY on the same symbol same tick → keep highest-confidence, drop rest.
6. **Hysteresis / per-bar latches / min_hold_minutes** — strategy-level cooldowns.
7. **Kill switch** — if latched, engine.on_tick early-returns.

SELL signals bypass exposure checks (closing a position can't add exposure).

## Known bugs (small, worth fixing)

_None tracked at the moment — file issues in GitHub as they surface._

## Frontend conventions

- Routing: HashRouter. URLs look like `http://localhost:3002/#/watchlist`.
- `app/src/components/Layout.tsx` is the shell — sidebar + top bar + main. `title` prop is optional; pages with their own in-body hero (Watchlist, Advisor, Squeeze, About) should omit it to avoid a duplicate page title.
- The flex column in Layout needs `min-w-0` or the inner `max-w-[1600px]` main forces horizontal scroll. Don't remove it.
- Mono font (`font-mono tabular-nums`) on every numeric value. Hero numbers use `text-2xl font-semibold`.
- Tokens: `bg-bg-base / bg-surface / bg-elevated / bg-input`, `text-text-primary / -secondary / -muted`, `border-border-subtle`, `accent-cyan` / `success-green` / `danger-red` / `warning-amber`.
- Strategy `metrics` shape: `{ total_pnl, total_trades, win_rate, ... }`. `config` shape varies — multi-symbol bots use `config.symbols: string[]`, legacy single-symbol bots use `config.symbol: string`.

## Persistent stores

- `data/equity/<account_id>.jsonl` — append-only equity history (used by `/portfolio/{id}/stats`).
- `data/watchlist.json` — watchlist (manual + bot-promoted picks).
- `data/positions/` — broker position snapshots.

## Don't break

File persistence, broker position sync, ensemble veto, same-side dedup, position-aware BUY gate, per-bar latches, hysteresis, debounce, SELL-doesn't-add-exposure. These gates interlock — removing any one re-introduces the "every restart adds a BUY" bug.

## Repo

GitHub: https://github.com/Choaterboater/voltanode (private).
