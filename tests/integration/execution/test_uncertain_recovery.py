"""Evidence-only recovery never recreates dispatch authority."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pa_agent.trading.application.recovery import RecoveryService
from pa_agent.trading.domain.models import GatewayEvidence, OrderState
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from pa_agent.trading.ports.gateway import GatewayOperationObserver, GatewayOperationResult
from tests.fixtures.fake_exchange import ReconciliationOnlyGateway
from tests.integration.execution.test_idempotency_recovery import _leased_outbound

pytestmark = pytest.mark.integration



class _RecordingOperationObserver(GatewayOperationObserver):
    def __init__(self) -> None:
        self.results: list[GatewayOperationResult] = []

    def observe_operation(self, result: GatewayOperationResult) -> None:
        self.results.append(result)

def test_recovery_after_ticket_derived_ambiguity_only_queries_durable_client_id(
    execution_database_path: Path,
) -> None:
    ledger, outbound = _leased_outbound(execution_database_path)
    ledger.mark_outbound_submission_ambiguous(outbound)
    ledger.close()
    reopened = SQLiteExecutionLedger(execution_database_path)
    gateway = ReconciliationOnlyGateway({outbound.client_order_id: None})
    result = RecoveryService(ledger=reopened, gateway=gateway).recover_startup()[0]
    reopened.close()
    assert result.lifecycle_state is OrderState.SUBMISSION_UNKNOWN
    assert gateway.lookup_client_order_ids == [outbound.client_order_id]
    assert gateway.submit_call_count == 0


def test_recovery_forwards_lookup_result_once_without_submission(
    execution_database_path: Path,
) -> None:
    """Recovery owns a single read-only observer delivery for its durable client ID."""
    ledger, outbound = _leased_outbound(execution_database_path)
    ledger.mark_outbound_submission_ambiguous(outbound)
    observer = _RecordingOperationObserver()
    gateway = ReconciliationOnlyGateway(
        {
            outbound.client_order_id: GatewayEvidence(
                evidence_id="rejected-after-recovery",
                client_order_id=outbound.client_order_id,
                state=OrderState.REJECTED,
                observed_at=datetime(2026, 7, 13, tzinfo=UTC),
            )
        }
    )
    try:
        result = RecoveryService(
            ledger=ledger,
            gateway=gateway,
            operation_observer=observer,
        ).recover_startup()[0]
        assert result.evidence_applied is True
        assert [entry.reference.client_order_id for entry in observer.results] == [outbound.client_order_id]
        assert gateway.lookup_client_order_ids == [outbound.client_order_id]
        assert gateway.submit_call_count == 0
    finally:
        ledger.close()
