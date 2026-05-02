# Live Trading Architecture Spec — VoltaNode

## Overview
Add a **Live Trading Mode** toggle to VoltaNode. The platform starts in Paper Mode (default). Users can flip to Live Mode after configuring broker credentials and safety settings. Live mode connects to real exchanges via broker adapters and executes real orders.

## Design Principles
1. **Paper-first, always.** Live mode is opt-in with multiple confirmations.
2. **Safety by default.** Hard kill switch, max loss limits, position size caps.
3. **One toggle, clear status.** The entire UI changes when live mode is on.
4. **Broker-agnostic.** Adapter pattern supports multiple exchanges.

## Backend Architecture

### New Module: `brokers/`
```
brokers/
  ├── __init__.py
  ├── base.py              # BrokerAdapter abstract class
  ├── binance.py           # Binance spot API adapter
  ├── alpaca.py            # Alpaca (US stocks) adapter
  ├── mock.py              # Mock broker for testing
  └── registry.py          # Broker factory/registry
```

`BrokerAdapter` interface:
- `connect(api_key, secret) -> bool`
- `get_balance() -> Dict[str, float]`
- `get_price(symbol) -> float`
- `place_order(order: Order) -> FillResult`
- `get_positions() -> List[Position]`
- `cancel_order(order_id) -> bool`
- `get_account_info() -> Dict`
- `is_connected() -> bool`

### Enhanced Engine: `bot/engine.py`
The existing `PaperTradingEngine` becomes the base. Add `LiveTradingEngine`:
```python
class LiveTradingEngine(PaperTradingEngine):
    def __init__(self, config: BotConfig, broker: BrokerAdapter):
        super().__init__(config)
        self.broker = broker
        self.live_mode = True
        self.daily_pnl_tracker = DailyPnlTracker()
        self.kill_switch_activated = False
    
    def execute_order(self, order: Order, current_price: float = None) -> FillResult:
        if self.kill_switch_activated:
            raise KillSwitchError("Trading halted. Kill switch is active.")
        if not self.broker.is_connected():
            raise BrokerConnectionError("Broker not connected.")
        
        # Safety checks
        self._check_max_daily_loss()
        self._check_position_size(order)
        self._check_exposure_limits(order)
        
        # Execute via broker
        fill = self.broker.place_order(order)
        self.daily_pnl_tracker.record(fill)
        return fill
    
    def _check_max_daily_loss(self):
        if self.daily_pnl_tracker.daily_pnl < -self.config.risk.max_daily_loss_pct:
            self.kill_switch_activated = True
            raise DailyLossLimitError("Daily loss limit exceeded. Trading halted.")
```

### New Module: `safety/`
```
safety/
  ├── __init__.py
  ├── kill_switch.py       # Kill switch logic
  ├── daily_tracker.py     # Daily P&L tracking
  ├── limits.py            # Position size, exposure validators
  └── notifier.py          # Alerts (console, webhook, email stubs)
```

### API Changes: `api/routes/settings.py`
New endpoints:
```
GET  /settings/live-mode          -> {live_mode: bool, broker: str, safety_config: {...}}
POST /settings/live-mode          -> {live_mode: bool}  # Toggle with confirmation
GET  /settings/brokers            -> List available brokers
POST /settings/broker             -> Configure broker (api_key, secret, testnet)
POST /settings/api-keys           -> Store encrypted API keys
POST /settings/safety             -> Configure max_daily_loss, max_position_pct, etc.
POST /settings/kill-switch        -> Activate kill switch
GET  /settings/safety-status      -> Current safety metrics
```

### API Key Security
- Store encrypted using `cryptography.fernet.Fernet`
- Encryption key from environment variable `VOLTANODE_SECRET_KEY`
- Never return decrypted keys in API responses
- API keys only decrypted when connecting to broker

### Config Updates
```yaml
# New sections in config.yaml
live_mode:
  enabled: false
  default_broker: "binance"
  confirmation_required: true

brokers:
  binance:
    testnet: true
    api_key: ""
    api_secret: ""
  alpaca:
    paper: true
    api_key: ""
    api_secret: ""

safety:
  max_daily_loss_pct: 5.0          # Stop trading after 5% daily loss
  max_position_size_pct: 20.0     # No position > 20% of portfolio
  max_exposure_pct: 50.0          # Total exposure < 50%
  require_confirmation: true        # Confirm every live order
  kill_switch_on_disconnect: true # Kill switch if broker disconnects
  max_orders_per_minute: 10       # Rate limit
  allowed_symbols: []             # Whitelist (empty = all)
  blocked_symbols: []             # Blacklist
```

## Frontend Architecture

### New Component: `ModeToggle` (in top bar)
- Toggle switch: PAPER (cyan) ↔ LIVE (red)
- When LIVE: entire top bar gets red border/glow
- Shows current broker name
- Click to open confirmation modal

### New Banner: `LiveModeBanner`
- Fixed banner below top bar when live mode is ON
- Red background, white text: "⚠ LIVE TRADING MODE — REAL MONEY AT RISK"
- Shows kill switch button
- Shows broker status (connected / disconnected)
- Shows daily P&L and remaining loss budget

### New Page: `Settings` (`/#/settings`)
Tabs:
1. **Trading Mode** — Live/Paper toggle with warnings
2. **Broker Setup** — Select broker, enter API keys (masked), test connection
3. **Safety Limits** — Sliders for max loss, position size, exposure
4. **Kill Switch** — Emergency stop, status display

### Page Updates
- **Order Entry (PaperTrading)**: When live, button says "PLACE LIVE ORDER" in red
- **Bot Lab**: Bots show PAPER/LIVE badge. Live bots have red warning
- **Dashboard**: Portfolio value is real when live, virtual when paper
- **All Pages**: Live mode banner is persistent across all routes

## Data Flow
```
User toggles Live Mode
  → Confirmation modal (3-step: warning → API check → confirm)
  → Frontend POST /settings/live-mode
  → Backend:
    1. Validate API keys are configured
    2. Test broker connection
    3. Set live_mode flag
    4. Activate safety limits
    5. Return status
  → Frontend:
    1. Show live mode banner
    2. Update all order buttons
    3. Start polling broker status
```

## Safety Checklist (Before Going Live)
- [ ] Paper trading for minimum 30 days
- [ ] Consistent profitability in backtests
- [ ] API keys configured and tested
- [ ] Max daily loss limit set (recommend 2-5%)
- [ ] Position size limits set (recommend 10-20%)
- [ ] Kill switch tested
- [ ] Broker testnet/paper verified
- [ ] Allowed symbols configured

## Implementation Order
1. Backend: Broker adapters (base + mock)
2. Backend: LiveTradingEngine with safety rails
3. Backend: Settings API routes
4. Backend: API key encryption
5. Frontend: ModeToggle component
6. Frontend: LiveModeBanner
7. Frontend: Settings page
8. Frontend: Update all order buttons with paper/live labels
9. Integration testing
