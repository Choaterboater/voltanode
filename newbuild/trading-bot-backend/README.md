# Paper Trading Bot Backend

A complete, runnable Python trading bot system with paper trading, 7+ algorithmic strategies, backtesting, data collection, and analytics.

## Features

- **Paper Trading Engine**: Realistic order execution with slippage and fees
- **7 Algorithmic Strategies**: Momentum, Mean Reversion, Grid, Breakout, Arbitrage, MACD, Ensemble ML
- **Backtesting**: Bar-by-bar backtest with walk-forward analysis
- **Risk Management**: Position sizing (fixed, percentage, Kelly, volatility), drawdown monitoring, exposure limits
- **Market Data**: CoinGecko (crypto) + Yahoo Finance (stocks) with caching
- **REST API**: FastAPI with full CRUD endpoints
- **CLI**: Typer-based command-line interface
- **Analytics**: Trade records, portfolio snapshots, performance reports, CSV/JSON export
- **Database**: SQLite with SQLAlchemy ORM

## Installation

```bash
cd trading-bot-backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Quick Start

### 1. Start the API Server

```bash
python run.py
```

Or with uvicorn directly:
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.
Visit `http://localhost:8000/docs` for Swagger UI.

### 2. Run the CLI Bot

```bash
python -m cli.main run-bot --strategy momentum --strategy macd --interval 10.0
```

### 3. Run a Backtest

```bash
python -m cli.main backtest momentum bitcoin --start 2023-01-01 --end 2023-12-31 --balance 10000
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `run-bot` | Start the paper trading bot tick loop |
| `backtest` | Run a strategy backtest on historical data |
| `export-records` | Export database records to CSV/JSON |
| `status` | Show current portfolio and active bots |
| `strategy-list` | List all strategies with descriptions |
| `report` | Generate performance report |
| `configure` | View or modify bot configuration |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/portfolio/{account_id}` | Get portfolio |
| POST | `/portfolio/{account_id}/deposit` | Deposit funds |
| GET | `/portfolio/{account_id}/positions` | Get open positions |
| POST | `/orders` | Submit order |
| GET | `/trades` | List trades |
| GET | `/trades/export` | Export trades |
| GET | `/strategies` | List strategies |
| POST | `/strategies/register` | Register strategy |
| POST | `/backtest/run` | Run backtest |
| GET | `/market/ohlcv/{symbol}` | Get OHLCV data |
| GET | `/market/prices` | Get current prices |
| GET | `/engine/status` | Engine status |
| POST | `/engine/start` | Start engine |
| POST | `/engine/stop` | Stop engine |

## Strategies

1. **Momentum**: EMA crossover trend following with ATR-based sizing
2. **Mean Reversion**: RSI + Bollinger Bands for oversold/overbought signals
3. **Grid**: Grid trading for ranging markets
4. **Breakout**: Support/resistance breakout with volume confirmation
5. **Arbitrage**: Cross-exchange price divergence scanner
6. **MACD**: MACD line/signal line crossover with histogram confirmation
7. **Ensemble ML**: Multi-indicator weighted scoring with optional Random Forest

## Project Structure

```
trading-bot-backend/
├── bot/                # Core engine, portfolio, orders, risk, config
├── strategies/         # 7 algorithmic trading strategies
├── data/               # Market data fetcher, storage, cache
├── backtest/           # Backtest runner and metrics
├── analytics/          # Records, reports, export
├── api/                # FastAPI app and routes
├── cli/                # Typer CLI commands
├── tests/              # pytest test suite
├── config.yaml         # Default configuration
├── requirements.txt    # Python dependencies
└── run.py             # Entry point
```

## Testing

```bash
pytest tests/ -v
```

## Configuration

Edit `config.yaml` or set environment variables with `BOT_` prefix:

```yaml
risk:
  max_drawdown_pct: 0.10
  fee_rate: 0.001
  position_sizing_method: "percentage"

strategies:
  momentum:
    enabled: true
    fast_ema: 12
    slow_ema: 26
```

## License

MIT
