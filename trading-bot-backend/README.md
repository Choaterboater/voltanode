# Paper Trading Bot Backend

A complete Python trading bot system with paper trading, 9 algorithmic strategies, backtesting, data collection, AI advisor, news sentiment analysis, and live trading support.

## Features

- **Paper Trading Engine**: Realistic order execution with slippage and fees
- **9 Algorithmic Strategies**: Momentum, Mean Reversion, Grid, Breakout, Arbitrage, MACD, Ensemble ML, News Sentiment
- **Backtesting**: Bar-by-bar backtest with walk-forward analysis
- **AI Advisor**: 18+ technical indicators, price targets, risk assessment, position sizing
- **News & Sentiment**: Alpaca News API + VADER + Ollama LLM hybrid sentiment analysis
- **Risk Management**: Position sizing (fixed, percentage, Kelly, volatility), drawdown monitoring, exposure limits, kill switch
- **Live Trading**: Alpaca broker adapter with paper/live mode toggle
- **Market Data**: CoinGecko (crypto) + Yahoo Finance (stocks) with caching
- **Security**: PBKDF2 encryption for API keys
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
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Or:
```bash
python run.py
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
| GET | `/engine/status` | Engine status |
| POST | `/engine/start` | Start engine |
| POST | `/engine/stop` | Stop engine |
| GET | `/portfolio/{account_id}` | Get portfolio |
| POST | `/portfolio/{account_id}/deposit` | Deposit funds |
| GET | `/portfolio/{account_id}/positions` | Get positions |
| GET | `/orders` | List orders |
| POST | `/orders` | Place order |
| POST | `/orders/{order_id}/cancel` | Cancel order |
| GET | `/trades` | List trades |
| GET | `/trades/export` | Export trades |
| GET | `/strategies` | List strategies |
| POST | `/strategies/register` | Register strategy |
| POST | `/strategies/{strategy_id}/toggle` | Toggle strategy |
| POST | `/backtest/run` | Run backtest |
| GET | `/backtest/results` | Backtest results |
| GET | `/market/prices` | Get prices |
| GET | `/market/ohlcv/{symbol}` | Get OHLCV |
| GET | `/market/symbols` | List symbols |
| GET | `/advisor/analyze` | AI advisor analysis |
| GET | `/settings/live-mode` | Live mode status |
| POST | `/settings/live-mode` | Toggle live mode |
| GET | `/settings/brokers` | List brokers |
| POST | `/settings/api-keys` | Store API keys |
| POST | `/settings/test-connection` | Test broker connection |
| GET | `/settings/safety-status` | Safety status |
| POST | `/settings/kill-switch` | Kill switch control |
| GET | `/news/status` | News module status |
| POST | `/news/analyze` | Analyze headline sentiment |
| POST | `/news/fetch` | Fetch news from Alpaca |
| GET | `/news/sentiment/{symbol}` | Symbol sentiment |
| GET | `/news/trending` | Trending symbols |

## Strategies

1. **Momentum**: EMA crossover trend following with ATR-based sizing
2. **Mean Reversion**: RSI + Bollinger Bands for oversold/overbought signals
3. **Grid**: Grid trading for ranging markets
4. **Breakout**: Support/resistance breakout with volume confirmation
5. **Arbitrage**: Cross-exchange price divergence scanner
6. **MACD**: MACD line/signal line crossover with histogram confirmation
7. **Ensemble ML**: Multi-indicator weighted scoring with optional Random Forest
8. **News Sentiment**: Trading signals based on news sentiment analysis

## Environment Variables

```bash
# Required
export VOLTANODE_SECRET_KEY="your-fernet-key"

# News & Sentiment (optional)
export ALPACA_API_KEY=""
export ALPACA_SECRET_KEY=""
export LLM_PROVIDER="ollama"      # ollama, kim, claude, openai
export LLM_MODEL="llama3.2:3b"
export LLM_API_KEY=""             # not needed for Ollama
export SENTIMENT_HYBRID_MODE="true"
export SENTIMENT_HYBRID_THRESHOLD="0.6"
```

## Project Structure

```
trading-bot-backend/
├── api/                # FastAPI app and routes
├── advisor/            # AI analysis engine
├── analytics/          # Reports, records, export
├── backtest/           # Backtest runner and metrics
├── bot/                # Core engine, portfolio, orders, risk
├── brokers/            # Alpaca, Mock adapters
├── cli/                # Typer CLI commands
├── data/               # Market data fetcher, cache, storage
├── news/               # News fetcher, sentiment engine, storage
├── safety/             # Kill switch, limits, notifier
├── security/           # PBKDF2 encryption
├── strategies/         # 9 algorithmic trading strategies
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
