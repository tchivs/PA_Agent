"""Integration coverage for complete, fail-closed fresh risk evidence."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
from pa_agent.trading.domain.errors import RiskRejectionReason
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
    select_phase2_policy,
)
from pa_agent.trading.ports.gateway import GatewayUnavailableError, TargetConnectionObservation
from tests.fixtures.execution_factories import (
    make_account_observation,
    make_candidate_execution_intent,
    make_execution_target,
)
from tests.fixtures.fake_exchange import ScriptedEvidenceGateway


pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 12, 10, 45, tzinfo=UTC)
CALL_SEQUENCE = [
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
]


def _gateway(*, fee_rates: list[object] | None = None, connections: list[object] | None = None) -> ScriptedEvidenceGateway:
    target = make_execution_target()
    quote = QuoteObservation(symbol="BTCUSDT", bid="7999.50", ask="8000", observed_at=NOW)
    return ScriptedEvidenceGateway(
        capabilities=[GatewayCapabilities(frozenset({ProductType.SPOT}), True)] * 2,
        rules=[
            RuleObservation(
                InstrumentRules("BTCUSDT", "0.50", "0.001", "0.001", "10"), NOW
            )
        ] * 2,
        accounts=[
            make_account_observation(
                observed_at=NOW,
                balances=(Balance("USDT", "2000", "1500", "0"),),
                positions=(),
            )
        ] * 2,
        quotes=[quote] * 2,
        server_times=[TimeObservation(server_time=NOW, observed_at=NOW)] * 2,
        connections=connections
        or [TargetConnectionObservation(target=target, connected=True, observed_at=NOW)] * 2,
        open_orders=[OpenOrderObservation(target=target, count=2, observed_at=NOW)] * 2,
        order_rates=[
            OrderRateObservation(
                target=target,
                count=4,
                window_started_at=NOW - timedelta(seconds=60),
                window_ends_at=NOW,
            )
        ] * 2,
        loss_drawdowns=[
            LossDrawdownObservation(
                target=target,
                realized_loss="99",
                drawdown="0.09",
                utc_day_started_at=datetime(2026, 7, 12, tzinfo=UTC),
                observed_at=NOW,
            )
        ] * 2,
        fee_rates=fee_rates
        or [
            FeeRateObservation(
                target=target,
                symbol="BTCUSDT",
                quote_identifier="BTCUSDT",
                fee_currency="USDT",
                rate="0.001",
                rate_version="fees-v1",
                observed_at=NOW,
            )
        ]
        * 2,
    )


def _assess(gateway: ScriptedEvidenceGateway):
    target = make_execution_target()
    return FreshEvidenceCollector(gateway=gateway, utc_now=lambda: NOW).assess(
        make_candidate_execution_intent(price="8000", quantity="0.125"),
        target,
        select_phase2_policy(target),
    )


def test_every_assessment_refreshes_the_complete_current_evidence_sequence() -> None:
    gateway = _gateway()

    first = _assess(gateway)
    second = _assess(gateway)

    assert first.accepted is True
    assert second.accepted is True
    assert first.fee_estimate is not None
    assert first.fee_estimate.amount == Decimal("1.000")
    assert first.fee_estimate.rate_version == "fees-v1"
    assert gateway.call_order == CALL_SEQUENCE * 2
    assert gateway.submit_call_count == 0


@pytest.mark.parametrize(
    ("fee_rate", "reason"),
    [
        (GatewayUnavailableError("offline"), RiskRejectionReason.FEE_EVIDENCE_MISSING),
        (
            FeeRateObservation(
                target=make_execution_target(), symbol="BTCUSDT", quote_identifier="BTCUSDT",
                fee_currency="USDT", rate="0.001", rate_version="fees-v1", observed_at=NOW - timedelta(seconds=61)
            ),
            RiskRejectionReason.FEE_EVIDENCE_STALE,
        ),
        (
            FeeRateObservation(
                target=make_execution_target(), symbol="ETHUSDT", quote_identifier="BTCUSDT",
                fee_currency="USDT", rate="0.001", rate_version="fees-v1", observed_at=NOW
            ),
            RiskRejectionReason.FEE_EVIDENCE_SYMBOL_MISMATCH,
        ),
    ],
)
def test_invalid_fee_evidence_fails_closed_without_cache_or_submission(
    fee_rate: object, reason: RiskRejectionReason
) -> None:
    gateway = _gateway(fee_rates=[fee_rate])

    assessment = _assess(gateway)

    assert assessment.accepted is False
    assert reason in assessment.reason_codes
    assert assessment.fee_estimate is None
    assert gateway.call_order == CALL_SEQUENCE
    assert gateway.submit_call_count == 0


def test_degraded_connection_rejects_before_risk_engine_or_submission() -> None:
    gateway = _gateway(
        connections=[
            TargetConnectionObservation(
                target=make_execution_target(), connected=False, observed_at=NOW
            )
        ]
    )

    assessment = _assess(gateway)

    assert assessment.accepted is False
    assert RiskRejectionReason.EVIDENCE_CONNECTION_DEGRADED in assessment.reason_codes
    assert gateway.call_order == CALL_SEQUENCE
    assert gateway.submit_call_count == 0
