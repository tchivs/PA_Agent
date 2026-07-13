"""Policy and approval contracts for immutable Paper product tickets."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pa_agent.trading.domain.approval import CandidateExecutionIntent, ExecutionTarget, TicketBinding
from pa_agent.trading.domain.errors import RiskRejection, RiskRejectionReason
from pa_agent.trading.domain.models import (
    IsolatedMarginOrderContext,
    Mode,
    OrderType,
    ProductType,
    ProtectiveExitPlan,
    Side,
    SpotOrderContext,
    UsdtPerpetualOrderContext,
)
from pa_agent.trading.domain.risk import FeeEstimate, select_paper_product_policy, select_phase2_policy

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _target(product: ProductType) -> ExecutionTarget:
    target_id = {
        ProductType.SPOT: "paper-spot-primary",
        ProductType.ISOLATED_MARGIN: "paper-margin-isolated-primary",
        ProductType.USDT_PERPETUAL: "paper-usdt-perpetual-primary",
    }[product]
    return ExecutionTarget(target_id, Mode.PAPER, "paper-account", product)


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
    context = _context(product)
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
        context=context,
    )


def _binding(candidate: CandidateExecutionIntent) -> TicketBinding:
    policy = select_paper_product_policy(candidate.target, candidate.context)
    fee = FeeEstimate(
        target=candidate.target,
        symbol=candidate.symbol,
        quote_identifier=candidate.symbol,
        expected_quote_price=Decimal("8000"),
        fee_currency="USDT",
        rate=Decimal("0.001"),
        rate_version="fees-v1",
        amount=Decimal("0.08"),
    )
    return TicketBinding.from_persisted_facts(
        candidate=candidate,
        policy=policy,
        evidence_digest="evidence-digest",
        quote_observed_at=NOW,
        fee_estimate=fee,
        risk_reason_codes=(),
        risk_metrics=(("slippage", Decimal("0.50")),),
    )


def test_catalog_selects_only_exact_immutable_product_policies() -> None:
    """Each exact Paper context selects a distinct immutable policy identity."""
    policies = [
        select_paper_product_policy(candidate.target, candidate.context)
        for candidate in (_candidate(product) for product in ProductType)
    ]

    assert [policy.policy_id for policy in policies] == [
        "paper-spot-primary",
        "paper-margin-isolated-primary",
        "paper-usdt-perpetual-primary",
    ]
    assert len({policy.policy_version for policy in policies}) == 3
    assert len({policy.policy_digest for policy in policies}) == 3
    assert all(isinstance(policy.maximum_order_notional, Decimal) for policy in policies)
    assert policies[1].product_limits is not None
    assert policies[1].product_limits.maximum_leverage == Decimal("3")
    assert policies[2].product_limits is not None
    assert policies[2].product_limits.maximum_leverage == Decimal("3")
    assert policies[2].product_limits.minimum_maintenance_margin_ratio == Decimal("0.05")


@pytest.mark.parametrize("product", tuple(ProductType))
def test_ticket_binding_retains_exact_policy_and_context(product: ProductType) -> None:
    candidate = _candidate(product)
    binding = _binding(candidate)

    assert binding.policy_id == select_paper_product_policy(candidate.target, candidate.context).policy_id
    assert binding.policy_version == select_paper_product_policy(candidate.target, candidate.context).policy_version
    assert binding.product_context_digest
    assert not binding.is_authorization_equivalent_to(
        replace(binding, product_context_digest="forged"),
        policy=select_paper_product_policy(candidate.target, candidate.context),
        now=NOW,
    )


def test_legacy_selector_remains_phase2_spot_only() -> None:
    legacy = select_phase2_policy(_target(ProductType.SPOT))
    assert legacy.policy_version == "phase2-v1"
    with pytest.raises(RiskRejection) as error:
        select_phase2_policy(_target(ProductType.ISOLATED_MARGIN))
    assert error.value.reason is RiskRejectionReason.UNSUPPORTED_TARGET


@pytest.mark.parametrize(
    ("target", "context"),
    (
        (
            ExecutionTarget("paper-margin-isolated-primary", Mode.PAPER, "paper-account", ProductType.ISOLATED_MARGIN),
            IsolatedMarginOrderContext("BTCUSDT", "USDT", False),
        ),
        (
            ExecutionTarget("paper-usdt-perpetual-primary", Mode.PAPER, "paper-account", ProductType.USDT_PERPETUAL),
            IsolatedMarginOrderContext("BTCUSDT", "USDT", True),
        ),
        (
            ExecutionTarget("paper-spot-primary", Mode.TESTNET, "paper-account", ProductType.SPOT),
            SpotOrderContext(),
        ),
    ),
)
def test_selector_rejects_unsupported_mode_or_context_before_authority(target, context) -> None:
    with pytest.raises((RiskRejection, ValueError)):
        select_paper_product_policy(target, context)
