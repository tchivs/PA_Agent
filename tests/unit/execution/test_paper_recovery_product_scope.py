"""Product-scoped, fail-closed recovery assessment contracts."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pa_agent.trading.application.recovery_assessment import RecoveryAssessmentService
from pa_agent.trading.domain.approval import ExecutionTarget, RecoveryScope
from pa_agent.trading.domain.models import (
    AccountObservation,
    GatewayCapabilities,
    InstrumentRules,
    IsolatedMarginOrderContext,
    Mode,
    ProtectiveExitPlan,
    ProductType,
    QuoteObservation,
    RuleObservation,
    Side,
    SpotOrderContext,
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
from pa_agent.trading.ports.gateway import GatewayUnavailableError
from tests.fixtures.fake_exchange import ScriptedEvidenceGateway

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


class _NoRecordLedger:
    """Proves assessments reject before a recorder could allocate authority."""

    def __init__(self) -> None:
        self.recorder_calls = 0

    def _record_recovery_assessment_from_service(self, scope: object, assessment: object) -> object:
        self.recorder_calls += 1
        raise AssertionError("rejected recovery evidence must never reach the recorder")


def _target(product: ProductType) -> ExecutionTarget:
    target_ids = {
        ProductType.SPOT: "paper-spot-primary",
        ProductType.ISOLATED_MARGIN: "paper-margin-isolated-primary",
        ProductType.USDT_PERPETUAL: "paper-usdt-perpetual-primary",
    }
    return ExecutionTarget(
        target_id=target_ids[product],
        mode=Mode.PAPER,
        account_id="paper-account",
        product=product,
    )


def _context(product: ProductType, key: str = "BTCUSDT") -> object:
    if product is ProductType.SPOT:
        return SpotOrderContext()
    if product is ProductType.ISOLATED_MARGIN:
        return IsolatedMarginOrderContext(
            isolated_symbol=key, borrow_asset="USDT", auto_repay=True
        )
    return UsdtPerpetualOrderContext(
        symbol=key,
        leverage=Decimal("3"),
        margin_mode="isolated",
        position_mode="one_way",
        protective_exit=ProtectiveExitPlan(
            symbol=key,
            entry_side=Side.BUY,
            trigger_price=Decimal("35000"),
            maximum_loss=Decimal("100"),
            policy_version="paper-usdt-perpetual-v1",
        ),
    )


def _scope(product: ProductType, key: str = "BTCUSDT") -> RecoveryScope:
    target = _target(product)
    context = _context(product, key)
    policy = select_paper_product_policy(target, context)
    return RecoveryScope.from_ledger_values(
        persistent_scope_id=f"scope-{product.value}",
        target=target,
        product_context=context,
        product_scope_key=key,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
    )


def _margin_evidence(scope: RecoveryScope, *, key: str = "BTCUSDT") -> IsolatedMarginProductEvidence:
    return IsolatedMarginProductEvidence(
        target=scope.target,
        isolated_symbol=key,
        collateral=Decimal("100"),
        available_collateral=Decimal("100"),
        debt_principal=Decimal("0"),
        accrued_interest=Decimal("0"),
        margin_health=Decimal("1.5"),
        borrow_available=Decimal("300"),
        repayment_required=False,
        observed_at=NOW,
        observation_version=1,
    )


def _perpetual_evidence(scope: RecoveryScope, *, key: str = "BTCUSDT") -> UsdtPerpetualProductEvidence:
    return UsdtPerpetualProductEvidence(
        target=scope.target,
        symbol=key,
        isolated_margin_confirmed=True,
        one_way_position_confirmed=True,
        maximum_leverage=Decimal("3"),
        available_margin=Decimal("200"),
        initial_margin=Decimal("0"),
        maintenance_margin=Decimal("0"),
        mark_price=Decimal("40000"),
        position_quantity=Decimal("0"),
        observed_at=NOW,
        observation_version=1,
    )


def _gateway(
    scope: RecoveryScope,
    *,
    margin: object | None = None,
    perpetual: object | None = None,
) -> ScriptedEvidenceGateway:
    key = scope.product_scope_key
    target = scope.target
    return ScriptedEvidenceGateway(
        capabilities=[GatewayCapabilities(frozenset({target.product}), True)],
        rules=[RuleObservation(InstrumentRules(key, "0.50", "0.001", "0.001", "10"), NOW)],
        accounts=[AccountObservation(target.account_id, target.product, NOW)],
        quotes=[QuoteObservation(key, "39999.50", "40000", NOW)],
        server_times=[TimeObservation(server_time=NOW, observed_at=NOW)],
        connections=[TargetConnectionObservation(target, True, NOW)],
        open_orders=[OpenOrderObservation(target, 0, NOW)],
        order_rates=[OrderRateObservation(target, 0, NOW - timedelta(seconds=60), NOW)],
        loss_drawdowns=[LossDrawdownObservation(target, "0", "0", NOW, NOW)],
        fee_rates=[FeeRateObservation(target, key, key, "USDT", "0.001", "fees-v1", NOW)],
        isolated_margin_evidence=(
            [] if target.product is not ProductType.ISOLATED_MARGIN else [
                _margin_evidence(scope) if margin is None else margin
            ]
        ),
        perpetual_evidence=(
            [] if target.product is not ProductType.USDT_PERPETUAL else [
                _perpetual_evidence(scope) if perpetual is None else perpetual
            ]
        ),
    )


@pytest.mark.parametrize(
    "product", [ProductType.SPOT, ProductType.ISOLATED_MARGIN, ProductType.USDT_PERPETUAL]
)
def test_recovery_scope_is_immutable_and_exact_to_one_product_key(product: ProductType) -> None:
    """The ledger scope binds target, context, policy, and only its product key."""
    scope = _scope(product)

    assert scope.product_scope_key == "BTCUSDT"
    assert scope.policy_id == select_paper_product_policy(
        scope.target, scope.product_context
    ).policy_id
    assert scope.is_canonical()
    with pytest.raises(FrozenInstanceError):
        scope.product_scope_key = "ETHUSDT"  # type: ignore[misc]
    with pytest.raises(ValueError):
        replace(scope, product_scope_key="ETHUSDT")


@pytest.mark.parametrize(
    "product", [ProductType.SPOT, ProductType.ISOLATED_MARGIN, ProductType.USDT_PERPETUAL]
)
def test_complete_fresh_exact_scope_product_evidence_is_assessed(product: ProductType) -> None:
    """The service chooses only the scope-selected product policy and exact evidence read."""
    scope = _scope(product)
    ledger = _NoRecordLedger()
    gateway = _gateway(scope)

    assessment = RecoveryAssessmentService(
        ledger=ledger, gateway=gateway, utc_now=lambda: NOW
    ).assess(scope)

    assert assessment.accepted
    assert assessment.policy_id == scope.policy_id
    assert assessment.scope_digest == scope.scope_digest
    assert gateway.submit_call_count == 0
    if product is ProductType.ISOLATED_MARGIN:
        assert gateway.isolated_margin_scopes == [(scope.target, "BTCUSDT")]
    if product is ProductType.USDT_PERPETUAL:
        assert gateway.perpetual_scopes == [(scope.target, "BTCUSDT")]


@pytest.mark.parametrize(
    ("product", "evidence"),
    [
        (ProductType.ISOLATED_MARGIN, lambda scope: _margin_evidence(scope, key="ETHUSDT")),
        (ProductType.USDT_PERPETUAL, lambda scope: _perpetual_evidence(scope, key="ETHUSDT")),
    ],
)
def test_cross_pair_or_symbol_evidence_denies_without_recording(
    product: ProductType, evidence: object
) -> None:
    """Same-account product facts from a different pair or symbol cannot substitute."""
    scope = _scope(product)
    ledger = _NoRecordLedger()
    gateway = _gateway(
        scope,
        margin=evidence(scope) if product is ProductType.ISOLATED_MARGIN else None,
        perpetual=evidence(scope) if product is ProductType.USDT_PERPETUAL else None,
    )

    result = RecoveryAssessmentService(
        ledger=ledger, gateway=gateway, utc_now=lambda: NOW
    ).assess_and_record(scope)

    assert result is None
    assert ledger.recorder_calls == 0
    assert gateway.submit_call_count == 0


@pytest.mark.parametrize(
    ("product", "evidence"),
    [
        (ProductType.ISOLATED_MARGIN, lambda scope: replace(_margin_evidence(scope), observed_at=NOW - timedelta(seconds=61))),
        (ProductType.USDT_PERPETUAL, lambda scope: replace(_perpetual_evidence(scope), observed_at=NOW - timedelta(seconds=61))),
    ],
)
def test_missing_or_stale_product_evidence_denies_before_authority(
    product: ProductType, evidence: object
) -> None:
    """Typed unavailable and stale product facts cannot become a clearance assessment."""
    scope = _scope(product)
    ledger = _NoRecordLedger()
    stale_gateway = _gateway(
        scope,
        margin=evidence(scope) if product is ProductType.ISOLATED_MARGIN else None,
        perpetual=evidence(scope) if product is ProductType.USDT_PERPETUAL else None,
    )
    missing_gateway = _gateway(
        scope,
        margin=GatewayUnavailableError("missing") if product is ProductType.ISOLATED_MARGIN else None,
        perpetual=GatewayUnavailableError("missing") if product is ProductType.USDT_PERPETUAL else None,
    )
    service = RecoveryAssessmentService(ledger=ledger, gateway=stale_gateway, utc_now=lambda: NOW)

    assert service.assess_and_record(scope) is None
    assert RecoveryAssessmentService(
        ledger=ledger, gateway=missing_gateway, utc_now=lambda: NOW
    ).assess_and_record(scope) is None
    assert ledger.recorder_calls == 0
    assert stale_gateway.submit_call_count == missing_gateway.submit_call_count == 0


def test_forged_scope_binding_cannot_reach_evidence_collection_or_recorder() -> None:
    """A modified durable ID/digest is rejected before any product read or recording."""
    scope = _scope(ProductType.SPOT)
    object.__setattr__(scope, "persistent_scope_id", "forged-scope")
    ledger = _NoRecordLedger()
    gateway = _gateway(scope)

    assessment = RecoveryAssessmentService(
        ledger=ledger, gateway=gateway, utc_now=lambda: NOW
    ).assess(scope)

    assert not assessment.accepted
    assert assessment.reason_codes == ("scope_malformed",)
    assert gateway.call_order == []
    assert ledger.recorder_calls == 0
