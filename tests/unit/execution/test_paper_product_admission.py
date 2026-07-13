"""Product-aware Paper admission stays fail-closed before ticket authority."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.evidence_collector import (
    EvidenceCollectionRejection,
    FreshEvidenceCollector,
)
from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.application.proposal import ProposalService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    GatewayCapabilities,
    InstrumentRules,
    IsolatedMarginOrderContext,
    Mode,
    ProductType,
    ProtectiveExitPlan,
    QuoteObservation,
    RuleObservation,
    Side,
    TimeObservation,
    UsdtPerpetualOrderContext,
)
from pa_agent.trading.domain.risk import (
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
from tests.fixtures.execution_factories import make_analysis_recommendation, make_source_analysis_snapshot
from tests.fixtures.fake_exchange import ScriptedEvidenceGateway

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


class _Clock:
    def utc_now(self) -> datetime:
        return NOW


def _target(product: ProductType) -> ExecutionTarget:
    return ExecutionTarget(
        {
            ProductType.ISOLATED_MARGIN: "paper-margin-isolated-primary",
            ProductType.USDT_PERPETUAL: "paper-usdt-perpetual-primary",
        }[product],
        Mode.PAPER,
        "paper-account",
        product,
    )


def _context(product: ProductType):
    if product is ProductType.ISOLATED_MARGIN:
        return IsolatedMarginOrderContext("BTCUSDT", "USDT", True)
    return UsdtPerpetualOrderContext(
        symbol="BTCUSDT",
        leverage=Decimal("3"),
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


def _candidate(product: ProductType):
    target = _target(product)
    snapshot = make_source_analysis_snapshot(
        completed_at=NOW,
        recommendation=make_analysis_recommendation(quantity=Decimal("0.01"), price=Decimal("8000")),
    )
    return IntentFactory(utc_now=lambda: NOW).propose(snapshot, target, _context(product))


def _margin(*, symbol: str = "BTCUSDT", observed_at: datetime = NOW, **overrides: object) -> IsolatedMarginProductEvidence:
    values: dict[str, object] = {
        "target": _target(ProductType.ISOLATED_MARGIN),
        "isolated_symbol": symbol,
        "collateral": Decimal("100"),
        "available_collateral": Decimal("80"),
        "debt_principal": Decimal("20"),
        "accrued_interest": Decimal("0.10"),
        "margin_health": Decimal("1.50"),
        "borrow_available": Decimal("300"),
        "repayment_required": True,
        "observed_at": observed_at,
        "observation_version": 7,
    }
    values.update(overrides)
    return IsolatedMarginProductEvidence(**values)  # type: ignore[arg-type]


def _perpetual(*, symbol: str = "BTCUSDT", observed_at: datetime = NOW, **overrides: object) -> UsdtPerpetualProductEvidence:
    values: dict[str, object] = {
        "target": _target(ProductType.USDT_PERPETUAL),
        "symbol": symbol,
        "isolated_margin_confirmed": True,
        "one_way_position_confirmed": True,
        "maximum_leverage": Decimal("3"),
        "available_margin": Decimal("200"),
        "initial_margin": Decimal("50"),
        "maintenance_margin": Decimal("10"),
        "mark_price": Decimal("8000"),
        "position_quantity": Decimal("0.01"),
        "observed_at": observed_at,
        "observation_version": 11,
    }
    values.update(overrides)
    return UsdtPerpetualProductEvidence(**values)  # type: ignore[arg-type]


def _gateway(target: ExecutionTarget, product_evidence: object) -> ScriptedEvidenceGateway:
    return ScriptedEvidenceGateway(
        capabilities=[GatewayCapabilities(frozenset(ProductType), True)],
        rules=[RuleObservation(InstrumentRules("BTCUSDT", "0.50", "0.001", "0.001", "10"), NOW)],
        accounts=[AccountObservation(target.account_id, target.product, NOW, (Balance("USDT", "20000", "20000", "0"),), ())],
        quotes=[QuoteObservation("BTCUSDT", "7999.50", "8000", NOW)],
        server_times=[TimeObservation(NOW, NOW)],
        connections=[TargetConnectionObservation(target, True, NOW)],
        open_orders=[OpenOrderObservation(target, 0, NOW)],
        order_rates=[OrderRateObservation(target, 0, NOW - timedelta(seconds=60), NOW)],
        loss_drawdowns=[LossDrawdownObservation(target, "0", "0", NOW.replace(hour=0), NOW)],
        fee_rates=[FeeRateObservation(target, "BTCUSDT", "BTCUSDT", "USDT", "0.001", "fees-v1", NOW)],
        isolated_margin_evidence=[product_evidence] if target.product is ProductType.ISOLATED_MARGIN else [],
        perpetual_evidence=[product_evidence] if target.product is ProductType.USDT_PERPETUAL else [],
    )


@pytest.mark.parametrize(
    ("product", "product_evidence"),
    ((ProductType.ISOLATED_MARGIN, _margin()), (ProductType.USDT_PERPETUAL, _perpetual())),
)
def test_fresh_exact_product_evidence_is_bound_to_accepted_assessment(
    product: ProductType, product_evidence: object
) -> None:
    """Valid pair/symbol facts are the only non-Spot route into an accepted assessment."""
    candidate = _candidate(product)
    policy = select_paper_product_policy(candidate.target, candidate.context)
    gateway = _gateway(candidate.target, product_evidence)

    evidence = FreshEvidenceCollector(gateway=gateway, utc_now=lambda: NOW).collect(
        candidate, candidate.target, policy
    )
    assessment = RiskEngine().assess(candidate, candidate.target, policy, evidence)

    assert assessment.accepted is True
    assert evidence.product_evidence is product_evidence
    assert evidence.product_context_digest
    assert gateway.submit_call_count == 0
    if product is ProductType.ISOLATED_MARGIN:
        assert gateway.isolated_margin_scopes == [(candidate.target, "BTCUSDT")]
    else:
        assert gateway.perpetual_scopes == [(candidate.target, "BTCUSDT")]


@pytest.mark.parametrize(
    ("product", "product_evidence"),
    (
        (ProductType.ISOLATED_MARGIN, _margin(symbol="ETHUSDT")),
        (ProductType.USDT_PERPETUAL, _perpetual(symbol="ETHUSDT")),
    ),
)
def test_cross_scope_product_evidence_rejects_before_assessment(
    product: ProductType, product_evidence: object
) -> None:
    """Facts for another pair or symbol cannot satisfy this target's admission."""
    candidate = _candidate(product)
    policy = select_paper_product_policy(candidate.target, candidate.context)

    with pytest.raises(EvidenceCollectionRejection):
        FreshEvidenceCollector(gateway=_gateway(candidate.target, product_evidence), utc_now=lambda: NOW).collect(
            candidate, candidate.target, policy
        )


@pytest.mark.parametrize(
    ("product", "product_evidence"),
    (
        (ProductType.ISOLATED_MARGIN, _margin(observed_at=NOW - timedelta(seconds=61))),
        (ProductType.USDT_PERPETUAL, _perpetual(observed_at=NOW - timedelta(seconds=61))),
    ),
)
def test_stale_product_evidence_rejects_before_risk_acceptance(
    product: ProductType, product_evidence: object
) -> None:
    """Freshness includes product observations, not merely the generic account snapshot."""
    candidate = _candidate(product)
    policy = select_paper_product_policy(candidate.target, candidate.context)

    with pytest.raises(EvidenceCollectionRejection):
        FreshEvidenceCollector(gateway=_gateway(candidate.target, product_evidence), utc_now=lambda: NOW).collect(
            candidate, candidate.target, policy
        )


@pytest.mark.parametrize(
    ("product", "product_evidence"),
    (
        (ProductType.ISOLATED_MARGIN, _margin(margin_health=Decimal("1.00"))),
        (ProductType.USDT_PERPETUAL, _perpetual(one_way_position_confirmed=False)),
    ),
)
def test_unsafe_product_facts_do_not_issue_ticket_or_permit(
    tmp_path: Path, product: ProductType, product_evidence: object
) -> None:
    """Rejected product entry leaves every authority and outbound effect absent."""
    candidate = _candidate(product)
    policy = select_paper_product_policy(candidate.target, candidate.context)
    gateway = _gateway(candidate.target, product_evidence)
    database_path = tmp_path / "product-admission.sqlite"
    ledger = SQLiteExecutionLedger(database_path, clock=_Clock())
    service = ProposalService(
        ledger=ledger,
        intent_factory=IntentFactory(utc_now=lambda: NOW),
        evidence_collector=FreshEvidenceCollector(gateway=gateway, utc_now=lambda: NOW),
        risk_engine=RiskEngine(),
        approval_service=ApprovalService(ledger=ledger, utc_now=lambda: NOW),
    )
    try:
        ledger.record_candidate(candidate)
        assessment = service.assess(candidate, candidate.target, policy)
        assert assessment.accepted is False
        assert ledger.list_approval_tickets() == ()
    finally:
        ledger.close()

    connection = open_sqlite_connection(database_path)
    try:
        accepted = connection.execute(
            "SELECT COUNT(*) FROM proposal_risk_assessments WHERE accepted = 1"
        ).fetchone()[0]
        tickets = connection.execute("SELECT COUNT(*) FROM approval_tickets").fetchone()[0]
        permits = connection.execute("SELECT COUNT(*) FROM outbound_dispatch_attempts").fetchone()[0]
        commands = connection.execute("SELECT COUNT(*) FROM order_commands").fetchone()[0]
    finally:
        connection.close()
    assert (accepted, tickets, permits, commands, gateway.submit_call_count) == (0, 0, 0, 0, 0)


def test_candidate_context_is_frozen_and_evidence_digest_cannot_be_substituted() -> None:
    """No caller can mutate product facts after conversion or swap them after collection."""
    candidate = _candidate(ProductType.USDT_PERPETUAL)
    with pytest.raises(FrozenInstanceError):
        candidate.context.leverage = Decimal("1")  # type: ignore[misc]

    policy = select_paper_product_policy(candidate.target, candidate.context)
    evidence = FreshEvidenceCollector(
        gateway=_gateway(candidate.target, _perpetual()), utc_now=lambda: NOW
    ).collect(candidate, candidate.target, policy)
    forged = replace(evidence, product_context_digest="forged-context")

    assert RiskEngine().assess(candidate, candidate.target, policy, forged).accepted is False
