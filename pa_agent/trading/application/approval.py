"""Restricted approval-ticket lifecycle coordination with no submission capability."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from pa_agent.trading.application.evidence_collector import (
    EvidenceCollectionRejection,
    FreshEvidenceCollector,
)
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.approval import (
    ApprovalTicket,
    ApprovalTicketStatus,
    CandidateExecutionIntent,
    ExecutionTarget,
    TicketBinding,
    TicketTerminalEvent,
)
from pa_agent.trading.domain.risk import RiskAssessment, RiskPolicy
from pa_agent.trading.ports.ledger import ExecutionLedger, OutboundDispatchPermit


class ApprovalService:
    """Issue and terminate review tickets using only durable proposal facts."""

    def __init__(
        self,
        *,
        ledger: ExecutionLedger,
        utc_now: Callable[[], datetime],
        evidence_collector: FreshEvidenceCollector | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self._ledger = ledger
        self._utc_now = utc_now
        self._evidence_collector = evidence_collector
        self._risk_engine = risk_engine

    def create_pending_ticket(
        self, candidate: CandidateExecutionIntent, assessment: RiskAssessment
    ) -> ApprovalTicket:
        """Idempotently create the one pending ticket after persisted acceptance."""
        if not assessment.accepted:
            raise ValueError("only an accepted persisted risk assessment can issue a ticket")
        if not assessment.policy_version or not assessment.policy_digest:
            raise ValueError("accepted risk assessment requires an immutable policy identity")
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

    def consume_ticket(
        self,
        ticket_id: str,
        candidate: CandidateExecutionIntent,
        target: ExecutionTarget,
        policy: RiskPolicy,
    ) -> OutboundDispatchPermit | None:
        """Refresh every fact and atomically convert one current ticket to a dispatch permit."""
        if self._evidence_collector is None or self._risk_engine is None:
            raise RuntimeError("ticket consumption requires fresh evidence and risk dependencies")
        ticket = next((item for item in self._ledger.list_approval_tickets() if item.ticket_id == ticket_id), None)
        if ticket is None or ticket.status is not ApprovalTicketStatus.PENDING:
            return None
        try:
            evidence = self._evidence_collector.collect(candidate, target, policy)
        except EvidenceCollectionRejection as error:
            if self._utc_now() > ticket.expires_at:
                self.expire_ticket(ticket_id, "approval_ticket_expired")
                return None
            self._invalidate_for_failed_refresh(ticket, error)
            return None
        if self._utc_now() > ticket.expires_at:
            self.expire_ticket(ticket_id, "approval_ticket_expired")
            return None
        if candidate.intent_digest != ticket.binding.candidate_digest:
            self.invalidate_ticket(
                ticket_id,
                "current_candidate_binding_mismatch",
                replace(
                    ticket.binding,
                    candidate_digest=candidate.intent_digest,
                    command_digest=candidate.intent_digest,
                ),
            )
            return None
        assessment = self._risk_engine.assess(candidate, target, policy, evidence)
        if not assessment.accepted:
            self.invalidate_ticket(
                ticket_id,
                "risk_reassessment_rejected",
                replace(
                    ticket.binding,
                    evidence_digest=assessment.evidence_digest,
                    policy_digest=assessment.policy_digest,
                ),
            )
            return None
        return self._ledger.consume_valid_ticket_and_begin_outbound(
            ticket_id, candidate, policy, evidence, assessment
        )

    def close(self) -> None:
        """Close an owned concrete ledger when a short-lived coordinator is finished."""
        close = getattr(self._ledger, "close", None)
        if callable(close):
            close()

    def _invalidate_for_failed_refresh(
        self, ticket: ApprovalTicket, error: EvidenceCollectionRejection
    ) -> None:
        """Persist a changed controlled evidence binding without raw gateway failures."""
        digest = sha256(",".join(reason.value for reason in error.reasons).encode("utf-8")).hexdigest()
        self.invalidate_ticket(
            ticket.ticket_id,
            "fresh_evidence_refresh_failed",
            replace(ticket.binding, evidence_digest=digest),
        )
