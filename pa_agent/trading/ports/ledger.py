"""Durable submission-admission contract for the future execution ledger."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pa_agent.trading.domain.models import (
    AccountObservation,
    ExecutionCommand,
    GatewayEvidence,
    LifecycleEvent,
    OrderState,
)

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
class SubmissionAdmission:
    """Durable admission result for one logical command submission.

    The first admission discards the caller candidate and allocates one opaque
    durable client-order ID. A non-admissible result returns the already
    persisted identities without a claim, so callers can recover evidence but
    cannot make a second remote submission.
    """

    command_id: str
    client_order_id: str
    reconciliation_job_id: str
    lifecycle_state: OrderState
    is_admissible: bool
    claim_token: str | None

    def __post_init__(self) -> None:
        if not all((self.command_id, self.client_order_id, self.reconciliation_job_id)):
            raise ValueError("submission admission requires persisted command, client, and job IDs")
        if self.lifecycle_state not in _NONTERMINAL_SUBMISSION_STATES:
            raise ValueError("submission admission requires a non-terminal lifecycle state")
        if self.is_admissible:
            if self.lifecycle_state is not OrderState.SUBMITTING:
                raise ValueError("only a submitting command can receive a submission claim")
            if not self.claim_token:
                raise ValueError("an admissible submission requires an opaque claim token")
        elif self.claim_token is not None:
            raise ValueError("a non-admissible submission cannot carry a claim token")


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


@runtime_checkable
class ExecutionLedger(Protocol):
    """Repository port that makes durable submission admission an atomic boundary."""

    def create_or_load_and_claim_submission(
        self, command: ExecutionCommand
    ) -> SubmissionAdmission:
        """Atomically create or load a command and decide its initial admission.

        First admission discards the caller candidate, allocates one opaque
        durable client-order ID, and persists the command, reconciliation job,
        and opaque claim before any gateway call. A repeat and recovery return
        exactly the stored ID without another claim, command, client-order ID,
        or reconciliation job.
        """

    def begin_outbound_submission(
        self, admission: SubmissionAdmission
    ) -> OutboundSubmission:
        """Consume one admission in an atomic durable state change.

        The operation reconstructs the command from durable canonical storage,
        starts its one irreversible outbound attempt, and returns its generated
        client-order ID. Later local ambiguity or cancellation may record
        reconciliation work but cannot revoke this authorization; a second begin
        request fails closed.
        """

    def record_account_observation(self, observation: AccountObservation) -> str:
        """Persist one explicit typed canonical account observation and return its ID."""


    def mark_submission_ambiguous(
        self,
        admission: SubmissionAdmission,
        *,
        event: LifecycleEvent = LifecycleEvent.LOCAL_TIMEOUT,
    ) -> None:
        """Record local ambiguity while retaining durable identities for reconciliation.

        This cannot revoke an authorization already returned by
        :meth:`begin_outbound_submission`.
        """

    def list_unresolved_reconciliation_jobs(self) -> tuple[ReconciliationJob, ...]:
        """Return persisted non-terminal jobs without allocating replacement identities."""

    def apply_reconciliation_evidence(
        self, job: ReconciliationJob, evidence: GatewayEvidence
    ) -> ReconciliationResult:
        """Append legal normalized evidence or retain state and record an incident."""
