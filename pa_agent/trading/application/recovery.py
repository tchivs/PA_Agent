"""Evidence-only startup recovery for durable execution reconciliation work."""
from __future__ import annotations

from dataclasses import dataclass

from pa_agent.trading.domain.models import OrderState
from pa_agent.trading.ports.gateway import TradingGateway
from pa_agent.trading.ports.ledger import ExecutionLedger, ReconciliationJob


@dataclass(frozen=True)
class RecoveryResult:
    """The durable result of inspecting one persisted reconciliation job."""

    reconciliation_job_id: str
    client_order_id: str
    lifecycle_state: OrderState
    evidence_applied: bool


class RecoveryService:
    """Reconcile durable jobs using canonical lookup evidence and never submission.

    The service deliberately queries the gateway only with each job's first
    persisted client-order ID. It allocates no command, client, job, or claim
    identity, and does not expose a submission path.
    """

    def __init__(self, *, ledger: ExecutionLedger, gateway: TradingGateway) -> None:
        self._ledger = ledger
        self._gateway = gateway

    def recover_startup(self) -> tuple[RecoveryResult, ...]:
        """Scan persisted unresolved jobs and reconcile each one from canonical evidence."""
        return tuple(
            self.reconcile_job(job) for job in self._ledger.list_unresolved_reconciliation_jobs()
        )

    def reconcile_job(self, job: ReconciliationJob) -> RecoveryResult:
        """Inspect one job by its durable client ID and append only legal evidence."""
        evidence = self._gateway.lookup_order_by_client_id(job.client_order_id)
        if evidence is None:
            return RecoveryResult(
                reconciliation_job_id=job.reconciliation_job_id,
                client_order_id=job.client_order_id,
                lifecycle_state=job.lifecycle_state,
                evidence_applied=False,
            )
        outcome = self._ledger.apply_reconciliation_evidence(job, evidence)
        return RecoveryResult(
            reconciliation_job_id=job.reconciliation_job_id,
            client_order_id=job.client_order_id,
            lifecycle_state=outcome.lifecycle_state,
            evidence_applied=outcome.evidence_applied,
        )
