"""Deterministic reconciliation-only gateway for execution recovery tests."""
from __future__ import annotations

from collections.abc import Mapping

from pa_agent.trading.domain.models import GatewayEvidence


class ReconciliationOnlyGateway:
    """Return scripted lookup evidence and fail if recovery tries to submit an order."""

    def __init__(self, evidence_by_client_order_id: Mapping[str, GatewayEvidence | None]) -> None:
        self._evidence_by_client_order_id = dict(evidence_by_client_order_id)
        self.lookup_client_order_ids: list[str] = []
        self.submit_call_count = 0

    def lookup_order_by_client_id(self, client_order_id: str) -> GatewayEvidence | None:
        """Record the persisted client ID lookup and return its scripted evidence."""
        self.lookup_client_order_ids.append(client_order_id)
        return self._evidence_by_client_order_id.get(client_order_id)

    def submit_order(self, *args: object, **kwargs: object) -> GatewayEvidence:
        """Reject every submission because recovery may only obtain evidence."""
        self.submit_call_count += 1
        raise AssertionError("recovery must never submit an order")
