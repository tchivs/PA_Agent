"""Durable, redacted rejection-audit coverage before approval tickets exist."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.application.proposal import ProposalService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.errors import ConversionRejectionReason, RiskRejectionReason
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
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from pa_agent.trading.ports.gateway import GatewayUnavailableError
from tests.fixtures.execution_factories import (
    make_account_observation,
    make_execution_target,
    make_source_analysis_snapshot,
)
from tests.fixtures.fake_exchange import ScriptedEvidenceGateway

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 12, 11, 0, tzinfo=UTC)


def _gateway(*, connection: object | None = None) -> ScriptedEvidenceGateway:
    """Build one offline evidence source with a controllable failure response."""
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
        connections=[connection or TargetConnectionObservation(target, True, NOW)],
        open_orders=[OpenOrderObservation(target, 2, NOW)],
        order_rates=[OrderRateObservation(target, 4, NOW - timedelta(seconds=60), NOW)],
        loss_drawdowns=[
            LossDrawdownObservation(target, "99", "0.09", datetime(2026, 7, 12, tzinfo=UTC), NOW)
        ],
        fee_rates=[FeeRateObservation(target, "BTCUSDT", "BTCUSDT", "USDT", "0.001", "fees-v1", NOW)],
    )


def _service(ledger: SQLiteExecutionLedger, gateway: ScriptedEvidenceGateway) -> ProposalService:
    return ProposalService(
        ledger=ledger,
        intent_factory=IntentFactory(),
        evidence_collector=FreshEvidenceCollector(gateway=gateway, utc_now=lambda: NOW),
        risk_engine=RiskEngine(),
    )


def test_conversion_and_evidence_rejections_survive_reopen_as_redacted_audit_facts(
    execution_database_path,
) -> None:
    """D-02/D-07 failures retain only controlled source/reason metadata."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    target = make_execution_target()
    gateway = _gateway(connection=GatewayUnavailableError("api_secret=synthetic-secret"))
    service = _service(ledger, gateway)

    rejected_candidate = service.propose(make_source_analysis_snapshot(repaired=True), target)
    candidate = service.propose(make_source_analysis_snapshot(), target)
    assessment = service.assess(candidate, target, select_phase2_policy(target))
    ledger.close()

    assert rejected_candidate is None
    assert candidate is not None
    assert assessment.accepted is False
    assert RiskRejectionReason.EVIDENCE_UNAVAILABLE in assessment.reason_codes
    assert gateway.submit_call_count == 0

    reopened = SQLiteExecutionLedger(execution_database_path)
    facts = reopened.list_proposal_audit_facts()
    reopened.close()

    assert [(fact.kind, fact.reason_code) for fact in facts] == [
        ("conversion_rejected", ConversionRejectionReason.REPAIRED_SOURCE.value),
        ("candidate_accepted", None),
        ("risk_rejected", RiskRejectionReason.EVIDENCE_UNAVAILABLE.value),
    ]
    assert all(fact.source_id == "analysis-001" for fact in facts)
    assert all(fact.source_digest for fact in facts)
    assert all("synthetic-secret" not in fact.summary_json for fact in facts)
    assert all("api_secret" not in fact.summary_json for fact in facts)
