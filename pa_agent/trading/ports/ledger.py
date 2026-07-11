"""Durable submission-admission contract for the future execution ledger."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pa_agent.trading.domain.models import ExecutionCommand, OrderState

_UNRESOLVED_SUBMISSION_STATES = frozenset(
    {OrderState.SUBMITTING, OrderState.SUBMISSION_UNKNOWN}
)


@dataclass(frozen=True)
class SubmissionAdmission:
    """The sole durable authority result for one logical command submission.

    An admissible result carries one opaque claim token. A non-admissible result
    returns the already-persisted first identities without a claim, so a caller
    can recover evidence but cannot make a second remote submission.
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
        if self.lifecycle_state not in _UNRESOLVED_SUBMISSION_STATES:
            raise ValueError("submission admission requires an unresolved lifecycle state")
        if self.is_admissible:
            if self.lifecycle_state is not OrderState.SUBMITTING:
                raise ValueError("only a submitting command can receive a submission claim")
            if not self.claim_token:
                raise ValueError("an admissible submission requires an opaque claim token")
        elif self.claim_token is not None:
            raise ValueError("a non-admissible submission cannot carry a claim token")


@runtime_checkable
class ExecutionLedger(Protocol):
    """Repository port that makes durable submission admission an atomic boundary."""

    def create_or_load_and_claim_submission(
        self, command: ExecutionCommand
    ) -> SubmissionAdmission:
        """Atomically create or load ``command`` by logical key and decide admission.

        The first unresolved logical command persists one command ID, client-order
        ID, reconciliation job, and opaque claim before any gateway call. A repeat
        returns those original identities as non-admissible and never allocates a
        second claim token, command, client-order ID, or reconciliation job.
        """

    def mark_submission_ambiguous(self, admission: SubmissionAdmission) -> None:
        """Record ambiguity and retain reconciliation using the same persisted identities.

        A coordinator calls this after an uncertain gateway outcome. Recovery may
        query gateway evidence only with the admission's command/client/job
        identities; it must not create replacement identities or infer a terminal
        result from local control flow.
        """
