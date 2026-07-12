"""Pure, deterministic risk assessment coverage for Phase 2 Paper Spot."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.errors import DecimalValueError, RiskRejectionReason
from pa_agent.trading.domain.models import (
    Balance,
    GatewayCapabilities,
    InstrumentRules,
    Position,
    ProductType,
    QuoteObservation,
    TimeObservation,
)
from pa_agent.trading.domain.risk import (
    EvidenceBundle,
    FeeRateObservation,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    estimate_fee,
    select_phase2_policy,
)
from tests.fixtures.execution_factories import (
    make_account_observation,
    make_candidate_execution_intent,
    make_execution_target,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_evidence_bundle(**overrides: object) -> EvidenceBundle:
    target = make_execution_target()
    values: dict[str, object] = {
        "capabilities": GatewayCapabilities(frozenset({ProductType.SPOT}), True),
        "instrument_rules": InstrumentRules(
            symbol="BTCUSDT",
            price_tick="0.50",
            quantity_step="0.001",
            minimum_quantity="0.001",
            minimum_notional="10",
        ),
        "rule_observed_at": NOW,
        "account": make_account_observation(
            observed_at=NOW,
            balances=(Balance(asset="USDT", total="2000", available="1500", reserved="0"),),
            positions=(),
        ),
        "quote": QuoteObservation(
            symbol="BTCUSDT", bid="7999.50", ask="8000", observed_at=NOW
        ),
        "server_time": TimeObservation(server_time=NOW, observed_at=NOW),
        "connection": TargetConnectionObservation(
            target=target, connected=True, observed_at=NOW
        ),
        "open_orders": OpenOrderObservation(target=target, count=2, observed_at=NOW),
        "order_rate": OrderRateObservation(
            target=target,
            count=4,
            window_started_at=NOW - timedelta(seconds=60),
            window_ends_at=NOW,
        ),
        "loss_drawdown": LossDrawdownObservation(
            target=target,
            realized_loss="99",
            drawdown="0.09",
            utc_day_started_at=datetime(2026, 1, 1, tzinfo=UTC),
            observed_at=NOW,
        ),
        "fee_rate": FeeRateObservation(
            target=target,
            symbol="BTCUSDT",
            quote_identifier="quote-001",
            fee_currency="USDT",
            rate="0.001",
            rate_version="fees-v1",
            observed_at=NOW,
        ),
    }
    values.update(overrides)
    return EvidenceBundle(**values)  # type: ignore[arg-type]


def assess(**overrides: object):
    target = make_execution_target()
    candidate = make_candidate_execution_intent(price="8000", quantity="0.125")
    evidence = make_evidence_bundle(**overrides)
    return RiskEngine().assess(candidate, target, select_phase2_policy(target), evidence)


def test_risk_engine_accepts_matching_complete_evidence_and_binds_digests() -> None:
    assessment = assess()

    assert assessment.accepted is True
    assert assessment.reason_codes == ()
    assert assessment.policy_version == "phase2-v1"
    assert assessment.policy_digest
    assert assessment.evidence_digest
    assert assessment.fee_estimate.amount == Decimal("1.000")
    assert assessment.fee_estimate.rate_version == "fees-v1"


def test_phase2_policy_binds_fixed_total_exposure_in_its_digest_material() -> None:
    policy = select_phase2_policy(make_execution_target())

    assert policy.maximum_total_exposure == Decimal("1000")
    assert policy._digest_material()["maximum_total_exposure"] == Decimal("1000")
    assert policy.policy_digest


def test_risk_engine_accepts_projected_exposure_at_the_fixed_boundary() -> None:
    assessment = assess()

    assert assessment.accepted is True
    assert dict(assessment.metrics)["existing_exposure"] == Decimal("0")
    assert dict(assessment.metrics)["projected_exposure"] == Decimal("1000.000")


def test_risk_engine_rejects_projected_exposure_above_limit_with_gross_positions() -> None:
    one_cent_existing_position = Position(
        symbol="BTCUSDT",
        quantity="0.00000125",
        entry_price="8000",
        mark_price="8000",
        unrealized_pnl="0",
        margin="0",
    )
    opposite_signed_position = Position(
        symbol="BTCUSDT",
        quantity="-0.125",
        entry_price="8000",
        mark_price="8000",
        unrealized_pnl="0",
        margin="0",
    )
    unrelated_position = Position(
        symbol="ETHUSDT",
        quantity="100",
        entry_price="1",
        mark_price="1",
        unrealized_pnl="0",
        margin="0",
    )

    one_cent_over = assess(
        account=make_account_observation(
            positions=(one_cent_existing_position, unrelated_position),
        )
    )
    opposite_signed = assess(
        account=make_account_observation(
            positions=(opposite_signed_position, unrelated_position),
        )
    )

    assert one_cent_over.accepted is False
    assert one_cent_over.reason_codes == (RiskRejectionReason.EXPOSURE_LIMIT_EXCEEDED,)
    assert dict(one_cent_over.metrics)["existing_exposure"] == Decimal("0.01000000")
    assert dict(one_cent_over.metrics)["projected_exposure"] == Decimal("1000.01000000")
    assert opposite_signed.accepted is False
    assert opposite_signed.reason_codes == (RiskRejectionReason.EXPOSURE_LIMIT_EXCEEDED,)
    assert dict(opposite_signed.metrics)["existing_exposure"] == Decimal("1000.000")


@pytest.mark.parametrize(
    ("evidence_overrides", "reason"),
    (
        ({"open_orders": OpenOrderObservation(target=make_execution_target(), count=3, observed_at=NOW)}, RiskRejectionReason.OPEN_ORDER_LIMIT_EXCEEDED),
        ({"order_rate": OrderRateObservation(target=make_execution_target(), count=5, window_started_at=NOW - timedelta(seconds=60), window_ends_at=NOW)}, RiskRejectionReason.ORDER_RATE_LIMIT_EXCEEDED),
        ({"loss_drawdown": LossDrawdownObservation(target=make_execution_target(), realized_loss="100", drawdown="0", utc_day_started_at=datetime(2026, 1, 1, tzinfo=UTC), observed_at=NOW)}, RiskRejectionReason.REALIZED_LOSS_LIMIT_EXCEEDED),
        ({"loss_drawdown": LossDrawdownObservation(target=make_execution_target(), realized_loss="0", drawdown="0.10", utc_day_started_at=datetime(2026, 1, 1, tzinfo=UTC), observed_at=NOW)}, RiskRejectionReason.DRAWDOWN_LIMIT_EXCEEDED),
    ),
)
def test_risk_engine_rejects_limit_boundaries(
    evidence_overrides: dict[str, object], reason: RiskRejectionReason
) -> None:
    assessment = assess(**evidence_overrides)

    assert assessment.accepted is False
    assert assessment.reason_codes == (reason,)


@pytest.mark.parametrize(
    ("candidate_overrides", "reason"),
    (
        ({"quantity": "0.1255", "price": "8000"}, RiskRejectionReason.QUANTITY_PRECISION_INVALID),
        ({"quantity": "0.125", "price": "8001.25"}, RiskRejectionReason.PRICE_PRECISION_INVALID),
    ),
)
def test_risk_engine_rejects_evidence_derived_precision(
    candidate_overrides: dict[str, object], reason: RiskRejectionReason
) -> None:
    target = make_execution_target()
    candidate = make_candidate_execution_intent(**candidate_overrides)
    assessment = RiskEngine().assess(candidate, target, select_phase2_policy(target), make_evidence_bundle())

    assert assessment.accepted is False
    assert reason in assessment.reason_codes


def test_risk_engine_rejects_notional_balance_and_fee_binding_failures() -> None:
    over_limit = RiskEngine().assess(
        make_candidate_execution_intent(price="8000", quantity="0.126"),
        make_execution_target(),
        select_phase2_policy(make_execution_target()),
        make_evidence_bundle(),
    )
    insufficient_balance = assess(
        account=make_account_observation(
            balances=(Balance(asset="USDT", total="100", available="999", reserved="0"),),
            positions=(),
        )
    )
    stale_fee = assess(
        fee_rate=FeeRateObservation(
            target=make_execution_target(), symbol="BTCUSDT", quote_identifier="quote-001",
            fee_currency="USDT", rate="0.001", rate_version="fees-v1", observed_at=NOW - timedelta(seconds=61)
        )
    )

    assert RiskRejectionReason.ORDER_NOTIONAL_LIMIT_EXCEEDED in over_limit.reason_codes
    assert RiskRejectionReason.INSUFFICIENT_AVAILABLE_BALANCE in insufficient_balance.reason_codes
    assert RiskRejectionReason.FEE_EVIDENCE_STALE in stale_fee.reason_codes


def test_fee_estimate_rejects_cross_target_or_missing_rate_binding() -> None:
    fee = make_evidence_bundle().fee_rate

    estimate = estimate_fee("0.125", "8000", fee)

    assert estimate.amount == Decimal("1.000")
    with pytest.raises(DecimalValueError):
        estimate_fee("NaN", "8000", fee)
