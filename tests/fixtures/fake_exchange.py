"""Deterministic offline gateways for execution-boundary tests."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from threading import Event

from pa_agent.trading.domain.models import GatewayEvidence, RuleObservation
from pa_agent.trading.ports.gateway import GatewayUnavailableError
from pa_agent.trading.ports.ledger import OutboundSubmission


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


class ScriptedEvidenceGateway:
    """Consume a complete scripted evidence sequence and reject submissions."""

    def __init__(
        self,
        *,
        capabilities: Sequence[object],
        rules: Sequence[object],
        accounts: Sequence[object],
        quotes: Sequence[object],
        server_times: Sequence[object],
        connections: Sequence[object],
        open_orders: Sequence[object],
        order_rates: Sequence[object],
        loss_drawdowns: Sequence[object],
        fee_rates: Sequence[object],
    ) -> None:
        self._responses = {
            "capabilities": list(capabilities),
            "rules": list(rules),
            "account": list(accounts),
            "quote": list(quotes),
            "server_time": list(server_times),
            "connection": list(connections),
            "open_orders": list(open_orders),
            "order_rate": list(order_rates),
            "loss_drawdown": list(loss_drawdowns),
            "fee_rate": list(fee_rates),
        }
        self.call_order: list[str] = []
        self.submit_call_count = 0

    def _next(self, name: str) -> object:
        self.call_order.append(name)
        responses = self._responses[name]
        if not responses:
            raise AssertionError(f"unexpected {name} lookup")
        response = responses.pop(0)
        if isinstance(response, GatewayUnavailableError):
            raise response
        return response

    def get_capabilities(self) -> object:
        return self._next("capabilities")

    def get_instrument_rules(self, symbol: str) -> object:
        del symbol
        return self._next("rules")

    def get_account_snapshot(self, account_id: str, product: object) -> object:
        del account_id, product
        return self._next("account")

    def get_quote(self, symbol: str) -> object:
        del symbol
        return self._next("quote")

    def get_server_time(self) -> object:
        return self._next("server_time")

    def get_connection(self, target: object) -> object:
        del target
        return self._next("connection")

    def get_open_order_count(self, target: object) -> object:
        del target
        return self._next("open_orders")

    def get_order_rate_window(self, target: object, window_seconds: int) -> object:
        del target, window_seconds
        return self._next("order_rate")

    def get_loss_drawdown(self, target: object) -> object:
        del target
        return self._next("loss_drawdown")

    def get_fee_rate(self, target: object, symbol: str, quote_identifier: str) -> object:
        del target, symbol, quote_identifier
        return self._next("fee_rate")

    def submit_order(self, *args: object, **kwargs: object) -> GatewayEvidence:
        self.submit_call_count += 1
        raise AssertionError("evidence collection must never submit an order")


class BlockingSubmissionGateway:
    """In-memory coordinator fake that blocks after protected authorization."""

    def __init__(self) -> None:
        self.submit_started = Event()
        self.release_submit = Event()
        self.outbound_submissions: list[OutboundSubmission] = []

    def submit_order(self, outbound: OutboundSubmission) -> None:
        """Record one authorization and wait for the deterministic race interleaving."""
        self.outbound_submissions.append(outbound)
        self.submit_started.set()
        if not self.release_submit.wait(timeout=1):
            raise AssertionError("test did not release the blocking gateway")
