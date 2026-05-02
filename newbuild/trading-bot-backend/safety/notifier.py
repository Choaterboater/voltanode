"""Safety notifier — console logging + webhook stub.

Can be extended to send Slack/Discord/email alerts on safety events.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("volta.safety")


class SafetyNotifier:
    """Multi-channel safety alert notifier.

    Levels: info, warning, critical.
    Critical alerts are also sent to configured webhooks.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        webhook_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.webhook_headers = webhook_headers or {}
        self._alert_history: list = []

    def alert(self, level: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Emit a safety alert.

        Args:
            level: One of "info", "warning", "critical".
            message: Human-readable alert text.
            extra: Optional key-value metadata.
        """
        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": ts,
            "level": level,
            "message": message,
            "extra": extra or {},
        }
        self._alert_history.append(entry)

        log_msg = f"[SAFETY {level.upper()}] {message}"
        if level == "critical":
            logger.critical(log_msg)
        elif level == "warning":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        if level == "critical" and self.webhook_url:
            self._send_webhook(entry)

    def _send_webhook(self, payload: dict) -> None:
        """Send alert to configured webhook URL. Stub — extend as needed."""
        logger.info(f"Webhook payload would be sent to {self.webhook_url}: {payload}")
        # Example real implementation:
        # import requests
        # requests.post(self.webhook_url, json=payload, headers=self.webhook_headers, timeout=5)

    def get_history(self, limit: int = 100) -> list:
        """Return recent alert history."""
        return self._alert_history[-limit:]
