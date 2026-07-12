"""Real-SQLite automatic pending-ticket issuance contracts."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.application.proposal import ProposalService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.approval import ApprovalTicketStatus, TicketTerminalEvent
from pa_agent.trading.domain.models import (
    Balance,
    GatewayCapabilities,
    InstrumentRules,
    OrderType,
    Position,
    ProductType,
    QuoteObservation,
    RuleObservation,
    Side,
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


def _gateway(
    *,
    accepted: bool = True,
    positions: tuple[Position, ...] = (),
    quote: QuoteObservation | None = None,
    balances: tuple[Balance, ...] | None = None,
) -> ScriptedEvidenceGateway:
    target = make_execution_target()
    return ScriptedEvidenceGateway(
        capabilities=[GatewayCapabilities(frozenset({ProductType.SPOT}), True)],
        rules=[RuleObservation(InstrumentRules("BTCUSDT", "0.50", "0.001", "0.001", "10"), NOW)],
        accounts=[
            make_account_observation(
                observed_at=NOW,
                balances=balances
                or (Balance("USDT", "2000", "1500" if accepted else "1", "0"),),
                positions=positions,
            )
        ],
        quotes=[quote or QuoteObservation("BTCUSDT", "7999.50", "8000", NOW)],
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


def _propose_and_assess(
    service: ProposalService,
    *,
    price: str | None = "8000",
    quantity: str = "0.125",
    side: Side = Side.BUY,
    order_type: OrderType = OrderType.LIMIT,
):
    target = make_execution_target()
    candidate = service.propose(
        make_source_analysis_snapshot(
            recommendation=make_analysis_recommendation(
                price=price, quantity=quantity, side=side, order_type=order_type
            )
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


@pytest.mark.parametrize("side", (Side.BUY, Side.SELL))
def test_market_proposals_issue_one_ticket_with_side_specific_fresh_economics(
    execution_database_path, side: Side
) -> None:
    """MARKET candidates retain no limit price and still cross the proposal boundary."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    balances = (Balance("USDT", "2000", "1500", "0"),)
    if side is Side.SELL:
        balances += (Balance("BTC", "1", "1", "0"),)
    gateway = _gateway(balances=balances)
    candidate, assessment = _propose_and_assess(
        _service(ledger, gateway), price=None, side=side, order_type=OrderType.MARKET
    )
    tickets = ledger.list_approval_tickets()
    ledger.close()

    assert candidate.price is None
    assert assessment.accepted is True
    assert len(tickets) == 1
    assert tickets[0].review.expected_price == (
        Decimal("8000") if side is Side.BUY else Decimal("7999.50")
    )
    assert gateway.submit_call_count == 0


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


def test_over_limit_exposure_persists_rejection_without_ticket_or_outbound_side_effects(
    execution_database_path,
) -> None:
    """Selected-account gross exposure rejects the automatic ticket boundary."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    gateway = _gateway(
        positions=(
            Position(
                symbol="BTCUSDT",
                quantity="0.001",
                entry_price="8000",
                mark_price="8000",
                unrealized_pnl="0",
                margin="0",
            ),
        )
    )
    candidate, assessment = _propose_and_assess(_service(ledger, gateway))
    audit_facts = ledger.list_proposal_audit_facts()
    tickets = ledger.list_approval_tickets()
    ledger.close()

    assert candidate is not None
    assert assessment.accepted is False
    assert [reason.value for reason in assessment.reason_codes] == ["exposure_limit_exceeded"]
    assert audit_facts[-1].kind == "risk_rejected"
    assert audit_facts[-1].reason_code == "exposure_limit_exceeded"
    assert tickets == ()
    assert gateway.submit_call_count == 0

    inspection = open_sqlite_connection(execution_database_path)
    try:
        assert inspection.execute("SELECT COUNT(*) FROM approval_tickets").fetchone()[0] == 0
        assert inspection.execute("SELECT COUNT(*) FROM order_commands").fetchone()[0] == 0
        assert inspection.execute("SELECT COUNT(*) FROM submission_claims").fetchone()[0] == 0
    finally:
        inspection.close()


@pytest.mark.parametrize(
    ("price", "quote", "reason"),
    (
        (
            "8080.50",
            QuoteObservation("BTCUSDT", "7999.50", "8000", NOW),
            "price_deviation_limit_exceeded",
        ),
        (
            "8000",
            QuoteObservation("BTCUSDT", "7995.50", "8000", NOW),
            "bid_ask_slippage_limit_exceeded",
        ),
    ),
)
def test_over_limit_quote_metrics_persist_rejection_without_ticket_or_outbound_side_effects(
    execution_database_path,
    price: str,
    quote: QuoteObservation,
    reason: str,
) -> None:
    """Adverse selected-target quote metrics cannot cross the ticket boundary."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    gateway = _gateway(quote=quote)
    candidate, assessment = _propose_and_assess(
        _service(ledger, gateway), price=price, quantity="0.100"
    )
    audit_facts = ledger.list_proposal_audit_facts()
    tickets = ledger.list_approval_tickets()
    ledger.close()

    assert candidate is not None
    assert assessment.accepted is False
    assert [item.value for item in assessment.reason_codes] == [reason]
    assert audit_facts[-1].kind == "risk_rejected"
    assert audit_facts[-1].reason_code == reason
    assert tickets == ()
    assert gateway.submit_call_count == 0

    inspection = open_sqlite_connection(execution_database_path)
    try:
        assert inspection.execute("SELECT COUNT(*) FROM approval_tickets").fetchone()[0] == 0
        assert inspection.execute("SELECT COUNT(*) FROM order_commands").fetchone()[0] == 0
        assert inspection.execute("SELECT COUNT(*) FROM submission_claims").fetchone()[0] == 0
    finally:
        inspection.close()


@pytest.mark.parametrize(
    ("event", "status"),
    [
        (TicketTerminalEvent.OPERATOR_REJECTED, ApprovalTicketStatus.REJECTED),
        (TicketTerminalEvent.EXPIRED, ApprovalTicketStatus.EXPIRED),
        (TicketTerminalEvent.BINDING_INVALIDATED, ApprovalTicketStatus.INVALIDATED),
    ],
)
def test_each_terminal_ticket_event_is_durable_and_distinct(
    execution_database_path, event: TicketTerminalEvent, status: ApprovalTicketStatus
) -> None:
    """D-12 retains the terminal reason, actor and binding snapshot after SQLite reopen."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    candidate, assessment = _propose_and_assess(_service(ledger, _gateway()))
    approval = ApprovalService(ledger=ledger, utc_now=lambda: NOW)
    ticket = ledger.list_approval_tickets()[0]
    if event is TicketTerminalEvent.OPERATOR_REJECTED:
        terminal = approval.reject_ticket(ticket.ticket_id, "operator_declined")
    elif event is TicketTerminalEvent.EXPIRED:
        terminal = approval.expire_ticket(ticket.ticket_id, "ticket_ttl_elapsed")
    else:
        terminal = approval.invalidate_ticket(
            ticket.ticket_id,
            "quote_changed",
            replace(ticket.binding, quote_digest="changed-quote"),
        )
    ledger.close()

    assert candidate is not None
    assert assessment.accepted is True
    assert terminal.status is status
    assert terminal.terminal_event is event

    inspection = open_sqlite_connection(execution_database_path)
    try:
        events = inspection.execute(
            "SELECT event_type, reason, actor_label FROM approval_ticket_events ORDER BY rowid"
        ).fetchall()
        assert events == [
            ("issued", "persisted_accepted_proposal", "proposal_service"),
            (
                event.value,
                "operator_declined"
                if event is TicketTerminalEvent.OPERATOR_REJECTED
                else "ticket_ttl_elapsed"
                if event is TicketTerminalEvent.EXPIRED
                else "quote_changed",
                "operator" if event is TicketTerminalEvent.OPERATOR_REJECTED else "system",
            ),
        ]
    finally:
        inspection.close()

    reopened = SQLiteExecutionLedger(execution_database_path)
    persisted = reopened.list_approval_tickets()[0]
    reopened.close()
    assert persisted.status is status
    assert persisted.terminal_event is event
