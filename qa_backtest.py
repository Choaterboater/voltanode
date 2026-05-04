import requests
import json
from datetime import date, timedelta

BASE = "http://localhost:8000"
TODAY = date(2026, 5, 3)
START_90 = (TODAY - timedelta(days=90)).isoformat()
START_365 = (TODAY - timedelta(days=365)).isoformat()
END = TODAY.isoformat()

def run_bt(payload, label):
    try:
        r = requests.post(f"{BASE}/backtest/run", json=payload, timeout=60)
        return r.status_code, r.json() if r.headers.get("content-type","").startswith("application/json") else r.text
    except Exception as e:
        return None, f"EXC: {e}"

def summarize(label, status, body):
    if status != 200:
        print(f"[{label}] HTTP {status}: {str(body)[:300]}")
        return None
    keys = list(body.keys()) if isinstance(body, dict) else []
    tot = body.get("total_return_pct")
    sh = body.get("sharpe_ratio")
    dd = body.get("max_drawdown_pct")
    wr = body.get("win_rate")
    pf = body.get("profit_factor")
    tr = body.get("total_trades")
    eq = body.get("equity_curve") or []
    bid = body.get("backtest_id")
    sid = body.get("strategy_id")
    print(f"[{label}] OK trades={tr} ret%={tot} sharpe={sh} dd%={dd} wr={wr} pf={pf} eq_len={len(eq)} bid={bid} sid={sid}")
    return body

print(f"== Date range 90d: {START_90} -> {END} ==")
print(f"== Date range 365d: {START_365} -> {END} ==")
print()

# Test 1: Schema check
print("--- Test 1: Schema check (momentum BTC 90d) ---")
payload = {"strategy_type":"momentum","symbol":"BTC","asset_class":"crypto","timeframe":"1d","start_date":START_90,"end_date":END}
status, body = run_bt(payload, "T1")
b1 = summarize("T1", status, body)
required = ["total_return_pct","sharpe_ratio","max_drawdown_pct","win_rate","profit_factor","total_trades","equity_curve","backtest_id","strategy_id"]
if isinstance(body, dict):
    missing = [f for f in required if f not in body]
    print(f"[T1] missing fields: {missing}")
    print(f"[T1] all keys: {list(body.keys())}")
print()

# Test 2: Strategy coverage
print("--- Test 2: Strategy coverage ---")
strategies = ["momentum","mean_reversion","macd","breakout","ensemble_ml","news_sentiment","multi_coin"]
results_by_strat = {}
for s in strategies:
    payload = {"strategy_type":s,"symbol":"BTC","asset_class":"crypto","timeframe":"1d","start_date":START_90,"end_date":END}
    status, body = run_bt(payload, s)
    b = summarize(f"T2:{s}", status, body)
    results_by_strat[s] = (status, b)
print()

# Test 3: OHLCV depth (uses T1)
print("--- Test 3: OHLCV depth ---")
if b1:
    eq_len = len(b1.get("equity_curve") or [])
    print(f"[T3] equity_curve length = {eq_len} (expected ~90)")
print()

# Test 4: 365-day momentum
print("--- Test 4: Momentum BTC 365d ---")
payload = {"strategy_type":"momentum","symbol":"BTC","asset_class":"crypto","timeframe":"1d","start_date":START_365,"end_date":END}
status, body = run_bt(payload, "T4")
b4 = summarize("T4", status, body)
print()

# Test 5: Stock backtest
print("--- Test 5: Momentum AAPL stock 365d ---")
payload = {"strategy_type":"momentum","symbol":"AAPL","asset_class":"stock","timeframe":"1d","start_date":START_365,"end_date":END}
status, body = run_bt(payload, "T5")
b5 = summarize("T5", status, body)
print()

# Test 6: PascalCase normalization
print("--- Test 6: PascalCase 'Momentum' ---")
payload = {"strategy_type":"Momentum","symbol":"BTC","asset_class":"crypto","timeframe":"1d","start_date":START_90,"end_date":END}
status, body = run_bt(payload, "T6")
b6 = summarize("T6", status, body)
print()

print("=== DONE ===")
