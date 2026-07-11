"""Integration coverage for evidence-only execution restart recovery."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pa_agent.trading.application.recovery import RecoveryService
from pa_agent.trading.domain.models import GatewayEvidence, LifecycleEvent, OrderState
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.execution_factories import make_spot_command
from tests.fixtures.fake_exchange import ReconciliationOnlyGateway

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "interruption",
    (
        LifecycleEvent.LOCAL_TIMEOUT,
        LifecycleEvent.LOCAL_CANCELLATION,
        LifecycleEvent.STREAM_GAP,
        LifecycleEvent.MALFORMED_ACKNOWLEDGEMENT,
    ),
)
def test_interruption_persists_uncertainty_and_retains_reconciliation_job(
    execution_database_path: Path, interruption: LifecycleEvent
) -> None:
    """Every local ambiguity remains recoverable rather than becoming a terminal result."""
    command = make_spot_command()
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(command)
    ledger.mark_submission_ambiguous(admission, event=interruption)
    ledger.close()

    reopened = SQLiteExecutionLedger(execution_database_path)
    jobs = reopened.list_unresolved_reconciliation_jobs()
    repeat = reopened.create_or_load_and_claim_submission(
        replace(command, command_id="replacement-command", client_order_id="replacement-client")
    )
    reopened.close()

    assert len(jobs) == 1
    assert jobs[0].lifecycle_state is OrderState.SUBMISSION_UNKNOWN
    assert jobs[0].client_order_id == admission.client_order_id
    assert jobs[0].reconciliation_job_id == admission.reconciliation_job_id
    assert repeat.is_admissible is False
    assert repeat.claim_token is None
    assert (repeat.command_id, repeat.client_order_id, repeat.reconciliation_job_id) == (
        admission.command_id,
        admission.client_order_id,
        admission.reconciliation_job_id,
    )


def test_recovery_after_reopen_queries_only_first_client_id_and_never_submits(
    execution_database_path: Path,
) -> None:
    """Restart recovery can inspect persisted work without renewing submission authority."""
    command = make_spot_command()
    first_ledger = SQLiteExecutionLedger(execution_database_path)
    admission = first_ledger.create_or_load_and_claim_submission(command)
    first_ledger.mark_submission_ambiguous(admission)
    first_ledger.close()

    reopened = SQLiteExecutionLedger(execution_database_path)
    gateway = ReconciliationOnlyGateway({admission.client_order_id: None})
    recovery = RecoveryService(ledger=reopened, gateway=gateway)

    results = recovery.recover_startup()
    repeat = reopened.create_or_load_and_claim_submission(
        replace(command, command_id="replacement-command", client_order_id="replacement-client")
    )
    reopened.close()

    assert len(results) == 1
    assert results[0].evidence_applied is False
    assert results[0].lifecycle_state is OrderState.SUBMISSION_UNKNOWN
    assert gateway.lookup_client_order_ids == [admission.client_order_id]
    assert gateway.submit_call_count == 0
    assert repeat.is_admissible is False
    assert repeat.claim_token is None
    assert (repeat.command_id, repeat.client_order_id, repeat.reconciliation_job_id) == (
        admission.command_id,
        admission.client_order_id,
        admission.reconciliation_job_id,
    )


def test_definitive_matching_evidence_alone_advances_the_lifecycle(
    execution_database_path: Path,
) -> None:
    """Recovery ignores empty evidence but applies normalized canonical proof once present."""
    command = make_spot_command()
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(command)
    ledger.mark_submission_ambiguous(admission)
    gateway = ReconciliationOnlyGateway(
        {
            admission.client_order_id: GatewayEvidence(
                evidence_id="rejection-evidence-001",
                client_order_id=admission.client_order_id,
                state=OrderState.REJECTED,
                observed_at=datetime(2026, 7, 11, tzinfo=UTC),
            )
        }
    )

    result = RecoveryService(ledger=ledger, gateway=gateway).recover_startup()
    assert result[0].evidence_applied is True
    assert result[0].lifecycle_state is OrderState.REJECTED
    assert gateway.submit_call_count == 0
    assert ledger.list_unresolved_reconciliation_jobs() == ()
    ledger.close()
