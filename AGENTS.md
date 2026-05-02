# VoltaNode — Agent Instructions

> This file contains context for AI agents working on the VoltaNode codebase. Human contributors should see `README.md` and `docs/` instead.

## Project Overview

VoltaNode is a full-stack paper trading platform by Choate Labs. React 19 + TypeScript frontend, Python 3.11 + FastAPI backend.

## Directory Structure

```
D:\VoltaNode/
├── app/                    # React frontend (Vite, Tailwind, shadcn/ui)
│   ├── src/pages/          # 11 pages (Home, Watchlist, Advisor, Paper, Strategies,
│   │                       #   Backtest, Analytics, BotLab, NewsSentiment, Settings, About)
│   ├── src/components/     # Layout, Navbar, MetricCard, Badge, DataTable, ErrorBoundary
│   ├── src/hooks/          # useAdvisor, useApi, useDashboard, useSettings
│   ├── src/lib/api.ts      # Centralized fetch functions + types
│   └── src/types/index.ts  # TypeScript interfaces
├── trading-bot-backend/    # Python FastAPI backend
│   ├── api/routes/         # 10 routers (portfolio, orders, strategies, trades,
│   │                       #   backtest, market, advisor, settings, news, health/engine)
│   ├── strategies/         # 9 strategies (momentum, mean_reversion, grid, breakout,
│   │                       #   macd, arbitrage, ensemble_ml, news_sentiment)
│   ├── news/               # Alpaca fetcher, VADER + LLM sentiment, SQLite storage
│   ├── brokers/            # Alpaca adapter, Mock adapter
│   ├── safety/             # Kill switch, limits, SMTP notifier
│   ├── security/           # PBKDF2 encryption
│   └── tests/              # pytest suite (45 tests)
├── docs/                   # API.md, ARCHITECTURE.md, README.md, DEPLOYMENT.md, SETUP.md
└── newbuild/               # Staging area — near-duplicates of docs and app. NOT the source of truth.
```

## Source of Truth

- **Frontend code**: `app/src/` (NOT `newbuild/app/src/`)
- **Backend code**: `trading-bot-backend/` (NOT `newbuild/trading-bot-backend/`)
- **Documentation**: `docs/` and root `.md` files (NOT `newbuild/docs/`)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, TypeScript 5, Vite 7, Tailwind CSS 3.4 |
| Frontend | Recharts, Framer Motion, Sonner (toasts), Lucide React |
| Backend | Python 3.11+, FastAPI, Pydantic v2, Uvicorn |
| Backend | Pandas, NumPy, scikit-learn, yfinance, vaderSentiment |
| Database | SQLite (news, trades, analytics) |
| LLM | Ollama (local), optional: Kimi, Claude, OpenAI, OpenRouter |
| External | CoinGecko, Yahoo Finance, Alpaca |

## Frontend Patterns

- **Routing**: HashRouter in `main.tsx`. All routes lazy-loaded via `React.lazy()`.
- **Layout**: Every page wrapped in `<Layout title="...">` with Navbar sidebar.
- **API**: Use `lib/api.ts` for new endpoints. Don't create duplicate fetch logic in hooks.
- **Styling**: Tailwind with custom color tokens (`bg-base`, `bg-surface`, `accent-cyan`, etc.).
- **Icons**: Lucide React only.
- **Toasts**: Use `sonner`'s `toast.success()` / `toast.error()`.

## Backend Patterns

- **Routers**: Add new endpoints in `api/routes/`, register in `api/main.py`.
- **Models**: Use Pydantic v2 in `api/models.py` or inline in route files.
- **Strategies**: Inherit from `BaseStrategy`, register in `STRATEGY_REGISTRY`.
- **Encryption**: Use `security/encrypt.py` for API keys (PBKDF2 + Fernet).
- **Logging**: Structured JSON logging via `bot/logging_config.py`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VOLTANODE_SECRET_KEY` | Yes | Fernet key for API encryption |
| `ALPACA_API_KEY` | No | For news fetching |
| `ALPACA_SECRET_KEY` | No | For news fetching |
| `LLM_PROVIDER` | No | `ollama`, `kimi`, `claude`, `openai` |
| `LLM_MODEL` | No | e.g. `llama3.2:3b` |
| `LLM_API_KEY` | No | Not needed for Ollama |
| `SENTIMENT_HYBRID_MODE` | No | `true`/`false` — default `true` |
| `SENTIMENT_HYBRID_THRESHOLD` | No | Default `0.6` |

## Running Locally

```bash
# Backend
cd trading-bot-backend
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd app
npm run dev -- --port 3000
```

## Testing

```bash
# Backend
cd trading-bot-backend
pytest tests/ -x -q

# Frontend
cd app
npm run build
```

## Git Hygiene

- Do NOT commit `__pycache__/`, `.db` files, `.env`, or `node_modules/`.
- Do NOT commit the ZIP file at root.
- The `data/cache/` directory is gitignored but may show up as untracked.
- `newbuild/` is a staging area — do not treat it as source of truth.

## Common Gotchas

1. **Ollama does not need an API key** — `LLM_API_KEY` can be empty for local Ollama.
2. **VADER is bad at financial text** — it scores financial headlines as neutral. The hybrid system falls back to LLM automatically.
3. **Two frontend copies exist** — `app/` is the working directory, `newbuild/app/` is a stale snapshot.
4. **Backend runs on `:8000`**, frontend dev server proxies `/api` to it via `vite.config.ts`.
5. **News fetch requires Alpaca keys** — without them, `/news/fetch` returns 0 articles, but `/news/analyze` works with any headline.
