"""Selected target policy coverage for the Phase 2 Paper Spot boundary."""
from __future__ import annotations

from decimal import Decimal

import pytest

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.errors import RiskRejection, RiskRejectionReason
from pa_agent.trading.domain.models import Mode, OrderType, ProductType
from pa_agent.trading.domain.risk import RiskPolicy, select_phase2_policy
from tests.fixtures.execution_factories import (
    make_candidate_execution_intent,
    make_execution_target,
)


def test_phase2_policy_selects_only_the_explicit_paper_spot_target() -> None:
    target = make_execution_target()

    policy = select_phase2_policy(target)

    assert policy.policy_version == "phase2-v1"
    assert policy.mode is Mode.PAPER
    assert policy.product is ProductType.SPOT
    assert policy.account_id == "paper-account"
    assert policy.symbols == frozenset({"BTCUSDT"})
    assert policy.order_types == frozenset({OrderType.MARKET, OrderType.LIMIT})
    assert policy.maximum_order_notional == Decimal("1000")
    assert policy.maximum_open_orders == 3
    assert policy.maximum_accepted_orders == 5
    assert policy.order_rate_window_seconds == 60
    assert policy.maximum_utc_day_realized_loss == Decimal("100")
    assert policy.maximum_utc_day_drawdown == Decimal("0.10")


@pytest.mark.parametrize(
    "target",
    (
        make_execution_target(mode=Mode.TESTNET),
        make_execution_target(mode=Mode.LIVE),
        make_execution_target(product=ProductType.ISOLATED_MARGIN),
        make_execution_target(product=ProductType.USDT_PERPETUAL),
        make_execution_target(account_id="other-account"),
    ),
)
def test_phase2_policy_rejects_every_unselected_target(target: ExecutionTarget) -> None:
    with pytest.raises(RiskRejection) as error:
        select_phase2_policy(target)

    assert error.value.reason is RiskRejectionReason.UNSUPPORTED_TARGET


def test_phase2_policy_rejects_candidate_target_and_scope_mismatches() -> None:
    policy = select_phase2_policy(make_execution_target())
    candidate = make_candidate_execution_intent(symbol="ETHUSDT")

    with pytest.raises(RiskRejection) as error:
        policy.require_matches(candidate, make_execution_target())

    assert error.value.reason is RiskRejectionReason.SYMBOL_NOT_ALLOWED


def test_phase2_policy_does_not_accept_caller_supplied_threshold_overrides() -> None:
    with pytest.raises(TypeError):
        RiskPolicy(  # type: ignore[call-arg]
            policy_version="phase2-v1",
            maximum_order_notional=Decimal("999999"),
        )
