"""Worker-facing command facade that preserves durable approval and latch boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from typing import Callable

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.kill_switch import KillSwitchService
from pa_agent.trading.application.proposal import ProposalService
from pa_agent.trading.application.submission import SubmissionCoordinator
from pa_agent.trading.domain.approval import (
    ApprovalTicket,
    ApprovalTicketStatus,
    CancellationWork,
    CandidateExecutionIntent,
    ExecutionTarget,
    KillSwitchState,
    KillSwitchStatus,
)
from pa_agent.trading.domain.models import ProductContext
from pa_agent.trading.domain.risk import RiskPolicy
from pa_agent.trading.ports.analysis_records import (
    AnalysisRecordSnapshotReader,
    EligibleAnalysisRecord,
    IneligibleAnalysisRecord,
)
from pa_agent.trading.ports.ledger import ExecutionLedger


@dataclass(frozen=True)
class TicketStateProjection:
    """Read-only durable ticket review suitable for a worker result."""

    ticket_id: str
    status: ApprovalTicketStatus | None
    target_digest: str | None
    is_read_only: bool
    review: object | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class TicketCommandResult:
    """Controlled result of a ticket command without dispatch authority."""

    ticket_id: str | None
    target_digest: str | None
    submitted: bool
    reason: str
    state: TicketStateProjection | None


@dataclass(frozen=True)
class CancellationRequestProjection:
    """Safe cancellation state which never treats a request as remote terminal proof."""

    work_id: str
    command_id: str
    client_order_id: str
    status: str
    request_outcome: str | None
    remote_resolution: str | None
    is_terminal: bool


@dataclass(frozen=True)
class KillSwitchProjection:
    """Persisted latch facts and blockers without local-state authority."""

    state: KillSwitchState
    approval_available: bool
    recovery_allowed: bool
    cancellation_requests: tuple[CancellationRequestProjection, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class RecoveryCommandResult:
    """Controlled completion result for a durable recovery service request."""

    accepted: bool
    projection: KillSwitchProjection


@dataclass(frozen=True)
class CancellationCommandResult:
    """Read-only persisted cancellation request results."""

    requests: tuple[CancellationRequestProjection, ...]


class TradingWorkspaceCommands:
    """Delegate workspace actions to existing durable services and read models only."""
    _approval_lock = Lock()


    def __init__(
        self,
        *,
        ledger: ExecutionLedger | None = None,
        analysis_reader: AnalysisRecordSnapshotReader | None = None,
        proposal_service: ProposalService | None = None,
        approval_service: ApprovalService | None = None,
        submission_coordinator: SubmissionCoordinator | None = None,
        kill_switch_service: KillSwitchService | None = None,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        self._analysis_reader = analysis_reader
        self._proposal_service = proposal_service
        self._submission_coordinator = submission_coordinator
        self._kill_switch_service = kill_switch_service
        self._ledger = ledger or self._ledger_from_service(approval_service, kill_switch_service)
        self._utc_now = utc_now or self._clock_from_service(approval_service)
        self._approval_service = approval_service

    def read_analysis_record(
        self, source_id: str
    ) -> EligibleAnalysisRecord | IneligibleAnalysisRecord:
        """Read strict persisted eligibility without granting any command authority."""
        if self._analysis_reader is None:
            return IneligibleAnalysisRecord(
                source_id=source_id,
                reason_code="RECORD_READER_UNAVAILABLE",
                safe_message="该分析记录当前无法用于创建审批单。",
            )
        return self._analysis_reader.read(source_id)

    def create_ticket(
        self,
        *,
        source_id: str,
        target: ExecutionTarget,
        policy: RiskPolicy,
        context: ProductContext | None = None,
    ) -> TicketCommandResult:
        """Create one durable review ticket from one strictly eligible record."""
        eligibility = self.read_analysis_record(source_id)
        if type(eligibility) is IneligibleAnalysisRecord:
            return TicketCommandResult(
                ticket_id=None,
                target_digest=None,
                submitted=False,
                reason=eligibility.reason_code.lower(),
                state=None,
            )
        if self._proposal_service is None or self._approval_service is None:
            return TicketCommandResult(None, None, False, "ticket_service_unavailable", None)
        try:
            candidate = self._proposal_service.propose(eligibility.snapshot, target, context)
            if candidate is None:
                return TicketCommandResult(None, None, False, "proposal_rejected", None)
            assessment = self._proposal_service.assess(candidate, target, policy)
            if not assessment.accepted:
                return TicketCommandResult(None, candidate.intent_digest, False, "risk_rejected", None)
            ticket = self._approval_service.create_pending_ticket(candidate, assessment)
        except Exception:
            return TicketCommandResult(None, None, False, "ticket_creation_unavailable", None)
        state = self._ticket_projection(ticket)
        return TicketCommandResult(ticket.ticket_id, state.target_digest, False, "ticket_created", state)

    def reject_ticket(self, ticket_id: str, reason: str) -> TicketCommandResult:
        """Persist a requested terminal rejection after rereading durable state."""
        ticket = self._ticket(ticket_id)
        if ticket is None:
            return TicketCommandResult(ticket_id, None, False, "ticket_not_found", None)
        if ticket.status is not ApprovalTicketStatus.PENDING:
            state = self._ticket_projection(ticket)
            return TicketCommandResult(ticket_id, state.target_digest, False, "ticket_not_pending", state)
        if self._approval_service is None:
            return TicketCommandResult(ticket_id, None, False, "ticket_service_unavailable", None)
        try:
            rejected = self._approval_service.reject_ticket(ticket_id, reason)
        except Exception:
            return self._controlled_ticket_failure(ticket_id)
        state = self._ticket_projection(rejected)
        return TicketCommandResult(ticket_id, state.target_digest, False, "ticket_rejected", state)

    def approve_ticket(
        self,
        *,
        ticket_id: str,
        candidate: CandidateExecutionIntent,
        target: ExecutionTarget,
        policy: RiskPolicy,
    ) -> TicketCommandResult:
        """Consume one current ticket then invoke the sole persisted submission route once."""
        with self._approval_lock:
            ticket = self._ticket(ticket_id)
            if ticket is None:
                return TicketCommandResult(ticket_id, None, False, "ticket_not_found", None)
            state = self._ticket_projection(ticket)
            if ticket.status is not ApprovalTicketStatus.PENDING:
                return TicketCommandResult(ticket_id, state.target_digest, False, "ticket_not_pending", state)
            if self._utc_now() > ticket.expires_at:
                if self._approval_service is not None:
                    try:
                        self._approval_service.expire_ticket(ticket_id, "approval_ticket_expired")
                    except Exception:
                        pass
                return self._controlled_ticket_failure(ticket_id, "ticket_expired")
            if self._approval_service is None or self._submission_coordinator is None:
                return TicketCommandResult(ticket_id, state.target_digest, False, "ticket_service_unavailable", state)
            try:
                permit = self._approval_service.consume_ticket(ticket_id, candidate, target, policy)
                if permit is None:
                    return self._controlled_ticket_failure(ticket_id)
                self._submission_coordinator.submit(permit)
            except Exception:
                return self._controlled_ticket_failure(ticket_id)
            return TicketCommandResult(
                ticket_id, state.target_digest, True, "submitted", self.ticket_state(ticket_id)
            )

    def approve_ticket_from_durable_ticket(
        self,
        *,
        ticket_id: str,
        target: ExecutionTarget,
        policy: RiskPolicy,
        context: ProductContext | None = None,
    ) -> TicketCommandResult:
        """Rebuild a candidate from the ticket's persisted source before approval.

        This keeps candidate, target, and policy construction in the application
        layer. A widget can provide only a durable ticket identifier.
        """
        ticket = self._ticket(ticket_id)
        if ticket is None:
            return TicketCommandResult(ticket_id, None, False, "ticket_not_found", None)
        state = self._ticket_projection(ticket)
        if ticket.status is not ApprovalTicketStatus.PENDING:
            return TicketCommandResult(ticket_id, state.target_digest, False, "ticket_not_pending", state)
        source_id = ticket.binding.source_provenance.get("source_id")
        if not source_id or self._proposal_service is None:
            return self._controlled_ticket_failure(ticket_id, "ticket_source_unavailable")
        eligibility = self.read_analysis_record(source_id)
        if type(eligibility) is IneligibleAnalysisRecord:
            return self._controlled_ticket_failure(ticket_id, "ticket_source_unavailable")
        try:
            candidate = self._proposal_service.propose(eligibility.snapshot, target, context)
        except Exception:
            return self._controlled_ticket_failure(ticket_id, "ticket_source_unavailable")
        if candidate.intent_digest != ticket.binding.candidate_digest:
            return self._controlled_ticket_failure(ticket_id, "ticket_binding_invalid")
        return self.approve_ticket(
            ticket_id=ticket_id,
            candidate=candidate,
            target=target,
            policy=policy,
        )

    def ticket_state(self, ticket_id: str) -> TicketStateProjection:
        """Reread the durable ticket rather than relying on a prior command result."""
        ticket = self._ticket(ticket_id)
        if ticket is None:
            return TicketStateProjection(ticket_id, None, None, True)
        return self._ticket_projection(ticket)

    def trigger_kill_switch(
        self,
        *,
        actor_label: str,
        reason: str,
        policy_summary: str,
        evidence_summary: str,
    ) -> KillSwitchProjection:
        """Request durable latching; the returned state comes only from the service."""
        if self._kill_switch_service is None:
            return self.kill_switch_state()
        self._kill_switch_service.latch(reason, actor_label, policy_summary, evidence_summary)
        return self.kill_switch_state()

    def process_cancellation_work(self) -> CancellationCommandResult:
        """Delegate cancellation requests without claiming remote terminal state."""
        if self._kill_switch_service is None:
            return CancellationCommandResult(())
        return CancellationCommandResult(
            tuple(
                self._cancellation_projection(work)
                for work in self._kill_switch_service.process_cancellation_work()
            )
        )

    def begin_kill_switch_recovery(self, *, actor_label: str) -> RecoveryCommandResult:
        """Request persisted recovery initiation and return its reread projection."""
        accepted = False
        if self._kill_switch_service is not None:
            accepted = self._kill_switch_service.begin_recovery(actor_label)
        return RecoveryCommandResult(accepted, self.kill_switch_state())

    def complete_kill_switch_recovery(self, *, actor_label: str) -> RecoveryCommandResult:
        """Request persisted recovery completion and return its reread projection."""
        accepted = False
        if self._kill_switch_service is not None:
            accepted = self._kill_switch_service.complete_recovery(actor_label)
        return RecoveryCommandResult(accepted, self.kill_switch_state())

    def kill_switch_state(self) -> KillSwitchProjection:
        """Project only durable latch and cancellation facts; never infer READY locally."""
        if self._ledger is None:
            state = KillSwitchState(KillSwitchStatus.LATCHED)
            return KillSwitchProjection(state, False, False, (), ("SERVICE_UNAVAILABLE",))
        state = self._ledger.get_kill_switch_state()
        requests = tuple(
            self._cancellation_projection(work)
            for work in self._ledger.list_cancellation_work(pending_only=False)
        )
        blockers = tuple(
            "CANCELLATION_RECONCILIATION_PENDING"
            for request in requests
            if not request.is_terminal
        )
        recovery_allowed = state.status is KillSwitchStatus.LATCHED and not blockers
        return KillSwitchProjection(
            state=state,
            approval_available=state.status is KillSwitchStatus.READY,
            recovery_allowed=recovery_allowed,
            cancellation_requests=requests,
            blockers=blockers,
        )

    def close(self) -> None:
        """Close the short-lived durable owner after a worker request completes."""
        close = getattr(self._ledger, "close", None)
        if callable(close):
            close()

    def _ticket(self, ticket_id: str) -> ApprovalTicket | None:
        if self._ledger is None:
            return None
        return next(
            (ticket for ticket in self._ledger.list_approval_tickets() if ticket.ticket_id == ticket_id),
            None,
        )

    @staticmethod
    def _ticket_projection(ticket: ApprovalTicket) -> TicketStateProjection:
        return TicketStateProjection(
            ticket_id=ticket.ticket_id,
            status=ticket.status,
            target_digest=(
                f"{ticket.binding.venue}:{ticket.binding.account_id}:{ticket.binding.product}"
            ),
            is_read_only=ticket.status is not ApprovalTicketStatus.PENDING,
            review=ticket.review,
            expires_at=ticket.expires_at,
        )

    def _controlled_ticket_failure(
        self, ticket_id: str, fallback_reason: str | None = None
    ) -> TicketCommandResult:
        state = self.ticket_state(ticket_id)
        if state.status is ApprovalTicketStatus.EXPIRED:
            reason = "ticket_expired"
        elif state.status is ApprovalTicketStatus.PENDING:
            reason = fallback_reason or "command_not_completed"
        else:
            reason = fallback_reason or "ticket_not_pending"
        return TicketCommandResult(ticket_id, state.target_digest, False, reason, state)

    @staticmethod
    def _cancellation_projection(work: CancellationWork) -> CancellationRequestProjection:
        return CancellationRequestProjection(
            work_id=work.work_id,
            command_id=work.command_id,
            client_order_id=work.client_order_id,
            status=work.status,
            request_outcome=work.request_outcome,
            remote_resolution=work.remote_resolution,
            is_terminal=work.remote_resolution in {"cancelled", "filled", "rejected"},
        )

    @staticmethod
    def _ledger_from_service(
        approval_service: ApprovalService | None, kill_switch_service: KillSwitchService | None
    ) -> ExecutionLedger | None:
        for service in (approval_service, kill_switch_service):
            ledger = getattr(service, "_ledger", None)
            if ledger is not None:
                return ledger
        return None

    @staticmethod
    def _clock_from_service(approval_service: ApprovalService | None) -> Callable[[], datetime]:
        clock = getattr(approval_service, "_utc_now", None)
        if callable(clock):
            return clock
        return lambda: datetime.now(UTC)
