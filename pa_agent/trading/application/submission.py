"""One-way application coordination for future abstract gateway submissions."""
from __future__ import annotations

from pa_agent.trading.domain.models import GatewayEvidence
from pa_agent.trading.ports.gateway import TradingGateway
from pa_agent.trading.ports.ledger import ExecutionLedger, OutboundSubmission


class SubmissionCoordinator:
    """Authorize exactly one outbound gateway call through the durable ledger.

    The coordinator accepts only the irreversible ledger authorization returned
    from ticket consumption. It has no command, ticket, admission, or claim
    input and therefore cannot recreate authority after a gateway exception.
    """

    def __init__(self, *, ledger: ExecutionLedger, gateway: TradingGateway) -> None:
        self._ledger = ledger
        self._gateway = gateway

    def submit(self, outbound: OutboundSubmission) -> GatewayEvidence:
        """Perform the single gateway call already authorized by the ledger."""
        if type(outbound) is not OutboundSubmission:
            raise TypeError("submission coordinator accepts only ledger-produced outbound submissions")
        try:
            return self._gateway.submit_order(outbound)
        except Exception:
            self._ledger.mark_outbound_submission_ambiguous(outbound)
            raise
