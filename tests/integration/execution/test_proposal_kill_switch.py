"""Real-SQLite regressions for the proposal risk-acceptance kill-switch gate."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.application.kill_switch import KillSwitchService
from pa_agent.trading.application.proposal import ProposalService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.approval import KillSwitchStatus
from pa_agent.trading.domain.models import (
    Balance,
    GatewayCapabilities,
    InstrumentRules,
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
    select_phase2_policy,
)
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerStorageError,
    open_sqlite_connection,
)
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.execution_factories import (
    make_account_observation,
    make_analysis_recommendation,
    make_execution_target,
    make_source_analysis_snapshot,
)
from tests.fixtures.fake_exchange import ScriptedEvidenceGateway

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


class _Clock:
    def utc_now(self) -> datetime:
        return NOW


class _LatchingRiskEngine(RiskEngine):
    """Latch after the service precheck to exercise the accepted-write race."""

    def __init__(self, ledger: SQLiteExecutionLedger) -> None:
        self._ledger = ledger

    def assess(self, candidate, target, policy, evidence):
        self._ledger.latch_kill_switch(
            reason="race-stop",
            actor_label="operator-1",
            policy_summary="paper-spot-primary",
            evidence_summary="race before accepted persistence",
            cancellation_supported=False,
        )
        return super().assess(candidate, target, policy, evidence)


def _gateway() -> ScriptedEvidenceGateway:
    target = make_execution_target()
    return ScriptedEvidenceGateway(
        capabilities=[GatewayCapabilities(frozenset({ProductType.SPOT}), True)],
        rules=[RuleObservation(InstrumentRules("BTCUSDT", "0.50", "0.001", "0.001", "10"), NOW)],
        accounts=[
            make_account_observation(
                observed_at=NOW,
                balances=(Balance("USDT", "2000", "1500", "0"),),
                positions=(),
            )
        ],
        quotes=[QuoteObservation("BTCUSDT", "7999.50", "8000", NOW)],
        server_times=[TimeObservation(server_time=NOW, observed_at=NOW)],
        connections=[TargetConnectionObservation(target, True, NOW)],
        open_orders=[OpenOrderObservation(target, 2, NOW)],
        order_rates=[OrderRateObservation(target, 4, NOW - timedelta(seconds=60), NOW)],
        loss_drawdowns=[
            LossDrawdownObservation(target, "99", "0.09", datetime(2026, 7, 12, tzinfo=UTC), NOW)
        ],
        fee_rates=[FeeRateObservation(target, "BTCUSDT", "BTCUSDT", "USDT", "0.001", "fees-v1", NOW)],
    )


def _service(
    ledger: SQLiteExecutionLedger,
    gateway: ScriptedEvidenceGateway,
    risk_engine: RiskEngine | None = None,
) -> ProposalService:
    return ProposalService(
        ledger=ledger,
        intent_factory=IntentFactory(utc_now=lambda: NOW),
        evidence_collector=FreshEvidenceCollector(gateway=gateway, utc_now=lambda: NOW),
        risk_engine=risk_engine or RiskEngine(),
        approval_service=ApprovalService(ledger=ledger, utc_now=lambda: NOW),
    )


def _candidate(service: ProposalService):
    target = make_execution_target()
    candidate = service.propose(
        make_source_analysis_snapshot(
            completed_at=NOW,
            recommendation=make_analysis_recommendation(price="8000", quantity="0.125"),
        ),
        target,
    )
    assert candidate is not None
    return candidate, target


def _latch(ledger: SQLiteExecutionLedger, gateway: ScriptedEvidenceGateway) -> None:
    state = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=_Clock().utc_now).latch(
        reason="operator-stop",
        actor_label="operator-1",
        policy_summary="paper-spot-primary",
        evidence_summary="manual safety stop",
    )
    assert state.status is KillSwitchStatus.LATCHED


def _assert_no_accepted_risk_or_authority(path) -> None:
    connection = open_sqlite_connection(path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM proposal_risk_assessments WHERE accepted = 1"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM approval_tickets").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM order_commands").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM submission_claims").fetchone()[0] == 0
    finally:
        connection.close()


def test_latched_proposal_assessment_is_audited_rejection_without_authority(
    execution_database_path,
) -> None:
    """A LATCHED ledger stops before fresh evidence, risk acceptance, or ticket issuance."""
    ledger = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    gateway = _gateway()
    service = _service(ledger, gateway)
    candidate, target = _candidate(service)
    _latch(ledger, gateway)

    assessment = service.assess(candidate, target, select_phase2_policy(target))
    facts = ledger.list_proposal_audit_facts()
    tickets = ledger.list_approval_tickets()
    ledger.close()

    assert assessment.accepted is False
    assert gateway.call_order == ["capabilities"]
    assert tickets == ()
    assert facts[-1].kind == "risk_rejected"
    assert facts[-1].reason_code == "kill_switch_not_ready"
    assert gateway.submit_call_count == 0
    _assert_no_accepted_risk_or_authority(execution_database_path)


def test_reopened_latched_ledger_rejects_proposal_assessment_without_authority(
    execution_database_path,
) -> None:
    """Restart retains the latch and its proposal-risk fail-closed behavior."""
    initial = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    initial_gateway = _gateway()
    initial_service = _service(initial, initial_gateway)
    candidate, target = _candidate(initial_service)
    _latch(initial, initial_gateway)
    initial.close()

    reopened = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    gateway = _gateway()
    assessment = _service(reopened, gateway).assess(candidate, target, select_phase2_policy(target))
    facts = reopened.list_proposal_audit_facts()
    reopened.close()

    assert assessment.accepted is False
    assert gateway.call_order == []
    assert facts[-1].kind == "risk_rejected"
    assert facts[-1].reason_code == "kill_switch_not_ready"
    assert gateway.submit_call_count == 0
    _assert_no_accepted_risk_or_authority(execution_database_path)


def test_latched_ledger_rejects_direct_accepted_assessment_write(execution_database_path) -> None:
    """The SQLite transaction guard backs the service-level READY precheck."""
    ledger = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    gateway = _gateway()
    candidate, target = _candidate(_service(ledger, gateway))
    _latch(ledger, gateway)

    with pytest.raises(LedgerStorageError, match="kill switch"):
        ledger.record_risk_assessment(
            candidate,
            RiskEngine().assess(
                candidate,
                target,
                select_phase2_policy(target),
                FreshEvidenceCollector(gateway=_gateway(), utc_now=lambda: NOW).collect(
                    candidate, target, select_phase2_policy(target)
                ),
            ),
        )
    ledger.close()

    _assert_no_accepted_risk_or_authority(execution_database_path)


def test_latch_between_service_precheck_and_accepted_write_becomes_rejection(
    execution_database_path,
) -> None:
    """The SQLite READY gate closes the narrow race after fresh evidence collection."""
    ledger = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    gateway = _gateway()
    service = _service(ledger, gateway, _LatchingRiskEngine(ledger))
    candidate, target = _candidate(service)

    assessment = service.assess(candidate, target, select_phase2_policy(target))
    facts = ledger.list_proposal_audit_facts()
    ledger.close()

    assert assessment.accepted is False
    assert facts[-1].kind == "risk_rejected"
    assert facts[-1].reason_code == "kill_switch_not_ready"
    _assert_no_accepted_risk_or_authority(execution_database_path)
