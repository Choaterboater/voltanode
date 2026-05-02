"""Kill switch — hard trading halt.

Once activated, no orders can execute until manually deactivated.
This is the final safety net for runaway losses or system failures.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


class KillSwitchError(Exception):
    """Raised when the kill switch is active and an order is attempted."""
    pass


class KillSwitch:
    """Hard trading halt mechanism.

    Attributes:
        activated: Whether the kill switch is currently active.
        reason: Human-readable reason for activation.
        activated_at: Timestamp when the switch was flipped.
    """

    def __init__(self) -> None:
        self.activated: bool = False
        self.reason: Optional[str] = None
        self.activated_at: Optional[datetime] = None

    def activate(self, reason: str) -> None:
        """Activate the kill switch. Once on, stays on until deactivate().

        Args:
            reason: Why trading was halted (logged and returned in errors).
        """
        self.activated = True
        self.reason = reason
        self.activated_at = datetime.now()

    def deactivate(self) -> None:
        """Manually reset the kill switch. Requires explicit operator action."""
        self.activated = False
        self.reason = None
        self.activated_at = None

    def check(self) -> None:
        """Verify the kill switch is not active.

        Raises:
            KillSwitchError: If the kill switch is activated.
        """
        if self.activated:
            raise KillSwitchError(
                f"Trading halted: {self.reason} (activated at {self.activated_at.isoformat() if self.activated_at else 'unknown'})"
            )

    def status(self) -> dict:
        """Return current kill switch status as a dict."""
        return {
            "activated": self.activated,
            "reason": self.reason,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
        }
