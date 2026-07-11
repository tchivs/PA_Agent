"""Deterministic reconciliation-only gateway for execution recovery tests."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from pa_agent.trading.domain.models import GatewayEvidence, RuleObservation
from pa_agent.trading.ports.gateway import GatewayUnavailableError


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

    def set_evidence(self, client_order_id: str, evidence: GatewayEvidence | None) -> None:
        """Replace one deterministic lookup response for a later recovery attempt."""
        self._evidence_by_client_order_id[client_order_id] = evidence

    def submit_order(self, *args: object, **kwargs: object) -> GatewayEvidence:
        """Reject every submission because recovery may only obtain evidence."""
        self.submit_call_count += 1
        raise AssertionError("recovery must never submit an order")


class ScriptedInstrumentRuleGateway:
    """Consume scripted rule observations and reject every attempted submission."""

    def __init__(self, responses: Sequence[RuleObservation | GatewayUnavailableError]) -> None:
        self._responses = list(responses)
        self.instrument_rule_symbols: list[str] = []
        self.submit_call_count = 0

    def get_instrument_rules(self, symbol: str) -> RuleObservation:
        """Record one symbol lookup and return its next typed scripted response."""
        self.instrument_rule_symbols.append(symbol)
        if not self._responses:
            raise AssertionError("unexpected instrument-rule lookup")
        response = self._responses.pop(0)
        if isinstance(response, GatewayUnavailableError):
            raise response
        return response

    def submit_order(self, *args: object, **kwargs: object) -> GatewayEvidence:
        """Reject every submission because validation may only obtain rule metadata."""
        self.submit_call_count += 1
        raise AssertionError("validation must never submit an order")
