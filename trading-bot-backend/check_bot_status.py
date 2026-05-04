import requests, json, sys

BASE = 'http://localhost:8000'

def get(path):
    try:
        r = requests.get(f'{BASE}{path}', timeout=10)
        return r.status_code, r.json() if r.text else None
    except Exception as e:
        return 0, str(e)

def post(path, data=None):
    try:
        r = requests.post(f'{BASE}{path}', json=data, timeout=10)
        return r.status_code, r.json() if r.text else None
    except Exception as e:
        return 0, str(e)

print('=== Bot Status Check ===\n')

# Engine
sc, d = get('/engine/status')
print(f'1. Engine: {d}')

# Live mode
sc, d = get('/settings/live-mode')
print(f'2. Live mode: {d}')

# Strategies
sc, d = get('/strategies')
strats = d.get('strategies', []) if d else []
print(f'3. Strategies: {len(strats)} total')
active = [s for s in strats if s.get('is_active')]
print(f'   Active: {len(active)}')
for s in active:
    print(f'   - {s["strategy_id"]}: {s["strategy_type"]} -> {s.get("config", {})}')

# Portfolio
sc, d = get('/portfolio/default')
if d:
    print(f'4. Portfolio: equity=${d.get("total_equity")}, positions={len(d.get("positions", []))}')
    for p in d.get('positions', []):
        print(f'   - {p["symbol"]}: {p["size"]} @ ${p["entry_price"]:.2f}')

# Orders
sc, d = get('/orders?account_id=default')
orders = d if d else []
print(f'5. Orders: {len(orders)}')
for o in orders[-5:]:
    print(f'   - {o["symbol"]} {o["side"]} {o["status"]} qty={o["quantity"]}')

# Trades
sc, d = get('/trades')
trades = d if d else []
print(f'6. Trades: {len(trades)}')

# Alpaca direct
print('\n=== Alpaca Direct ===')
sys.path.insert(0, '.')
from brokers.alpaca import AlpacaBroker
broker = AlpacaBroker(paper=True)
try:
    broker.connect(
        api_key='PKFIWUUWGPBB6BMEAONXYSH75B',
        api_secret='G3RxtUoUvZvkWhgrXjXgpVfeZpY42gbS7a8bZgVUBb9j'
    )
    bal = broker.get_balance()
    print(f'Balance: {bal}')
    pos = broker.get_positions()
    print(f'Positions: {len(pos)}')
    for p in pos:
        print(f'  {p["symbol"]}: {p["size"]} @ ${p["entry_price"]:.2f}')
except Exception as e:
    print(f'Alpaca error: {e}')

# Try to toggle a strategy and see what happens
print('\n=== Strategy Toggle Test ===')
if active:
    sid = active[0]["strategy_id"]
    sc, d = post(f'/strategies/{sid}/toggle', {'strategy_id': sid, 'active': False})
    print(f'Toggle OFF {sid}: {sc} -> {d}')
    sc, d = post(f'/strategies/{sid}/toggle', {'strategy_id': sid, 'active': True})
    print(f'Toggle ON  {sid}: {sc} -> {d}')
