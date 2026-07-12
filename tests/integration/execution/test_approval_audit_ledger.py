"""Real-SQLite audit coverage for accepted pre-ticket proposal facts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.application.proposal import ProposalService
from pa_agent.trading.application.risk_engine import RiskEngine
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
from pa_agent.trading.persistence.sqlite_connection import open_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.execution_factories import (
    make_account_observation,
    make_analysis_recommendation,
    make_execution_target,
    make_source_analysis_snapshot,
)
from tests.fixtures.fake_exchange import ScriptedEvidenceGateway

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 12, 11, 0, tzinfo=UTC)


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


def test_accepted_candidate_evidence_fee_and_assessment_are_queryable_after_reopen(
    execution_database_path,
) -> None:
    """SIM-03 audit rows retain canonical bindings without creating a ticket or claim."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    target = make_execution_target()
    gateway = _gateway()
    service = ProposalService(
        ledger=ledger,
        intent_factory=IntentFactory(),
        evidence_collector=FreshEvidenceCollector(gateway=gateway, utc_now=lambda: NOW),
        risk_engine=RiskEngine(),
    )

    candidate = service.propose(
        make_source_analysis_snapshot(
            recommendation=make_analysis_recommendation(price="8000", quantity="0.125")
        ),
        target,
    )
    assessment = service.assess(candidate, target, select_phase2_policy(target))
    ledger.close()

    assert candidate is not None
    assert assessment.accepted is True
    assert assessment.fee_estimate is not None
    assert assessment.fee_estimate.amount == Decimal("1.000")
    assert gateway.submit_call_count == 0

    inspection = open_sqlite_connection(execution_database_path)
    try:
        assert inspection.execute("SELECT COUNT(*) FROM order_commands").fetchone()[0] == 0
        assert inspection.execute("SELECT COUNT(*) FROM submission_claims").fetchone()[0] == 0
        audit_foreign_keys = {
            row[2] for row in inspection.execute("PRAGMA foreign_key_list(proposal_audit_facts)")
        }
        assert audit_foreign_keys == {"proposal_candidates", "proposal_sources"}
        assert inspection.execute("PRAGMA foreign_key_list(proposal_evidence)").fetchone() is not None
    finally:
        inspection.close()

    reopened = SQLiteExecutionLedger(execution_database_path)
    facts = reopened.list_proposal_audit_facts()
    reopened.close()

    assert [fact.kind for fact in facts] == [
        "candidate_accepted",
        "evidence_recorded",
        "risk_assessed",
    ]
    assert facts[0].source_digest == candidate.intent_digest
    assert facts[1].evidence_digest == assessment.evidence_digest
    assert facts[2].policy_digest == assessment.policy_digest
    assert facts[2].evidence_digest == assessment.evidence_digest
    assert facts[2].fee_amount == "1.000000"
