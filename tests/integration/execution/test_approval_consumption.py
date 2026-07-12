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
from pa_agent.trading.domain.approval import TicketRiskResult
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
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerStorageError,
    open_sqlite_connection,
)
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from pa_agent.trading.ports.gateway import GatewayUnavailableError
from pa_agent.trading.ports.ledger import OutboundDispatchPermit, OutboundSubmission
from tests.fixtures.execution_factories import (
    make_account_observation,
    make_analysis_recommendation,
    make_execution_target,
    make_source_analysis_snapshot,
    make_spot_command,
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

    def __init__(
        self,
        *,
        fail_refresh: bool = False,
        account_position_sequence: tuple[tuple[Position, ...], ...] | None = None,
        quote_sequence: tuple[QuoteObservation, ...] | None = None,
        balances: tuple[Balance, ...] | None = None,
        fail_submit: bool = False,
    ) -> None:
        self.fail_refresh = fail_refresh
        self._account_position_sequence = (
            list(account_position_sequence) if account_position_sequence is not None else None
        )
        self._quote_sequence = list(quote_sequence) if quote_sequence is not None else None
        self._balances = balances or (Balance("USDT", "2000", "1500", "0"),)
        self.fail_submit = fail_submit
        self.observed_at = NOW
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
        return RuleObservation(
            InstrumentRules(symbol, "0.50", "0.001", "0.001", "10"), self.observed_at
        )

    def get_account_snapshot(self, account_id: str, product: ProductType) -> object:
        self._record("account")
        positions = ()
        if self._account_position_sequence is not None:
            if not self._account_position_sequence:
                raise AssertionError("unexpected account lookup")
            positions = self._account_position_sequence.pop(0)
        return make_account_observation(
            account_id=account_id,
            product=product,
            observed_at=self.observed_at,
            balances=self._balances,
            positions=positions,
        )

    def get_quote(self, symbol: str) -> QuoteObservation:
        self._record("quote")
        if self._quote_sequence is not None:
            if not self._quote_sequence:
                raise AssertionError("unexpected quote lookup")
            return self._quote_sequence.pop(0)
        return QuoteObservation(symbol, "7999.50", "8000", self.observed_at)

    def get_server_time(self) -> TimeObservation:
        self._record("server_time")
        return TimeObservation(server_time=self.observed_at, observed_at=self.observed_at)

    def get_connection(self, target: object) -> object:
        self._record("connection")
        return TargetConnectionObservation(target, True, self.observed_at)

    def get_open_order_count(self, target: object) -> object:
        self._record("open_orders")
        return OpenOrderObservation(target, 2, self.observed_at)

    def get_order_rate_window(self, target: object, window_seconds: int) -> object:
        self._record("order_rate")
        return OrderRateObservation(
            target,
            4,
            self.observed_at - timedelta(seconds=window_seconds),
            self.observed_at,
        )

    def get_loss_drawdown(self, target: object) -> object:
        self._record("loss_drawdown")
        return LossDrawdownObservation(
            target,
            "99",
            "0.09",
            self.observed_at.replace(hour=0, minute=0, second=0, microsecond=0),
            self.observed_at,
        )

    def get_fee_rate(self, target: object, symbol: str, quote_identifier: str) -> object:
        self._record("fee_rate")
        return FeeRateObservation(
            target, symbol, quote_identifier, "USDT", "0.001", "fees-v1", self.observed_at
        )

    def submit_order(self, outbound: OutboundSubmission) -> object:
        if type(outbound) is not OutboundSubmission:
            raise AssertionError("gateway accepts only ledger-produced OutboundSubmission values")
        self.outbound_submissions.append(outbound)
        if self.fail_submit:
            raise RuntimeError("injected gateway outage")
        return object()


def _row_counts(database_path: Path) -> dict[str, int]:
    connection = open_sqlite_connection(database_path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "approval_tickets",
                "approval_ticket_events",
                "order_commands",
                "submission_claims",
                "outbound_dispatch_attempts",
            )
        }
    finally:
        connection.close()


def _issue_ticket(
    database_path: Path,
    clock: _Clock,
    gateway: _EvidenceAndSubmissionGateway,
    *,
    side: Side = Side.BUY,
    order_type: OrderType = OrderType.LIMIT,
    price: str | None = "8000",
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
            recommendation=make_analysis_recommendation(
                price=price, quantity="0.125", side=side, order_type=order_type
            )
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


def test_concurrent_current_ticket_consumption_returns_one_permit_and_one_gateway_call(
    execution_database_path: Path,
) -> None:
    """D-11 double-clicks use one immediate transaction and one outbound handoff."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    barrier = Barrier(2)

    def consume() -> OutboundDispatchPermit | None:
        service = _consumer(execution_database_path, clock, gateway)
        try:
            barrier.wait(timeout=2)
            return service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
        finally:
            service.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outbounds = list(executor.map(lambda _: consume(), range(2)))

    permit = next(result for result in outbounds if result is not None)
    assert sum(result is not None for result in outbounds) == 1
    outbound_ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    try:
        SubmissionCoordinator(ledger=outbound_ledger, gateway=gateway).submit(permit)
    finally:
        outbound_ledger.close()
    assert _row_counts(execution_database_path) == {
        "approval_tickets": 1,
        "approval_ticket_events": 2,
        "order_commands": 1,
        "submission_claims": 1,
        "outbound_dispatch_attempts": 1,
    }
    assert len(gateway.outbound_submissions) == 1
    assert gateway.outbound_submissions[0].client_order_id == permit.client_order_id


@pytest.mark.parametrize("side", (Side.BUY, Side.SELL))
def test_market_ticket_consumes_once_with_fresh_side_specific_evidence(
    execution_database_path: Path, side: Side
) -> None:
    """MARKET candidates cross issuance and one fresh consumption boundary without a limit price."""
    clock = _Clock(NOW)
    balances = (Balance("USDT", "2000", "1500", "0"),)
    if side is Side.SELL:
        balances += (Balance("BTC", "1", "1", "0"),)
    gateway = _EvidenceAndSubmissionGateway(balances=balances)
    ticket, candidate, policy = _issue_ticket(
        execution_database_path,
        clock,
        gateway,
        side=side,
        order_type=OrderType.MARKET,
        price=None,
    )
    service = _consumer(execution_database_path, clock, gateway)
    try:
        permit = service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
        assert service._ledger.list_approval_tickets()[0].status.value == "consumed"
        SubmissionCoordinator(ledger=service._ledger, gateway=gateway).submit(permit)
    finally:
        service.close()

    assert candidate.price is None
    assert type(permit) is OutboundDispatchPermit
    assert len(gateway.outbound_submissions) == 1


def test_t0_to_t0_plus_one_equivalent_fresh_evidence_consumes_once(
    execution_database_path: Path,
) -> None:
    """Only a complete, unchanged one-second refresh may consume one ticket."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    issued_evidence_digest = ticket.binding.evidence_digest

    clock.now = NOW + timedelta(seconds=1)
    gateway.observed_at = clock.now
    service = _consumer(execution_database_path, clock, gateway)
    try:
        permit = service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
        assert type(permit) is OutboundDispatchPermit
        SubmissionCoordinator(ledger=service._ledger, gateway=gateway).submit(permit)
        assert service._ledger.list_approval_tickets()[0].status.value == "consumed"
    finally:
        service.close()

    connection = open_sqlite_connection(execution_database_path)
    try:
        evidence_rows = connection.execute(
            "SELECT evidence_digest FROM proposal_evidence ORDER BY rowid"
        ).fetchall()
        assessment_rows = connection.execute(
            "SELECT assessment_id FROM proposal_risk_assessments ORDER BY rowid"
        ).fetchall()
        event_rows = connection.execute(
            "SELECT event_type FROM approval_ticket_events WHERE ticket_id = ? ORDER BY rowid",
            (ticket.ticket_id,),
        ).fetchall()
    finally:
        connection.close()

    assert len(gateway.outbound_submissions) == 1
    assert _row_counts(execution_database_path) == {
        "approval_tickets": 1,
        "approval_ticket_events": 2,
        "order_commands": 1,
        "submission_claims": 1,
        "outbound_dispatch_attempts": 1,
    }
    assert len(evidence_rows) == 2
    assert evidence_rows[0][0] == issued_evidence_digest
    assert evidence_rows[0][0] != evidence_rows[1][0]
    assert len(assessment_rows) == 2
    assert event_rows == [("issued",), ("consumed",)]


@pytest.mark.parametrize(
    ("mutation", "current"),
    (
        ("candidate", lambda binding: replace(binding, candidate_digest="changed-candidate")),
        ("source", lambda binding: replace(binding, source_digest="changed-source")),
        ("target", lambda binding: replace(binding, target_digest="changed-target")),
        ("policy", lambda binding: replace(binding, policy_digest="changed-policy")),
        ("capabilities", lambda binding: replace(binding, authorization_evidence_digest="changed-capabilities")),
        ("rules", lambda binding: replace(binding, authorization_evidence_digest="changed-rules")),
        ("account", lambda binding: replace(binding, authorization_evidence_digest="changed-account")),
        ("quote", lambda binding: replace(binding, quote_digest="changed-quote")),
        ("fee", lambda binding: replace(binding, fee_rate_digest="changed-fee")),
        ("open-order", lambda binding: replace(binding, authorization_evidence_digest="changed-open-orders")),
        ("rate", lambda binding: replace(binding, authorization_evidence_digest="changed-order-rate")),
        ("loss-drawdown", lambda binding: replace(binding, authorization_evidence_digest="changed-loss")),
        ("quantity", lambda binding: replace(binding, amount=binding.amount + 1)),
        ("expected-price", lambda binding: replace(binding, expected_price=binding.expected_price + 1)),
        ("fee-amount", lambda binding: replace(binding, estimated_fee=binding.estimated_fee + 1)),
        ("slippage", lambda binding: replace(binding, slippage=binding.slippage + 1)),
        (
            "risk-result",
            lambda binding: replace(
                binding,
                risk_result=TicketRiskResult(
                    accepted=False,
                    reason_codes=("changed-risk",),
                    metrics=binding.risk_result.metrics,
                ),
            ),
        ),
        ("stale", lambda binding: replace(binding, data_observed_at=NOW - timedelta(seconds=61))),
    ),
)
def test_authorization_equivalence_rejects_every_d10_binding_mutation(
    execution_database_path: Path,
    mutation: str,
    current: object,
) -> None:
    """D-10 remains exact for every authorization fact other than fresh timestamps."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, _, policy = _issue_ticket(execution_database_path, clock, gateway)
    changed_binding = current(ticket.binding)

    assert ticket.binding.is_authorization_equivalent_to(
        changed_binding, policy=policy, now=NOW + timedelta(seconds=1)
    ) is False, mutation


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
        "outbound_dispatch_attempts": 0,
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


def test_refreshed_over_limit_exposure_invalidates_ticket_before_outbound_authority(
    execution_database_path: Path,
) -> None:
    """A current ticket cannot authorize work after fresh exposure becomes excessive."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway(
        account_position_sequence=(
            (),
            (
                Position(
                    symbol="BTCUSDT",
                    quantity="0.001",
                    entry_price="8000",
                    mark_price="8000",
                    unrealized_pnl="0",
                    margin="0",
                ),
            ),
        )
    )
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    service = _consumer(execution_database_path, clock, gateway)
    try:
        result = service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
    finally:
        service.close()

    assert result is None
    assert _row_counts(execution_database_path) == {
        "approval_tickets": 1,
        "approval_ticket_events": 2,
        "order_commands": 0,
        "submission_claims": 0,
        "outbound_dispatch_attempts": 0,
    }
    assert gateway.outbound_submissions == []
    connection = open_sqlite_connection(execution_database_path)
    try:
        event_type, reason = connection.execute(
            "SELECT event_type, reason FROM approval_ticket_events "
            "WHERE ticket_id = ? ORDER BY rowid DESC",
            (ticket.ticket_id,),
        ).fetchone()
        assert (event_type, reason) == ("binding_invalidated", "risk_reassessment_rejected")
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("quotes", "reason"),
    (
        (
            (
                QuoteObservation("BTCUSDT", "7999.50", "8000", NOW),
                QuoteObservation("BTCUSDT", "7919", "7919.50", NOW),
            ),
            "price_deviation_limit_exceeded",
        ),
        (
            (
                QuoteObservation("BTCUSDT", "7999.50", "8000", NOW),
                QuoteObservation("BTCUSDT", "7995.50", "8000", NOW),
            ),
            "bid_ask_slippage_limit_exceeded",
        ),
    ),
)
def test_refreshed_over_limit_quote_metrics_invalidate_ticket_before_outbound_authority(
    execution_database_path: Path,
    quotes: tuple[QuoteObservation, QuoteObservation],
    reason: str,
) -> None:
    """Fresh adverse quote facts invalidate prior approval before SQLite outbound authority."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway(quote_sequence=quotes)
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    service = _consumer(execution_database_path, clock, gateway)
    try:
        result = service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
    finally:
        service.close()

    assert result is None
    assert _row_counts(execution_database_path) == {
        "approval_tickets": 1,
        "approval_ticket_events": 2,
        "order_commands": 0,
        "submission_claims": 0,
        "outbound_dispatch_attempts": 0,
    }
    assert gateway.outbound_submissions == []
    connection = open_sqlite_connection(execution_database_path)
    try:
        event_type, event_reason = connection.execute(
            "SELECT event_type, reason FROM approval_ticket_events "
            "WHERE ticket_id = ? ORDER BY rowid DESC",
            (ticket.ticket_id,),
        ).fetchone()
        assert (event_type, event_reason) == ("binding_invalidated", "risk_reassessment_rejected")
        assert reason in {
            "price_deviation_limit_exceeded",
            "bid_ask_slippage_limit_exceeded",
        }
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
        "outbound_dispatch_attempts": 0,
    }
    assert gateway.outbound_submissions == []


def test_legacy_outbound_submission_is_rejected_before_lease_or_gateway_mutation(
    execution_database_path: Path,
) -> None:
    """A field-consistent public legacy value cannot bypass durable proof leasing."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    command = make_spot_command(
        command_id="legacy-command",
        client_order_id="legacy-client",
        logical_command_key="legacy-logical-command",
    )
    legacy = OutboundSubmission(
        command=command,
        command_id=command.command_id,
        client_order_id=command.client_order_id,
        reconciliation_job_id="legacy-job",
        outbound_attempt_token="legacy-attempt",
    )
    before = _row_counts(execution_database_path)
    try:
        with pytest.raises((TypeError, LedgerStorageError)):
            SubmissionCoordinator(ledger=ledger, gateway=gateway).submit(legacy)
    finally:
        ledger.close()

    assert gateway.outbound_submissions == []
    assert _row_counts(execution_database_path) == before


def test_legacy_admission_and_begin_entries_are_unavailable_without_authority_side_effects(
    execution_database_path: Path,
) -> None:
    """Raw commands and admissions have no public route to gateway-facing authority."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ledger = SQLiteExecutionLedger(execution_database_path, clock=clock)
    before = _row_counts(execution_database_path)
    try:
        for entry_name in (
            "create_or_load_and_claim_submission",
            "begin_outbound_submission",
        ):
            with pytest.raises(AttributeError):
                getattr(ledger, entry_name)
    finally:
        ledger.close()

    assert gateway.outbound_submissions == []
    assert _row_counts(execution_database_path) == before


def test_only_persisted_current_permit_can_dispatch_once(
    execution_database_path: Path,
) -> None:
    """A real consumed permit leases exactly once; forged identities and proof do not."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    service = _consumer(execution_database_path, clock, gateway)
    try:
        permit = service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
        assert type(permit) is OutboundDispatchPermit
        coordinator = SubmissionCoordinator(ledger=service._ledger, gateway=gateway)
        before = _row_counts(execution_database_path)
        forged_permits = (
            replace(permit, outbound_attempt_proof="forged-proof"),
            replace(permit, command_id="forged-command"),
            replace(permit, client_order_id="forged-client"),
            replace(permit, reconciliation_job_id="forged-job"),
        )
        for forged in forged_permits:
            with pytest.raises(LedgerStorageError):
                coordinator.submit(forged)
            assert gateway.outbound_submissions == []
            assert _row_counts(execution_database_path) == before

        coordinator.submit(permit)
        assert len(gateway.outbound_submissions) == 1
        with pytest.raises(LedgerStorageError):
            coordinator.submit(permit)
        assert len(gateway.outbound_submissions) == 1
    finally:
        service.close()


def test_expired_and_restart_reloaded_permits_cannot_dispatch(
    execution_database_path: Path,
) -> None:
    """Expiry and a reopened leased proof remain fail-closed with zero gateway calls."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway()
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    service = _consumer(execution_database_path, clock, gateway)
    try:
        permit = service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
        assert type(permit) is OutboundDispatchPermit
        clock.now = NOW + timedelta(seconds=61)
        with pytest.raises(LedgerStorageError):
            SubmissionCoordinator(ledger=service._ledger, gateway=gateway).submit(permit)
        assert gateway.outbound_submissions == []
    finally:
        service.close()

    restart_database_path = execution_database_path.with_name("restart.sqlite3")
    fresh_clock = _Clock(NOW)
    fresh_gateway = _EvidenceAndSubmissionGateway()
    fresh_ticket, fresh_candidate, fresh_policy = _issue_ticket(
        restart_database_path, fresh_clock, fresh_gateway
    )
    fresh_service = _consumer(restart_database_path, fresh_clock, fresh_gateway)
    try:
        fresh_permit = fresh_service.consume_ticket(
            fresh_ticket.ticket_id, fresh_candidate, fresh_candidate.target, fresh_policy
        )
        assert type(fresh_permit) is OutboundDispatchPermit
        SubmissionCoordinator(ledger=fresh_service._ledger, gateway=fresh_gateway).submit(fresh_permit)
    finally:
        fresh_service.close()

    reopened_gateway = _EvidenceAndSubmissionGateway()
    reopened_ledger = SQLiteExecutionLedger(restart_database_path, clock=fresh_clock)
    try:
        with pytest.raises(LedgerStorageError):
            SubmissionCoordinator(ledger=reopened_ledger, gateway=reopened_gateway).submit(fresh_permit)
    finally:
        reopened_ledger.close()

    assert reopened_gateway.outbound_submissions == []


def test_post_lease_gateway_failure_records_ambiguity_without_replacement_dispatch(
    execution_database_path: Path,
) -> None:
    """A gateway exception follows a lease and leaves only reconciliation recovery."""
    clock = _Clock(NOW)
    gateway = _EvidenceAndSubmissionGateway(fail_submit=True)
    ticket, candidate, policy = _issue_ticket(execution_database_path, clock, gateway)
    service = _consumer(execution_database_path, clock, gateway)
    try:
        permit = service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
        assert type(permit) is OutboundDispatchPermit
        coordinator = SubmissionCoordinator(ledger=service._ledger, gateway=gateway)
        with pytest.raises(RuntimeError, match="injected gateway outage"):
            coordinator.submit(permit)
        with pytest.raises(LedgerStorageError):
            coordinator.submit(permit)
        assert len(gateway.outbound_submissions) == 1
        assert service._ledger.list_unresolved_reconciliation_jobs()[0].lifecycle_state.value == "submission_unknown"
    finally:
        service.close()
