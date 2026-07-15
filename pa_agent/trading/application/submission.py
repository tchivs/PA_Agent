"""One-way application coordination for future abstract gateway submissions."""
from __future__ import annotations

from pa_agent.trading.ports.gateway import (
    GatewayOperationObserver,
    GatewayOperationResult,
    TradingGateway,
)
from pa_agent.trading.ports.ledger import ExecutionLedger, OutboundDispatchPermit


class SubmissionCoordinator:
    """Authorize exactly one outbound gateway call through the durable ledger.

    The coordinator accepts only the irreversible ledger authorization returned
    from ticket consumption. It has no command, ticket, admission, or claim
    input and therefore cannot recreate authority after a gateway exception.
    """

    def __init__(
        self,
        *,
        ledger: ExecutionLedger,
        gateway: TradingGateway,
        operation_observer: GatewayOperationObserver | None = None,
    ) -> None:
        self._ledger = ledger
        self._gateway = gateway
        self._operation_observer = operation_observer

    def submit(self, permit: OutboundDispatchPermit) -> GatewayOperationResult:
        """Lease one permit, then make the sole gateway call with the rebuilt value."""
        if type(permit) is not OutboundDispatchPermit:
            raise TypeError("submission coordinator accepts only dispatch permits")
        outbound = self._ledger.lease_outbound_submission(permit)
        try:
            result = self._gateway.submit_order(outbound)
        except Exception:
            self._ledger.mark_outbound_submission_ambiguous(outbound)
            raise
        if self._operation_observer is not None:
            try:
                self._operation_observer.observe_operation(result)
            except Exception:
                self._ledger.mark_outbound_submission_ambiguous(outbound)
                raise
        return result
