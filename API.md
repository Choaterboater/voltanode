# Backend API Reference

All endpoints are served from the FastAPI application root (`http://localhost:8000`).

Swagger UI: `http://localhost:8000/docs`

---

## Base Routes

### Health Check
```
GET /health
```
**Response:**
```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

### Engine Status
```
GET /engine/status
```
**Response:**
```json
{
  "running": true,
  "account_count": 1
}
```

### Start Engine
```
POST /engine/start
```
**Response:** `{"status": "started"}`

### Stop Engine
```
POST /engine/stop
```
**Response:** `{"status": "stopped"}`

---

## Portfolio Router (`/portfolio`)

### Get Portfolio
```
GET /portfolio/{account_id}
```
**Response:** Portfolio with balances, positions, equity, P&L.

### Deposit Funds
```
POST /portfolio/{account_id}/deposit
```
**Body:** `{"asset": "USDT", "amount": 5000.0}`

### Get Positions
```
GET /portfolio/{account_id}/positions
```

### Get Snapshots
```
GET /portfolio/{account_id}/snapshots
```

---

## Orders Router (`/orders`)

### List Orders
```
GET /orders?account_id=default
```

### Place Order
```
POST /orders
```
**Body:**
```json
{
  "symbol": "BTC/USD",
  "side": "buy",
  "order_type": "market",
  "quantity": 0.5,
  "price": 45000,
  "account_id": "default",
  "strategy_id": null
}
```

### Cancel Order
```
POST /orders/{order_id}/cancel?account_id=default
```

---

## Strategies Router (`/strategies`)

### List All Strategies
```
GET /strategies/
```

### Register Strategy
```
POST /strategies/register
```
**Body:** `{"strategy_type": "momentum", "config": {"fast_ema": 12}}`

### Toggle Strategy
```
POST /strategies/{strategy_id}/toggle
```
**Body:** `{"strategy_id": "...", "active": true}`

### Get Strategy Metrics
```
GET /strategies/{strategy_id}/metrics
```

---

## Trades Router (`/trades`)

### List Trades
```
GET /trades/?account_id=&strategy_id=&limit=100
```

### Export Trades
```
GET /trades/export?format=csv
```

---

## Backtest Router (`/backtest`)

### Run Backtest
```
POST /backtest/run
```
**Body:**
```json
{
  "strategy_type": "momentum",
  "symbol": "bitcoin",
  "asset_class": "crypto",
  "timeframe": "1d",
  "initial_balance": {"USDT": 10000.0}
}
```

### List Results
```
GET /backtest/results
```

---

## Market Router (`/market`)

### Get Prices
```
GET /market/prices?symbols=bitcoin,ethereum
```

### Bulk Prices
```
GET /market/prices/bulk
```

### Get OHLCV
```
GET /market/ohlcv/{symbol}?asset_class=crypto&timeframe=1d&limit=100
```

### Get Symbols
```
GET /market/symbols
```

### Search Symbols
```
GET /market/search?query=apple
```

---

## Advisor Router (`/advisor`)

### Analyze Symbol
```
POST /advisor/analyze
GET /advisor/analyze?symbol=bitcoin&asset_type=crypto&lookback_days=90
```
**Response:** Verdict, confidence, indicators, price targets, risk level, position sizing, chart data.

---

## Settings Router (`/settings`)

### Live Mode
```
GET  /settings/live-mode
POST /settings/live-mode         # Body: {"enabled": true, "broker_name": "alpaca"}
```

### Brokers
```
GET /settings/brokers             # List registered brokers
```

### Broker Config
```
GET  /settings/broker/{broker_name}
POST /settings/broker             # Body: {"broker_name", "testnet", "paper"}
```

### API Keys
```
POST /settings/api-keys           # Body: {"broker_name", "api_key", "api_secret"}
```

### Test Connection
```
POST /settings/test-connection    # Body: {"broker_name", "testnet", "paper"}
```

### Safety
```
POST /settings/safety             # Body: safety limits
POST /settings/kill-switch        # Body: {"action": "activate|deactivate", "reason"}
GET  /settings/safety-status
```

### Disconnect
```
POST /settings/disconnect
```

### Register Broker
```
POST /settings/register-broker    # Body: {"broker_name", "description", "testnet", "paper"}
```

---

## News & Sentiment Router (`/news`)

### Status
```
GET /news/status
```
**Response:**
```json
{
  "alpaca_configured": false,
  "llm_provider": "ollama",
  "llm_configured": true,
  "hybrid_mode": true,
  "hybrid_threshold": 0.6,
  "vader_available": true,
  "ollama_available": true
}
```

### Analyze Headline
```
POST /news/analyze?headline=...&summary=...&source=...&symbols=AAPL
```
**Response:** Sentiment results with compound score, confidence, impact, themes.

### Fetch News
```
POST /news/fetch?symbols=AAPL,MSFT&hours=24&analyze=true
```

### Get Articles
```
GET /news/articles?symbol=AAPL&hours=24&limit=50
```

### Symbol Sentiment
```
GET /news/sentiment/{symbol}?hours=24&model=vader
```

### Trending
```
GET /news/trending?hours=24&min_articles=3
```

### Cleanup
```
POST /news/cleanup?days=7
```

---

## Error Responses

| Status | Meaning | Typical Cause |
|--------|---------|---------------|
| `400` | Bad Request | Invalid strategy type, malformed body |
| `404` | Not Found | Account or strategy not found |
| `422` | Validation Error | Pydantic schema mismatch |
| `500` | Internal Server | Engine error, unhandled exception |
| `503` | Service Unavailable | Engine not initialized |
