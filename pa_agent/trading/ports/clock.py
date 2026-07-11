"""Injectable UTC clock contract for trading persistence and reconciliation."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class UtcClock(Protocol):
    """Provides timezone-aware UTC time without exposing the system clock to callers."""

    def utc_now(self) -> datetime:
        """Return the current timezone-aware UTC timestamp."""
