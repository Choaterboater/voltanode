# VoltaNode — Session Handoff (2026-06-09, evening)

> New session: read this file first. Supersedes the morning handoff.

## TL;DR
- **PR #10's bug fixes are LIVE** — the backend was restarted on the fix branch
  today (verified `max_position_loss_pct: 6.0` in safety-status). The git merge
  to main is still yours to do.
- **A second wave shipped on `claude/feature-edge-overhaul` → PR #11 (draft)**:
  6 new features + 10 adversarial-review hardening fixes + a **full UI
  redesign**. Tip `90b3a20`. **341 backend tests pass, tsc clean. NOT deployed**
  (the running backend has PR #10 code only; the new features need one more
  restart after you merge/review).
- The frontend redesign IS already visible on :3001 (Vite serves the working
  tree).

## Why the bot loses (one line)
Exits, not entries: 72% of losers went UP ≥1% first; 16/32 losers hit +2%
before dying at −2% stops; winners trimmed at avg +$18 vs losers −$58.
PR #10 + PR #11 attack exactly this.

## What's in PR #11 (`claude/feature-edge-overhaul`)
1. **Drawdown halt lets position-REDUCING exits through** (side-checked,
   clamped); risk alerts logged/notified + exposed in `/settings/safety-status`
   (`risk_alerts`).
2. **auto_discovery exit latch fixed** (mid-band reset disarmed the exit —
   live record was 15 buys / 1 sell) + latch now resyncs with the portfolio
   (restart/external-close safe).
3. **regime_gate default-ON for macd + news_sentiment** (BUY below EMA-100 →
   HOLD; SELLs never gated). Deep config merge so partial overrides can't
   silently disable it.
4. **ATR-aware exits**: position remembers its ATR stop distance (re-measured
   after restarts); hard loss cap honors wider ATR stops (operator switch
   `safety.atr_widens_position_loss_cap`); breakeven AND trail-arm scale
   1.25x ATR, giveback 1.0x ATR; all `pm_*` knobs are real config keys.
5. **Honest scoreboard**: every trade carries `origin_strategy_id` (the entry
   strategy, not the exit manager) — in fills.jsonl, `/trades`, and trade
   memory; phantom-lot FIFO guard (TARA −$717 → broker-true −$306);
   `GET /learning/stats` = entry-attributed PF per bot.
6. **Auto-disable supervisor** (`learning/supervisor.py`): benches any entry
   strategy with PF < 0.7 over ≥10 closed round trips. Bench = entries-only
   veto (`entries_disabled`) — exits stay armed. Never auto re-enables;
   operator toggle clears it; re-bench needs 5 fresh trades.
7. **capital_allocator disabled** (config.yaml `capital_deployment.enabled:
   false`) — it was an ungated 30-min loop holding ~$33k (~34% of equity);
   funding loop self-gates to zero Binance calls while nothing consumes it.
8. **Full UI redesign**: new tokens/type scale/depth system, grouped sidebar,
   panels/pills/segmented controls, restyled charts, allocation stacked bar,
   aligned stat grids — all 13 pages. (Also fixed `bg-bg-card` /
   `text-accent-foreground` referencing undefined tokens — some cards had NO
   background before.)

## Operator actions (in order)
```powershell
cd D:\VoltaNode
# 1. Review + merge PR #11 (it contains PR #10's commits; merging auto-closes both)
gh pr view 11 --web
git checkout main
git merge --ff-only claude/feature-edge-overhaul
git push origin main

# 2. Restart the backend so the new features go live
#    (stop.bat lies — verify the python PID is gone)
.\stop.bat ; .\start.bat
curl http://localhost:8000/settings/safety-status   # expect risk_alerts: []
curl http://localhost:8000/learning/stats           # entry-attributed scoreboard

# 3. Bench the proven losers (I was not permitted to do this for you).
#    Analysis says: 7 news_sentiment bots (oversized 5x clips, -$637 attributed),
#    4 momentum bots (0-for-6 realized), 1 squeeze bot (trades TARA/GRPN tier).
#    The supervisor would bench most of these automatically after 10 round trips,
#    but they keep bleeding until then:
$ids = @('news_sentiment_1777846168578','news_sentiment_1777846170298',
         'news_sentiment_1777846172479','news_sentiment_1777846173915',
         'news_sentiment_1777846175801','news_sentiment_1777846177240',
         'news_sentiment_1777847084768','momentum_1777844811849',
         'momentum_1777846151673','momentum_1777846184599',
         'momentum_1777853706176','squeeze_1778512092633')
foreach ($id in $ids) {
  Invoke-RestMethod -Method Post -Uri "http://localhost:8000/strategies/$id/toggle" `
    -ContentType 'application/json' -Body '{"active": false}'
}
# Surviving book: 2 mean_reversion + 2 auto_discovery + 3 macd (now regime-gated)
# + engine exit managers.

# 4. Optional cleanup
git push origin --delete claude/alpha-fixes claude/epic-bhabha-98ef50 `
  claude/flamboyant-blackwell-91694c claude/nervous-hertz-7f6087
# Dust positions (~12 sub-cent residues): POST /portfolio/default/flatten?symbols=...&trim_pct=1.0
# Kronos edge-check: see the morning handoff section below (unchanged).
```

## How to judge the next 2 weeks (the go/no-go)
- `GET /learning/stats` — per-bot entry-attributed PF, n, bench status. This is
  the honest scoreboard; ignore the family P&L in `/trades` (exit-manager ids).
- Target: post-fee PF > 1 on the surviving book over ≥30 closed round trips.
- The supervisor will bench anything that proves PF < 0.7 — if everything gets
  benched, the answer is "no edge in these strategy families"; stop adding
  machinery and either run the Kronos check or paper-trade mean_reversion only.

## Known gaps / next session candidates
- Backtest engine lacks the live profit-manager (bug #14 second half) — exit
  knobs can't be tuned offline yet. `scripts/ab_backtest.py` A/B + CPCV harness
  is the right first build next session.
- CPCV gate `min_trades_per_fold=3` near-auto-fails sparse daily-bar configs —
  benched bots may be unable to re-qualify on a technicality (pooled-fold
  relaxation needed).
- Crypto 365d cached bars have degenerate OHLC (open=high=low=close) — refetch
  ≤90d windows for real high/low before any crypto backtest.
- Duplicate-order root cause (two TSLA fills 31s apart on 6/4) undiagnosed.
- MEDIUM bugs remaining: #9 realized_pnl exit-fee inconsistency · #11 FIFO
  /stats via Alpaca activities · #15 rate-limit before SELL bypass (live engine
  doesn't call RiskManager.check_order at all — drawdown halt is paper-only;
  SafetyValidator governs live).
- 5/27 00:00Z −$1,935 one-minute marks glitch still pollutes equity_history.

## Pointers
- Branch / PR: `claude/feature-edge-overhaul` / **PR #11** (contains PR #10).
- Tests: `tests/test_feature_edge_overhaul.py` (39) + `tests/test_p0_risk_overhaul.py`
  (28); full suite `python -m pytest -q` → **341 passing**.
- Workflow run ids: feature-hunt `wf_17c893a7-f0c` · review `wf_80b767fd-859`
  (41 agents) · UI sweep `wf_2b0095f0-f3c`.
- Kronos edge-check + run commands: unchanged from the morning handoff —
  `pip install torch transformers huggingface_hub einops`, clone
  https://github.com/shiyu-coder/Kronos, then
  `python scripts/kronos_backtest.py --symbol BTC --asset-class crypto --days 365`.
  (Note: the no-CSV path has a known crash — `MarketData()` needs
  `MarketData(cache=DataCache())`, scripts/kronos_backtest.py:62.)
