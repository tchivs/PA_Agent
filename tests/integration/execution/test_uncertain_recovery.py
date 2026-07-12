"""Evidence-only recovery never recreates dispatch authority."""
from __future__ import annotations

from pathlib import Path

import pytest

from pa_agent.trading.application.recovery import RecoveryService
from pa_agent.trading.domain.models import OrderState
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.fake_exchange import ReconciliationOnlyGateway
from tests.integration.execution.test_idempotency_recovery import _leased_outbound

pytestmark = pytest.mark.integration


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
