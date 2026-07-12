"""Restart-safe recovery coverage using only ticket-derived dispatch permits."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pa_agent.trading.application.recovery import RecoveryService
from pa_agent.trading.domain.models import GatewayEvidence, OrderState
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerStorageError,
    open_sqlite_connection,
)
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.fake_exchange import ReconciliationOnlyGateway
from tests.integration.execution.test_approval_consumption import (
    NOW,
    _Clock,
    _consumer,
    _EvidenceAndSubmissionGateway,
    _issue_ticket,
)

pytestmark = pytest.mark.integration


def _leased_outbound(database_path: Path) -> tuple[SQLiteExecutionLedger, object]:
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(database_path, clock, gateway)
    service = _consumer(database_path, clock, gateway)
    try:
        permit = service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
        assert permit is not None
        outbound = service._ledger.lease_outbound_submission(permit)
    finally:
        service.close()
    return SQLiteExecutionLedger(database_path, clock=clock), outbound


def test_leased_outbound_ambiguity_survives_restart_without_replacement_authority(
    execution_database_path: Path,
) -> None:
    ledger, outbound = _leased_outbound(execution_database_path)
    ledger.mark_outbound_submission_ambiguous(outbound)
    ledger.close()

    reopened = SQLiteExecutionLedger(execution_database_path)
    gateway = ReconciliationOnlyGateway({outbound.client_order_id: None})
    results = RecoveryService(ledger=reopened, gateway=gateway).recover_startup()
    reopened.close()

    assert results[0].lifecycle_state is OrderState.SUBMISSION_UNKNOWN
    assert results[0].evidence_applied is False
    assert gateway.lookup_client_order_ids == [outbound.client_order_id]
    assert gateway.submit_call_count == 0


def test_recovery_evidence_applies_to_ticket_derived_unresolved_command(
    execution_database_path: Path,
) -> None:
    ledger, outbound = _leased_outbound(execution_database_path)
    ledger.mark_outbound_submission_ambiguous(outbound)
    job = ledger.list_unresolved_reconciliation_jobs()[0]
    result = ledger.apply_reconciliation_evidence(
        job,
        GatewayEvidence(
            evidence_id="rejected-after-lease",
            client_order_id=outbound.client_order_id,
            state=OrderState.REJECTED,
            observed_at=datetime(2026, 7, 12, tzinfo=UTC),
        ),
    )
    ledger.close()
    assert result.lifecycle_state is OrderState.REJECTED
    assert result.evidence_applied is True


def test_legacy_entries_are_not_reintroduced_for_recovery_setup(execution_database_path: Path) -> None:
    ledger = SQLiteExecutionLedger(execution_database_path)
    try:
        assert not hasattr(ledger, "create_or_load_and_claim_submission")
        assert not hasattr(ledger, "begin_outbound_submission")
        with pytest.raises((LedgerStorageError, TypeError)):
            ledger.lease_outbound_submission(object())  # type: ignore[arg-type]
    finally:
        ledger.close()
    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM order_commands").fetchone()[0] == 0
    finally:
        connection.close()
