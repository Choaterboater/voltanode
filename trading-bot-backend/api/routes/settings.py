"""Settings API routes for live trading configuration.

Endpoints:
    GET  /settings/live-mode          -> Current live mode status
    POST /settings/live-mode          -> Toggle live mode
    GET  /settings/brokers            -> List available brokers
    POST /settings/broker              -> Configure broker (testnet, paper)
    POST /settings/api-keys            -> Store encrypted API keys
    POST /settings/safety              -> Configure safety limits
    POST /settings/kill-switch         -> Activate/deactivate kill switch
    GET  /settings/safety-status       -> Current safety metrics
    POST /settings/restart             -> Restart the backend process
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from bot.config import BotConfig
from brokers.registry import get_broker, list_brokers
from security.encryption import ApiKeyStore

logger = logging.getLogger("volta.api.settings")

router = APIRouter()


@router.post("/restart")
async def restart_backend() -> Dict[str, Any]:
    """Spawn a detached helper that waits briefly, kills this backend, and
    starts a fresh one in a new console.

    Returns immediately so the HTTP response lands before this process dies.
    The frontend should poll ``GET /engine/status`` after ~3s to detect the
    new backend is up.

    Windows-only implementation: uses ``cmd /c`` + ``start`` to detach the
    restart helper from the dying parent process.
    """
    parent_pid = os.getpid()
    # routes/ -> api/ -> trading-bot-backend/
    backend_dir = Path(__file__).resolve().parents[2]

    # Detached cmd chain:
    #   1. wait 2s so this HTTP response can complete
    #   2. force-kill the current backend
    #   3. cd into the backend dir
    #   4. spawn a new backend in its own console window
    chain = (
        f'timeout /t 2 /nobreak >nul & '
        f'taskkill /F /PID {parent_pid} >nul 2>&1 & '
        f'cd /d "{backend_dir}" & '
        f'start "VoltaNode backend" cmd /k python run.py --mode api --host 127.0.0.1 --port 8000'
    )

    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    try:
        subprocess.Popen(
            f'cmd /c "{chain}"',
            shell=True,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except Exception as exc:
        logger.error(f"restart: failed to spawn helper: {exc}")
        raise HTTPException(status_code=500, detail=f"restart helper failed: {exc}")

    logger.warning(f"restart: scheduled (parent PID {parent_pid} will die in ~2s)")
    return {
        "scheduled": True,
        "pid_to_kill": parent_pid,
        "estimated_downtime_sec": 5,
    }


# ── Pydantic Request / Response Models ──

class LiveModeToggleRequest(BaseModel):
    enabled: bool
    broker_name: Optional[str] = None


class LiveModeStatusResponse(BaseModel):
    live_mode: bool
    broker_name: str
    broker_connected: bool
    confirmation_required: bool


class BrokerListResponse(BaseModel):
    brokers: Dict[str, str]


class BrokerConfigRequest(BaseModel):
    broker_name: str
    testnet: Optional[bool] = None
    paper: Optional[bool] = None


class RegisterBrokerRequest(BaseModel):
    broker_name: str
    description: Optional[str] = None
    testnet: Optional[bool] = True
    paper: Optional[bool] = True


class BrokerConfigResponse(BaseModel):
    broker_name: str
    testnet: bool
    paper: bool
    api_key_configured: bool
    api_secret_configured: bool


class ApiKeysRequest(BaseModel):
    broker_name: str
    api_key: str
    api_secret: str


class ApiKeysResponse(BaseModel):
    broker_name: str
    api_key_stored: bool
    api_secret_stored: bool
    message: str


class SafetyConfigRequest(BaseModel):
    max_daily_loss_pct: Optional[float] = None
    max_position_size_pct: Optional[float] = None
    max_exposure_pct: Optional[float] = None
    require_confirmation: Optional[bool] = None
    kill_switch_on_disconnect: Optional[bool] = None
    max_orders_per_minute: Optional[int] = None
    allowed_symbols: Optional[list] = None
    blocked_symbols: Optional[list] = None


class SafetyConfigResponse(BaseModel):
    max_daily_loss_pct: float
    max_position_size_pct: float
    max_exposure_pct: float
    require_confirmation: bool
    kill_switch_on_disconnect: bool
    max_orders_per_minute: int
    allowed_symbols: list
    blocked_symbols: list


class KillSwitchRequest(BaseModel):
    action: str  # "activate" | "deactivate"
    reason: Optional[str] = None


class KillSwitchResponse(BaseModel):
    activated: bool
    reason: Optional[str] = None
    activated_at: Optional[str] = None


class SafetyStatusResponse(BaseModel):
    live_mode: bool
    broker_connected: bool
    kill_switch: dict
    daily_tracker: dict
    safety_limits: dict


class TestConnectionResponse(BaseModel):
    broker_name: str
    connected: bool
    message: str


# ── Helper: get engine from app state ──

def _get_engine(request: Request):
    return getattr(request.app.state, "engine", None)


def _get_config(request: Request) -> BotConfig:
    cfg = getattr(request.app.state, "config", None)
    if cfg is None:
        raise HTTPException(status_code=503, detail="Server configuration not initialized")
    return cfg


def _get_key_store() -> Optional[ApiKeyStore]:
    """Attempt to create an ApiKeyStore from env. Returns None if no key set."""
    try:
        return ApiKeyStore.from_env()
    except RuntimeError:
        return None


# ── Endpoints ──

@router.get("/live-mode", response_model=LiveModeStatusResponse)
async def get_live_mode(request: Request) -> dict:
    """Get current live mode status."""
    config = _get_config(request)
    engine = _get_engine(request)

    broker_connected = False
    broker_name = config.live_mode.default_broker
    if engine and hasattr(engine, "broker"):
        if config.live_mode.enabled:
            # Live mode ON: report the actual running broker
            broker_name = engine.broker.name
            if engine.broker.name == "mock" and config.live_mode.default_broker != "mock":
                # Stale-mock: startup key restore failed, show configured broker as disconnected
                broker_connected = False
            else:
                broker_connected = engine.broker.is_connected()
        # Live mode OFF: broker_connected stays False — mock doesn't count as a real connection

    return {
        "live_mode": config.live_mode.enabled,
        "broker_name": broker_name,
        "broker_connected": broker_connected,
        "confirmation_required": config.live_mode.confirmation_required,
    }


@router.post("/live-mode", response_model=LiveModeStatusResponse)
async def set_live_mode(request: Request, body: LiveModeToggleRequest) -> dict:
    """Toggle live trading mode.

    - Validates broker selection.
    - Tests broker connection if live mode is being enabled.
    - Requires API keys to be stored for real brokers.
    """
    config = _get_config(request)
    engine = _get_engine(request)
    broker_name = body.broker_name or config.live_mode.default_broker

    if body.enabled:
        # Enabling live mode — validate everything
        if broker_name == "mock":
            # Mock broker: always OK, no keys needed
            if engine and hasattr(engine, "broker"):
                engine.broker.connect("mock_key", "mock_secret")
        else:
            # Real broker: check API keys exist
            broker_cfg = config.brokers.get(broker_name)
            if broker_cfg is None:
                raise HTTPException(status_code=400, detail=f"Broker '{broker_name}' not configured")
            if not broker_cfg.api_key_encrypted or not broker_cfg.api_secret_encrypted:
                raise HTTPException(
                    status_code=400,
                    detail=f"API keys for '{broker_name}' not stored. Use POST /settings/api-keys first.",
                )

            # Swap to real broker on the existing engine
            if engine and hasattr(engine, "broker"):
                try:
                    from brokers.registry import get_broker
                    real_broker = get_broker(broker_name)
                    key_store = _get_key_store()
                    if key_store:
                        api_key = key_store.decrypt(broker_cfg.api_key_encrypted)
                        api_secret = key_store.decrypt(broker_cfg.api_secret_encrypted)
                        real_broker.connect(
                            api_key, api_secret,
                            testnet=getattr(broker_cfg, "testnet", True),
                            paper=getattr(broker_cfg, "paper", True),
                        )
                        try:
                            engine.broker.disconnect()
                        except Exception:
                            pass
                        engine.broker = real_broker
                    else:
                        logger.warning("No encryption key available; cannot connect real broker")
                except Exception as exc:
                    logger.error(f"Broker connection failed: {exc}")
                    raise HTTPException(status_code=400, detail=f"Broker connection failed: {exc}")
    else:
        # Disabling live mode — swap back to mock broker
        if engine and hasattr(engine, "broker"):
            from brokers.registry import get_broker
            try:
                engine.broker.disconnect()
            except Exception:
                pass
            mock_broker = get_broker("mock")
            mock_broker.connect("mock_key", "mock_secret")
            engine.broker = mock_broker

    config.live_mode.enabled = body.enabled
    if body.broker_name:
        config.live_mode.default_broker = body.broker_name

    # Persist config to disk so default_broker survives restarts
    try:
        import os
        config_path = os.environ.get("BOT_CONFIG", "config.yaml")
        config.to_yaml(config_path)
    except Exception as exc:
        logger.warning(f"Failed to persist config: {exc}")

    return {
        "live_mode": config.live_mode.enabled,
        "broker_name": broker_name,
        "broker_connected": engine.broker.is_connected() if engine and hasattr(engine, "broker") else False,
        "confirmation_required": config.live_mode.confirmation_required,
    }


@router.get("/brokers", response_model=BrokerListResponse)
async def list_available_brokers(request: Request) -> dict:
    """Return all registered broker adapters and configured brokers."""
    config = _get_config(request)
    registered = list_brokers()
    # Merge with any dynamically configured brokers
    for name, cfg in config.brokers.items():
        if name not in registered:
            registered[name] = f"Custom broker ({name})"
    return {"brokers": registered}


@router.post("/broker", response_model=BrokerConfigResponse)
async def configure_broker(request: Request, body: BrokerConfigRequest) -> dict:
    """Configure broker settings (testnet/paper mode)."""
    config = _get_config(request)
    broker_cfg = config.brokers.get(body.broker_name)
    if broker_cfg is None:
        raise HTTPException(status_code=400, detail=f"Unknown broker: {body.broker_name}")

    if body.testnet is not None:
        broker_cfg.testnet = body.testnet
    if body.paper is not None:
        broker_cfg.paper = body.paper

    # Persist config to disk
    try:
        import os
        config_path = os.environ.get("BOT_CONFIG", "config.yaml")
        config.to_yaml(config_path)
    except Exception as exc:
        logger.warning(f"Failed to persist config: {exc}")

    return {
        "broker_name": body.broker_name,
        "testnet": broker_cfg.testnet,
        "paper": broker_cfg.paper,
        "api_key_configured": bool(broker_cfg.api_key_encrypted),
        "api_secret_configured": bool(broker_cfg.api_secret_encrypted),
    }


@router.get("/broker/{broker_name}", response_model=BrokerConfigResponse)
async def get_broker_config(request: Request, broker_name: str) -> dict:
    """Get current configuration for a broker (without exposing keys)."""
    config = _get_config(request)
    broker_cfg = config.brokers.get(broker_name)
    if broker_cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown broker: {broker_name}")

    return {
        "broker_name": broker_name,
        "testnet": broker_cfg.testnet,
        "paper": broker_cfg.paper,
        "api_key_configured": bool(broker_cfg.api_key_encrypted),
        "api_secret_configured": bool(broker_cfg.api_secret_encrypted),
    }


@router.post("/api-keys", response_model=ApiKeysResponse)
async def store_api_keys(request: Request, body: ApiKeysRequest) -> dict:
    """Encrypt and store API keys for a broker.

    Keys are encrypted with VOLTANODE_SECRET_KEY and stored in config.
    They are NEVER returned in any response.
    """
    config = _get_config(request)
    key_store = _get_key_store()
    if key_store is None:
        raise HTTPException(
            status_code=503,
            detail="Encryption not configured on server. Set VOLTANODE_SECRET_KEY.",
        )

    broker_cfg = config.brokers.get(body.broker_name)
    if broker_cfg is None:
        raise HTTPException(status_code=400, detail=f"Unknown broker: {body.broker_name}")

    # Encrypt and store
    broker_cfg.api_key_encrypted = key_store.encrypt(body.api_key)
    broker_cfg.api_secret_encrypted = key_store.encrypt(body.api_secret)

    # Immediately clear plaintext from memory
    del body.api_key
    del body.api_secret

    # Persist config to disk so keys survive restarts
    try:
        import os
        config_path = os.environ.get("BOT_CONFIG", "config.yaml")
        config.to_yaml(config_path)
        logger.info(f"Config persisted to {config_path}")
    except Exception as exc:
        logger.warning(f"Failed to persist config: {exc}")

    return {
        "broker_name": body.broker_name,
        "api_key_stored": True,
        "api_secret_stored": True,
        "message": "API keys encrypted and stored securely.",
    }


@router.post("/safety", response_model=SafetyConfigResponse)
async def configure_safety(request: Request, body: SafetyConfigRequest) -> dict:
    """Update safety limits configuration."""
    config = _get_config(request)
    safety = config.safety

    if body.max_daily_loss_pct is not None:
        safety.max_daily_loss_pct = body.max_daily_loss_pct
    if body.max_position_size_pct is not None:
        safety.max_position_size_pct = body.max_position_size_pct
    if body.max_exposure_pct is not None:
        safety.max_exposure_pct = body.max_exposure_pct
    if body.require_confirmation is not None:
        safety.require_confirmation = body.require_confirmation
    if body.kill_switch_on_disconnect is not None:
        safety.kill_switch_on_disconnect = body.kill_switch_on_disconnect
    if body.max_orders_per_minute is not None:
        safety.max_orders_per_minute = body.max_orders_per_minute
    if body.allowed_symbols is not None:
        safety.allowed_symbols = body.allowed_symbols
    if body.blocked_symbols is not None:
        safety.blocked_symbols = body.blocked_symbols

    # Push updates into the running SafetyValidator. Two distinct caches
    # need refreshing:
    #   1. validator.config — read by get_status() (the /safety-status
    #      response) and by validate_order() when no explicit config is
    #      threaded through. Stale here means the operator sees the old
    #      limits forever via /safety-status even though the BotConfig
    #      itself has been mutated.
    #   2. rate_limiter.max_per_minute — cached at constructor time.
    engine = _get_engine(request)
    if engine is not None and hasattr(engine, "safety_validator"):
        sv = engine.safety_validator
        sv.config.max_daily_loss_pct = safety.max_daily_loss_pct
        sv.config.max_position_size_pct = safety.max_position_size_pct
        sv.config.max_exposure_pct = safety.max_exposure_pct
        sv.config.max_orders_per_minute = safety.max_orders_per_minute
        sv.config.allowed_symbols = list(safety.allowed_symbols)
        sv.config.blocked_symbols = list(safety.blocked_symbols)
        sv.rate_limiter.max_per_minute = safety.max_orders_per_minute

    # Persist to disk so the limits survive the next restart. Without this
    # the BotConfig YAML keeps the old values and the engine boots back to
    # them. Pattern matches the other route handlers in this file (broker,
    # live-mode, app config).
    try:
        import os
        config_path = os.environ.get("BOT_CONFIG", "config.yaml")
        config.to_yaml(config_path)
    except Exception as exc:
        logger.warning(f"Failed to persist safety config: {exc}")

    return {
        "max_daily_loss_pct": safety.max_daily_loss_pct,
        "max_position_size_pct": safety.max_position_size_pct,
        "max_exposure_pct": safety.max_exposure_pct,
        "require_confirmation": safety.require_confirmation,
        "kill_switch_on_disconnect": safety.kill_switch_on_disconnect,
        "max_orders_per_minute": safety.max_orders_per_minute,
        "allowed_symbols": safety.allowed_symbols,
        "blocked_symbols": safety.blocked_symbols,
    }


@router.post("/kill-switch", response_model=KillSwitchResponse)
async def kill_switch_action(request: Request, body: KillSwitchRequest) -> dict:
    """Activate or deactivate the kill switch.

    Activation requires a reason.
    Deactivation requires explicit action.
    """
    engine = _get_engine(request)
    if engine is None or not hasattr(engine, "kill_switch"):
        raise HTTPException(status_code=400, detail="Live engine not initialized")

    ks = engine.kill_switch
    if body.action == "activate":
        reason = body.reason or "Manual activation via API"
        ks.activate(reason)
        logger.critical(f"Kill switch ACTIVATED: {reason}")
        if hasattr(engine, "notifier"):
            engine.notifier.alert("critical", f"Kill switch activated: {reason}")
    elif body.action == "deactivate":
        ks.deactivate()
        logger.warning("Kill switch DEACTIVATED")
        if hasattr(engine, "notifier"):
            engine.notifier.alert("warning", "Kill switch deactivated")
    else:
        raise HTTPException(status_code=400, detail="action must be 'activate' or 'deactivate'")

    return {
        "activated": ks.activated,
        "reason": ks.reason,
        "activated_at": ks.activated_at.isoformat() if ks.activated_at else None,
    }


@router.get("/safety-status", response_model=SafetyStatusResponse)
async def get_safety_status(request: Request) -> dict:
    """Get comprehensive safety status: kill switch, daily P&L, limits."""
    config = _get_config(request)
    engine = _get_engine(request)

    if engine and hasattr(engine, "get_live_status"):
        return {
            "live_mode": engine.live_mode if hasattr(engine, "live_mode") else config.live_mode.enabled,
            "broker_connected": engine.broker.is_connected() if hasattr(engine, "broker") else False,
            "kill_switch": engine.kill_switch.status() if hasattr(engine, "kill_switch") else {"activated": False},
            "daily_tracker": engine.daily_tracker.get_status() if hasattr(engine, "daily_tracker") else {},
            "safety_limits": engine.safety_validator.get_status() if hasattr(engine, "safety_validator") else {},
        }

    # Fallback for paper engine (no SafetyValidator / daily_tracker instance)
    return {
        "live_mode": False,
        "broker_connected": False,
        "kill_switch": {"activated": False},
        "daily_tracker": {},
        "safety_limits": {
            "max_daily_loss_pct": config.safety.max_daily_loss_pct,
            "max_position_size_pct": config.safety.max_position_size_pct,
            "max_exposure_pct": config.safety.max_exposure_pct,
            "max_position_loss_pct": config.safety.max_position_loss_pct,
            "max_orders_per_minute": config.safety.max_orders_per_minute,
            "allowed_symbols": list(config.safety.allowed_symbols),
            "blocked_symbols": list(config.safety.blocked_symbols),
            # Paper engine has no live rate counter; surface the configured cap.
            "orders_remaining_this_minute": config.safety.max_orders_per_minute,
        },
    }


@router.post("/register-broker", response_model=BrokerConfigResponse)
async def register_broker(request: Request, body: RegisterBrokerRequest) -> dict:
    """Register a new broker configuration dynamically.

    Creates a new BrokerConfig entry so API keys and settings can be stored
    for brokers not in the default registry.
    """
    config = _get_config(request)
    name = body.broker_name.lower().strip()
    if not name:
        raise HTTPException(status_code=400, detail="Broker name is required")

    if name not in config.brokers:
        from bot.config import BrokerConfig
        config.brokers[name] = BrokerConfig(
            testnet=body.testnet if body.testnet is not None else True,
            paper=body.paper if body.paper is not None else True,
        )
        logger.info(f"Registered new broker configuration: {name}")

    broker_cfg = config.brokers[name]
    return {
        "broker_name": name,
        "testnet": broker_cfg.testnet,
        "paper": broker_cfg.paper,
        "api_key_configured": bool(broker_cfg.api_key_encrypted),
        "api_secret_configured": bool(broker_cfg.api_secret_encrypted),
    }


@router.post("/disconnect")
async def disconnect_broker(request: Request) -> dict:
    """Disconnect from the current broker without deleting API keys."""
    engine = _get_engine(request)
    if engine and hasattr(engine, "broker"):
        try:
            engine.broker.disconnect()
            return {"status": "disconnected", "broker": engine.broker.name}
        except Exception as exc:
            logger.warning(f"Disconnect failed: {exc}")
            return {"status": "error", "message": str(exc)}
    return {"status": "noop", "message": "No live engine or broker available"}


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_broker_connection(request: Request, body: BrokerConfigRequest) -> dict:
    """Test broker connection without changing live mode."""
    config = _get_config(request)
    broker_cfg = config.brokers.get(body.broker_name)
    if broker_cfg is None:
        raise HTTPException(status_code=400, detail=f"Unknown broker: {body.broker_name}")

    try:
        broker = get_broker(body.broker_name)
        if body.broker_name == "mock":
            broker.connect("test_key", "test_secret")
            return {
                "broker_name": body.broker_name,
                "connected": True,
                "message": "Mock broker connected successfully.",
            }

        key_store = _get_key_store()
        if key_store is None:
            return {
                "broker_name": body.broker_name,
                "connected": False,
                "message": "VOLTANODE_SECRET_KEY not set — cannot decrypt keys.",
            }

        if not broker_cfg.api_key_encrypted or not broker_cfg.api_secret_encrypted:
            return {
                "broker_name": body.broker_name,
                "connected": False,
                "message": "API keys not stored. Use POST /settings/api-keys first.",
            }

        api_key = key_store.decrypt(broker_cfg.api_key_encrypted)
        api_secret = key_store.decrypt(broker_cfg.api_secret_encrypted)
        connected = broker.connect(
            api_key, api_secret,
            testnet=getattr(broker_cfg, "testnet", True),
            paper=getattr(broker_cfg, "paper", True),
        )
        return {
            "broker_name": body.broker_name,
            "connected": connected,
            "message": f"{'Connected' if connected else 'Failed'} to {body.broker_name}.",
        }
    except Exception as exc:
        return {
            "broker_name": body.broker_name,
            "connected": False,
            "message": f"Connection failed: {exc}",
        }
