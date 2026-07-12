"""Durable submission-admission contract for the future execution ledger."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from pa_agent.trading.domain.approval import (
    ApprovalTicket,
    CancellationWork,
    CandidateExecutionIntent,
    ExecutionTarget,
    KillSwitchState,
    RecoveryScope,
    SourceAnalysisSnapshot,
    TicketBinding,
    TicketTerminalEvent,
)
from pa_agent.trading.domain.errors import ConversionRejectionReason
from pa_agent.trading.domain.models import (
    AccountObservation,
    ExecutionCommand,
    GatewayEvidence,
    OrderState,
)
from pa_agent.trading.domain.risk import EvidenceBundle, RiskAssessment

_NONTERMINAL_SUBMISSION_STATES = frozenset(
    {
        OrderState.SUBMITTING,
        OrderState.SUBMISSION_UNKNOWN,
        OrderState.ACKNOWLEDGED,
        OrderState.OPEN,
        OrderState.PARTIALLY_FILLED,
        OrderState.CANCEL_REQUESTED,
    }
)


@dataclass(frozen=True)
class OutboundSubmission:
    """Irreversible ledger authorization for exactly one future gateway call.

    The ledger reconstructs ``command`` from its durable canonical record and
    binds it to the generated client-order ID. The opaque attempt token exists
    only after atomic consumption of an admissible submission claim.
    """

    command: ExecutionCommand
    command_id: str
    client_order_id: str
    reconciliation_job_id: str
    outbound_attempt_token: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.command_id,
                self.client_order_id,
                self.reconciliation_job_id,
                self.outbound_attempt_token,
            )
        ):
            raise ValueError("outbound submission requires durable identities and attempt token")
        if self.command.command_id != self.command_id:
            raise ValueError("outbound submission command must match its durable command ID")
        if self.command.client_order_id != self.client_order_id:
            raise ValueError("outbound submission command must use its generated client-order ID")


@dataclass(frozen=True)
class OutboundDispatchPermit:
    """Opaque durable identities and proof awaiting a future ledger lease.

    This is contract preparation only: callers may hold or reconstruct a
    lookalike permit, so it does not block forgery by itself. Only the future
    ledger implementation may verify the persisted proof and rebuild the
    gateway-facing :class:`OutboundSubmission`.
    """

    command_id: str
    client_order_id: str
    reconciliation_job_id: str
    outbound_attempt_proof: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.command_id,
                self.client_order_id,
                self.reconciliation_job_id,
                self.outbound_attempt_proof,
            )
        ):
            raise ValueError("outbound dispatch permit requires durable identities and opaque proof")


@dataclass(frozen=True)
class ReconciliationJob:
    """Persisted recovery identity for one non-terminal command."""

    command_id: str
    client_order_id: str
    reconciliation_job_id: str
    lifecycle_state: OrderState

    def __post_init__(self) -> None:
        if not all((self.command_id, self.client_order_id, self.reconciliation_job_id)):
            raise ValueError("reconciliation job requires persisted command, client, and job IDs")


@dataclass(frozen=True)
class ReconciliationResult:
    """Result of applying one normalized reconciliation observation."""

    lifecycle_state: OrderState
    evidence_applied: bool


@dataclass(frozen=True)
class ProposalAuditFact:
    """Controlled, queryable pre-ticket audit fact without execution authority."""

    kind: str
    source_id: str
    source_digest: str
    policy_digest: str | None
    evidence_digest: str | None
    reason_code: str | None
    fee_amount: str | None
    observed_at: datetime
    recorded_at: datetime
    summary_json: str


@runtime_checkable
class ExecutionLedger(Protocol):
    """Repository port for ticket-derived durable execution authority."""

    def consume_valid_ticket_and_begin_outbound(
        self,
        ticket_id: str,
        candidate: CandidateExecutionIntent,
        policy: object,
        evidence: EvidenceBundle,
        assessment: RiskAssessment,
    ) -> OutboundDispatchPermit | None:
        """Persist one expiring dispatch proof while atomically consuming a ticket."""

    def lease_outbound_submission(self, permit: OutboundDispatchPermit) -> OutboundSubmission:
        """Lease one gateway submission after one-time durable proof verification.

        The ledger verifies the persisted identity and proof in one transaction,
        uses a conditional rowcount check to consume its one-time lease, then
        reconstructs the canonical command. Callers cannot turn a lookalike
        permit into a gateway-facing value.
        """

    def mark_outbound_submission_ambiguous(self, outbound: OutboundSubmission) -> None:
        """Record local ambiguity for an already-authorized outbound submission."""

    def record_account_observation(self, observation: AccountObservation) -> str:
        """Persist one explicit typed canonical account observation and return its ID."""

    def record_conversion_rejection(
        self,
        snapshot: SourceAnalysisSnapshot,
        target: ExecutionTarget,
        reason: ConversionRejectionReason,
    ) -> None:
        """Persist one controlled D-02 conversion rejection without a command or ticket."""

    def record_candidate(self, candidate: CandidateExecutionIntent) -> None:
        """Persist an accepted candidate before fresh evidence or ticket creation."""

    def record_evidence(self, candidate: CandidateExecutionIntent, evidence: EvidenceBundle) -> None:
        """Persist one complete immutable evidence bundle for an accepted candidate."""

    def record_risk_assessment(
        self, candidate: CandidateExecutionIntent, assessment: RiskAssessment
    ) -> None:
        """Persist an allowlisted risk result; this cannot issue or consume a ticket."""

    def list_proposal_audit_facts(self) -> tuple[ProposalAuditFact, ...]:
        """Return pre-ticket controlled audit facts in their durable recorded order."""

    def create_pending_ticket_if_absent(
        self,
        candidate: CandidateExecutionIntent,
        assessment: RiskAssessment,
        created_at: datetime,
    ) -> ApprovalTicket:
        """Create or load one pending ticket after verifying durable accepted proposal facts."""

    def list_approval_tickets(self) -> tuple[ApprovalTicket, ...]:
        """Return durable approval tickets without granting consumption authority."""

    def terminate_approval_ticket(
        self,
        ticket_id: str,
        event: TicketTerminalEvent,
        reason: str,
        binding: TicketBinding | None = None,
    ) -> ApprovalTicket:
        """Append one distinct terminal ticket event using the persisted immutable binding."""

    def get_kill_switch_state(self) -> KillSwitchState:
        """Return the singleton durable authorization state, defaulting only to READY."""

    def latch_kill_switch(
        self,
        *,
        reason: str,
        actor_label: str,
        policy_summary: str,
        evidence_summary: str,
        cancellation_supported: bool,
    ) -> KillSwitchState:
        """Atomically latch, revoke pending tickets, and enqueue eligible work."""

    def list_cancellation_work(self, *, pending_only: bool = False) -> tuple[CancellationWork, ...]:
        """Return durable cancellation work without inferring a remote outcome."""

    def record_cancellation_work_result(self, work_id: str, outcome: str) -> CancellationWork:
        """Record an attempted cancellation request without claiming it resolved exposure."""

    def count_recovery_assessments(self) -> int:
        """Return recovery clearance rows for boundary-oriented verification only."""

    def begin_kill_switch_recovery(self, actor_label: str, *, assessment_ids: tuple[str, ...]) -> bool:
        """Move LATCHED to RECOVERING only after exact current-scope assessment verification."""

    def list_kill_switch_recovery_scopes(self) -> tuple[RecoveryScope, ...]:
        """Return each persisted account/product scope needing fresh gateway evidence."""

    def complete_kill_switch_recovery(
        self, actor_label: str, *, assessment_ids: tuple[str, ...]
    ) -> bool:
        """Return READY only through a separately revalidated scope-ID set."""

    def list_unresolved_reconciliation_jobs(self) -> tuple[ReconciliationJob, ...]:
        """Return persisted non-terminal jobs without allocating replacement identities."""

    def apply_reconciliation_evidence(
        self, job: ReconciliationJob, evidence: GatewayEvidence
    ) -> ReconciliationResult:
        """Append legal normalized evidence or retain state and record an incident."""
