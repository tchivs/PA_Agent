"""Real-SQLite coverage for single-use, re-evidenced approval consumption."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.evidence_collector import FreshEvidenceCollector
from pa_agent.trading.application.intent_factory import IntentFactory
from pa_agent.trading.application.proposal import ProposalService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.application.submission import SubmissionCoordinator
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
from pa_agent.trading.persistence.sqlite_connection import LedgerStorageError, open_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from pa_agent.trading.ports.gateway import GatewayUnavailableError
from pa_agent.trading.ports.ledger import OutboundSubmission
from tests.fixtures.execution_factories import (
    make_account_observation,
    make_analysis_recommendation,
    make_execution_target,
    make_source_analysis_snapshot,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def utc_now(self) -> datetime:
        return self.now


class _EvidenceAndSubmissionGateway:
    """Offline fresh-evidence fake that records the only permitted outbound shape."""

    def __init__(self, *, fail_refresh: bool = False) -> None:
        self.fail_refresh = fail_refresh
        self.call_order: list[str] = []
        self.outbound_submissions: list[OutboundSubmission] = []

    def _record(self, name: str) -> None:
        self.call_order.append(name)
        if self.fail_refresh and name == "capabilities":
            raise GatewayUnavailableError("offline refresh failure")

    def get_capabilities(self) -> GatewayCapabilities:
        self._record("capabilities")
        return GatewayCapabilities(frozenset({ProductType.SPOT}), True)

    def get_instrument_rules(self, symbol: str) -> RuleObservation:
        self._record("rules")
        return RuleObservation(InstrumentRules(symbol, "0.50", "0.001", "0.001", "10"), NOW)

    def get_account_snapshot(self, account_id: str, product: ProductType) -> object:
        self._record("account")
        return make_account_observation(
            account_id=account_id,
            product=product,
            observed_at=NOW,
            balances=(Balance("USDT", "2000", "1500", "0"),),
            positions=(),
        )

    def get_quote(self, symbol: str) -> QuoteObservation:
        self._record("quote")
        return QuoteObservation(symbol, "7999.50", "8000", NOW)

    def get_server_time(self) -> TimeObservation:
        self._record("server_time")
        return TimeObservation(server_time=NOW, observed_at=NOW)

    def get_connection(self, target: object) -> object:
        self._record("connection")
        return TargetConnectionObservation(target, True, NOW)

    def get_open_order_count(self, target: object) -> object:
        self._record("open_orders")
        return OpenOrderObservation(target, 2, NOW)

    def get_order_rate_window(self, target: object, window_seconds: int) -> object:
        self._record("order_rate")
        return OrderRateObservation(target, 4, NOW - timedelta(seconds=window_seconds), NOW)

    def get_loss_drawdown(self, target: object) -> object:
        self._record("loss_drawdown")
        return LossDrawdownObservation(target, "99", "0.09", NOW.replace(hour=0), NOW)

    def get_fee_rate(self, target: object, symbol: str, quote_identifier: str) -> object:
        self._record("fee_rate")
        return FeeRateObservation(target, symbol, quote_identifier, "USDT", "0.001", "fees-v1", NOW)

    def submit_order(self, outbound: OutboundSubmission) -> object:
        if type(outbound) is not OutboundSubmission:
            raise AssertionError("gateway accepts only ledger-produced OutboundSubmission values")
        self.outbound_submissions.append(outbound)
        return object()


def _row_counts(database_path: Path) -> dict[str, int]:
    connection = open_sqlite_connection(database_path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("approval_tickets", "approval_ticket_events", "order_commands", "submission_claims")
        }
    finally:
        connection.close()


def _issue_ticket(
    database_path: Path, clock: _Clock, gateway: _EvidenceAndSubmissionGateway
) -> tuple[object, object, object]:
    ledger = SQLiteExecutionLedger(database_path, clock=clock)
    target = make_execution_target()
    policy = select_phase2_policy(target)
    approval = ApprovalService(ledger=ledger, utc_now=clock.utc_now)
    proposal = ProposalService(
        ledger=ledger,
        intent_factory=IntentFactory(),
        evidence_collector=FreshEvidenceCollector(gateway=gateway, utc_now=clock.utc_now),
        risk_engine=RiskEngine(),
        approval_service=approval,
    )
    candidate = proposal.propose(
        make_source_analysis_snapshot(
            recommendation=make_analysis_recommendation(price="8000", quantity="0.125")
        ),
        target,
    )
    assessment = proposal.assess(candidate, target, policy)
    assert candidate is not None
    assert assessment.accepted is True
    ticket = ledger.list_approval_tickets()[0]
    ledger.close()
    return ticket, candidate, policy


def _consumer(
    database_path: Path, clock: _Clock, gateway: _EvidenceAndSubmissionGateway
) -> ApprovalService:
    return ApprovalService(
        ledger=SQLiteExecutionLedger(database_path, clock=clock),
        utc_now=clock.utc_now,
        evidence_collector=FreshEvidenceCollector(gateway=gateway, utc_now=clock.utc_now),
        risk_engine=RiskEngine(),
    )


def test_concurrent_current_ticket_consumption_returns_one_outbound_and_one_gateway_call(
    execution_database_path: Path,
) -> None:
    """D-11 double-clicks use one immediate transaction and one outbound handoff."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    barrier = Barrier(2)

    def consume() -> OutboundSubmission | None:
        service = _consumer(execution_database_path, clock, gateway)
        try:
            barrier.wait(timeout=2)
            return service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
        finally:
            service.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outbounds = list(executor.map(lambda _: consume(), range(2)))

    outbound = next(result for result in outbounds if result is not None)
    assert sum(result is not None for result in outbounds) == 1
    SubmissionCoordinator(gateway=gateway).submit(outbound)
    assert _row_counts(execution_database_path) == {
        "approval_tickets": 1,
        "approval_ticket_events": 2,
        "order_commands": 1,
        "submission_claims": 1,
    }
    assert len(gateway.outbound_submissions) == 1
    assert gateway.outbound_submissions[0].client_order_id == outbound.client_order_id


@pytest.mark.parametrize("mode", ["expired", "binding_changed", "refresh_failed"])
def test_noncurrent_ticket_attempts_terminate_without_claim_or_gateway_submission(
    execution_database_path: Path, mode: str
) -> None:
    """D-05/D-06/D-10 failures persist a terminal audit event before authority exists."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    if mode == "expired":
        clock.now = NOW + timedelta(seconds=61)
    if mode == "refresh_failed":
        gateway.fail_refresh = True
    current_candidate = replace(candidate, quantity=candidate.quantity + 1) if mode == "binding_changed" else candidate
    service = _consumer(execution_database_path, clock, gateway)
    try:
        result = service.consume_ticket(ticket.ticket_id, current_candidate, current_candidate.target, policy)
    finally:
        service.close()

    assert result is None
    assert _row_counts(execution_database_path) == {
        "approval_tickets": 1,
        "approval_ticket_events": 2,
        "order_commands": 0,
        "submission_claims": 0,
    }
    assert gateway.outbound_submissions == []
    connection = open_sqlite_connection(execution_database_path)
    try:
        event_type = connection.execute(
            "SELECT event_type FROM approval_ticket_events WHERE ticket_id = ? ORDER BY rowid DESC",
            (ticket.ticket_id,),
        ).fetchone()[0]
        assert event_type == ("expired" if mode == "expired" else "binding_invalidated")
    finally:
        connection.close()


def test_injected_consumption_failure_rolls_back_ticket_command_and_outbound_start(
    execution_database_path: Path,
) -> None:
    """A failure in the immediate transaction leaves the ticket pending and replay-safe."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)

    def fail(stage: str) -> None:
        if stage == "before_ticket_consumption":
            raise LedgerStorageError("injected consumption failure")

    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock, failure_injector=fail)
    service = ApprovalService(
        ledger=ledger,
        utc_now=clock.utc_now,
        evidence_collector=FreshEvidenceCollector(gateway=gateway, utc_now=clock.utc_now),
        risk_engine=RiskEngine(),
    )
    with pytest.raises(LedgerStorageError, match="injected consumption failure"):
        service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
    ledger.close()

    assert _row_counts(execution_database_path) == {
        "approval_tickets": 1,
        "approval_ticket_events": 1,
        "order_commands": 0,
        "submission_claims": 0,
    }
    assert gateway.outbound_submissions == []
