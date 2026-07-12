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
from pa_agent.trading.application.recovery_assessment import RecoveryAssessmentService
from pa_agent.trading.domain.approval import (
    KillSwitchStatus,
    RecoveryAssessment,
)
from pa_agent.trading.domain.models import (
    AccountObservation,
    GatewayCapabilities,
    GatewayEvidence,
    InstrumentRules,
    OrderState,
    ProductType,
    QuoteObservation,
    RuleObservation,
    TimeObservation,
)
from pa_agent.trading.domain.risk import (
    FeeRateObservation,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
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

    def get_instrument_rules(self, symbol: str) -> RuleObservation:
        return RuleObservation(InstrumentRules(symbol, "0.50", "0.001", "0.001", "10"), NOW)

    def get_quote(self, symbol: str) -> QuoteObservation:
        return QuoteObservation(symbol, "7999.50", "8000", NOW)

    def get_server_time(self) -> TimeObservation:
        return TimeObservation(server_time=NOW, observed_at=NOW)

    def get_connection(self, target: object) -> TargetConnectionObservation:
        return TargetConnectionObservation(target, True, NOW)

    def get_open_order_count(self, target: object) -> OpenOrderObservation:
        return OpenOrderObservation(target, 0, NOW)

    def get_order_rate_window(self, target: object, window_seconds: int) -> OrderRateObservation:
        return OrderRateObservation(target, 0, NOW - timedelta(seconds=window_seconds), NOW)

    def get_loss_drawdown(self, target: object) -> LossDrawdownObservation:
        return LossDrawdownObservation(target, "0", "0", NOW, NOW)

    def get_fee_rate(self, target: object, symbol: str, quote_identifier: str) -> FeeRateObservation:
        return FeeRateObservation(target, symbol, quote_identifier, "USDT", "0.001", "fees-v1", NOW)


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
    assert service.begin_recovery("operator-1") is True
    assert ledger.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
    assert service.complete_recovery("operator-1", assessment_ids=("forged-assessment-id",)) is False
    assessment_id = _only_recovery_assessment_id(execution_database_path)
    assert service.complete_recovery("operator-1", assessment_ids=(assessment_id,)) is True
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

        assert not hasattr(ledger, "record_recovery_assessment")
        assert service.begin_recovery("operator-1")
        inspection = open_sqlite_connection(execution_database_path)
        try:
            assert inspection.execute("SELECT COUNT(*) FROM recovery_assessments").fetchone()[0] == 1
            assert inspection.execute("SELECT COUNT(*) FROM proposal_risk_assessments").fetchone()[0] == 0
        finally:
            inspection.close()
        assessment_id = _only_recovery_assessment_id(execution_database_path)
        assert ledger.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
        ledger.close()

        reopened = SQLiteExecutionLedger(execution_database_path, clock=clock)
        resumed = KillSwitchService(ledger=reopened, gateway=gateway, utc_now=clock.utc_now)
        assert reopened.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
        assert not resumed.complete_recovery("operator-1", assessment_ids=("forged-assessment-id",))
        assert reopened.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
        assert resumed.complete_recovery("operator-1", assessment_ids=(assessment_id,))
        assert reopened.get_kill_switch_state().status is KillSwitchStatus.READY
        assert gateway.submit_call_count == 0
        reopened.close()
    finally:
        ledger.close()


def _only_recovery_assessment_id(database_path: Path) -> str:
    connection = open_sqlite_connection(database_path)
    try:
        row = connection.execute(
            "SELECT recovery_assessment_id FROM recovery_assessments ORDER BY recorded_at_utc"
        ).fetchone()
        assert row is not None
        return str(row[0])
    finally:
        connection.close()


def test_caller_built_empty_assessment_has_no_persistence_path_or_authority(
    execution_database_path: Path,
) -> None:
    """An active scope must not let a caller mint clearance from empty observations."""
    clock = _Clock()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        client_order_id = _create_open_order(ledger)
        gateway = _CancellationGateway({client_order_id: None})
        service = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)
        service.latch("operator-stop", "operator-1", "paper-spot-primary", "manual safety stop")
        scope = ledger.list_kill_switch_recovery_scopes()[0]
        fabricated = RecoveryAssessment(
            recovery_assessment_id=None,
            persistent_scope_id=scope.persistent_scope_id,
            scope_digest=scope.scope_digest,
            target_digest=scope.target_digest,
            policy_version=scope.policy_version,
            policy_digest=scope.policy_digest,
            evidence_digest="forged-evidence",
            evidence_json='{"account":{},"capabilities":{},"connection":{},"fee_rate":{},"loss_drawdown":{},"open_orders":{},"order_rate":{},"quote":{},"rules":{},"server_time":{}}',
            accepted=True,
            reason_codes=(),
            observed_at=NOW,
        )
        before = ledger.count_recovery_assessments()
        assert not hasattr(ledger, "record_recovery_assessment")
        assert fabricated.recovery_assessment_id is None
        assert ledger.count_recovery_assessments() == before
        assert not service.begin_recovery("operator-1", assessment_ids=("forged-assessment-id",))
        assert ledger.get_kill_switch_state().status is KillSwitchStatus.LATCHED
        assert gateway.submit_call_count == 0
    finally:
        ledger.close()


def test_callable_recorder_rejects_forged_or_stale_canonical_evidence_before_id_allocation(
    execution_database_path: Path,
) -> None:
    """A caller cannot mint recovery clearance from a real scope and plausible JSON."""
    clock = _Clock()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        client_order_id = _create_open_order(ledger)
        gateway = _CancellationGateway(
            {
                client_order_id: GatewayEvidence(
                    evidence_id="cancelled-before-forgery",
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
        baseline = _authorization_row_counts(execution_database_path)

        fabricated_evidence = {
            name: {"fabricated": f"{name}-observation"}
            for name in (
                "capabilities",
                "rules",
                "account",
                "quote",
                "server_time",
                "connection",
                "open_orders",
                "order_rate",
                "loss_drawdown",
                "fee_rate",
            )
        }
        fabricated_json = json.dumps(
            fabricated_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        forged = _accepted_recovery_assessment(scope, fabricated_json)

        assert ledger._record_recovery_assessment_from_service(scope, forged) is None
        assert _authorization_row_counts(execution_database_path) == baseline
        assert not service.begin_recovery("operator-1", assessment_ids=("forged-assessment-id",))
        assert not service.complete_recovery("operator-1", assessment_ids=("forged-assessment-id",))
        assert ledger.get_kill_switch_state().status is KillSwitchStatus.LATCHED
        assert gateway.submit_call_count == 0

        controlled = RecoveryAssessmentService(
            ledger=ledger, gateway=gateway, utc_now=clock.utc_now
        ).assess(scope)
        assert controlled.accepted
        stale_evidence = json.loads(controlled.evidence_json)
        stale_evidence["quote"]["observed_at"] = (NOW - timedelta(seconds=61)).isoformat()
        stale_json = json.dumps(stale_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        stale = _accepted_recovery_assessment(scope, stale_json)

        assert ledger._record_recovery_assessment_from_service(scope, stale) is None
        assert _authorization_row_counts(execution_database_path) == baseline
        assert not service.begin_recovery("operator-1", assessment_ids=("stale-assessment-id",))
        assert not service.complete_recovery("operator-1", assessment_ids=("stale-assessment-id",))
        assert ledger.get_kill_switch_state().status is KillSwitchStatus.LATCHED
        assert gateway.submit_call_count == 0
    finally:
        ledger.close()


def _accepted_recovery_assessment(scope: object, evidence_json: str) -> RecoveryAssessment:
    """Build a caller-supplied accepted value with real durable scope bindings."""
    return RecoveryAssessment(
        recovery_assessment_id=None,
        persistent_scope_id=scope.persistent_scope_id,
        scope_digest=scope.scope_digest,
        target_digest=scope.target_digest,
        policy_version=scope.policy_version,
        policy_digest=scope.policy_digest,
        evidence_digest=sha256(evidence_json.encode("utf-8")).hexdigest(),
        evidence_json=evidence_json,
        accepted=True,
        reason_codes=(),
        observed_at=NOW,
    )


def _authorization_row_counts(database_path: Path) -> dict[str, int]:
    connection = open_sqlite_connection(database_path)
    try:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "recovery_assessments",
                "proposal_risk_assessments",
                "approval_tickets",
                "order_commands",
                "submission_claims",
                "outbound_dispatch_attempts",
            )
        }
    finally:
        connection.close()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda gateway, scope: setattr(gateway, "get_quote", lambda symbol: object()),
        lambda gateway, scope: setattr(gateway, "get_connection", lambda target: TargetConnectionObservation(scope.target, True, NOW - timedelta(seconds=61))),
        lambda gateway, scope: setattr(gateway, "get_fee_rate", lambda target, symbol, quote: FeeRateObservation(replace(scope.target, account_id="other-account"), symbol, quote, "USDT", "0.001", "fees-v1", NOW)),
        lambda gateway, scope: setattr(gateway, "get_open_order_count", lambda target: (_ for _ in ()).throw(RuntimeError("unavailable"))),
    ],
    ids=["malformed", "stale", "cross-target", "unavailable"],
)
def test_invalid_controlled_observations_cannot_allocate_accepted_recovery_authority(
    execution_database_path: Path,
    mutation: object,
) -> None:
    """Malformed, stale, cross-target, and unavailable evidence fail before accepted clearance."""
    clock = _Clock()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        client_order_id = _create_open_order(ledger)
        gateway = _CancellationGateway({client_order_id: None})
        service = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)
        service.latch("operator-stop", "operator-1", "paper-spot-primary", "manual safety stop")
        scope = ledger.list_kill_switch_recovery_scopes()[0]
        mutation(gateway, scope)

        assessment = RecoveryAssessmentService(
            ledger=ledger, gateway=gateway, utc_now=clock.utc_now
        ).assess_and_record(scope)

        assert assessment is None
        assert ledger.count_recovery_assessments() == 0
        assert not service.begin_recovery("operator-1", assessment_ids=("forged-assessment-id",))
        assert ledger.get_kill_switch_state().status is KillSwitchStatus.LATCHED
        assert gateway.submit_call_count == 0
    finally:
        ledger.close()
