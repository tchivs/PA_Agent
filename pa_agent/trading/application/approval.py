"""Restricted approval-ticket lifecycle coordination with no submission capability."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pa_agent.trading.domain.approval import (
    ApprovalTicket,
    CandidateExecutionIntent,
    TicketBinding,
    TicketTerminalEvent,
)
from pa_agent.trading.domain.risk import RiskAssessment
from pa_agent.trading.ports.ledger import ExecutionLedger


class ApprovalService:
    """Issue and terminate review tickets using only durable proposal facts."""

    def __init__(self, *, ledger: ExecutionLedger, utc_now: Callable[[], datetime]) -> None:
        self._ledger = ledger
        self._utc_now = utc_now

    def create_pending_ticket(
        self, candidate: CandidateExecutionIntent, assessment: RiskAssessment
    ) -> ApprovalTicket:
        """Idempotently create the one pending ticket after persisted acceptance."""
        if not assessment.accepted:
            raise ValueError("only an accepted persisted risk assessment can issue a ticket")
        if assessment.policy_version != "phase2-v1":
            raise ValueError("pending tickets require the fixed phase2-v1 policy")
        return self._ledger.create_pending_ticket_if_absent(candidate, assessment, self._utc_now())

    def reject_ticket(self, ticket_id: str, reason: str) -> ApprovalTicket:
        """Persist an operator rejection with its durable binding snapshot."""
        return self._ledger.terminate_approval_ticket(
            ticket_id, TicketTerminalEvent.OPERATOR_REJECTED, reason
        )

    def expire_ticket(self, ticket_id: str, reason: str) -> ApprovalTicket:
        """Persist expiry without collecting fresh evidence or consuming authority."""
        return self._ledger.terminate_approval_ticket(ticket_id, TicketTerminalEvent.EXPIRED, reason)

    def invalidate_ticket(
        self, ticket_id: str, reason: str, binding: TicketBinding
    ) -> ApprovalTicket:
        """Persist a detected binding mutation with the caller's binding snapshot."""
        return self._ledger.terminate_approval_ticket(
            ticket_id, TicketTerminalEvent.BINDING_INVALIDATED, reason, binding
        )
