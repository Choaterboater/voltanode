# Crypto & Finance Paper Trading Bot Platform - Plan

## Overview
Build a full-stack paper trading platform with:
- Paper trading engine (no real money)
- Multiple trading algorithms/strategies
- Crypto and traditional finance assets
- Short selling, long positions, options scenarios
- Data collection and backtesting records
- Static trading records and performance analytics
- Modern React frontend dashboard

## Architecture
- **Frontend**: React + TypeScript + Tailwind + shadcn/ui dashboard
- **Backend**: Python FastAPI trading engine
- **Data**: SQLite for trade records, CSV/JSON for market data
- **Market Data**: Free APIs (CoinGecko for crypto, Yahoo Finance proxy for stocks)
- **Strategies**: Multiple algorithm implementations

## Stage 1 — Skill Loading & Design
- Load vibecoding-webapp-swarm and vibecoding-general-swarm
- Design system architecture
- Create database schema
- Plan trading algorithms and scenarios

## Stage 2 — Backend Core Engine (Python FastAPI)
Sub-agents in parallel:
- **Trading_Engine_Agent**: Core paper trading engine, portfolio, positions, P&L
- **Market_Data_Agent**: Data collection from CoinGecko/Yahoo, caching, historical data
- **Strategies_Agent**: Implement 6+ trading algorithms (momentum, mean reversion, arbitrage, grid, ML-signal, breakout)
- **Records_Agent**: Trade logging, performance analytics, static records export

## Stage 3 — Frontend Dashboard (React)
- **Dashboard_Agent**: Main trading dashboard UI
- **Charts_Agent**: Recharts/trading view charts, performance visualization
- **Scenarios_Agent**: Different use case pages (shorts, crypto, stocks, backtest)

## Stage 4 — Integration & Testing
- Connect frontend to backend
- Test paper trading scenarios
- Validate all strategies work in paper mode
- Build and deploy

## Stage 5 — Deployment
- Deploy website
- Final testing

## Key Features
1. Paper trading accounts with virtual balances
2. Real-time market data (crypto via CoinGecko, stocks via Yahoo)
3. 6+ Trading algorithms:
   - Momentum/Trend Following
   - Mean Reversion
   - Grid Trading
   - Breakout Detection
   - Arbitrage Scanner
   - RSI/MACD Signal Bot
4. Scenario modes:
   - Long positions
   - Short selling (paper)
   - Crypto spot trading
   - Multi-asset portfolio
   - Backtesting mode
5. Data collection & static records:
   - Trade history CSV export
   - Performance metrics (Sharpe, win rate, P&L)
   - Algorithm comparison reports
   - Daily portfolio snapshots
6. Frontend pages:
   - Dashboard overview
   - Active bots & algorithms
   - Market data view
   - Trade history & records
   - Backtest lab
   - Settings & paper account config

## Deliverables
- /mnt/agents/output/trading-bot/ (full source code)
- Deployed website URL
- README with setup instructions
