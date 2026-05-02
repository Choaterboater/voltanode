"""Pydantic configuration for the trading bot."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PositionSide(Enum):
    """Position side enumeration."""
    LONG = "long"
    SHORT = "short"


class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    STOP_LIMIT = "stop_limit"


class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


class SignalType(Enum):
    """Signal type enumeration."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"


class AssetClass(Enum):
    """Asset class enumeration."""
    CRYPTO = "crypto"
    STOCK = "stock"
    FOREX = "forex"


class SizingMethod(Enum):
    """Position sizing method enumeration."""
    FIXED = "fixed"
    PERCENTAGE = "percentage"
    KELLY = "kelly"
    VOLATILITY = "volatility"


class RiskConfig(BaseModel):
    """Risk management configuration."""
    max_drawdown_pct: float = 0.10
    max_position_size_pct: float = 0.20
    max_exposure_per_asset_pct: float = 0.30
    default_stop_loss_pct: float = 0.02
    default_take_profit_pct: float = 0.06
    position_sizing_method: SizingMethod = SizingMethod.PERCENTAGE
    position_sizing_value: float = 0.02
    fee_rate: float = 0.001
    slippage_model: str = "fixed"
    slippage_bps: float = 5.0


class CoinGeckoConfig(BaseModel):
    """CoinGecko API configuration."""
    enabled: bool = True
    base_url: str = "https://api.coingecko.com/api/v3"
    rate_limit_per_minute: int = 30


class YFinanceConfig(BaseModel):
    """Yahoo Finance configuration."""
    enabled: bool = True


class CacheConfig(BaseModel):
    """Cache configuration."""
    enabled: bool = True
    ttl_seconds: float = 300.0
    max_entries: int = 10000


class MarketDataConfig(BaseModel):
    """Market data configuration."""
    coingecko: CoinGeckoConfig = CoinGeckoConfig()
    yfinance: YFinanceConfig = YFinanceConfig()
    cache: CacheConfig = CacheConfig()
    default_timeframe: str = "1h"
    symbols: Dict[str, List[str]] = Field(default_factory=lambda: {
        "crypto": [
            # CoinGecko IDs (for paper mode / backtest)
            "bitcoin", "ethereum", "solana", "cardano",
            # Common tickers (also valid for CoinGecko normalizer)
            "BTC", "ETH", "SOL", "ADA", "XRP", "DOT", "LINK", "AVAX", "MATIC",
            "DOGE", "SHIB", "LTC", "BCH", "UNI", "AAVE", "ETC", "ALGO", "FIL",
            "ATOM", "MANA", "SAND", "AXS", "GRT", "FTM", "ICP", "NEAR", "XTZ",
        ],
        "stocks": ["AAPL", "TSLA", "MSFT", "GOOGL", "NVDA", "AMZN", "META", "AMD"],
    })


class EngineConfig(BaseModel):
    """Engine configuration."""
    tick_interval_seconds: float = 5.0
    max_accounts: int = 10
    auto_start_strategies: bool = True


class AppConfig(BaseModel):
    """Application configuration."""
    name: str = "PaperTradingBot"
    log_level: str = "INFO"
    json_logs: bool = True
    data_dir: str = "./data"


class APIConfig(BaseModel):
    """API server configuration."""
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class BacktestConfigSection(BaseModel):
    """Backtest configuration section."""
    default_initial_balance: Dict[str, float] = Field(default_factory=lambda: {
        "USDT": 10000.0,
        "USD": 10000.0,
    })
    allow_short: bool = True


class StrategyConfig(BaseModel):
    """Individual strategy configuration."""
    enabled: bool = False
    symbols: List[str] = Field(default_factory=list)


class LiveModeConfig(BaseModel):
    """Live trading mode configuration."""
    enabled: bool = False
    default_broker: str = "mock"
    confirmation_required: bool = True


class BrokerConfig(BaseModel):
    """Per-broker credentials and mode configuration."""
    testnet: bool = True
    paper: bool = True
    api_key_encrypted: str = ""
    api_secret_encrypted: str = ""


class SafetyConfig(BaseModel):
    """Live trading safety limits configuration.

    All defaults are conservative and safe:
    - paper/testnet mode
    - 5% max daily loss
    - 20% max single position
    - 50% max total exposure
    """
    max_daily_loss_pct: float = 5.0
    max_position_size_pct: float = 20.0
    max_exposure_pct: float = 50.0
    require_confirmation: bool = True
    kill_switch_on_disconnect: bool = True
    max_orders_per_minute: int = 10
    allowed_symbols: List[str] = Field(default_factory=list)
    blocked_symbols: List[str] = Field(default_factory=list)


class BotConfig(BaseSettings):
    """Root configuration object loaded from config.yaml and environment variables."""

    app: AppConfig = AppConfig()
    engine: EngineConfig = EngineConfig()
    market_data: MarketDataConfig = MarketDataConfig()
    risk: RiskConfig = RiskConfig()
    api: APIConfig = APIConfig()
    backtest: BacktestConfigSection = BacktestConfigSection()
    strategies: Dict[str, Any] = Field(default_factory=dict)
    live_mode: LiveModeConfig = LiveModeConfig()
    brokers: Dict[str, BrokerConfig] = Field(default_factory=lambda: {
        "binance": BrokerConfig(testnet=True, paper=False),
        "alpaca": BrokerConfig(testnet=False, paper=True),
        "mock": BrokerConfig(testnet=False, paper=False),
    })
    safety: SafetyConfig = SafetyConfig()

    model_config = SettingsConfigDict(
        env_prefix="BOT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BotConfig":
        """Load configuration from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

    def to_yaml(self, path: str | Path) -> None:
        """Save current configuration to a YAML file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.model_dump(mode="json"), f, default_flow_style=False, sort_keys=False)
