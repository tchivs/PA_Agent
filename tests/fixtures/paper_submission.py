"""Test-only leased-submission seam for Paper accounting unit contracts.

Production PaperGateway instances receive a SQLite-backed verifier through
PaperTradingRuntime.  This fixture models only the verifier boundary, so product
accounting tests can issue an authorization without recreating approval workflows.
"""
from __future__ import annotations

from pa_agent.trading.domain.models import ExecutionCommand
from pa_agent.trading.ports.ledger import OutboundSubmission


class TestLeasedSubmissionVerifier:
    """Issue process-local test leases and reject every unissued lookalike value."""

    __test__ = False

    def __init__(self) -> None:
        self._issued: dict[str, OutboundSubmission] = {}

    def lease(self, command: ExecutionCommand) -> OutboundSubmission:
        """Create one test authorization tied to the exact immutable command."""
        outbound = OutboundSubmission(
            command=command,
            command_id=command.command_id,
            client_order_id=command.client_order_id,
            reconciliation_job_id=f"test-job:{command.command_id}",
            outbound_attempt_token=f"test-lease:{command.command_id}",
        )
        if outbound.client_order_id in self._issued:
            raise AssertionError("test lease may be issued only once per client order")
        self._issued[outbound.client_order_id] = outbound
        return outbound

    def validate_leased_outbound_submission(self, outbound: OutboundSubmission) -> None:
        """Reject local lookalikes instead of simulating durable authority."""
        if self._issued.get(outbound.client_order_id) != outbound:
            raise AssertionError("Paper test gateway requires an issued test lease")
