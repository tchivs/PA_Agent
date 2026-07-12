"""Real-SQLite coverage for the durable approval kill-switch boundary."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pa_agent.trading.application.kill_switch import KillSwitchService
from pa_agent.trading.application.recovery import RecoveryService
from pa_agent.trading.domain.approval import KillSwitchStatus
from pa_agent.trading.domain.models import (
    AccountObservation,
    GatewayCapabilities,
    GatewayEvidence,
    OrderState,
    ProductType,
)
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerStorageError,
    open_sqlite_connection,
)
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.execution_factories import make_spot_command
from tests.fixtures.fake_exchange import ReconciliationOnlyGateway

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def utc_now(self) -> datetime:
        return self.now


class _CancellationGateway(ReconciliationOnlyGateway):
    """Offline gateway that records cancellation requests without inventing closure."""

    def __init__(self, evidence_by_client_id: dict[str, GatewayEvidence | None]) -> None:
        super().__init__(evidence_by_client_id)
        self.cancelled_client_ids: list[str] = []

    def cancel_order(self, client_order_id: str) -> GatewayEvidence:
        self.cancelled_client_ids.append(client_order_id)
        evidence = self.lookup_order_by_client_id(client_order_id)
        if evidence is None:
            raise TimeoutError("cancellation response unavailable")
        return evidence

    def get_capabilities(self) -> GatewayCapabilities:
        return GatewayCapabilities(
            products=frozenset({ProductType.SPOT}),
            supports_order_lookup=True,
            supports_cancellation=True,
        )

    def get_account_snapshot(self, account_id: str, product: ProductType) -> AccountObservation:
        return AccountObservation(account_id=account_id, product=product, observed_at=NOW)

    def list_open_orders(self, account_id: str, product: ProductType) -> tuple[object, ...]:
        del account_id, product
        return ()


def _create_open_order(ledger: SQLiteExecutionLedger) -> str:
    admission = ledger.create_or_load_and_claim_submission(make_spot_command())
    outbound = ledger.begin_outbound_submission(admission)
    ledger.mark_outbound_submission_ambiguous(outbound)
    job = ledger.list_unresolved_reconciliation_jobs()[0]
    ledger.apply_reconciliation_evidence(
        job,
        GatewayEvidence(
            evidence_id="open-before-latch",
            client_order_id=outbound.client_order_id,
            state=OrderState.OPEN,
            observed_at=NOW,
        ),
    )
    return outbound.client_order_id


def test_latch_survives_reopen_records_work_and_never_infers_remote_cancel(
    execution_database_path: Path,
) -> None:
    """A durable latch requests cancellation only and remains latched after restart."""
    clock = _Clock()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    client_order_id = _create_open_order(ledger)
    gateway = _CancellationGateway({client_order_id: None})
    service = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)

    latched = service.latch(
        reason="operator-stop",
        actor_label="operator-1",
        policy_summary="paper-spot-primary",
        evidence_summary="manual safety stop",
    )

    assert latched.status is KillSwitchStatus.LATCHED
    assert gateway.cancelled_client_ids == []
    assert service.process_cancellation_work()[0].request_outcome == "timeout"
    assert gateway.cancelled_client_ids == [client_order_id]
    ledger.close()

    reopened = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        assert reopened.get_kill_switch_state().status is KillSwitchStatus.LATCHED
        assert reopened.list_cancellation_work()[0].client_order_id == client_order_id
        assert reopened.list_cancellation_work()[0].remote_resolution is None
        with pytest.raises(LedgerStorageError, match="kill switch"):
            reopened.create_or_load_and_claim_submission(make_spot_command())
    finally:
        reopened.close()


def test_reset_requires_processed_work_fresh_evidence_and_explicit_operator_action(
    execution_database_path: Path,
) -> None:
    """Cancellation requests and empty lookups cannot themselves reopen authority."""
    clock = _Clock()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    client_order_id = _create_open_order(ledger)
    gateway = _CancellationGateway(
        {
            client_order_id: GatewayEvidence(
                evidence_id="cancel-request-ack",
                client_order_id=client_order_id,
                state=OrderState.CANCEL_REQUESTED,
                observed_at=NOW,
            )
        }
    )
    service = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)
    service.latch("operator-stop", "operator-1", "paper-spot-primary", "manual safety stop")
    service.process_cancellation_work()

    recovery = RecoveryService(ledger=ledger, gateway=gateway)
    recovery.recover_startup()
    assert service.begin_recovery("operator-1", assessment_accepted=True) is False

    gateway.set_evidence(
        client_order_id,
        GatewayEvidence(
            evidence_id="cancelled-evidence",
            client_order_id=client_order_id,
            state=OrderState.CANCELLED,
            observed_at=NOW,
        ),
    )
    recovery.recover_startup()
    assert service.begin_recovery("operator-1", assessment_accepted=True) is True
    assert ledger.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
    assert service.complete_recovery("operator-1", assessment_accepted=False) is False
    assert service.complete_recovery("operator-1", assessment_accepted=True) is True
    assert ledger.get_kill_switch_state().status is KillSwitchStatus.READY
    ledger.close()


def test_latch_rejects_new_ticket_consumption_and_preserves_existing_client_identity(
    execution_database_path: Path,
) -> None:
    """Recovery never allocates a replacement client ID or a second outbound authority."""
    clock = _Clock()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    client_order_id = _create_open_order(ledger)
    gateway = _CancellationGateway({client_order_id: None})
    service = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)
    service.latch("operator-stop", "operator-1", "paper-spot-primary", "manual safety stop")

    with pytest.raises(LedgerStorageError, match="kill switch"):
        ledger.begin_outbound_submission(
            replace(
                ledger.create_or_load_and_claim_submission(make_spot_command()),
                claim_token="replacement-claim",
                is_admissible=True,
                lifecycle_state=OrderState.SUBMITTING,
            )
        )

    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute("SELECT client_order_id FROM order_commands").fetchone()[0] == client_order_id
        assert connection.execute("SELECT lifecycle_state FROM orders").fetchone()[0] == OrderState.OPEN.value
        assert connection.execute("SELECT COUNT(*) FROM cancellation_work").fetchone()[0] == 1
    finally:
        connection.close()
        ledger.close()
