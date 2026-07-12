"""Read-only completed-analysis snapshot contract for the trading boundary."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pa_agent.trading.domain.approval import SourceAnalysisSnapshot


@runtime_checkable
class CompletedAnalysisSnapshotReader(Protocol):
    """Load a completed frozen snapshot by its stable persisted source identifier."""

    def load_completed_snapshot(self, source_id: str) -> SourceAnalysisSnapshot | None:
        """Return one immutable completed snapshot without exposing storage details."""
