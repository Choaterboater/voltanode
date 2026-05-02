# VoltaNode

A [Choate Labs](https://choatelabs.app/) product.

VoltaNode is a full-stack paper trading platform that enables developers and traders to simulate crypto and stock trading strategies in a risk-free environment. The application features a dark-themed React dashboard for visualizing portfolio performance, managing trading bots, running backtests, analyzing market data, and monitoring news sentiment — all backed by a Python FastAPI backend with integrated strategy engines, risk management, AI-powered trading advisor, and local LLM sentiment analysis.

## Key Features

- **Dashboard Overview**: Real-time portfolio equity curve, asset allocation pie charts, active bot cards, market ticker tape, and system alerts
- **Watchlist**: Curated crypto + stock watchlists with recommendations, one-click advisor analysis
- **AI Trading Advisor**: Symbol analysis with 18+ technical indicators, price targets, risk assessment, position sizing, and interactive price charts
- **Paper Trading**: Virtual order execution with realistic slippage, fees, and multi-account portfolio tracking
- **Strategy Library**: 9 built-in strategies including Momentum, Mean Reversion, Grid, Breakout, MACD, Arbitrage, ML Ensemble, and News Sentiment
- **Backtest Engine**: Bar-by-bar backtesting with equity curves and comprehensive metrics (Sharpe, drawdown, profit factor, win rate)
- **Bot Lab**: Manage, start, pause, and monitor automated trading bots with live P&L sparklines
- **News & Sentiment**: Alpaca News API integration with dual-tier sentiment (VADER + Ollama LLM), headline analyzer, trending symbols
- **Settings**: Broker connection management (API keys, test connections), kill switch, safety limits, live/paper mode toggle
- **Market Data**: Unified fetcher supporting CoinGecko (crypto) and Yahoo Finance (stocks) with intelligent caching
- **Analytics & Reporting**: Trade history, CSV export, P&L by symbol, win/loss distribution

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend | React | 19 |
| Frontend | TypeScript | 5.x |
| Frontend | Vite | 7.x |
| Frontend | Tailwind CSS | 3.4 |
| Frontend | Recharts | latest |
| Frontend | Framer Motion | latest |
| Frontend | Sonner | latest |
| Frontend | Lucide React | latest |
| Backend | Python | 3.11+ |
| Backend | FastAPI | 0.104+ |
| Backend | Uvicorn | 0.24+ |
| Backend | Pydantic | 2.5+ |
| Backend | Pandas | 2.1+ |
| Backend | NumPy | 1.26+ |
| Backend | scikit-learn | 1.3+ |
| Backend | yfinance | 0.2.28+ |
| Backend | vaderSentiment | 3.3+ |
| LLM | Ollama | local |

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | Portfolio metrics, equity curve, allocation, bots, market ticker |
| `/watchlist` | Watchlist | Crypto + stock recommendations with advisor shortcut |
| `/advisor` | AI Advisor | Technical analysis, price targets, risk sizing, charts |
| `/paper` | Paper Trading | Order entry, positions, orders, cancel |
| `/strategies` | Strategies | Active strategies, library, register & toggle |
| `/backtest` | Backtest | Configure & run backtests, equity curve results |
| `/analytics` | Analytics | Trade history, P&L charts, performance metrics |
| `/bots` | Bot Lab | Create, manage, play/pause/delete bots |
| `/news` | News & Sentiment | Headline analyzer, symbol lookup, trending |
| `/settings` | Settings | Brokers, safety, live mode |
| `/about` | About | Features, Choate Labs branding, disclaimer |

## Live URL

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`

---

Built by [Choate Labs](https://choatelabs.app/) — Precision software for modern markets.
