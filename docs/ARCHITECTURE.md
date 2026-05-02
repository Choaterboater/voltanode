# Architecture Overview

## Frontend Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Browser / Client                    │
├─────────────────────────────────────────────────────┤
│  HashRouter  →  Routes  →  Page Components         │
│                                                    │
│  Layout (Navbar + Header + Main + Footer)         │
│    ├── Home (Dashboard)                             │
│    ├── PaperTrading                                 │
│    ├── Strategies                                   │
│    ├── Backtest                                     │
│    ├── Analytics                                    │
│    └── BotLab                                       │
│                                                    │
│  Shared Components                                  │
│    ├── MetricCard, Badge, StatusDot, DataTable      │
│    └── Recharts (AreaChart, PieChart, LineChart)    │
│                                                    │
│  Data Layer                                         │
│    ├── mockData.ts (static demo data)               │
│    └── types/index.ts (TypeScript interfaces)       │
├─────────────────────────────────────────────────────┤
│  Tailwind CSS  +  Custom Theme Tokens                │
│  Framer Motion (page transitions & stagger)         │
└─────────────────────────────────────────────────────┘
```

### Component Hierarchy

```
App.tsx
└── HashRouter
    └── Routes
        ├── /           → Home.tsx (Layout)
        ├── /paper      → PaperTrading.tsx (Layout)
        ├── /strategies → Strategies.tsx (Layout)
        ├── /backtest   → Backtest.tsx (Layout)
        ├── /analytics  → Analytics.tsx (Layout)
        └── /bots       → BotLab.tsx (Layout)

Layout.tsx
├── Navbar.tsx
│   ├── Mobile toggle button
│   ├── Overlay (mobile)
│   └── Sidebar nav (NavLink items)
├── Header (title + rightContent slot)
├── <main> (page content)
└── Footer.tsx
```

### State Management

- **No global state library** (Redux/Zustand not used)
- **Local React state** via `useState` for UI state (time ranges, mobile menu, view toggles)
- **Mock data** served statically from `src/data/mockData.ts`
- **Future**: Backend API integration via React Query or SWR recommended

### Data Flow

1. `mockData.ts` exports typed static arrays/objects
2. Page components import the data they need
3. Components compute derived values (formatters, filters) in render
4. Charts receive data directly via Recharts `<ResponsiveContainer>`
5. No async data fetching in the current build

## Backend Architecture

```
┌─────────────────────────────────────────────────────┐
│                  FastAPI Application                 │
├─────────────────────────────────────────────────────┤
│  Lifespan (startup / shutdown)                       │
│    ├── DataCache initialization                      │
│    ├── MarketData service                            │
│    └── PaperTradingEngine initialization             │
│                                                      │
│  Router Registration                                 │
│    ├── /portfolio   → portfolio.py                   │
│    ├── /strategies  → strategies.py                  │
│    ├── /trades      → trades.py                      │
│    ├── /backtest    → backtest.py                    │
│    ├── /market      → market.py                      │
│    ├── /advisor     → advisor.py                     │
│    └── /health, /engine/* (app-level)                │
├─────────────────────────────────────────────────────┤
│  Core Modules                                        │
│    ├── bot/          → Engine, Portfolio, Orders, Risk│
│    ├── strategies/   → 7 strategy implementations     │
│    ├── backtest/     → Runner, Metrics, Config       │
│    ├── data/         → Cache, Fetcher, Storage       │
│    ├── advisor/      → Analyzer, Indicators, Predictor│
│    ├── analytics/    → Reports, Export, Records      │
│    └── api/          → Routes, Pydantic Models       │
├─────────────────────────────────────────────────────┤
│  External APIs                                       │
│    ├── CoinGecko (crypto prices & OHLCV)            │
│    └── Yahoo Finance (stock prices & OHLCV)           │
└─────────────────────────────────────────────────────┘
```

### File Structure Tree

```
trading-bot-backend/
├── api/
│   ├── __init__.py
│   ├── main.py              # FastAPI app factory & lifespan
│   ├── models.py            # Pydantic request/response schemas
│   └── routes/
│       ├── __init__.py
│       ├── advisor.py       # AI symbol analysis endpoints
│       ├── backtest.py      # Backtest run & results endpoints
│       ├── market.py        # Price & OHLCV data endpoints
│       ├── portfolio.py     # Portfolio & positions endpoints
│       ├── strategies.py    # Strategy registration & toggle
│       └── trades.py        # Trade history & export
├── advisor/
│   ├── analyzer.py          # SymbolAnalyzer orchestrator
│   ├── indicators.py        # Technical indicator library
│   ├── models.py            # AnalysisResult dataclasses
│   ├── predictor.py         # Price target prediction
│   └── recommender.py       # Verdict & confidence engine
├── analytics/
│   ├── export.py            # CSV/JSON export utilities
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
├── cli/
│   └── main.py              # Typer CLI entry point
├── data/
│   ├── cache.py             # In-memory + disk cache
│   ├── fetcher.py           # MarketData unified fetcher
│   └── storage.py           # Persistent storage helpers
├── strategies/
│   ├── __init__.py          # StrategyFactory & registry
│   ├── base.py              # BaseStrategy ABC
│   ├── momentum.py          # Momentum strategy
│   ├── mean_reversion.py    # Mean Reversion strategy
│   ├── grid.py              # Grid Trading strategy
│   ├── breakout.py          # Breakout strategy
│   ├── macd.py              # MACD strategy
│   ├── arbitrage.py         # Arbitrage strategy
│   └── ensemble_ml.py       # ML Ensemble strategy
├── tests/
│   ├── test_backtest.py
│   ├── test_engine.py
│   └── test_strategies.py
├── config.yaml              # Default configuration
├── requirements.txt         # Python dependencies
└── run.py                   # Application entry point
```

## Key Design Decisions

1. **Static mock data in frontend**: The current build uses fully static TypeScript data for rapid UI iteration. Future iterations should replace this with API calls to the backend.

2. **HashRouter**: Used instead of BrowserRouter to support static file hosting (e.g., GitHub Pages, S3) without server-side rewrite rules.

3. **No ORM for portfolio**: The backend uses plain Python dataclasses and dictionaries for portfolio state, avoiding SQLAlchemy complexity for the demo phase. Persistence can be added via the `data/storage.py` module.

4. **Strategy pattern**: All trading strategies inherit from `BaseStrategy` and are registered in `STRATEGY_REGISTRY`. The factory function enables runtime strategy instantiation by name.

5. **Synthetic data fallback**: Both the market fetcher and advisor analyzer generate realistic synthetic OHLCV data when external APIs fail, ensuring the UI never crashes due to network issues.
