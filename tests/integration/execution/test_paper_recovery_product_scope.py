"""Real-SQLite recovery authorization checks for immutable Paper product scopes."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.kill_switch import KillSwitchService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.application.submission import SubmissionCoordinator
from pa_agent.trading.domain.approval import CandidateExecutionIntent, ExecutionTarget
from pa_agent.trading.domain.approval import KillSwitchStatus
from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    GatewayCapabilities,
    GatewayEvidence,
    InstrumentRules,
    IsolatedMarginOrderContext,
    Mode,
    OrderState,
    OrderType,
    ProductType,
    ProtectiveExitPlan,
    QuoteObservation,
    RuleObservation,
    Side,
    SpotOrderContext,
    TimeObservation,
    UsdtPerpetualOrderContext,
    product_context_digest,
)
from pa_agent.trading.domain.risk import (
    EvidenceBundle,
    FeeRateObservation,
    IsolatedMarginProductEvidence,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    UsdtPerpetualProductEvidence,
    select_paper_product_policy,
)
from pa_agent.trading.persistence.sqlite_connection import open_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from pa_agent.trading.ports.gateway import GatewayOperationReference, GatewayOperationResult
from pa_agent.trading.ports.ledger import OutboundSubmission
from tests.fixtures.fake_exchange import ScriptedEvidenceGateway

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def utc_now(self) -> datetime:
        return self.now


class _SeedGateway:
    """Accepts only coordinator-leased submissions while tests seed durable work."""

    def __init__(self) -> None:
        self.submissions: list[OutboundSubmission] = []

    def submit_order(self, outbound: OutboundSubmission) -> GatewayOperationResult:
        self.submissions.append(outbound)
        return GatewayOperationResult(
            evidence=GatewayEvidence(
                evidence_id=f"seed:{outbound.client_order_id}",
                client_order_id=outbound.client_order_id,
                state=OrderState.OPEN,
                observed_at=NOW,
            ),
            reference=GatewayOperationReference(
                operation_id=f"seed:{outbound.client_order_id}",
                client_order_id=outbound.client_order_id,
            ),
        )


def _target(product: ProductType) -> ExecutionTarget:
    return ExecutionTarget(
        {
            ProductType.SPOT: "paper-spot-primary",
            ProductType.ISOLATED_MARGIN: "paper-margin-isolated-primary",
            ProductType.USDT_PERPETUAL: "paper-usdt-perpetual-primary",
        }[product],
        Mode.PAPER,
        "paper-account",
        product,
    )


def _context(product: ProductType, key: str) -> object:
    if product is ProductType.SPOT:
        return SpotOrderContext()
    if product is ProductType.ISOLATED_MARGIN:
        return IsolatedMarginOrderContext(key, "USDT", True)
    return UsdtPerpetualOrderContext(
        leverage=Decimal("3"),
        symbol=key,
        margin_mode="isolated",
        position_mode="one_way",
        protective_exit=ProtectiveExitPlan(
            symbol=key,
            entry_side=Side.BUY,
            trigger_price=Decimal("7900"),
            limit_price=Decimal("7890"),
            maximum_loss=Decimal("100"),
            policy_version="paper-usdt-perpetual-v1",
        ),
    )


def _candidate(product: ProductType, key: str) -> CandidateExecutionIntent:
    return CandidateExecutionIntent(
        source_id=f"analysis-{product.value}",
        source_completed_at=NOW,
        source_schema_version="analysis-v1",
        source_parser_version="parser-v1",
        source_decision_digest=f"decision-{product.value}",
        target=_target(product),
        symbol=key,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.01"),
        price=Decimal("8000"),
        risk_basis=Decimal("0.01"),
        context=_context(product, key),
    )


def _evidence(candidate: CandidateExecutionIntent) -> EvidenceBundle:
    target = candidate.target
    product_evidence: object | None = None
    if target.product is ProductType.ISOLATED_MARGIN:
        product_evidence = IsolatedMarginProductEvidence(
            target, candidate.symbol, "100", "80", "20", "0.10", "1.50", "300", True, NOW, 7
        )
    elif target.product is ProductType.USDT_PERPETUAL:
        product_evidence = UsdtPerpetualProductEvidence(
            target, candidate.symbol, True, True, "3", "200", "50", "10", "8000", "0.01", NOW, 11
        )
    return EvidenceBundle(
        capabilities=GatewayCapabilities(frozenset(ProductType), True),
        instrument_rules=InstrumentRules(candidate.symbol, "0.50", "0.001", "0.001", "10"),
        rule_observed_at=NOW,
        account=AccountObservation(
            target.account_id, target.product, NOW, (Balance("USDT", "20000", "20000", "0"),), ()
        ),
        quote=QuoteObservation(candidate.symbol, "7999.50", "8000", NOW),
        server_time=TimeObservation(NOW, NOW),
        connection=TargetConnectionObservation(target, True, NOW),
        open_orders=OpenOrderObservation(target, 0, NOW),
        order_rate=OrderRateObservation(target, 0, NOW - timedelta(seconds=60), NOW),
        loss_drawdown=LossDrawdownObservation(target, "0", "0", NOW.replace(hour=0), NOW),
        fee_rate=FeeRateObservation(target, candidate.symbol, candidate.symbol, "USDT", "0.001", "fees-v1", NOW),
        product_context_digest=product_context_digest(candidate.context),
        product_evidence=product_evidence,
    )


def _seed_terminal_command(
    path: Path, clock: _Clock, product: ProductType, key: str
) -> _SeedGateway:
    """Use only ticket -> permit -> lease -> coordinator to create recovery work."""
    candidate = _candidate(product, key)
    policy = select_paper_product_policy(candidate.target, candidate.context)
    evidence = _evidence(candidate)
    assessment = RiskEngine().assess(candidate, candidate.target, policy, evidence)
    assert assessment.accepted
    gateway = _SeedGateway()
    ledger = SQLiteExecutionLedger(path, clock=clock)
    try:
        ledger.record_candidate(candidate)
        ledger.record_evidence(candidate, evidence)
        ledger.record_risk_assessment(candidate, assessment)
        ticket = ApprovalService(ledger=ledger, utc_now=clock.utc_now).create_pending_ticket(
            candidate, assessment
        )
        permit = ledger.consume_valid_ticket_and_begin_outbound(
            ticket.ticket_id, candidate, policy, evidence, assessment
        )
        assert permit is not None
        SubmissionCoordinator(ledger=ledger, gateway=gateway).submit(permit)
        job = ledger.list_unresolved_reconciliation_jobs()[0]
        assert ledger.apply_reconciliation_evidence(
            job,
            GatewayEvidence(
                evidence_id=f"open:{permit.client_order_id}",
                client_order_id=permit.client_order_id,
                state=OrderState.OPEN,
                observed_at=NOW,
            ),
        ).evidence_applied
        ledger.latch_kill_switch(
            reason="operator-stop",
            actor_label="operator",
            policy_summary="paper",
            evidence_summary="stop",
            cancellation_supported=True,
        )
        work = ledger.list_cancellation_work(pending_only=True)[0]
        ledger.record_cancellation_work_result(work.work_id, "requested")
        assert ledger.apply_reconciliation_evidence(
            job,
            GatewayEvidence(
                evidence_id=f"terminal:{permit.client_order_id}",
                client_order_id=permit.client_order_id,
                state=OrderState.CANCELLED,
                observed_at=NOW,
            ),
        ).evidence_applied
    finally:
        ledger.close()
    return gateway


def _recovery_gateway(scope: object, *, rounds: int = 2) -> ScriptedEvidenceGateway:
    target = scope.target
    key = scope.product_scope_key
    timestamps = tuple(NOW + timedelta(seconds=index) for index in range(rounds))
    margin = []
    perpetual = []
    if target.product is ProductType.ISOLATED_MARGIN:
        margin = [
            IsolatedMarginProductEvidence(target, key, "100", "100", "0", "0", "1.5", "300", False, now, 1)
            for now in timestamps
        ]
    if target.product is ProductType.USDT_PERPETUAL:
        perpetual = [
            UsdtPerpetualProductEvidence(target, key, True, True, "3", "200", "0", "0", "8000", "0", now, 1)
            for now in timestamps
        ]
    return ScriptedEvidenceGateway(
        capabilities=[GatewayCapabilities(frozenset({target.product}), True) for _ in timestamps],
        rules=[RuleObservation(InstrumentRules(key, "0.50", "0.001", "0.001", "10"), now) for now in timestamps],
        accounts=[AccountObservation(target.account_id, target.product, now) for now in timestamps],
        quotes=[QuoteObservation(key, "7999.50", "8000", now) for now in timestamps],
        server_times=[TimeObservation(now, now) for now in timestamps],
        connections=[TargetConnectionObservation(target, True, now) for now in timestamps],
        open_orders=[OpenOrderObservation(target, 0, now) for now in timestamps],
        order_rates=[OrderRateObservation(target, 0, now - timedelta(seconds=60), now) for now in timestamps],
        loss_drawdowns=[LossDrawdownObservation(target, "0", "0", now.replace(hour=0), now) for now in timestamps],
        fee_rates=[FeeRateObservation(target, key, key, "USDT", "0.001", "fees-v1", now) for now in timestamps],
        isolated_margin_evidence=margin,
        perpetual_evidence=perpetual,
    )


def _authority_snapshot(path: Path) -> dict[str, int]:
    connection = open_sqlite_connection(path)
    try:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "approval_tickets",
                "order_commands",
                "submission_claims",
                "outbound_dispatch_attempts",
                "recovery_assessments",
                "kill_switch_events",
            )
        }
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("product", "key"),
    [
        (ProductType.SPOT, "BTCUSDT"),
        (ProductType.ISOLATED_MARGIN, "BTCUSDT"),
        (ProductType.USDT_PERPETUAL, "BTCUSDT"),
    ],
)
def test_reopened_scope_retains_exact_product_target_policy_and_key(
    execution_database_path: Path, product: ProductType, key: str
) -> None:
    clock = _Clock()
    _seed_terminal_command(execution_database_path, clock, product, key)
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        ledger.latch_kill_switch(
            reason="operator-stop", actor_label="operator", policy_summary="paper", evidence_summary="stop", cancellation_supported=True
        )
        scope = ledger.list_kill_switch_recovery_scopes()[0]
    finally:
        ledger.close()

    reopened = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        restored = reopened.list_kill_switch_recovery_scopes()
        assert restored == (scope,)
        assert scope.target == _target(product)
        assert scope.product_scope_key == key
        assert scope.policy_id == _target(product).target_id
        assert scope.is_canonical()
    finally:
        reopened.close()


@pytest.mark.parametrize("failure", ["missing", "cross_key", "stale", "forged", "replay"])
def test_nonzero_recovery_denials_preserve_latch_and_allocate_no_authority(
    execution_database_path: Path, failure: str
) -> None:
    clock = _Clock()
    seed_gateway = _seed_terminal_command(execution_database_path, clock, ProductType.ISOLATED_MARGIN, "BTCUSDT")
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    ledger.latch_kill_switch(
        reason="operator-stop", actor_label="operator", policy_summary="paper", evidence_summary="stop", cancellation_supported=True
    )
    scope = ledger.list_kill_switch_recovery_scopes()[0]
    gateway = _recovery_gateway(scope, rounds=2)
    service = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)
    baseline = _authority_snapshot(execution_database_path)
    try:
        if failure == "missing":
            gateway._responses["isolated_margin"] = []  # noqa: SLF001 - deterministic missing source
            assert service.begin_recovery("operator") is False
        elif failure == "cross_key":
            gateway._responses["isolated_margin"] = [  # noqa: SLF001 - deterministic foreign pair
                IsolatedMarginProductEvidence(scope.target, "ETHUSDT", "100", "100", "0", "0", "1.5", "300", False, NOW, 1)
            ]
            assert service.begin_recovery("operator") is False
        elif failure == "stale":
            gateway._responses["isolated_margin"] = [  # noqa: SLF001 - deterministic stale fact
                IsolatedMarginProductEvidence(scope.target, "BTCUSDT", "100", "100", "0", "0", "1.5", "300", False, NOW - timedelta(seconds=61), 1)
            ]
            assert service.begin_recovery("operator") is False
        elif failure == "forged":
            assert service.begin_recovery("operator", assessment_ids=("forged",)) is False
        else:
            assert service.begin_recovery("operator") is True
            before_replay = _authority_snapshot(execution_database_path)
            clock.now = NOW + timedelta(seconds=1)
            assert service.complete_recovery("operator") is True
            assert service.complete_recovery("operator") is False
            assert _authority_snapshot(execution_database_path) == {
                **before_replay,
                "recovery_assessments": before_replay["recovery_assessments"] + 1,
                "kill_switch_events": before_replay["kill_switch_events"] + 1,
            }
            assert ledger.get_kill_switch_state().status is KillSwitchStatus.READY
            return
        assert ledger.get_kill_switch_state().status is KillSwitchStatus.LATCHED
        assert _authority_snapshot(execution_database_path) == baseline
        assert gateway.submit_call_count == 0
        assert len(seed_gateway.submissions) == 1
    finally:
        ledger.close()


def test_restart_requires_distinct_exact_scope_assessments_before_ready(
    execution_database_path: Path,
) -> None:
    clock = _Clock()
    _seed_terminal_command(execution_database_path, clock, ProductType.USDT_PERPETUAL, "BTCUSDT")
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    ledger.latch_kill_switch(
        reason="operator-stop", actor_label="operator", policy_summary="paper", evidence_summary="stop", cancellation_supported=True
    )
    scope = ledger.list_kill_switch_recovery_scopes()[0]
    gateway = _recovery_gateway(scope, rounds=2)
    service = KillSwitchService(ledger=ledger, gateway=gateway, utc_now=clock.utc_now)
    try:
        assert service.begin_recovery("operator") is True
        assert ledger.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
    finally:
        ledger.close()

    clock.now = NOW + timedelta(seconds=1)
    reopened = SQLiteExecutionLedger(execution_database_path, clock=clock)
    resumed = KillSwitchService(ledger=reopened, gateway=gateway, utc_now=clock.utc_now)
    try:
        assert resumed.complete_recovery("operator") is True
        assert reopened.get_kill_switch_state().status is KillSwitchStatus.READY
        assert gateway.submit_call_count == 0
    finally:
        reopened.close()
