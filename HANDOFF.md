# VoltaNode — Session Handoff (2026-06-09)

> New session: read this file first. It captures the state of the risk overhaul,
> what's deployed vs. not, what's left, and the exact commands to finish.

## TL;DR
- A 50-agent audit (run `wf_037fb0bb-143`) found the bot is **net −6%/month** from
  **both** a no-edge strategy design **and** a cluster of bugs. The "no edge" read
  is trustworthy on the math (needs a ~76% win rate to break even at the realized
  payoff).
- **9 of 20 audit bugs are now fixed — including BOTH criticals and every HIGH** —
  on branch **`claude/p0-risk-overhaul`** → **PR #10** (still a **draft**).
  Tip commit `246594f`. **302 tests pass. Working tree clean. All pushed.**
- **NOT deployed yet.** The fixes only matter once PR #10 is merged and the bot is
  restarted. See **Deploy** below.

## What shipped in PR #10 (`claude/p0-risk-overhaul`, supersedes PR #9)
9 commits beyond `main` (3 inherited from PR #9 + 6 from this work):

| Audit bug | Fix | Where |
|---|---|---|
| #1 CRIT | Crypto taker fee now recorded (was hardcoded `fee=0.0` → P&L overstated) | `brokers/alpaca.py`, `bot/engine.py`, `config` |
| #2 CRIT | ATR-adaptive stop floor (the entry-daily / exit-5s timeframe mismatch) | `bot/risk.py:atr_stop_fraction`, `bot/engine.py` |
| #3 HIGH | Exit-sizing inversion fixed — full winner runs with a trail wider than the loss stop; 40% trim OFF by default | `bot/engine.py:_profit_manager_order` |
| #4 HIGH | Momentum symmetric exit — full SELL only on a confirmed trend break (state-based; fires on gradual breakdowns); in-uptrend pullbacks HOLD | `strategies/momentum.py` |
| #5 HIGH | Kill switch exempts protective EXITS (a daily-loss halt flattens losers instead of freezing stops) | `bot/engine.py` |
| #6 HIGH | No phantom shorts / null P&L on unmatched SELLs (the ~20 dropped trades now count in win-rate/PF) | `bot/engine.py` |
| #7 HIGH | Daily-loss tracker seeds cost basis from open positions (no longer blind to overnight/restart losers) | `safety/daily_tracker.py` |
| #8 HIGH | Backtest Sharpe annualization inferred from bar spacing (was `sqrt(252)` on 1h bars → ~6× understated → corrupted the promotion gate) | `backtest/metrics.py` |
| #12 MED | `max_position_loss_pct` surfaced in `/settings/safety-status` + default 10→6 | (from PR #9) |

Plus:
- **Backtest fidelity**: backtest now mirrors live crypto fee + ATR stop floor.
- **CPCV/DSR promotion gate is default-ON** (`promotion_gate.enabled=true`): apply-hyperopt
  must clear CPCV/DSR or it's blocked (422); `force=true` overrides; charges the crypto
  fee; returns 503 on a data blip.
- **Kronos edge-check** now charges the honest crypto fee (`--crypto-fee`, default 25 bps).
- An adversarial-review workflow (`wf_dd206c83-d4d`) caught + we fixed 2 HIGH defects in
  the #4/gate commit before merge.

## Why the bot loses money (root cause, ranked)
1. **Exit-sizing inversion** (fixed #3): winners were trimmed to 40% at +8% while losers ran
   the full stop → avg win +$18 vs avg loss −$58 → PF ~0.37.
2. **Entry clock ≠ exit clock** (fixed #2): daily-bar entries shaken out by intraday wicks;
   `trailing_stop` exits were 30/30 losers.
3. **Long-only into a falling month**; **zero-fee accounting** overstated P&L (fixed #1).

## Deploy (your machine, PowerShell) — DO THIS to make the fixes live
```powershell
cd D:\VoltaNode
git checkout main
git merge --ff-only claude/p0-risk-overhaul   # clean fast-forward; pulls in PR #9 too
git push origin main                           # auto-closes PR #9 and #10
.\stop.bat ; .\start.bat
curl http://localhost:8000/settings/safety-status   # confirm max_position_loss_pct shows 6.0
```
Then watch a session: with fees booked + stops sized to volatility + dropped trades now
counted, the **honest post-fee profit factor is finally measurable**. If PF stays < 1 after
~a week, **retire the EMA momentum bots** rather than adding machinery — the data says no edge.

## Run the Kronos edge-check (your machine — HF is firewalled in the agent sandbox)
```powershell
pip install torch transformers huggingface_hub einops
git clone https://github.com/shiyu-coder/Kronos
$env:PYTHONPATH += ";$PWD\Kronos"
cd D:\VoltaNode\trading-bot-backend
python scripts/kronos_backtest.py --symbol BTC --csv data\BTCUSD_1h.csv   # supply your own OHLCV CSV
# or: python scripts/kronos_backtest.py --symbol BTC --asset-class crypto --days 365
```
VERDICT line: `EDGE` = beats buy-and-hold + PF>1 → wire it in; `NO EDGE` = don't deploy;
`NO TRADES` = model didn't load (fix torch/Kronos setup, not a result). The strategy
`strategies/kronos_forecast.py` is intentionally **not registered** (can't go live by accident).

## What's LEFT (no criticals/highs remain)
**Bugs — MEDIUM:** #9 `realized_pnl` exit-fee inconsistency · #11 FIFO `/stats` (needs Alpaca
`/v2/account/activities`) · #13 `risk.py:check_order` trims a full-close SELL (no side check) ·
#14 backtest fills same-bar close + lacks the live profit-manager breakeven/trail · #15
rate-limit runs before the SELL bypass (protective stop can be throttled).
**Bugs — LOW:** #16 in-memory latches wiped on restart · #17 `simple_trend` unclamped sizing
(dormant) · #18 daily-reset ordering · #19 backtest fee inconsistency · #20 DSR `n_returns`.

**Features not built (P1/P2):** auto-disable-edgeless-bots supervisor · trend-strength entry
(ADX / EMA-slope) instead of crossover-moment · wire the correlation haircut
(`analysis/correlation.py` is built + tested but has **zero callers**) · wire drawdown alerts
(`engine.py` discards them) · controlled short/cash side in bear regimes · meta-label filter.

**Deferred gap:** the CPCV gate guards only `apply-hyperopt`; `register_strategy` still pushes
configs live ungated — not a single go-live choke point.

**Operational (must be done by the operator — the agent sandbox can't):**
- Delete 4 stale branches:
  `git push origin --delete claude/alpha-fixes claude/epic-bhabha-98ef50 claude/flamboyant-blackwell-91694c claude/nervous-hertz-7f6087`
- Run the Kronos backtest (above).
- Merge & deploy PR #10 (above).

## Pointers
- Branch / PR: `claude/p0-risk-overhaul` / PR #10 (draft). Tip `246594f`.
- New tests for all fixes: `trading-bot-backend/tests/test_p0_risk_overhaul.py` (28 tests).
- Full suite: `cd trading-bot-backend && python -m pytest -q` → 302 passing.
- Audit run id: `wf_037fb0bb-143` · review run id: `wf_dd206c83-d4d`.
- Diagnostics: `GET /engine/status`, `/portfolio/default`, `/portfolio/default/stats`,
  `/settings/safety-status` (see `CLAUDE.md` for the full endpoint map).
