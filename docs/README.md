# VoltaNode

A [Choate Labs](https://choatelabs.app/) product.

VoltaNode is a full-stack paper trading platform that enables developers and traders to simulate crypto and stock trading strategies in a risk-free environment. The application features a dark-themed React dashboard for visualizing portfolio performance, managing trading bots, running backtests, and analyzing market data — all backed by a Python FastAPI backend with integrated strategy engines, risk management, and an AI-powered trading advisor.

## Key Features

- **Dashboard Overview**: Real-time portfolio equity curve, asset allocation pie charts, active bot cards, market ticker tape, and system alerts
- **Paper Trading**: Virtual order execution with realistic slippage, fees, and multi-account portfolio tracking
- **Strategy Library**: 7 built-in strategies including Momentum, Mean Reversion, Grid Trading, Breakout, MACD, Arbitrage, and ML Ensemble
- **Backtest Engine**: Bar-by-bar backtesting with walk-forward analysis, equity curves, and comprehensive performance metrics (Sharpe, Sortino, Calmar, profit factor)
- **AI Trading Advisor**: Symbol analysis with 18 technical indicators, price targets, risk assessment, and position sizing recommendations
- **Bot Lab**: Manage, start, pause, and monitor automated trading bots with live P&L sparklines
- **Market Data**: Unified fetcher supporting CoinGecko (crypto) and Yahoo Finance (stocks) with intelligent caching
- **Analytics & Reporting**: Trade history, CSV export, daily reports, and portfolio snapshots

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend | React | 19 |
| Frontend | TypeScript | 5.x |
| Frontend | Vite | 7.2.4 |
| Frontend | Tailwind CSS | 3.4.19 |
| Frontend | Recharts | latest |
| Frontend | Framer Motion | latest |
| Frontend | Lucide React | latest |
| Backend | Python | 3.11+ |
| Backend | FastAPI | 0.104+ |
| Backend | Uvicorn | 0.24+ |
| Backend | Pydantic | 2.5+ |
| Backend | Pandas | 2.1+ |
| Backend | NumPy | 1.26+ |
| Backend | scikit-learn | 1.3+ |
| Backend | yfinance | 0.2.28+ |
| Backend | SQLAlchemy | 2.0+ |

## Screenshot Descriptions

### Dashboard (`/`)
A dark-themed analytics hub featuring four metric cards (Total Virtual Balance, Today's P&L, Active Positions, Win Rate), a large portfolio equity area chart, asset allocation pie chart, active bot cards with sparklines, an animated market ticker tape, recent trades table, and system alerts panel.

### AI Advisor (`/advisor`)
Search any stock or crypto ticker to get a professional-grade BUY/SELL/HOLD recommendation. Features a big verdict card with confidence percentage, predicted price targets (entry zone, take-profit, stop-loss), 18 technical indicator readings, signal strength meter, risk assessment, and a price chart with prediction overlay.

### Paper Trading (`/paper`)
Virtual order execution interface with order entry forms, open positions table with live P&L, account activity log, and paper balance tracking.

### Strategies (`/strategies`)
Strategy library with 7 filterable strategy cards, detail drawers with parameter editors, performance charts, and side-by-side strategy comparison.

### Backtest (`/backtest`)
Backtest configuration and results dashboard with equity curve charts, monthly returns heatmap, trade history table, and comprehensive performance metrics.

### Analytics (`/analytics`)
Detailed trade analytics with sortable data tables, pagination, CSV export, win/loss distribution charts, and monthly report cards.

### Bot Lab (`/bots`)
Bot management interface with list/grid toggle, creation modals, detail drawers with terminal-style logs, and live performance monitoring.

## Live URL

The frontend is served via Vite dev server at `http://localhost:3000` (or the configured port). The backend API runs at `http://localhost:8000` with Swagger UI at `http://localhost:8000/docs`.

---

Built by [Choate Labs](https://choatelabs.app/) — Precision software for modern markets.
