"""Real-SQLite coverage for the durable approval kill-switch boundary."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from pa_agent.trading.application.kill_switch import KillSwitchService
from pa_agent.trading.application.recovery import RecoveryService
from pa_agent.trading.domain.approval import (
    KillSwitchStatus,
    RecoveryAssessment,
    RecoveryScope,
)
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
    assert service.begin_recovery("operator-1", assessment_ids=("forged-assessment-id",)) is False

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
    scope = ledger.list_kill_switch_recovery_scopes()[0]
    persisted = ledger.record_recovery_assessment(scope, _recovery_assessment_for(scope))
    assert persisted is not None
    assert service.begin_recovery("operator-1", assessment_ids=(persisted.recovery_assessment_id,)) is True
    assert ledger.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
    assert service.complete_recovery("operator-1", assessment_ids=("forged-assessment-id",)) is False
    assert service.complete_recovery("operator-1", assessment_ids=(persisted.recovery_assessment_id,)) is True
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


def _recovery_assessment_for(
    scope: RecoveryScope,
    *,
    accepted: bool = True,
    observed_at: datetime = NOW,
    evidence_digest: str | None = None,
) -> RecoveryAssessment:
    """Build a caller-held clearance assertion that SQLite must independently verify."""
    evidence_json = json.dumps(
        {
            "account": {},
            "capabilities": {},
            "connection": {},
            "fee_rate": {},
            "loss_drawdown": {},
            "open_orders": {},
            "order_rate": {},
            "quote": {},
            "rules": {},
            "server_time": {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return RecoveryAssessment(
        recovery_assessment_id=None,
        persistent_scope_id=scope.persistent_scope_id,
        scope_digest=scope.scope_digest,
        target_digest=scope.target_digest,
        policy_version=scope.policy_version,
        policy_digest=scope.policy_digest,
        evidence_digest=evidence_digest or sha256(evidence_json.encode("utf-8")).hexdigest(),
        evidence_json=evidence_json,
        accepted=accepted,
        reason_codes=() if accepted else ("unresolved_exposure",),
        observed_at=observed_at,
    )


def test_recovery_scope_assessment_ids_are_the_only_path_to_ready(
    execution_database_path: Path,
) -> None:
    """Both durable recovery transitions must independently verify the same scope-ID set."""
    clock = _Clock()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        client_order_id = _create_open_order(ledger)
        gateway = _CancellationGateway(
            {
                client_order_id: GatewayEvidence(
                    evidence_id="terminal-before-assessment",
                    client_order_id=client_order_id,
                    state=OrderState.CANCELLED,
                    observed_at=NOW,
                )
            }
        )
        service = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)
        service.latch("operator-stop", "operator-1", "paper-spot-primary", "manual safety stop")
        service.process_cancellation_work()
        RecoveryService(ledger=ledger, gateway=gateway).recover_startup()

        scope = ledger.list_kill_switch_recovery_scopes()[0]
        assessment = _recovery_assessment_for(scope)
        persisted = ledger.record_recovery_assessment(scope, assessment)

        assert persisted is not None
        inspection = open_sqlite_connection(execution_database_path)
        try:
            assert inspection.execute("SELECT COUNT(*) FROM recovery_assessments").fetchone()[0] == 1
            assert inspection.execute("SELECT COUNT(*) FROM proposal_risk_assessments").fetchone()[0] == 0
        finally:
            inspection.close()
        assert service.begin_recovery("operator-1", assessment_ids=(persisted.recovery_assessment_id,))
        assert ledger.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
        ledger.close()

        reopened = SQLiteExecutionLedger(execution_database_path, clock=clock)
        resumed = KillSwitchService(ledger=reopened, gateway=gateway, utc_now=clock.utc_now)
        assert reopened.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
        assert not resumed.complete_recovery("operator-1", assessment_ids=("forged-assessment-id",))
        assert reopened.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
        assert resumed.complete_recovery("operator-1", assessment_ids=(persisted.recovery_assessment_id,))
        assert reopened.get_kill_switch_state().status is KillSwitchStatus.READY
        assert gateway.submit_call_count == 0
        reopened.close()
    finally:
        ledger.close()


@pytest.mark.parametrize(
    ("scope_override", "assessment_override", "persists"),
    [
        ({"persistent_scope_id": "invented-scope"}, {}, False),
        ({"scope_digest": "tampered-scope"}, {}, False),
        ({"target_digest": "tampered-target"}, {}, False),
        ({"policy_digest": "tampered-policy"}, {}, False),
        ({}, {"evidence_digest": "tampered-evidence"}, False),
        ({}, {"accepted": False, "reason_codes": ("unresolved_exposure",)}, True),
        ({}, {"observed_at": NOW - timedelta(seconds=61)}, True),
    ],
)
def test_forged_or_cross_boundary_recovery_assessment_never_writes_or_recovers(
    execution_database_path: Path,
    scope_override: dict[str, object],
    assessment_override: dict[str, object],
    persists: bool,
) -> None:
    """Caller-built scope or assessment values cannot mint authority while latched."""
    clock = _Clock()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        client_order_id = _create_open_order(ledger)
        gateway = _CancellationGateway({client_order_id: None})
        service = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)
        service.latch("operator-stop", "operator-1", "paper-spot-primary", "manual safety stop")
        scope = ledger.list_kill_switch_recovery_scopes()[0]
        supplied_scope = replace(scope, **scope_override)
        supplied_assessment = replace(_recovery_assessment_for(supplied_scope), **assessment_override)

        before = ledger.count_recovery_assessments()
        persisted = ledger.record_recovery_assessment(supplied_scope, supplied_assessment)

        assert (persisted is not None) is persists
        assert ledger.count_recovery_assessments() == before + int(persists)
        ids = (persisted.recovery_assessment_id,) if persisted is not None else ("forged-assessment-id",)
        assert not service.begin_recovery("operator-1", assessment_ids=ids)
        assert ledger.get_kill_switch_state().status is KillSwitchStatus.LATCHED
        assert gateway.submit_call_count == 0
    finally:
        ledger.close()
