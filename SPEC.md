# Paper Trading Bot Platform — Backend Specification

**Version:** 1.0.0  
**Language:** Python 3.11+  
**Pattern:** Modular, event-driven with plugin strategies  
**Database:** SQLite + SQLAlchemy ORM  
**Config:** Pydantic v2 Settings  
**API:** FastAPI  
**CLI:** Typer  
**Logging:** Structured JSON (python-json-logger)  
**Testing:** pytest + fixtures  

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Module Specifications](#2-module-specifications)
   - 2.1 Paper Trading Engine
   - 2.2 Market Data Collection
   - 2.3 Trading Strategies
   - 2.4 Backtesting Engine
   - 2.5 Data Records & Analytics
   - 2.6 Risk Management
3. [API Specification](#3-api-specification)
4. [CLI Specification](#4-cli-specification)
5. [Database Schema](#5-database-schema)
6. [Configuration Schema](#6-configuration-schema)
7. [File Structure](#7-file-structure)
8. [Interface Contracts](#8-interface-contracts)
9. [Data Schemas & Types](#9-data-schemas--types)
10. [Testing Strategy](#10-testing-strategy)
11. [Scenarios](#11-scenarios)
12. [Appendix](#12-appendix)

---

## 1. Architecture Overview

### 1.1 High-Level Design

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PAPER TRADING BOT PLATFORM                   │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌──────────┐ │
│  │   FastAPI   │   │   Typer     │   │  Config     │   │ Logging  │ │
│  │   Routes    │   │   CLI       │   │  (Pydantic) │   │ (JSON)   │ │
│  └──────┬──────┘   └──────┬──────┘   └─────────────┘   └──────────┘ │
│         │                 │                                        │
│  ┌──────▼─────────────────▼──────┐                                 │
│  │      PaperTradingEngine        │◄──── Event-driven tick loop    │
│  │  ┌──────────┐  ┌──────────┐    │                                 │
│  │  │Portfolio │  │  Orders  │    │                                 │
│  │  │ Manager  │  │  Engine  │    │                                 │
│  │  └──────────┘  └──────────┘    │                                 │
│  └──────────┬────────────────────┘                                 │
│             │                                                        │
│  ┌──────────▼────────────────────┐   ┌────────────────────────┐  │
│  │     Strategy Plugin System      │   │     RiskManager        │  │
│  │  ┌────────┐ ┌────────┐ ┌─────┐ │   │  - Position sizing     │  │
│  │  │Momentum│ │MeanRev │ │Grid │ │   │  - Stop-loss/take-prof │  │
│  │  │Breakout│ │Arbitrge│ │MACD │ │   │  - Max drawdown alert  │  │
│  │  │Ensemble│ │  ...   │ │     │ │   │  - Exposure limits     │  │
│  │  └────────┘ └────────┘ └─────┘ │   └────────────────────────┘  │
│  └─────────────────────────────────┘                                │
│             │                                                        │
│  ┌──────────▼────────────────────┐   ┌────────────────────────┐  │
│  │      MarketData Service        │   │     BacktestEngine     │  │
│  │  - CoinGecko (crypto)          │   │  - Walk-forward        │  │
│  │  - Yahoo Finance (stocks)      │   │  - Sharpe, drawdown    │  │
│  │  - SQLite cache                │   │  - Equity curve export   │  │
│  │  - OHLCV streaming             │   │  - Trade log CSV         │  │
│  └─────────────────────────────────┘   └────────────────────────┘  │
│             │                                                        │
│  ┌──────────▼────────────────────┐                                 │
│  │    SQLite + Analytics Layer    │                                 │
│  │  ┌────────┐ ┌────────┐ ┌────┐ │                                 │
│  │  │Trades  │ │Portfolio│ │Perf│ │                                 │
│  │  │Positions│ │Snapshots│ │Reports│                                │
│  │  └────────┘ └────────┘ └────┘ │                                 │
│  └─────────────────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Design Patterns

| Pattern | Application |
|---------|-------------|
| **Strategy Pattern** | All trading algorithms inherit from `BaseStrategy` and are loaded as plugins |
| **Observer Pattern** | `PaperEngine` emits events (tick, fill, price_update) that strategies observe |
| **Repository Pattern** | Database access abstracted through SQLAlchemy repositories in `analytics/records.py` |
| **Factory Pattern** | `StrategyFactory` instantiates strategies by name from config |
| **Singleton** | `MarketData` service and `PaperEngine` are singletons within the async context |
| **Command Pattern** | CLI commands and API routes both delegate to engine commands |

### 1.3 Tech Stack

| Layer | Library |
|-------|---------|
| Web Framework | `fastapi` + `uvicorn` |
| CLI | `typer` |
| ORM / DB | `sqlalchemy` (SQLite) |
| Data / ML | `pandas`, `numpy`, `ta-lib` (or `pandas-ta`) |
| Validation | `pydantic` v2 |
| HTTP Client | `httpx` (async) |
| Finance API | `yfinance` (Yahoo), `httpx` → CoinGecko REST |
| Config | `pydantic-settings`, `pyyaml` |
| Testing | `pytest`, `pytest-asyncio`, `factory-boy` |
| Logging | `python-json-logger`, `structlog` |

### 1.4 Async Strategy

- Market data fetching: **async** (`httpx.AsyncClient`)
- Price streaming simulation: **async** generator with `asyncio`
- FastAPI endpoints: **async**
- Strategy `on_tick()`: **sync** (compute-bound, runs in thread pool if needed)
- Database writes: **sync** SQLAlchemy within `async` endpoints (or async SA if configured)
- Order execution: **sync** within engine tick handler

### 1.5 Event Loop

```
Tick Loop (async)
  ├─ Fetch prices from MarketData
  ├─ For each active strategy:
  │   ├─ strategy.on_tick(price_data)
  │   ├─ signal = strategy.generate_signal(price_data)
  │   └─ if signal: engine.submit_order(signal.to_order())
  ├─ engine.process_orders()
  ├─ engine.update_positions()
  ├─ risk_manager.check_limits(portfolio)
  └─ analytics.snapshot(portfolio)
```

---

## 2. Module Specifications

---

### 2.1 Paper Trading Engine (`bot/`)

#### 2.1.1 `engine.py` — PaperTradingEngine

The core orchestrator. Maintains the event loop, manages the order book, and coordinates strategies, portfolio, and risk.

```python
class PaperTradingEngine:
    """Core paper trading engine with multi-account support."""

    def __init__(
        self,
        config: BotConfig,
        market_data: MarketData,
        risk_manager: RiskManager,
        db_session: Session | None = None,
    ) -> None: ...

    # ── Lifecycle ──
    def register_strategy(self, strategy: BaseStrategy, account_id: str = "default") -> None:
        """Attach a strategy to an account. Strategies are isolated per account."""

    def start(self) -> None:
        """Begin the tick loop. Blocking in sync mode; coroutine in async mode."""

    def stop(self) -> None:
        """Gracefully stop the tick loop and flush state."""

    def reset(self, account_id: str | None = None) -> None:
        """Reset all state (or single account). Useful for tests."""

    # ── Order Handling ──
    def submit_order(self, order: Order, account_id: str = "default") -> str:
        """Submit an order. Returns order_id."""

    def cancel_order(self, order_id: str, account_id: str = "default") -> bool:
        """Cancel a pending order. Returns success."""

    def get_order_status(self, order_id: str, account_id: str = "default") -> OrderStatus:
        """Return status of an order."""

    def execute_order(self, order: Order, current_price: float) -> FillResult:
        """
        Simulate order execution with slippage and fees.
        Called internally when market conditions match order criteria.
        """

    # ── Portfolio ──
    def get_portfolio(self, account_id: str = "default") -> Portfolio:
        """Return current portfolio for an account."""

    def get_all_portfolios(self) -> dict[str, Portfolio]:
        """Return all account portfolios."""

    # ── Events ──
    def on_tick(self, tick: TickData) -> None:
        """Process a price tick: update positions, check SL/TP, notify strategies."""

    def on_fill(self, fill: FillResult) -> None:
        """Callback when an order is filled. Records trade, updates portfolio."""
```

#### 2.1.2 `portfolio.py` — Portfolio & Position Management

```python
@dataclass
class Position:
    symbol: str
    side: PositionSide          # LONG | SHORT
    size: float                 # absolute quantity
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    opened_at: datetime
    # computed property: market_value = size * current_price

class Portfolio:
    """Virtual portfolio for a single account."""

    def __init__(self, account_id: str, initial_balance: dict[str, float]) -> None:
        """initial_balance: {"USDT": 10000.0, "USD": 50000.0}"""

    # ── Balance ──
    def deposit(self, asset: str, amount: float) -> None: ...
    def withdraw(self, asset: str, amount: float) -> bool: ...
    def get_balance(self, asset: str) -> float: ...
    def get_total_equity(self, prices: dict[str, float]) -> float: ...

    # ── Positions ──
    def open_position(self, symbol: str, side: PositionSide, size: float, price: float) -> Position: ...
    def close_position(self, symbol: str, price: float) -> tuple[Position, float]:
        """Close position at price. Returns (closed_position, realized_pnl)."""

    def update_position_price(self, symbol: str, current_price: float) -> None: ...
    def get_position(self, symbol: str) -> Position | None: ...
    def get_all_positions(self) -> list[Position]: ...
    def get_exposure(self, asset: str) -> float: ...

    # ── Snapshots ──
    def snapshot(self, timestamp: datetime) -> PortfolioSnapshot: ...
```

#### 2.1.3 `orders.py` — Order Types & Execution

```python
class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    STOP_LIMIT = "stop_limit"

class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"

@dataclass
class Order:
    id: str                      # UUID4
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None          # limit price
    stop_price: float | None       # trigger for stop / stop-limit
    time_in_force: str = "GTC"   # GTC, IOC, FOK
    created_at: datetime
    strategy_id: str | None        # originating strategy
    account_id: str = "default"

@dataclass
class FillResult:
    order_id: str
    symbol: str
    filled_qty: float
    filled_price: float
    fee: float
    slippage: float
    timestamp: datetime
    side: OrderSide
    realized_pnl: float | None   # for closing orders

class ExecutionSimulator:
    """Simulates realistic execution conditions."""

    def __init__(self, fee_rate: float = 0.001, slippage_model: str = "fixed") -> None: ...

    def apply_slippage(self, price: float, side: OrderSide, volatility: float | None = None) -> float:
        """Return price after slippage. Models: fixed, proportional, volatility-based."""

    def calculate_fee(self, notional: float) -> float:
        """Return trading fee. Supports maker/taker if configured."""

    def execute(self, order: Order, current_price: float, market_depth: dict | None = None) -> FillResult:
        """Execute an order at current market conditions."""
```

#### 2.1.4 `risk.py` — Risk Management

```python
class RiskManager:
    """Central risk controller. Blocks/modifies orders that violate rules."""

    def __init__(self, config: RiskConfig) -> None: ...

    # ── Position Sizing ──
    def calculate_position_size(
        self,
        method: SizingMethod,
        portfolio: Portfolio,
        signal_strength: float,
        entry_price: float,
        stop_price: float | None = None,
    ) -> float:
        """
        Methods:
        - FIXED: fixed quantity (e.g., 0.1 BTC)
        - PERCENTAGE: % of equity per trade (e.g., 2%)
        - KELLY: Kelly criterion fraction
        - VOLATILITY: ATR-based sizing
        """

    # ── Pre-trade Checks ──
    def check_order(self, order: Order, portfolio: Portfolio) -> RiskCheckResult:
        """Returns (allowed: bool, modified_order: Order | None, reason: str | None)"""

    def check_portfolio_limits(self, portfolio: Portfolio) -> list[RiskAlert]:
        """Check aggregate exposure, concentration, drawdown."""

    # ── Trailing & Brackets ──
    def update_trailing_stops(self, portfolio: Portfolio, current_prices: dict[str, float]) -> list[Order]:
        """Generate stop-loss orders for trailing stop logic."""

@dataclass
class RiskCheckResult:
    allowed: bool
    order: Order | None
    reason: str | None

@dataclass
class RiskAlert:
    level: str          # "warning" | "critical"
    rule: str
    message: str
    timestamp: datetime
```

#### 2.1.5 `config.py` — Pydantic Settings

```python
class BotConfig(BaseSettings):
    """Root configuration object. Loaded from config.yaml + env vars."""

    # General
    app_name: str = "PaperTradingBot"
    log_level: str = "INFO"
    json_logs: bool = True

    # Engine
    tick_interval_seconds: float = 5.0
    max_accounts: int = 10

    # Market Data
    coingecko_enabled: bool = True
    yfinance_enabled: bool = True
    cache_dir: str = "./data/cache"
    default_timeframe: str = "1h"

    # Risk
    risk: RiskConfig = RiskConfig()

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    model_config = SettingsConfigDict(env_prefix="BOT_", yaml_file="config.yaml")

class RiskConfig(BaseModel):
    max_drawdown_pct: float = 0.10          # 10% max drawdown
    max_position_size_pct: float = 0.20     # 20% of equity per position
    max_exposure_per_asset_pct: float = 0.30
    default_stop_loss_pct: float = 0.02     # 2%
    default_take_profit_pct: float = 0.06   # 6%
    position_sizing_method: SizingMethod = SizingMethod.PERCENTAGE
    position_sizing_value: float = 0.02     # 2% per trade
    fee_rate: float = 0.001                 # 0.1%
    slippage_model: str = "fixed"
    slippage_bps: float = 5.0               # 5 basis points
```

---

### 2.2 Market Data Collection (`data/`)

#### 2.2.1 `fetcher.py` — MarketData Service

```python
class MarketData:
    """Unified market data fetcher with caching. Singleton per process."""

    def __init__(self, cache: DataCache, config: BotConfig) -> None: ...

    # ── Crypto (CoinGecko) ──
    async def get_crypto_price(self, symbol: str, vs_currency: str = "usd") -> float:
        """Fetch current price from CoinGecko. E.g., symbol='bitcoin'."""

    async def get_crypto_ohlcv(
        self,
        symbol: str,
        vs_currency: str = "usd",
        days: int = 30,
        interval: str = "daily",
    ) -> pd.DataFrame:
        """Return OHLCV DataFrame with columns: [timestamp, open, high, low, close, volume]."""

    async def get_crypto_market_chart(
        self, symbol: str, vs_currency: str = "usd", days: int = 30
    ) -> pd.DataFrame:
        """Full market chart: prices, market_caps, total_volumes."""

    # ── Stocks / Forex (Yahoo Finance) ──
    def get_stock_ohlcv(
        self, ticker: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        """Sync fetch via yfinance. Cached to SQLite."""

    def get_stock_price(self, ticker: str) -> float: ...

    # ── Generic ──
    async def get_price(self, symbol: str, asset_class: AssetClass) -> float:
        """Route to correct provider based on asset class."""

    async def get_ohlcv(
        self, symbol: str, asset_class: AssetClass, timeframe: str = "1d", limit: int = 500
    ) -> pd.DataFrame:
        """Unified OHLCV fetcher with caching."""

    # ── Streaming Simulation ──
    async def price_stream(self, symbols: list[str], interval_sec: float = 5.0) -> AsyncGenerator[TickData, None]:
        """Async generator that yields simulated real-time ticks."""
```

#### 2.2.2 `storage.py` — SQLAlchemy ORM Models

```python
# Core entities
class OHLCVRecord(Base):
    __tablename__ = "ohlcv"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    asset_class: Mapped[str] = mapped_column(String(16))
    timeframe: Mapped[str] = mapped_column(String(8))
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float]
    high: Mapped[float]
    low: Mapped[float]
    close: Mapped[float]
    volume: Mapped[float]
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "timestamp"),)

class PriceTick(Base):
    __tablename__ = "price_ticks"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    price: Mapped[float]
    bid: Mapped[float | None]
    ask: Mapped[float | None]
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
```

#### 2.2.3 `cache.py` — DataCache

```python
class DataCache:
    """Multi-layer cache: memory (LRU) → SQLite → CSV fallback."""

    def __init__(self, db_session: Session, cache_dir: str) -> None: ...

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame | None: ...
    def store_ohlcv(self, df: pd.DataFrame, symbol: str, timeframe: str) -> None: ...
    def get_price(self, symbol: str) -> float | None: ...
    def store_price(self, symbol: str, price: float, timestamp: datetime) -> None: ...
    def export_to_csv(self, symbol: str, timeframe: str, path: str) -> None: ...
    def clear_cache(self, symbol: str | None = None) -> None: ...
```

---

### 2.3 Trading Strategies (`strategies/`)

#### 2.3.1 `base.py` — Abstract Strategy Class

```python
class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"

@dataclass
class Signal:
    strategy_id: str
    symbol: str
    signal_type: SignalType
    confidence: float            # 0.0 – 1.0
    timestamp: datetime
    metadata: dict[str, Any]     # strategy-specific context
    suggested_size: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None

    def to_order(self, account_id: str = "default") -> Order | None:
        """Convert signal to an Order if applicable."""

class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    def __init__(self, strategy_id: str, config: dict[str, Any]) -> None:
        self.strategy_id = strategy_id
        self.config = config
        self.is_active = True
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_pnl = 0.0
        self._history: list[Signal] = []

    # ── Required ──
    @abstractmethod
    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """
        Analyze data and emit a trading signal.
        data: OHLCV DataFrame up to current point.
        Returns Signal with confidence and metadata.
        """

    # ── Lifecycle ──
    def on_tick(self, tick: TickData, portfolio: Portfolio) -> Signal | None:
        """
        Called on every price tick. Default: fetches OHLCV and calls generate_signal.
        Override for tick-level strategies (e.g., order book strategies).
        """

    def on_fill(self, fill: FillResult, portfolio: Portfolio) -> None:
        """Callback when an order from this strategy is filled."""

    def on_init(self, market_data: MarketData) -> None:
        """Pre-load historical data, warm up indicators."""

    def on_stop(self) -> None:
        """Cleanup, persist state."""

    # ── Metrics ──
    def get_metrics(self) -> StrategyMetrics:
        """Return performance metrics for this strategy."""

    def reset(self) -> None:
        """Reset internal state for backtesting or restart."""

    # ── Helpers ──
    def _get_ohlcv(self, market_data: MarketData, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Fetch OHLCV with caching."""

    def _record_signal(self, signal: Signal) -> None: ...


@dataclass
class StrategyMetrics:
    strategy_id: str
    total_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    sharpe_ratio: float | None
    max_drawdown: float
    current_streak: int
    total_pnl: float
```

#### 2.3.2 Strategy Implementations

**`momentum.py` — MomentumStrategy**
```python
class MomentumStrategy(BaseStrategy):
    """EMA crossover trend following."""

    DEFAULT_CONFIG = {
        "fast_ema": 12,
        "slow_ema": 26,
        "signal_ema": 9,
        "trend_filter_ema": 200,
    }

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """
        Buy when fast EMA crosses above slow EMA AND price > trend_filter_ema.
        Sell when fast crosses below.
        Confidence based on momentum strength (distance between EMAs / volatility).
        """
```

**`mean_reversion.py` — MeanReversionStrategy**
```python
class MeanReversionStrategy(BaseStrategy):
    """RSI + Bollinger Bands mean reversion."""

    DEFAULT_CONFIG = {
        "rsi_period": 14,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
        "bb_period": 20,
        "bb_std": 2.0,
    }

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """
        Buy when RSI < oversold AND price touches lower BB.
        Sell when RSI > overbought AND price touches upper BB.
        """
```

**`grid.py` — GridStrategy**
```python
class GridStrategy(BaseStrategy):
    """Grid trading for ranging markets."""

    DEFAULT_CONFIG = {
        "grid_levels": 10,
        "grid_spacing_pct": 0.01,       # 1% between grids
        "upper_price": float | None,    # auto if None
        "lower_price": float | None,
        "quantity_per_grid": 0.01,
    }

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """
        Place buy orders on grid levels below price, sell orders above.
        On tick: if price crosses a grid level, generate opposite-side order for next grid.
        """

    def on_tick(self, tick: TickData, portfolio: Portfolio) -> Signal | None:
        """Grid requires tick-level price monitoring, not just bar close."""
```

**`breakout.py` — BreakoutStrategy**
```python
class BreakoutStrategy(BaseStrategy):
    """Support/resistance breakout with volume confirmation."""

    DEFAULT_CONFIG = {
        "lookback_period": 20,
        "volume_multiplier": 1.5,
        "breakout_threshold_pct": 0.005,
    }

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """
        Buy when price breaks above resistance (lookback high) with volume > avg * multiplier.
        Sell on support breakdown.
        """
```

**`arbitrage.py` — ArbitrageStrategy**
```python
class ArbitrageStrategy(BaseStrategy):
    """Cross-market price arbitrage scanner."""

    DEFAULT_CONFIG = {
        "min_spread_pct": 0.5,          # 0.5% min spread to trade
        "markets": ["coingecko", "binance_sim"],
        "fee_adjusted": True,
    }

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """
        Not bar-based. Uses on_tick to compare prices across markets.
        Signal: BUY on cheaper market, SELL on expensive market (simulated cross-market).
        """

    async def scan(self, market_data: MarketData, symbols: list[str]) -> list[ArbitrageOpportunity]:
        """Async scan for arb opportunities."""
```

**`macd.py` — MACDStrategy**
```python
class MACDStrategy(BaseStrategy):
    """MACD signal line crossover."""

    DEFAULT_CONFIG = {
        "fast": 12,
        "slow": 26,
        "signal": 9,
    }

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """
        Buy when MACD line crosses above signal line.
        Sell when MACD crosses below.
        Confidence = |MACD - Signal| normalized.
        """
```

**`ensemble_ml.py` — EnsembleMLStrategy**
```python
class EnsembleMLStrategy(BaseStrategy):
    """Multi-indicator weighted scoring ensemble."""

    DEFAULT_CONFIG = {
        "indicators": {
            "rsi": {"weight": 0.2, "period": 14},
            "macd": {"weight": 0.3},
            "ema_cross": {"weight": 0.2, "fast": 12, "slow": 26},
            "bb_position": {"weight": 0.15, "period": 20},
            "volume_trend": {"weight": 0.15},
        },
        "buy_threshold": 0.6,
        "sell_threshold": 0.4,
    }

    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal:
        """
        Each sub-indicator produces a score in [-1, 1].
        Weighted average -> composite_score.
        Buy if composite > buy_threshold, Sell if < sell_threshold.
        Confidence = |composite_score|.
        """

    def _score_rsi(self, rsi: float) -> float: ...
    def _score_macd(self, macd_line: float, signal_line: float) -> float: ...
    def _score_ema_cross(self, fast: float, slow: float) -> float: ...
    def _score_bb_position(self, price: float, upper: float, lower: float) -> float: ...
    def _score_volume_trend(self, volume: float, avg_volume: float) -> float: ...
```

---

### 2.4 Backtesting Engine (`backtest/`)

#### 2.4.1 `engine.py` — BacktestRunner

```python
class BacktestRunner:
    """Run strategies on historical data with realistic execution simulation."""

    def __init__(
        self,
        strategy: BaseStrategy,
        data: pd.DataFrame,              # OHLCV historical data
        config: BacktestConfig,
        initial_balance: dict[str, float],
    ) -> None: ...

    def run(self) -> BacktestResult:
        """
        Iterate through data bar-by-bar (or tick-by-tick).
        For each bar:
          1. Update portfolio with bar close
          2. strategy.on_tick() → generate_signal()
          3. Risk-check + execute_order()
          4. Record fills
        Returns BacktestResult with full history.
        """

    def walk_forward(
        self,
        data: pd.DataFrame,
        train_size: int,
        test_size: int,
        step_size: int | None = None,
    ) -> list[BacktestResult]:
        """
        Walk-forward analysis: train on [i, i+train), test on [i+train, i+train+test).
        Step window forward by step_size.
        Returns list of results per window.
        """

@dataclass
class BacktestConfig:
    initial_balance: dict[str, float]
    fee_rate: float = 0.001
    slippage_bps: float = 5.0
    allow_short: bool = True
    position_sizing: SizingMethod = SizingMethod.PERCENTAGE
    position_sizing_value: float = 0.02

@dataclass
class BacktestResult:
    strategy_id: str
    equity_curve: pd.DataFrame       # timestamp, equity, drawdown
    trades: list[TradeRecord]
    metrics: BacktestMetrics
    config: BacktestConfig
    duration: timedelta

    def to_csv(self, path: str) -> None:
        """Export trades + equity curve to CSV files."""

    def to_dict(self) -> dict[str, Any]: ...
```

#### 2.4.2 `metrics.py` — Performance Calculations

```python
class BacktestMetrics:
    """Comprehensive performance metrics."""

    def __init__(self, equity_curve: pd.DataFrame, trades: list[TradeRecord]) -> None: ...

    @property
    def total_return_pct(self) -> float: ...
    @property
    def sharpe_ratio(self) -> float: ...
    @property
    def sortino_ratio(self) -> float: ...
    @property
    def max_drawdown_pct(self) -> float: ...
    @property
    def max_drawdown_duration(self) -> timedelta: ...
    @property
    def win_rate(self) -> float: ...
    @property
    def profit_factor(self) -> float: ...
    @property
    def avg_trade_return(self) -> float: ...
    @property
    def avg_win(self) -> float: ...
    @property
    def avg_loss(self) -> float: ...
    @property
    def payoff_ratio(self) -> float: ...
    @property
    def calmar_ratio(self) -> float: ...
    @property
    def trades_per_month(self) -> float: ...

    def to_dict(self) -> dict[str, float | timedelta]: ...

def calculate_sharpe(returns: pd.Series, risk_free_rate: float = 0.0) -> float: ...
def calculate_max_drawdown(equity: pd.Series) -> tuple[float, int, int]: ...
def calculate_win_rate(trades: list[TradeRecord]) -> float: ...
def calculate_profit_factor(trades: list[TradeRecord]) -> float: ...
```

---

### 2.5 Data Records & Analytics (`analytics/`)

#### 2.5.1 `records.py` — Trade Records & Snapshots

```python
class TradeRepository:
    """CRUD for trade records."""

    def __init__(self, session: Session) -> None: ...

    def create(self, record: TradeRecord) -> int: ...
    def get_by_strategy(self, strategy_id: str, limit: int = 100) -> list[TradeRecord]: ...
    def get_by_account(self, account_id: str, start: datetime | None = None, end: datetime | None = None) -> list[TradeRecord]: ...
    def get_all(self, limit: int = 1000) -> list[TradeRecord]: ...

class PortfolioSnapshotRepository:
    """CRUD for portfolio snapshots."""

    def create_snapshot(self, portfolio: Portfolio, timestamp: datetime) -> int: ...
    def get_snapshots(self, account_id: str, start: datetime, end: datetime) -> list[PortfolioSnapshot]: ...
    def get_latest(self, account_id: str) -> PortfolioSnapshot | None: ...

class StrategyPerformanceRepository:
    """Persist strategy metrics over time."""

    def record(self, strategy_id: str, metrics: StrategyMetrics, timestamp: datetime) -> int: ...
    def get_history(self, strategy_id: str) -> list[StrategyPerformanceRecord]: ...
```

#### 2.5.2 `reports.py` — Performance Reports

```python
class ReportGenerator:
    """Generate human-readable and machine-readable reports."""

    def __init__(self, db_session: Session) -> None: ...

    def generate_daily_report(self, date: date, account_id: str = "default") -> DailyReport:
        """P&L, trades, positions, drawdown for a single day."""

    def generate_strategy_report(self, strategy_id: str) -> StrategyReport:
        """Lifetime performance of a strategy."""

    def generate_portfolio_report(self, account_id: str) -> PortfolioReport:
        """Full portfolio summary with asset allocation."""

@dataclass
class DailyReport:
    date: date
    starting_equity: float
    ending_equity: float
    realized_pnl: float
    unrealized_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    top_gainer: str | None
    top_loser: str | None

@dataclass
class StrategyReport:
    strategy_id: str
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float | None
    max_drawdown: float
    equity_curve: list[tuple[datetime, float]]
    trades: list[TradeRecord]
```

#### 2.5.3 `export.py` — CSV/JSON Export

```python
class DataExporter:
    """Export all database records to flat files."""

    def __init__(self, db_session: Session, output_dir: str = "./exports") -> None: ...

    def export_trades(
        self,
        path: str | None = None,
        account_id: str | None = None,
        strategy_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> str:
        """Export trades to CSV. Returns file path."""

    def export_portfolio_snapshots(self, path: str | None = None, account_id: str | None = None) -> str: ...
    def export_strategy_performance(self, path: str | None = None, strategy_id: str | None = None) -> str: ...
    def export_all(self, base_path: str | None = None) -> dict[str, str]:
        """Export everything. Returns {table_name: file_path}."""

    def export_to_json(self, table_name: str, path: str) -> str: ...
```

---

### 2.6 Risk Management — Extended

Already covered in `bot/risk.py` (2.1.4). Additional components:

#### 2.6.1 Position Sizing Implementations

```python
class PositionSizer:
    @staticmethod
    def fixed(amount: float) -> float:
        """Fixed quantity regardless of price or equity."""

    @staticmethod
    def percentage_of_equity(equity: float, pct: float, price: float) -> float:
        """e.g., 2% of $10,000 = $200 → $200 / $100 = 2 units."""

    @staticmethod
    def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> float:
        """f* = (p*b - q) / b, where b = avg_win/avg_loss."""

    @staticmethod
    def volatility_based(equity: float, atr: float, risk_per_trade_pct: float, price: float) -> float:
        """Size = (equity * risk_pct) / (atr * price)."""
```

#### 2.6.2 Drawdown & Exposure Monitors

```python
class DrawdownMonitor:
    def __init__(self, max_drawdown_pct: float = 0.10) -> None: ...
    def update(self, equity: float, timestamp: datetime) -> DrawdownStatus: ...
    def is_breached(self) -> bool: ...

class ExposureMonitor:
    def check(self, portfolio: Portfolio, limits: dict[str, float]) -> list[RiskAlert]: ...
```

---

## 3. API Specification

### 3.1 FastAPI App (`api/main.py`)

```python
from fastapi import FastAPI

app = FastAPI(
    title="Paper Trading Bot API",
    version="1.0.0",
    description="REST API for paper trading bot management",
)

# Register routers
app.include_router(portfolio_router, prefix="/portfolio", tags=["Portfolio"])
app.include_router(trades_router, prefix="/trades", tags=["Trades"])
app.include_router(strategies_router, prefix="/strategies", tags=["Strategies"])
app.include_router(backtest_router, prefix="/backtest", tags=["Backtest"])
app.include_router(market_router, prefix="/market", tags=["Market Data"])
```

### 3.2 Pydantic Request/Response Models (`api/models.py`)

```python
# ── Portfolio ──
class PortfolioResponse(BaseModel):
    account_id: str
    balances: dict[str, float]
    positions: list[PositionResponse]
    total_equity: float
    unrealized_pnl: float
    realized_pnl: float
    timestamp: datetime

class PositionResponse(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    market_value: float

# ── Orders ──
class OrderRequest(BaseModel):
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    account_id: str = "default"
    strategy_id: str | None = None

class OrderResponse(BaseModel):
    order_id: str
    status: str
    filled_qty: float
    avg_fill_price: float | None
    fee: float
    created_at: datetime

# ── Strategies ──
class StrategyListResponse(BaseModel):
    strategies: list[StrategyInfo]

class StrategyInfo(BaseModel):
    strategy_id: str
    strategy_type: str
    is_active: bool
    config: dict[str, Any]
    metrics: StrategyMetrics | None

class StrategyToggleRequest(BaseModel):
    strategy_id: str
    active: bool

# ── Backtest ──
class BacktestRequest(BaseModel):
    strategy_type: str
    symbol: str
    asset_class: AssetClass
    start_date: date
    end_date: date
    timeframe: str = "1d"
    initial_balance: dict[str, float]
    config: dict[str, Any] | None = None

class BacktestResponse(BaseModel):
    backtest_id: str
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int
    equity_curve_url: str | None
    trades_csv_url: str | None

# ── Market ──
class PriceResponse(BaseModel):
    symbol: str
    price: float
    bid: float | None
    ask: float | None
    timestamp: datetime

class OHLCVResponse(BaseModel):
    symbol: str
    timeframe: str
    data: list[OHLCVBar]

class OHLCVBar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
```

### 3.3 Endpoint List

| Method | Endpoint | Description | Request Body |
|--------|----------|-------------|--------------|
| `GET` | `/health` | Health check | — |
| `GET` | `/portfolio/{account_id}` | Get portfolio | — |
| `POST` | `/portfolio/{account_id}/deposit` | Deposit virtual funds | `{"asset": "USDT", "amount": 1000}` |
| `GET` | `/portfolio/{account_id}/snapshots` | Historical snapshots | Query: `start`, `end` |
| `POST` | `/orders` | Submit order | `OrderRequest` |
| `GET` | `/orders/{order_id}` | Order status | — |
| `DELETE` | `/orders/{order_id}` | Cancel order | — |
| `GET` | `/trades` | List trades | Query: `account_id`, `strategy_id`, `start`, `end` |
| `GET` | `/trades/export` | Export trades CSV | Query: format |
| `GET` | `/strategies` | List available & active strategies | — |
| `POST` | `/strategies/register` | Register a strategy | `{"strategy_type": "momentum", "config": {}}` |
| `POST` | `/strategies/{id}/toggle` | Activate/deactivate | `{"active": true}` |
| `GET` | `/strategies/{id}/metrics` | Strategy metrics | — |
| `POST` | `/backtest/run` | Run backtest | `BacktestRequest` |
| `GET` | `/backtest/{backtest_id}` | Backtest result | — |
| `GET` | `/backtest/{backtest_id}/equity` | Equity curve data | — |
| `GET` | `/market/price/{symbol}` | Current price | Query: `asset_class` |
| `GET` | `/market/ohlcv/{symbol}` | Historical OHLCV | Query: `timeframe`, `limit` |
| `GET` | `/market/symbols` | Available symbols | — |
| `GET` | `/reports/daily` | Daily report | Query: `date`, `account_id` |
| `GET` | `/reports/strategy/{id}` | Strategy report | — |
| `POST` | `/engine/start` | Start tick loop | — |
| `POST` | `/engine/stop` | Stop tick loop | — |
| `GET` | `/engine/status` | Engine status | — |

---

## 4. CLI Specification

### 4.1 CLI App (`cli/main.py`)

Uses **Typer** for command-line interface.

```python
import typer

app = typer.Typer(help="Paper Trading Bot CLI")

# ── Commands ──
@app.command()
def run_bot(
    config: str = typer.Option("config.yaml", "--config", "-c"),
    account: str = typer.Option("default", "--account", "-a"),
    strategies: list[str] = typer.Option([], "--strategy", "-s"),
    interval: float = typer.Option(5.0, "--interval"),
) -> None:
    """Start the paper trading bot tick loop."""

@app.command()
def backtest(
    strategy: str = typer.Argument(..., help="Strategy type name"),
    symbol: str = typer.Argument(...),
    asset_class: str = typer.Option("crypto", "--asset-class"),
    start: str = typer.Option(..., "--start", help="YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="YYYY-MM-DD"),
    timeframe: str = typer.Option("1d", "--timeframe"),
    initial_balance: float = typer.Option(10000.0, "--balance"),
    output: str = typer.Option("./backtest_results", "--output"),
    walk_forward: bool = typer.Option(False, "--walk-forward"),
) -> None:
    """Run a strategy backtest on historical data."""

@app.command()
def export_records(
    table: str = typer.Option("all", "--table", help="trades|snapshots|performance|all"),
    output_dir: str = typer.Option("./exports", "--output"),
    account_id: str | None = typer.Option(None, "--account"),
    strategy_id: str | None = typer.Option(None, "--strategy"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    format: str = typer.Option("csv", "--format"),
) -> None:
    """Export database records to CSV or JSON."""

@app.command()
def configure(
    key: str | None = typer.Option(None, "--set"),
    value: str | None = typer.Option(None, "--value"),
    show: bool = typer.Option(False, "--show"),
    init: bool = typer.Option(False, "--init"),
) -> None:
    """View or modify bot configuration. --init creates default config.yaml."""

@app.command()
def status() -> None:
    """Show bot status: engine, strategies, portfolio summary."""

@app.command()
def report(
    type: str = typer.Argument(..., help="daily|strategy|portfolio"),
    date: str | None = typer.Option(None, "--date"),
    account_id: str = typer.Option("default", "--account"),
    strategy_id: str | None = typer.Option(None, "--strategy"),
    output: str | None = typer.Option(None, "--output"),
) -> None:
    """Generate and optionally save a performance report."""

@app.command()
def strategy_list() -> None:
    """List all available strategy types and their configs."""
```

### 4.2 CLI Usage Examples

```bash
# Initialize default config
python -m trading_bot.cli configure --init

# Start the bot with momentum + grid strategies
python -m trading_bot.cli run-bot \
  --config config.yaml \
  --strategy momentum \
  --strategy grid \
  --interval 10.0

# Backtest momentum strategy on BTC
python -m trading_bot.cli backtest momentum bitcoin \
  --asset-class crypto \
  --start 2023-01-01 \
  --end 2023-12-31 \
  --timeframe 1h \
  --balance 10000 \
  --output ./results/momentum_btc_2023

# Export all trades to CSV
python -m trading_bot.cli export-records \
  --table trades \
  --output ./exports \
  --account default \
  --start 2024-01-01

# Generate daily report
python -m trading_bot.cli report daily --date 2024-06-01 --output report.json
```

---

## 5. Database Schema

### 5.1 Entity Relationship Diagram

```
┌─────────────┐       ┌─────────────┐       ┌──────────────────┐
│   accounts  │       │  portfolios │       │ portfolio_snapshots│
├─────────────┤       ├─────────────┤       ├──────────────────┤
│ id (PK)     │◄──────│ account_id  │◄──────│ account_id (FK)  │
│ name        │       │ asset       │       │ timestamp         │
│ created_at  │       │ balance     │       │ total_equity      │
└─────────────┘       └─────────────┘       │ unrealized_pnl    │
                                            │ realized_pnl      │
                                            │ positions_json     │
                                            └──────────────────┘
┌─────────────┐       ┌─────────────┐       ┌──────────────────┐
│    trades   │       │   orders    │       │  order_fills     │
├─────────────┤       ├─────────────┤       ├──────────────────┤
│ id (PK)     │◄──────│ id (PK)     │◄──────│ id (PK)          │
│ order_id(FK)│       │ account_id  │       │ order_id (FK)    │
│ symbol      │       │ symbol      │       │ filled_qty        │
│ side        │       │ side        │       │ filled_price      │
│ quantity    │       │ order_type  │       │ fee               │
│ price       │       │ quantity    │       │ slippage          │
│ fee         │       │ price       │       │ timestamp         │
│ pnl         │       │ stop_price  │       └──────────────────┘
│ strategy_id │       │ status      │
│ timestamp   │       │ created_at  │
└─────────────┘       └─────────────┘

┌─────────────────────┐     ┌──────────────────────────┐
│ strategy_performance │     │        ohlcv             │
├─────────────────────┤     ├──────────────────────────┤
│ id (PK)             │     │ id (PK)                  │
│ strategy_id         │     │ symbol (IDX)             │
│ timestamp           │     │ asset_class              │
│ total_trades        │     │ timeframe                │
│ win_rate            │     │ timestamp (IDX)          │
│ profit_factor       │     │ open, high, low, close   │
│ sharpe_ratio        │     │ volume                   │
│ max_drawdown        │     │ UNIQUE(sym,tf,ts)        │
│ total_pnl           │     └──────────────────────────┘
└─────────────────────┘

┌─────────────────────┐
│      positions      │
├─────────────────────┤
│ id (PK)             │
│ account_id (FK)     │
│ symbol              │
│ side                │
│ size                │
│ entry_price         │
│ current_price       │
│ unrealized_pnl      │
│ realized_pnl        │
│ opened_at           │
│ closed_at (NULL=open)│
│ status              │
└─────────────────────┘
```

### 5.2 SQLAlchemy Model Definitions

```python
# accounts
class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex[:16])
    name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(default=True)

# trades (aggregated from fills)
class TradeRecord(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(String(32), ForeignKey("accounts.id"), index=True)
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    strategy_id: Mapped[str | None] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))        # "buy" | "sell"
    quantity: Mapped[float]
    price: Mapped[float]
    fee: Mapped[float]
    realized_pnl: Mapped[float | None]
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)

# orders
class OrderRecord(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(32), ForeignKey("accounts.id"), index=True)
    strategy_id: Mapped[str | None] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[float]
    price: Mapped[float | None]
    stop_price: Mapped[float | None]
    filled_quantity: Mapped[float] = mapped_column(default=0.0)
    avg_fill_price: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|filled|partial|canceled
    fee: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# portfolio_snapshots
class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(String(32), ForeignKey("accounts.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    total_equity: Mapped[float]
    cash_balance: Mapped[float]
    unrealized_pnl: Mapped[float]
    realized_pnl: Mapped[float]
    positions_json: Mapped[str] = mapped_column(Text)   # JSON-encoded positions list

# strategy_performance
class StrategyPerformance(Base):
    __tablename__ = "strategy_performance"
    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    total_trades: Mapped[int]
    win_rate: Mapped[float]
    profit_factor: Mapped[float]
    sharpe_ratio: Mapped[float | None]
    max_drawdown: Mapped[float]
    total_pnl: Mapped[float]

# positions
class PositionRecord(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[str] = mapped_column(String(32), ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))
    size: Mapped[float]
    entry_price: Mapped[float]
    current_price: Mapped[float]
    unrealized_pnl: Mapped[float]
    realized_pnl: Mapped[float]
    opened_at: Mapped[datetime]
    closed_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|closed
```

---

## 6. Configuration Schema

### 6.1 Default `config.yaml`

```yaml
# config.yaml — Paper Trading Bot Configuration

app:
  name: "PaperTradingBot"
  log_level: INFO
  json_logs: true
  data_dir: "./data"

engine:
  tick_interval_seconds: 5.0
  max_accounts: 10
  auto_start_strategies: true

market_data:
  coingecko:
    enabled: true
    base_url: "https://api.coingecko.com/api/v3"
    rate_limit_per_minute: 30
  yfinance:
    enabled: true
  cache:
    enabled: true
    ttl_seconds: 300
    max_entries: 10000
  default_timeframe: "1h"
  symbols:
    crypto: ["bitcoin", "ethereum", "solana", "cardano"]
    stocks: ["AAPL", "TSLA", "MSFT", "GOOGL"]

risk:
  max_drawdown_pct: 0.10
  max_position_size_pct: 0.20
  max_exposure_per_asset_pct: 0.30
  default_stop_loss_pct: 0.02
  default_take_profit_pct: 0.06
  position_sizing_method: "percentage"   # fixed | percentage | kelly | volatility
  position_sizing_value: 0.02
  fee_rate: 0.001
  slippage_model: "fixed"               # fixed | proportional | volatility
  slippage_bps: 5.0

strategies:
  momentum:
    enabled: true
    symbols: ["bitcoin", "ethereum"]
    fast_ema: 12
    slow_ema: 26
    trend_filter_ema: 200
  mean_reversion:
    enabled: true
    symbols: ["bitcoin"]
    rsi_period: 14
    rsi_overbought: 70
    rsi_oversold: 30
    bb_period: 20
    bb_std: 2.0
  grid:
    enabled: false
    symbols: ["bitcoin"]
    grid_levels: 10
    grid_spacing_pct: 0.01
    quantity_per_grid: 0.01
  breakout:
    enabled: false
    symbols: ["ethereum"]
    lookback_period: 20
    volume_multiplier: 1.5
    breakout_threshold_pct: 0.005
  arbitrage:
    enabled: false
    symbols: ["bitcoin", "ethereum"]
    min_spread_pct: 0.5
  macd:
    enabled: true
    symbols: ["bitcoin"]
    fast: 12
    slow: 26
    signal: 9
  ensemble_ml:
    enabled: true
    symbols: ["bitcoin", "ethereum"]
    buy_threshold: 0.6
    sell_threshold: 0.4
    indicators:
      rsi: { weight: 0.2, period: 14 }
      macd: { weight: 0.3 }
      ema_cross: { weight: 0.2, fast: 12, slow: 26 }
      bb_position: { weight: 0.15, period: 20 }
      volume_trend: { weight: 0.15 }

api:
  host: "0.0.0.0"
  port: 8000
  cors_origins: ["http://localhost:3000"]

backtest:
  default_initial_balance:
    USDT: 10000.0
    USD: 10000.0
  allow_short: true
```

---

## 7. File Structure

```
trading_bot/
├── bot/
│   ├── __init__.py
│   ├── engine.py              # PaperTradingEngine — core tick loop, order execution
│   ├── portfolio.py           # Portfolio, Position, PositionSide dataclasses
│   ├── orders.py              # Order, FillResult, OrderType, ExecutionSimulator
│   ├── risk.py                # RiskManager, PositionSizer, DrawdownMonitor, ExposureMonitor
│   └── config.py              # BotConfig, RiskConfig, SizingMethod pydantic models
│
├── strategies/
│   ├── __init__.py            # StrategyFactory, strategy registry
│   ├── base.py                # BaseStrategy, Signal, SignalType, StrategyMetrics
│   ├── momentum.py            # MomentumStrategy (EMA crossover)
│   ├── mean_reversion.py      # MeanReversionStrategy (RSI + Bollinger Bands)
│   ├── grid.py                # GridStrategy
│   ├── breakout.py            # BreakoutStrategy (support/resistance + volume)
│   ├── arbitrage.py           # ArbitrageStrategy (cross-market spread scanner)
│   ├── macd.py                # MACDStrategy
│   └── ensemble_ml.py         # EnsembleMLStrategy (multi-indicator weighted scoring)
│
├── data/
│   ├── __init__.py
│   ├── fetcher.py             # MarketData — CoinGecko + Yahoo Finance unified fetcher
│   ├── coingecko_client.py    # Async CoinGecko API client (thin wrapper)
│   ├── yfinance_client.py     # Sync Yahoo Finance wrapper
│   ├── storage.py             # SQLAlchemy ORM models (OHLCVRecord, PriceTick, etc.)
│   └── cache.py               # DataCache — LRU + SQLite + CSV multi-layer cache
│
├── backtest/
│   ├── __init__.py
│   ├── engine.py              # BacktestRunner, BacktestConfig, BacktestResult
│   └── metrics.py             # BacktestMetrics, calculate_sharpe, calculate_max_drawdown, etc.
│
├── analytics/
│   ├── __init__.py
│   ├── records.py             # TradeRepository, PortfolioSnapshotRepository, StrategyPerformanceRepository
│   ├── reports.py             # ReportGenerator, DailyReport, StrategyReport, PortfolioReport
│   └── export.py              # DataExporter — CSV/JSON export for all tables
│
├── api/
│   ├── __init__.py
│   ├── main.py                # FastAPI app factory, router registration
│   ├── dependencies.py        # FastAPI Depends: get_db, get_engine, get_market_data
│   ├── models.py              # Pydantic request/response models
│   └── routes/
│       ├── __init__.py
│       ├── portfolio.py       # GET /portfolio, POST /deposit, GET /snapshots
│       ├── strategies.py      # GET /strategies, POST /register, POST /toggle, GET /metrics
│       ├── trades.py          # GET /trades, GET /export
│       ├── orders.py          # POST /orders, GET /orders/{id}, DELETE /orders/{id}
│       ├── backtest.py        # POST /backtest/run, GET /backtest/{id}, GET /equity
│       ├── market.py          # GET /price, GET /ohlcv, GET /symbols
│       └── engine.py          # POST /start, POST /stop, GET /status
│
├── cli/
│   ├── __init__.py
│   └── main.py                # Typer CLI: run-bot, backtest, export-records, configure, status, report, strategy-list
│
├── tests/
│   ├── conftest.py            # pytest fixtures: mock_db, mock_market_data, sample_ohlcv
│   ├── test_engine.py         # Portfolio, Order execution, Engine tick loop tests
│   ├── test_strategies.py     # Signal generation for all 7 strategies
│   ├── test_backtest.py       # BacktestRunner, metrics calculations
│   ├── test_api.py            # FastAPI endpoint tests (TestClient)
│   ├── test_risk.py           # Position sizing, drawdown, exposure tests
│   └── test_data.py           # Fetcher, cache, storage tests
│
├── data/                      # Runtime data directory (gitignored)
│   ├── cache/
│   ├── exports/
│   └── bot.db                 # SQLite database
│
├── requirements.txt
├── config.yaml                # Default configuration file
├── README.md                  # Setup & usage guide
└── run.py                     # Application entry point
```

---

## 8. Interface Contracts

### 8.1 BaseStrategy Contract

Every strategy **MUST** implement:

```python
class BaseStrategy(ABC):
    strategy_id: str
    config: dict[str, Any]
    is_active: bool

    def __init__(self, strategy_id: str, config: dict[str, Any]) -> None: ...

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Signal: ...

    def on_tick(self, tick: TickData, portfolio: Portfolio) -> Signal | None:
        # Default implementation: get OHLCV, call generate_signal
        ...

    def on_fill(self, fill: FillResult, portfolio: Portfolio) -> None: ...
    def on_init(self, market_data: MarketData) -> None: ...
    def on_stop(self) -> None: ...
    def get_metrics(self) -> StrategyMetrics: ...
    def reset(self) -> None: ...
```

**Invariants:**
- `generate_signal` must not mutate the input `data` DataFrame.
- `Signal.confidence` must be in `[0.0, 1.0]`.
- `Signal.timestamp` must be timezone-aware UTC.
- Strategies must be stateless with respect to the engine (all state in `self._history` / `self.config`).

### 8.2 PaperEngine Contract

```python
class PaperTradingEngine:
    # Invariants:
    # - One portfolio per account_id.
    # - Orders are immutable once submitted; modifications create new orders.
    # - Fills are recorded atomically with portfolio updates.
    # - Tick processing is single-threaded per account (no concurrent ticks).

    def submit_order(self, order: Order, account_id: str = "default") -> str: ...
    def execute_order(self, order: Order, current_price: float) -> FillResult: ...
    def get_portfolio(self, account_id: str = "default") -> Portfolio: ...
```

### 8.3 MarketData Contract

```python
class MarketData:
    # Invariants:
    # - OHLCV data is sorted by timestamp ascending.
    # - All prices are in the quote currency (USD/USDT).
    # - Cached data is used if available and not expired.

    async def get_ohlcv(self, symbol: str, asset_class: AssetClass, timeframe: str, limit: int) -> pd.DataFrame: ...
    async def get_price(self, symbol: str, asset_class: AssetClass) -> float: ...
```

### 8.4 BacktestRunner Contract

```python
class BacktestRunner:
    # Invariants:
    # - Data index must be monotonic datetime.
    # - Strategy state is reset before each run.
    # - Execution uses the same ExecutionSimulator as live trading.
    # - Short selling is allowed only if config.allow_short = True.

    def run(self) -> BacktestResult: ...
    def walk_forward(self, data, train_size, test_size, step_size) -> list[BacktestResult]: ...
```

---

## 9. Data Schemas & Types

### 9.1 Core Enumerations

```python
class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    STOP_LIMIT = "stop_limit"

class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderStatus(Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"

class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"

class AssetClass(Enum):
    CRYPTO = "crypto"
    STOCK = "stock"
    FOREX = "forex"

class SizingMethod(Enum):
    FIXED = "fixed"
    PERCENTAGE = "percentage"
    KELLY = "kelly"
    VOLATILITY = "volatility"
```

### 9.2 Key Data Structures

```python
@dataclass
class TickData:
    symbol: str
    price: float
    bid: float | None
    ask: float | None
    volume: float | None
    timestamp: datetime

@dataclass
class Signal:
    strategy_id: str
    symbol: str
    signal_type: SignalType
    confidence: float            # 0.0 – 1.0
    timestamp: datetime
    metadata: dict[str, Any]
    suggested_size: float | None
    stop_loss: float | None
    take_profit: float | None

@dataclass
class Order:
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None
    stop_price: float | None
    time_in_force: str
    created_at: datetime
    strategy_id: str | None
    account_id: str

@dataclass
class FillResult:
    order_id: str
    symbol: str
    filled_qty: float
    filled_price: float
    fee: float
    slippage: float
    timestamp: datetime
    side: OrderSide
    realized_pnl: float | None

@dataclass
class PortfolioSnapshot:
    account_id: str
    timestamp: datetime
    balances: dict[str, float]
    positions: list[Position]
    total_equity: float
    unrealized_pnl: float
    realized_pnl: float

@dataclass
class StrategyMetrics:
    strategy_id: str
    total_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    sharpe_ratio: float | None
    max_drawdown: float
    current_streak: int
    total_pnl: float

@dataclass
class BacktestMetrics:
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration: timedelta
    win_rate: float
    profit_factor: float
    avg_trade_return: float
    avg_win: float
    avg_loss: float
    payoff_ratio: float
    calmar_ratio: float
    trades_per_month: float
```

---

## 10. Testing Strategy

### 10.1 Test Structure

| File | Scope |
|------|-------|
| `test_engine.py` | Order submission, fill simulation, portfolio updates, multi-account isolation |
| `test_strategies.py` | Signal generation for all 7 strategies on synthetic/mock data |
| `test_backtest.py` | BacktestRunner correctness, metrics accuracy, walk-forward |
| `test_api.py` | FastAPI endpoints with `TestClient`, request/validation |
| `test_risk.py` | Position sizing formulas, drawdown alerts, exposure limits |
| `test_data.py` | Cache hit/miss, fetcher mocking, storage CRUD |

### 10.2 Fixtures (`conftest.py`)

```python
@pytest.fixture
def mock_db() -> Session:
    """In-memory SQLite session with all tables created."""

@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """100 rows of synthetic OHLCV data with known trend/reversion patterns."""

@pytest.fixture
def mock_market_data(mock_db) -> MarketData:
    """MarketData with mocked HTTP responses."""

@pytest.fixture
def engine(mock_db, mock_market_data) -> PaperTradingEngine:
    """Pre-configured engine with default account."""
```

### 10.3 Key Test Cases

```python
def test_market_order_fill():
    # Submit market order, verify fill price = current price + slippage
    # Verify portfolio balance reduced, position opened

def test_limit_order_pending_then_fill():
    # Submit limit below market, verify pending
    # Advance tick to price < limit, verify fill

def test_stop_loss_execution():
    # Open position with SL
    # Advance tick to SL price, verify auto-close, realized PnL recorded

def test_momentum_signal_generation():
    # Feed EMA-crossover data, verify BUY/SELL signals

def test_backtest_equity_curve():
    # Run backtest, verify equity curve starts at initial balance
    # Verify final equity = initial + sum(realized PnL) - fees

def test_risk_max_drawdown_alert():
    # Simulate 15% drawdown with max=10%, verify RiskAlert generated
    # Verify engine halts or warns
```

---

## 11. Scenarios

### 11.1 Scenario Matrix

| # | Scenario | Strategy | Asset | Key Config |
|---|----------|----------|-------|------------|
| 1 | Long-only crypto spot | Momentum / MACD | BTC, ETH | `allow_short: false` |
| 2 | Short selling (paper) | Momentum / MeanReversion | BTC | `allow_short: true` |
| 3 | Multi-asset portfolio | EnsembleML | BTC, ETH, AAPL, TSLA | Multiple symbols per strategy |
| 4 | Grid trading ranging | Grid | BTC | `grid_levels: 10`, `spacing: 1%` |
| 5 | Breakout trending | Breakout | ETH | `lookback: 20`, `vol_mult: 1.5` |
| 6 | Arbitrage scanning | Arbitrage | BTC, ETH | Compare CoinGecko vs simulated Binance |
| 7 | Backtest historical | Any | Any | `backtest.run()` with date range |
| 8 | ML ensemble signal gathering | EnsembleML | BTC, ETH | Composite scoring, no trading |

### 11.2 Scenario Implementation Notes

**Scenario 1 — Long-only crypto spot:**
- Engine rejects SELL orders that would create short positions when `allow_short=false`.
- Portfolio only tracks positive sizes.

**Scenario 2 — Short selling:**
- Portfolio supports negative `size` for shorts.
- `unrealized_pnl` for shorts = (entry_price - current_price) * size.
- Margin requirements tracked in `cash_balance` (not borrowed funds — purely paper).

**Scenario 3 — Multi-asset:**
- One engine manages multiple strategies across accounts.
- Each strategy can subscribe to multiple symbols.
- `get_total_equity()` sums across all quote currencies using latest prices.

**Scenario 4 — Grid trading:**
- GridStrategy maintains internal grid level state.
- On tick, checks if price crossed a grid line → emits opposing order.
- Requires tick-level granularity (not just bar close).

**Scenario 5 — Breakout:**
- Uses rolling window highs/lows as support/resistance.
- Volume confirmation via comparison to rolling average volume.
- Confidence scales with breakout magnitude beyond threshold.

**Scenario 6 — Arbitrage:**
- Scans two or more price sources for the same symbol.
- Minimum spread threshold after fee adjustment.
- Emits paired signals (BUY on cheap, SELL on expensive).
- Requires `on_tick` override for real-time scanning.

**Scenario 7 — Backtest:**
- Full historical replay with bar-by-bar execution.
- Equity curve and trade log exported to CSV.
- Walk-forward splits data into train/test windows.

**Scenario 8 — ML Ensemble (signal gathering mode):**
- Strategy can run with `dry_run=true` → signals recorded but no orders submitted.
- Use for data collection and feature engineering before going live.
- All signals stored in `strategy_performance` table for analysis.

---

## 12. Appendix

### 12.1 Entry Points

| File | Purpose | Command |
|------|---------|---------|
| `run.py` | Start API server + optional bot | `python run.py --mode api` |
| `run.py` | Start CLI bot only | `python run.py --mode bot` |
| `cli/main.py` | CLI entry | `python -m trading_bot.cli <command>` |
| `api/main.py` | API server | `uvicorn trading_bot.api.main:app --reload` |

### 12.2 Logging Format

```json
{
  "timestamp": "2024-01-15T09:23:01.123Z",
  "level": "INFO",
  "logger": "trading_bot.engine",
  "event": "order_filled",
  "order_id": "abc-123",
  "symbol": "bitcoin",
  "filled_price": 42350.00,
  "fee": 42.35,
  "account_id": "default"
}
```

### 12.3 Performance Budgets

| Operation | Target Latency |
|-----------|---------------|
| Tick loop iteration | < 100ms |
| Signal generation | < 50ms per strategy |
| Order execution | < 10ms |
| API response (read) | < 50ms |
| API response (write) | < 100ms |
| Backtest 1 year daily | < 5 seconds |

### 12.4 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BOT_API_PORT` | FastAPI port | `8000` |
| `BOT_LOG_LEVEL` | Logging level | `INFO` |
| `BOT_DATA_DIR` | Data/cache directory | `./data` |
| `BOT_CONFIG_PATH` | Config file path | `./config.yaml` |

### 12.5 Third-Party API Limits

| Provider | Free Tier | Rate Limit |
|----------|-----------|------------|
| CoinGecko | No API key | 10-30 calls/min |
| Yahoo Finance (yfinance) | Free | ~2000 requests/hour |

---

## 13. Glossary

| Term | Definition |
|------|------------|
| **Paper Trading** | Simulated trading with virtual balances; no real money at risk. |
| **OHLCV** | Open, High, Low, Close, Volume — standard bar data format. |
| **Slippage** | Difference between expected price and actual fill price. |
| **Sharpe Ratio** | Risk-adjusted return: (return - risk_free) / volatility. |
| **Max Drawdown** | Largest peak-to-trough decline in equity curve. |
| **Walk-Forward** | Backtesting technique that trains on past data, tests on future data, then steps forward. |
| **Kelly Criterion** | Position sizing formula maximizing log-utility of wealth. |
| **Grid Trading** | Placing buy/sell orders at fixed intervals around a price. |

---

*End of Specification v1.0.0*
