"""Real-SQLite automatic pending-ticket issuance contracts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.application.proposal import ProposalService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.approval import ApprovalTicketStatus
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


def _gateway(*, accepted: bool = True) -> ScriptedEvidenceGateway:
    target = make_execution_target()
    return ScriptedEvidenceGateway(
        capabilities=[GatewayCapabilities(frozenset({ProductType.SPOT}), True)],
        rules=[RuleObservation(InstrumentRules("BTCUSDT", "0.50", "0.001", "0.001", "10"), NOW)],
        accounts=[
            make_account_observation(
                observed_at=NOW,
                balances=(Balance("USDT", "2000", "1500" if accepted else "1", "0"),),
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


def _service(ledger: SQLiteExecutionLedger, gateway: ScriptedEvidenceGateway) -> ProposalService:
    return ProposalService(
        ledger=ledger,
        intent_factory=IntentFactory(),
        evidence_collector=FreshEvidenceCollector(gateway=gateway, utc_now=lambda: NOW),
        risk_engine=RiskEngine(),
        approval_service=ApprovalService(ledger=ledger, utc_now=lambda: NOW),
    )


def _propose_and_assess(service: ProposalService):
    target = make_execution_target()
    candidate = service.propose(
        make_source_analysis_snapshot(
            recommendation=make_analysis_recommendation(price="8000", quantity="0.125")
        ),
        target,
    )
    assessment = service.assess(candidate, target, select_phase2_policy(target))
    assert candidate is not None
    return candidate, assessment


def test_accepted_persisted_proposal_issues_one_complete_ticket_without_submission_side_effects(
    execution_database_path,
) -> None:
    """D-04 only creates the review record after all accepted facts are durable."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    gateway = _gateway()
    candidate, assessment = _propose_and_assess(_service(ledger, gateway))
    tickets = ledger.list_approval_tickets()
    ledger.close()

    assert assessment.accepted is True
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket.status is ApprovalTicketStatus.PENDING
    assert ticket.candidate_digest == candidate.intent_digest
    assert ticket.evidence_digest == assessment.evidence_digest
    assert ticket.policy_digest == assessment.policy_digest
    assert ticket.review.estimated_fee == Decimal("1.000")
    assert ticket.review.fee_currency == "USDT"
    assert ticket.review.fee_rate_version == "fees-v1"
    assert ticket.review.quote_identifier == "BTCUSDT"
    assert ticket.expires_at == NOW + timedelta(seconds=60)
    assert gateway.submit_call_count == 0

    inspection = open_sqlite_connection(execution_database_path)
    try:
        assert inspection.execute("SELECT COUNT(*) FROM approval_tickets").fetchone()[0] == 1
        assert inspection.execute("SELECT COUNT(*) FROM approval_ticket_events").fetchone()[0] == 1
        assert inspection.execute("SELECT COUNT(*) FROM order_commands").fetchone()[0] == 0
        assert inspection.execute("SELECT COUNT(*) FROM submission_claims").fetchone()[0] == 0
    finally:
        inspection.close()


def test_retry_and_sqlite_reopen_return_the_same_single_pending_ticket(execution_database_path) -> None:
    """Candidate and accepted-assessment uniqueness survive retries and process restart."""
    first_ledger = SQLiteExecutionLedger(execution_database_path)
    gateway = _gateway()
    candidate, assessment = _propose_and_assess(_service(first_ledger, gateway))
    first_ticket = first_ledger.list_approval_tickets()[0]
    repeated = ApprovalService(ledger=first_ledger, utc_now=lambda: NOW).create_pending_ticket(
        candidate, assessment
    )
    first_ledger.close()

    reopened = SQLiteExecutionLedger(execution_database_path)
    after_reopen = ApprovalService(ledger=reopened, utc_now=lambda: NOW).create_pending_ticket(
        candidate, assessment
    )
    tickets = reopened.list_approval_tickets()
    reopened.close()

    assert repeated.ticket_id == first_ticket.ticket_id
    assert after_reopen.ticket_id == first_ticket.ticket_id
    assert [ticket.ticket_id for ticket in tickets] == [first_ticket.ticket_id]


@pytest.mark.parametrize("accepted", [False])
def test_rejected_assessment_creates_no_ticket(execution_database_path, accepted: bool) -> None:
    """Rejected risk results never reach restricted ticket issuance."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    candidate, assessment = _propose_and_assess(_service(ledger, _gateway(accepted=accepted)))
    tickets = ledger.list_approval_tickets()
    ledger.close()

    assert candidate is not None
    assert assessment.accepted is False
    assert tickets == ()
