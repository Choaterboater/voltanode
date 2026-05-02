# Backend API Reference

All endpoints are served from the FastAPI application root (`http://localhost:8000`).

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
**Response:**
```json
{"status": "started"}
```

### Stop Engine
```
POST /engine/stop
```
**Response:**
```json
{"status": "stopped"}
```

---

## Portfolio Router (`/portfolio`)

### Get Portfolio
```
GET /portfolio/{account_id}
```
**Description:** Retrieve full portfolio state for an account including balances, positions, and P&L.

**Path Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `account_id` | string | Account identifier (e.g., `default`) |

**Response Schema (`PortfolioResponse`):**
```json
{
  "account_id": "default",
  "balances": {"USDT": 10000.0},
  "positions": [
    {
      "symbol": "BTC/USD",
      "side": "long",
      "size": 0.5,
      "entry_price": 45000.0,
      "current_price": 46000.0,
      "unrealized_pnl": 500.0,
      "market_value": 23000.0
    }
  ],
  "total_equity": 33000.0,
  "unrealized_pnl": 500.0,
  "realized_pnl": 0.0,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Deposit Funds
```
POST /portfolio/{account_id}/deposit
```
**Request Body (`DepositRequest`):**
```json
{
  "asset": "USDT",
  "amount": 5000.0
}
```

**Response:**
```json
{
  "account_id": "default",
  "asset": "USDT",
  "amount": 5000.0,
  "balance": 15000.0
}
```

### Get Positions
```
GET /portfolio/{account_id}/positions
```
**Response:** Array of `PositionResponse` objects.

### Get Snapshots
```
GET /portfolio/{account_id}/snapshots
```
**Response:**
```json
{
  "account_id": "default",
  "snapshots": []
}
```

---

## Strategies Router (`/strategies`)

### List All Strategies
```
GET /strategies/
```
**Response Schema (`StrategyListResponse`):**
```json
{
  "strategies": [
    {
      "strategy_id": "momentum",
      "strategy_type": "MomentumStrategy",
      "is_active": false,
      "config": {"fast_ema": 12, "slow_ema": 26},
      "metrics": null
    }
  ]
}
```

### Register Strategy
```
POST /strategies/register
```
**Request Body (`StrategyRegisterRequest`):**
```json
{
  "strategy_type": "momentum",
  "config": {"fast_ema": 5, "slow_ema": 10}
}
```

**Response:**
```json
{
  "strategy_id": "momentum_12345678",
  "strategy_type": "momentum",
  "status": "registered"
}
```

### Toggle Strategy
```
POST /strategies/{strategy_id}/toggle
```
**Request Body (`StrategyToggleRequest`):**
```json
{
  "strategy_id": "momentum_12345678",
  "active": true
}
```

**Response:**
```json
{
  "strategy_id": "momentum_12345678",
  "active": true
}
```

### Get Strategy Metrics
```
GET /strategies/{strategy_id}/metrics
```
**Response:** Dictionary of performance metrics (win rate, profit factor, Sharpe, etc.).

---

## Trades Router (`/trades`)

### List Trades
```
GET /trades/
```
**Query Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `account_id` | string | `null` | Filter by account |
| `strategy_id` | string | `null` | Filter by strategy |
| `limit` | integer | `100` | Maximum results |

**Response:** Array of trade objects:
```json
[
  {
    "id": "trade-1",
    "order_id": "order-1",
    "strategy_id": "momentum",
    "symbol": "BTC/USD",
    "side": "buy",
    "quantity": 0.5,
    "price": 45000.0,
    "fee": 22.5,
    "realized_pnl": 500.0,
    "timestamp": "2024-01-15T10:30:00Z"
  }
]
```

### Export Trades
```
GET /trades/export?format=csv
```
**Query Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `format` | string | `csv` | Export format (`csv` or `json`) |

**Response:**
```json
{
  "path": "./exports/trades_20240115_103000.csv",
  "count": "42"
}
```

---

## Backtest Router (`/backtest`)

### Run Backtest
```
POST /backtest/run
```
**Request Body (`BacktestRequest`):**
```json
{
  "strategy_type": "momentum",
  "symbol": "bitcoin",
  "asset_class": "crypto",
  "start_date": "2024-01-01",
  "end_date": "2024-01-30",
  "timeframe": "1d",
  "initial_balance": {"USDT": 10000.0},
  "config": {"fast_ema": 12, "slow_ema": 26}
}
```

**Response:**
```json
{
  "backtest_id": "a1b2c3d4",
  "strategy_id": "momentum_12345678",
  "total_return_pct": 8.45,
  "sharpe_ratio": 1.72,
  "max_drawdown_pct": -12.5,
  "win_rate": 62.4,
  "profit_factor": 2.14,
  "total_trades": 28,
  "equity_curve": [
    {"date": "2024-01-01", "equity": 10000},
    {"date": "2024-01-02", "equity": 10028}
  ]
}
```

### List Backtest Results
```
GET /backtest/results
```
**Response:**
```json
{"results": []}
```

---

## Market Router (`/market`)

### Get Prices
```
GET /market/prices?symbols=bitcoin,ethereum
```
**Query Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `symbols` | string | Comma-separated CoinGecko IDs or tickers |

**Response:** Array of `PriceResponse`:
```json
[
  {
    "symbol": "bitcoin",
    "price": 67432.5,
    "timestamp": "2024-01-15T10:30:00Z"
  }
]
```

### Get OHLCV
```
GET /market/ohlcv/{symbol}?asset_class=crypto&timeframe=1d&limit=100
```
**Path Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `symbol` | string | Trading symbol |

**Query Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `asset_class` | string | `crypto` | `crypto` or `stock` |
| `timeframe` | string | `1d` | `1d`, `1h`, `15m`, `1wk` |
| `limit` | integer | `100` | Number of bars |

**Response (`OHLCVResponse`):**
```json
{
  "symbol": "bitcoin",
  "timeframe": "1d",
  "data": [
    {
      "timestamp": "2024-01-01T00:00:00Z",
      "open": 42000.0,
      "high": 43500.0,
      "low": 41800.0,
      "close": 43000.0,
      "volume": 1250000000.0
    }
  ]
}
```

### Get Symbols
```
GET /market/symbols
```
**Response:**
```json
{
  "crypto": ["bitcoin", "ethereum", "solana", "cardano"],
  "stocks": ["AAPL", "TSLA", "MSFT", "GOOGL"]
}
```

---

## Advisor Router (`/advisor`)

### Analyze Symbol (POST)
```
POST /advisor/analyze
```
**Request Body (`AnalyzeRequest`):**
```json
{
  "symbol": "bitcoin",
  "asset_type": "crypto",
  "lookback_days": 90
}
```

### Analyze Symbol (GET)
```
GET /advisor/analyze?symbol=bitcoin&asset_type=crypto&lookback_days=90
```

**Response (`AnalysisResponse`):**
```json
{
  "symbol": "bitcoin",
  "current_price": 67432.5,
  "asset_type": "crypto",
  "verdict": "BUY",
  "confidence": 72.5,
  "summary": "Strong upward momentum with SMA crossover and positive MACD histogram.",
  "indicators": [
    {
      "name": "SMA 20/50",
      "value": 2.34,
      "signal": "bullish",
      "strength": 0.85,
      "description": "Price 67432.5 vs SMA20 66200 and SMA50 64500."
    }
  ],
  "price_targets": [
    {
      "label": "Bull Case",
      "price": 72000.0,
      "probability": 0.35,
      "rationale": "Breakout above resistance with volume confirmation."
    }
  ],
  "risk_level": "moderate",
  "suggested_position_size": 0.07,
  "entry_zone_low": 66800.0,
  "entry_zone_high": 67432.5,
  "stop_loss": 65000.0,
  "take_profit": 71000.0,
  "time_horizon": "medium_term"
}
```

---

## Error Responses

All routers return standard FastAPI HTTP exceptions:

| Status | Meaning | Typical Cause |
|--------|---------|---------------|
| `400` | Bad Request | Invalid strategy type, malformed request body |
| `404` | Not Found | Account or strategy not found |
| `422` | Validation Error | Pydantic schema mismatch |
| `500` | Internal Server | Backtest engine error, unhandled exception |
| `503` | Service Unavailable | Engine not initialized |
