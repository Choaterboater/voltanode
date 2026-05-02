"""Safety notifier — console logging + webhook + email alerts.

Can be extended to send Slack/Discord/SMS alerts on safety events.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

logger = logging.getLogger("volta.safety")


class SafetyNotifier:
    """Multi-channel safety alert notifier.

    Levels: info, warning, critical.
    Critical alerts are also sent to configured webhooks and email.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        webhook_headers: Optional[Dict[str, str]] = None,
        email_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.webhook_headers = webhook_headers or {}
        self.email_config = email_config or {}
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

        if level == "critical":
            self._send_webhook(entry)
            self._send_email(entry)

    def _send_webhook(self, payload: dict) -> None:
        """Send alert to configured webhook URL with retry logic."""
        if not self.webhook_url:
            return
        try:
            import requests
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=self.webhook_headers,
                timeout=5,
            )
            response.raise_for_status()
            logger.info(f"Webhook alert sent successfully to {self.webhook_url}")
        except Exception as exc:
            logger.error(f"Webhook alert failed: {exc}")

    def _send_email(self, payload: dict) -> None:
        """Send alert via SMTP email."""
        cfg = self.email_config
        smtp_host = cfg.get("smtp_host", "")
        smtp_port = cfg.get("smtp_port", 587)
        smtp_user = cfg.get("smtp_user", "")
        smtp_password = cfg.get("smtp_password", "")
        email_from = cfg.get("email_from", "")
        email_to = cfg.get("email_to", "")

        if not smtp_host or not email_from or not email_to:
            return

        try:
            subject = f"[VoltaNode CRITICAL] {payload['message'][:80]}"
            body = (
                f"VoltaNode Safety Alert\n"
                f"=====================\n"
                f"Level: {payload['level']}\n"
                f"Time:  {payload['timestamp']}\n"
                f"Message: {payload['message']}\n"
            )
            if payload.get("extra"):
                body += f"Extra: {payload['extra']}\n"

            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = email_from
            msg["To"] = email_to

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                if smtp_user and smtp_password:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                server.sendmail(email_from, email_to.split(","), msg.as_string())

            logger.info(f"Email alert sent to {email_to}")
        except Exception as exc:
            logger.error(f"Email alert failed: {exc}")

    def get_history(self, limit: int = 100) -> list:
        """Return recent alert history."""
        return self._alert_history[-limit:]
