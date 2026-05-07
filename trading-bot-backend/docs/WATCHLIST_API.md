# Watchlist API — external integration

How to push tickers from another app (scanner, alerts pipeline, Discord
bot, etc.) into the VoltaNode watchlist.

## Endpoint

Base URL: `http://127.0.0.1:8000/watchlist/`

| Method | Path | Purpose |
|---|---|---|
| GET | `/watchlist/` | List all watchlist entries (newest first). Optional `?asset_type=stock` filter. |
| POST | `/watchlist/` | Add or refresh a single ticker. Idempotent on `(symbol, asset_type)`. |
| POST | `/watchlist/bulk` | Add a batch of tickers in one request. |
| GET | `/watchlist/contains/{symbol}?asset_type=stock` | Quick `{in_watchlist: bool}` check. |
| DELETE | `/watchlist/{symbol}?asset_type=stock` | Remove a ticker. |

## Request body shape

```json
{
  "symbol": "RXT",
  "asset_type": "stock",            // "stock" or "crypto"
  "note": "high SI, breakout +14% volume spike",
  "source": "external-scanner"      // free-text — shows on the chip in the UI
}
```

`source` is rendered as a colored chip on the Watchlist page, so use a
distinctive value per producer app (e.g. `"my-screener"`, `"discord-bot"`,
`"chatgpt"`) and you can tell at a glance where each pick came from.

## Examples

### curl (single)
```bash
curl -X POST http://127.0.0.1:8000/watchlist/ \
  -H "Content-Type: application/json" \
  -d '{"symbol":"RXT","asset_type":"stock","note":"5% short squeeze setup","source":"my-app"}'
```

### curl (bulk — preferred for batches)
```bash
curl -X POST http://127.0.0.1:8000/watchlist/bulk \
  -H "Content-Type: application/json" \
  -d '[
    {"symbol":"RXT","asset_type":"stock","source":"my-app","note":"high SI"},
    {"symbol":"GME","asset_type":"stock","source":"my-app","note":"Reddit chatter"},
    {"symbol":"BTC","asset_type":"crypto","source":"my-app"}
  ]'
```

### Python
```python
import requests
requests.post(
    "http://127.0.0.1:8000/watchlist/bulk",
    json=[
        {"symbol": "RXT", "asset_type": "stock", "source": "my-app", "note": "Form 4 buying"},
        {"symbol": "KWR", "asset_type": "stock", "source": "my-app"},
    ],
    timeout=10,
).raise_for_status()
```

### JavaScript / Node
```js
await fetch("http://127.0.0.1:8000/watchlist/bulk", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify([
    { symbol: "RXT", asset_type: "stock", source: "my-app", note: "high SI" },
    { symbol: "GME", asset_type: "stock", source: "my-app" },
  ]),
});
```

## Same-machine vs remote

By default the backend binds to `127.0.0.1:8000` (localhost only). Three
ways to reach it from another app:

1. **Same machine, different process** — works out of the box. Hit
   `http://127.0.0.1:8000/watchlist/`.
2. **Same network, different machine** — start the backend with
   `--host 0.0.0.0` so it binds to all interfaces, then hit
   `http://<your-pc-ip>:8000/watchlist/` from the other machine. ⚠
   Anyone on your LAN can write to your watchlist; add auth (below) if
   that matters.
3. **Internet** — use a tunnel (Cloudflare Tunnel, ngrok, Tailscale)
   rather than exposing port 8000 directly. Always pair with auth.

## Adding auth (optional)

Currently the endpoints are unauthenticated — assumes single-tenant
localhost. If you expose them remotely, add a simple bearer token:

1. Pick a long random string and put it in `.env` as `WATCHLIST_TOKEN=...`.
2. In `api/routes/watchlist.py`, add a dependency that checks
   `request.headers.get("Authorization") == f"Bearer {os.environ['WATCHLIST_TOKEN']}"`
   and raises 401 otherwise.
3. External apps include `Authorization: Bearer <token>` in every request.

## Storage

Entries persist to `trading-bot-backend/data/watchlist.json`. File is
human-readable / hand-editable if you ever need to bulk-clean it
outside the API.

## What it triggers

Adding to the watchlist:
- ✅ Surfaces the ticker on the **Watchlist** tab in the frontend
- ✅ Tags it with the `source` you specified (visible chip)
- ❌ Does **not** automatically trade it — to actually trade a ticker
   you have to register a strategy/bot configured for that symbol.
   Watchlist is research/observation only.
