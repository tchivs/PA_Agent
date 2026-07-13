"""Real-SQLite authority tests for immutable Paper product policy tickets."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.application.submission import SubmissionCoordinator
from pa_agent.trading.domain.approval import CandidateExecutionIntent, ExecutionTarget
from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    GatewayCapabilities,
    InstrumentRules,
    IsolatedMarginOrderContext,
    Mode,
    OrderType,
    ProductType,
    ProtectiveExitPlan,
    QuoteObservation,
    RuleObservation,
    Side,
    SpotOrderContext,
    TimeObservation,
    UsdtPerpetualOrderContext,
)
from pa_agent.trading.domain.risk import (
    EvidenceBundle,
    FeeRateObservation,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    select_paper_product_policy,
)

from pa_agent.trading.persistence.sqlite_connection import LedgerStorageError, open_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from pa_agent.trading.ports.ledger import OutboundSubmission

pytestmark = pytest.mark.integration
NOW = datetime(2026, 7, 13, tzinfo=UTC)


class _Clock:
    def utc_now(self) -> datetime:
        return NOW


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


def _context(product: ProductType):
    if product is ProductType.SPOT:
        return SpotOrderContext()
    if product is ProductType.ISOLATED_MARGIN:
        return IsolatedMarginOrderContext("BTCUSDT", "USDT", True)
    return UsdtPerpetualOrderContext(
        leverage=Decimal("3"),
        symbol="BTCUSDT",
        margin_mode="isolated",
        position_mode="one_way",
        protective_exit=ProtectiveExitPlan(
            symbol="BTCUSDT",
            entry_side=Side.BUY,
            trigger_price=Decimal("7900"),
            limit_price=Decimal("7890"),
            maximum_loss=Decimal("100"),
            policy_version="paper-usdt-perpetual-v1",
        ),
    )


def _candidate(product: ProductType) -> CandidateExecutionIntent:
    return CandidateExecutionIntent(
        source_id=f"analysis-{product.value}",
        source_completed_at=NOW,
        source_schema_version="analysis-v1",
        source_parser_version="parser-v1",
        source_decision_digest=f"decision-{product.value}",
        target=_target(product),
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.01"),
        price=Decimal("8000"),
        risk_basis=Decimal("0.01"),
        context=_context(product),
    )


def _evidence(target: ExecutionTarget) -> EvidenceBundle:
    return EvidenceBundle(
        capabilities=GatewayCapabilities(frozenset(ProductType), True),
        instrument_rules=InstrumentRules("BTCUSDT", "0.50", "0.001", "0.001", "10"),
        rule_observed_at=NOW,
        account=AccountObservation(
            target.account_id,
            target.product,
            NOW,
            (Balance("USDT", "20000", "20000", "0"),),
            (),
        ),
        quote=QuoteObservation("BTCUSDT", "7999.50", "8000", NOW),
        server_time=TimeObservation(NOW, NOW),
        connection=TargetConnectionObservation(target, True, NOW),
        open_orders=OpenOrderObservation(target, 0, NOW),
        order_rate=OrderRateObservation(target, 0, NOW - timedelta(seconds=60), NOW),
        loss_drawdown=LossDrawdownObservation(target, "0", "0", NOW.replace(hour=0), NOW),
        fee_rate=FeeRateObservation(target, "BTCUSDT", "BTCUSDT", "USDT", "0.001", "fees-v1", NOW),
    )


class _GatewaySentinel:
    def __init__(self) -> None:
        self.submissions: list[OutboundSubmission] = []

    def submit_order(self, outbound: OutboundSubmission) -> object:
        self.submissions.append(outbound)
        return object()


def _counts(path: Path) -> tuple[int, int, int, int]:
    ledger = SQLiteExecutionLedger(path)
    try:
        connection = ledger._require_connection()  # noqa: SLF001 - schema-backed authority assertion
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("proposal_risk_assessments", "approval_tickets", "outbound_dispatch_attempts", "order_commands")
        )
    finally:
        ledger.close()


def test_reopened_ledger_issues_and_leases_once_for_each_product(execution_database_path: Path) -> None:
    """The ordinary persisted candidate -> ticket -> permit -> lease route stays unique per product."""
    gateway = _GatewaySentinel()
    permits = []
    ledger = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    try:
        for product in ProductType:
            candidate = _candidate(product)
            policy = select_paper_product_policy(candidate.target, candidate.context)
            evidence = _evidence(candidate.target)
            assessment = RiskEngine().assess(candidate, candidate.target, policy, evidence)
            assert assessment.accepted
            ledger.record_candidate(candidate)
            ledger.record_evidence(candidate, evidence)
            ledger.record_risk_assessment(candidate, assessment)
            ticket = ApprovalService(ledger=ledger, utc_now=lambda: NOW).create_pending_ticket(candidate, assessment)
            permits.append(ledger.consume_valid_ticket_and_begin_outbound(ticket.ticket_id, candidate, policy, evidence, assessment))
        assert all(permit is not None for permit in permits)
    finally:
        ledger.close()

    reopened = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    try:
        for permit in permits:
            assert permit is not None
            SubmissionCoordinator(ledger=reopened, gateway=gateway).submit(permit)
    finally:
        reopened.close()

    assert len(gateway.submissions) == 3
    assert {submission.command.context.product for submission in gateway.submissions} == set(ProductType)
    assert _counts(execution_database_path) == (6, 3, 3, 3)
    durable = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    try:
        bindings = durable._require_connection().execute(  # noqa: SLF001 - durable binding assertion
            "SELECT policy_id, policy_version_bound, policy_digest_bound FROM order_commands ORDER BY policy_id"
        ).fetchall()
    finally:
        durable.close()
    assert [binding[0] for binding in bindings] == [
        "paper-margin-isolated-primary",
        "paper-spot-primary",
        "paper-usdt-perpetual-primary",
    ]
    assert all(binding[1] and binding[2] for binding in bindings)


def test_unsupported_policy_creates_no_persisted_authority(execution_database_path: Path) -> None:
    """Unsupported target/context combinations fail before an accepted assessment or ticket exists."""
    candidate = _candidate(ProductType.ISOLATED_MARGIN)
    forged_target = ExecutionTarget("paper-spot-primary", Mode.PAPER, "paper-account", ProductType.ISOLATED_MARGIN)

    with pytest.raises(Exception):
        select_paper_product_policy(forged_target, candidate.context)

    assert _counts(execution_database_path) == (0, 0, 0, 0)


def test_tampered_durable_policy_refuses_lease_before_gateway_authority(
    execution_database_path: Path,
) -> None:
    """A forged policy digest cannot turn a persisted permit into an outbound lease."""
    candidate = _candidate(ProductType.ISOLATED_MARGIN)
    policy = select_paper_product_policy(candidate.target, candidate.context)
    evidence = _evidence(candidate.target)
    assessment = RiskEngine().assess(candidate, candidate.target, policy, evidence)
    ledger = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    try:
        ledger.record_candidate(candidate)
        ledger.record_evidence(candidate, evidence)
        ledger.record_risk_assessment(candidate, assessment)
        ticket = ApprovalService(ledger=ledger, utc_now=lambda: NOW).create_pending_ticket(candidate, assessment)
        permit = ledger.consume_valid_ticket_and_begin_outbound(
            ticket.ticket_id, candidate, policy, evidence, assessment
        )
        assert permit is not None
    finally:
        ledger.close()

    connection = open_sqlite_connection(execution_database_path)
    try:
        connection.execute(
            "UPDATE order_commands SET policy_digest_bound = ? WHERE command_id = ?",
            ("forged-policy-digest", permit.command_id),
        )
        connection.commit()
    finally:
        connection.close()

    reopened = SQLiteExecutionLedger(execution_database_path, clock=_Clock())
    try:
        with pytest.raises(LedgerStorageError, match="policy"):
            reopened.lease_outbound_submission(permit)
        status = reopened._require_connection().execute(  # noqa: SLF001 - lease side-effect assertion
            "SELECT status FROM outbound_dispatch_attempts WHERE command_id = ?",
            (permit.command_id,),
        ).fetchone()
    finally:
        reopened.close()
    assert status == ("pending",)
