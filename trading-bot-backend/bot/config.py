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
    # Crypto taker fee (Alpaca ~15-25 bps). Equities are commission-free, so
    # the live broker path applies this only to crypto symbols. Wired onto the
    # broker by LiveTradingEngine.__init__ (audit 2026-06-09 fee fix).
    crypto_fee_rate: float = 0.0025
    slippage_model: str = "fixed"
    slippage_bps: float = 5.0
    # ATR-adaptive stop floor (audit 2026-06-09 timeframe-mismatch fix). Entries
    # decide on daily bars but stops fire on the live 5s tick, so a fixed % stop
    # gets shaken out by normal intraday range. Widen the stop to >= mult*ATR so
    # a daily-cadence entry survives its own noise. Only widens, never tightens;
    # clamped to [min, max]; no-op when OHLCV isn't available.
    atr_stop_enabled: bool = True
    atr_stop_mult: float = 2.5
    atr_stop_period: int = 14
    atr_stop_min_pct: float = 0.03
    atr_stop_max_pct: float = 0.12
    # Profit-manager knobs (previously getattr-only phantoms on the engine —
    # unconfigurable without a code change). Fractions of entry price. When a
    # position carries atr_stop_pct, breakeven/giveback are widened to
    # 1.25x/1.0x that value so high-vol names aren't scratched at +4% by
    # normal range (the sltp_manager "62% wins yet net -$931" signature).
    pm_breakeven_pct: float = 0.04
    pm_trail_arm_pct: float = 0.08
    pm_trail_giveback_pct: float = 0.08
    pm_partial_enabled: bool = False
    # ATR multipliers for the scaling above (review 2026-06-09: hardcoding
    # them re-created the unconfigurable-exit-policy problem the pm_* keys
    # exist to solve). breakeven AND trail-arm both scale by the same floor —
    # arming the trail before breakeven re-tightens the stop inside the noise
    # band the ATR sizing is meant to stay out of.
    pm_atr_breakeven_mult: float = 1.25
    pm_atr_trail_arm_mult: float = 1.25
    pm_atr_giveback_mult: float = 1.0


class CapitalDeploymentConfig(BaseModel):
    """Paper-mode capital allocator settings."""
    enabled: bool = True
    target_exposure_pct: float = 95.0
    max_cash_pct: float = 20.0
    min_cash_reserve_pct: float = 5.0
    position_pct: float = 5.0
    max_new_positions_per_cycle: int = 2
    deploy_interval_minutes: float = 30.0
    min_score: float = 48.0
    min_source_count: int = 2
    max_open_positions: int = 28
    initial_stop_loss_pct: float = 0.07
    initial_take_profit_pct: float = 0.20
    asset_class: str = "stock"
    min_order_notional: float = 25.0


class PromotionGateSettings(BaseModel):
    """CPCV + Deflated-Sharpe gate on apply-hyperopt / go-live. Default ON.

    When ``enabled``, applying hyperopt params requires the candidate to clear
    combinatorial purged cross-validation with a Deflated Sharpe Ratio above
    ``min_dsr`` — the discipline that blocks promoting a curve-fit edge.

    Default ON as of 2026-06-09: the Sharpe-annualization bug (#8) that made the
    gate reject real edges as noise is fixed, so the gate is now trustworthy.
    The apply-hyperopt route still honors ``force=true`` to override.
    """
    enabled: bool = True
    n_groups: int = 6
    n_test_groups: int = 2
    embargo_pct: float = 0.01
    min_dsr: float = 0.5
    min_oos_sharpe: float = 0.0
    min_trades_per_fold: int = 3


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
    # Shorter window in paper mode so take-profit exits can re-enter sooner.
    post_close_cooldown_minutes: float = 15.0


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

    Defaults match paper-mode operator tuning (see config.yaml):
    - 5% max daily loss
    - 20% max single position
    - 300% max total exposure (multi-bot crypto books)
    - 300 orders/minute rate budget
    """
    max_daily_loss_pct: float = 5.0
    max_position_size_pct: float = 20.0
    max_exposure_pct: float = 300.0
    # Hard per-position loss cap, as a PERCENT of entry (engine converts to a
    # fraction). Force-closes any position down more than this regardless of its
    # own stop — bounds the tail. Tightened 10 -> 6: realized P&L was a high
    # win-rate masking a 0.58 profit factor, because a few names ran to -8/-10%
    # (META -$292, ENLT -$401) while winners were trimmed at +8%. 0 = off.
    max_position_loss_pct: float = 6.0
    # When True, a position whose ATR-sized stop is WIDER than the cap above
    # keeps its ATR distance (the cap would otherwise front-run the stop and
    # re-create the churn the ATR floor fixes). Operator-facing switch so the
    # safety knob is never silently overridden without consent (review
    # 2026-06-09); set False to make max_position_loss_pct absolute.
    atr_widens_position_loss_cap: bool = True
    require_confirmation: bool = True
    kill_switch_on_disconnect: bool = True
    max_orders_per_minute: int = 300
    allowed_symbols: List[str] = Field(default_factory=list)
    blocked_symbols: List[str] = Field(default_factory=list)
    # Alert channels
    webhook_url: str = ""
    webhook_headers: Dict[str, str] = Field(default_factory=dict)
    # Email alerts (SMTP)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password_encrypted: str = ""
    alert_email_from: str = ""
    alert_email_to: str = ""


class BotConfig(BaseSettings):
    """Root configuration object loaded from config.yaml and environment variables."""

    app: AppConfig = AppConfig()
    engine: EngineConfig = EngineConfig()
    market_data: MarketDataConfig = MarketDataConfig()
    risk: RiskConfig = RiskConfig()
    capital_deployment: CapitalDeploymentConfig = CapitalDeploymentConfig()
    promotion_gate: PromotionGateSettings = PromotionGateSettings()
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
