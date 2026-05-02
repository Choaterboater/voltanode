# Architecture Overview

## Frontend Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser / Client                          │
├─────────────────────────────────────────────────────────────┤
│  HashRouter → Routes → React.lazy() pages                   │
│                                                             │
│  ErrorBoundary → Suspense → PageLoader                      │
│                                                             │
│  Layout (Navbar + Header + Main + Footer)                   │
│    ├── Home (Dashboard)                                     │
│    ├── Watchlist                                            │
│    ├── Advisor                                              │
│    ├── PaperTrading                                         │
│    ├── Strategies                                           │
│    ├── Backtest                                             │
│    ├── Analytics                                            │
│    ├── BotLab                                               │
│    ├── News & Sentiment                                     │
│    ├── Settings                                             │
│    └── About                                                │
│                                                             │
│  Shared Components                                          │
│    ├── Layout, Navbar, Footer                               │
│    ├── MetricCard, Badge, StatusDot, DataTable              │
│    └── ErrorBoundary                                        │
│                                                             │
│  Charts: Recharts (AreaChart, PieChart, BarChart, Composed) │
│                                                             │
│  Data Layer                                                 │
│    ├── lib/api.ts     (centralized fetch + types)           │
│    ├── hooks/         (useAdvisor, useSettings, useApi)     │
│    ├── types/index.ts (TypeScript interfaces)               │
│    └── data/mockData.ts (static demo data fallback)         │
├─────────────────────────────────────────────────────────────┤
│  Tailwind CSS + Custom Theme Tokens                         │
│  Framer Motion (page transitions & stagger)                 │
│  Sonner (toast notifications)                               │
│  Lucide React (icons)                                       │
└─────────────────────────────────────────────────────────────┘
```

### Component Hierarchy

```
main.tsx
├── HashRouter
│   ├── Toaster (sonner)
│   └── App.tsx
│       └── ErrorBoundary
│           └── Suspense → PageLoader
│               └── Routes
│                   ├── /           → Home.tsx (Layout)
│                   ├── /watchlist  → Watchlist.tsx (Layout)
│                   ├── /advisor    → Advisor.tsx (Layout)
│                   ├── /paper      → PaperTrading.tsx (Layout)
│                   ├── /strategies → Strategies.tsx (Layout)
│                   ├── /backtest   → Backtest.tsx (Layout)
│                   ├── /analytics  → Analytics.tsx (Layout)
│                   ├── /bots       → BotLab.tsx (Layout)
│                   ├── /news       → NewsSentiment.tsx (Layout)
│                   ├── /settings   → Settings.tsx (Layout)
│                   └── /about      → About.tsx (Layout)
```

### State Management

- **No global state library** (Redux/Zustand not used)
- **Local React state** via `useState` for UI state
- **Backend API integration** via centralized `lib/api.ts` fetch functions
- **Hooks** for domain-specific data: `useAdvisor`, `useSettings`, `useApi`, `useDashboard`
- **Mock data fallback** in `useDashboard` for bots/equity curve when backend doesn't serve them

---

## Backend Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI Application                         │
├─────────────────────────────────────────────────────────────┤
│  Lifespan (startup / shutdown)                               │
│    ├── DataCache initialization                              │
│    ├── MarketData service                                    │
│    └── PaperTradingEngine initialization                     │
│                                                              │
│  Router Registration                                         │
│    ├── /portfolio   → portfolio.py                           │
│    ├── /orders      → orders.py                              │
│    ├── /strategies  → strategies.py                          │
│    ├── /trades      → trades.py                              │
│    ├── /backtest    → backtest.py                            │
│    ├── /market      → market.py                              │
│    ├── /advisor     → advisor.py                             │
│    ├── /settings    → settings.py                            │
│    ├── /news        → news.py                                │
│    └── /health, /engine/* (app-level)                        │
├─────────────────────────────────────────────────────────────┤
│  Core Modules                                                │
│    ├── bot/          → Engine, Portfolio, Orders, Risk       │
│    ├── strategies/   → 9 strategy implementations            │
│    ├── backtest/     → Runner, Metrics, Config               │
│    ├── data/         → Cache, Fetcher, Storage               │
│    ├── advisor/      → Analyzer, Indicators, Predictor       │
│    ├── analytics/    → Reports, Export, Records              │
│    ├── news/         → Fetcher, Sentiment (VADER + LLM)      │
│    ├── brokers/      → Alpaca, Mock adapters                 │
│    ├── safety/       → Kill switch, limits, notifier         │
│    ├── security/     → PBKDF2 encryption                     │
│    └── api/          → Routes, Pydantic Models               │
├─────────────────────────────────────────────────────────────┤
│  External APIs                                               │
│    ├── CoinGecko     (crypto prices & OHLCV)                 │
│    ├── Yahoo Finance (stock prices & OHLCV)                  │
│    ├── Alpaca        (news, live trading)                    │
│    └── Ollama        (local LLM for sentiment)               │
└─────────────────────────────────────────────────────────────┘
```

### File Structure

```
trading-bot-backend/
├── api/
│   ├── main.py              # FastAPI app factory & lifespan
│   ├── models.py            # Pydantic request/response schemas
│   └── routes/
│       ├── advisor.py       # AI symbol analysis
│       ├── backtest.py      # Backtest run & results
│       ├── market.py        # Price & OHLCV data
│       ├── news.py          # News fetch & sentiment
│       ├── orders.py        # Order placement & cancel
│       ├── portfolio.py     # Portfolio & positions
│       ├── settings.py      # Broker, live mode, safety
│       ├── strategies.py    # Strategy registration & toggle
│       └── trades.py        # Trade history & export
├── advisor/
│   ├── analyzer.py          # SymbolAnalyzer orchestrator
│   ├── indicators.py        # Technical indicator library
│   ├── models.py            # AnalysisResult dataclasses
│   ├── predictor.py         # Price target prediction
│   └── recommender.py       # Verdict & confidence engine
├── analytics/
│   ├── export.py            # CSV/JSON export
│   ├── records.py           # Trade record management
│   └── reports.py           # Daily report generation
├── backtest/
│   ├── engine.py            # BacktestRunner bar-by-bar
│   └── metrics.py           # BacktestMetrics calculations
├── bot/
│   ├── config.py            # Pydantic settings & enums
│   ├── engine.py            # PaperTradingEngine core
│   ├── orders.py            # Order, FillResult, ExecutionSimulator
│   ├── portfolio.py         # Portfolio & Position management
│   └── risk.py              # RiskManager & PositionSizer
├── brokers/
│   ├── alpaca.py            # Alpaca broker adapter
│   └── mock.py              # Mock/simulation broker
├── cli/
│   └── main.py              # Typer CLI entry point
├── data/
│   ├── cache.py             # In-memory + disk cache
│   ├── fetcher.py           # MarketData unified fetcher
│   └── storage.py           # Persistent storage helpers
├── news/
│   ├── fetcher.py           # Alpaca News API client
│   ├── models.py            # NewsArticle, SentimentResult
│   ├── sentiment.py         # VADER + LLM (Ollama/Claude/Kimi)
│   └── storage.py           # SQLite persistence
├── safety/
│   ├── limits.py            # Safety limits & daily tracker
│   ├── notifier.py          # SMTP email alerts
│   └── switch.py            # Kill switch
├── security/
│   └── encrypt.py           # PBKDF2-based encryption
├── strategies/
│   ├── __init__.py          # StrategyFactory & registry (9 strategies)
│   ├── base.py              # BaseStrategy ABC
│   ├── arbitrage.py
│   ├── breakout.py
│   ├── ensemble_ml.py
│   ├── grid.py
│   ├── macd.py
│   ├── mean_reversion.py
│   ├── momentum.py
│   └── news_sentiment.py    # Trading via news sentiment
├── tests/
│   ├── test_backtest.py
│   ├── test_engine.py
│   └── test_strategies.py
├── config.yaml
├── requirements.txt
└── run.py
```

---

## Key Design Decisions

1. **Lazy-loaded pages**: Each route is its own JS chunk via `React.lazy()` for faster initial load.

2. **ErrorBoundary**: Catches React render errors and shows a reload UI instead of a white screen.

3. **HashRouter**: Supports static file hosting without server-side rewrite rules.

4. **No ORM for portfolio**: Plain Python dataclasses for portfolio state. SQLite used for news, trades, and analytics.

5. **Strategy pattern**: All strategies inherit from `BaseStrategy` and register in `STRATEGY_REGISTRY`.

6. **Hybrid sentiment**: VADER (fast, local) for clear-cut headlines; Ollama LLM (smart, local) for ambiguous ones.

7. **Synthetic data fallback**: Market fetcher and advisor generate realistic synthetic data when external APIs fail.

8. **PBKDF2 encryption**: API keys are encrypted at rest with Fernet derived from `VOLTANODE_SECRET_KEY`.
