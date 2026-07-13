"""Filesystem regression for leased, restartable Paper Spot gateway truth."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.trading.application.approval import ApprovalService
from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.application.submission import SubmissionCoordinator
from pa_agent.trading.domain.approval import CandidateExecutionIntent, ExecutionTarget
from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    GatewayCapabilities,
    InstrumentRules,
    Mode,
    OrderState,
    OrderType,
    ProductType,
    QuoteObservation,
    RuleObservation,
    Side,
    SpotOrderContext,
    TimeObservation,
)
from pa_agent.trading.domain.risk import (
    EvidenceBundle,
    FeeRateObservation,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    select_paper_product_policy,
)
from pa_agent.trading.gateways.paper.gateway import PaperGateway
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from pa_agent.trading.ports.gateway import (
    GatewayOperationObserver,
    GatewayOperationReference,
    GatewayOperationResult,
    GatewayUnavailableError,
)
from tests.fixtures.paper_scenarios import make_observation, make_policy

NOW = datetime(2026, 7, 13, tzinfo=UTC)


class _Clock:
    def utc_now(self) -> datetime:
        return NOW


class _RecordingOperationObserver(GatewayOperationObserver):
    def __init__(self, *, fail: bool = False) -> None:
        self.results: list[GatewayOperationResult] = []
        self._fail = fail

    def observe_operation(self, result: GatewayOperationResult) -> None:
        self.results.append(result)
        if self._fail:
            raise RuntimeError("injected paper observer failure")


def _target() -> ExecutionTarget:
    return ExecutionTarget("paper-spot-primary", Mode.PAPER, "paper-account", ProductType.SPOT)


def _candidate() -> CandidateExecutionIntent:
    return CandidateExecutionIntent(
        source_id="paper-analysis",
        source_completed_at=NOW,
        source_schema_version="analysis-v1",
        source_parser_version="parser-v1",
        source_decision_digest="paper-decision",
        target=_target(),
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        price=Decimal("110"),
        risk_basis=Decimal("0.01"),
        context=SpotOrderContext(),
    )


def _evidence(target: ExecutionTarget) -> EvidenceBundle:
    return EvidenceBundle(
        capabilities=GatewayCapabilities(frozenset(ProductType), True, True, True),
        instrument_rules=InstrumentRules("BTCUSDT", "0.01", "0.001", "0.001", "10"),
        rule_observed_at=NOW,
        account=AccountObservation(target.account_id, target.product, NOW, (Balance("USDT", "1000", "1000", "0"),), ()),
        quote=QuoteObservation("BTCUSDT", "99", "100", NOW),
        server_time=TimeObservation(NOW, NOW),
        connection=TargetConnectionObservation(target, True, NOW),
        open_orders=OpenOrderObservation(target, 0, NOW),
        order_rate=OrderRateObservation(target, 0, NOW - timedelta(seconds=60), NOW),
        loss_drawdown=LossDrawdownObservation(target, "0", "0", NOW.replace(hour=0), NOW),
        fee_rate=FeeRateObservation(target, "BTCUSDT", "BTCUSDT", "USDT", "0.001", "fee-v1", NOW),
    )


def _leased_permit(path: Path):
    candidate = _candidate()
    policy = select_paper_product_policy(candidate.target, candidate.context)
    evidence = _evidence(candidate.target)
    assessment = RiskEngine().assess(candidate, candidate.target, policy, evidence)
    assert assessment.accepted
    ledger = SQLiteExecutionLedger(path, clock=_Clock())
    ledger.record_candidate(candidate)
    ledger.record_evidence(candidate, evidence)
    ledger.record_risk_assessment(candidate, assessment)
    ticket = ApprovalService(ledger=ledger, utc_now=lambda: NOW).create_pending_ticket(candidate, assessment)
    permit = ledger.consume_valid_ticket_and_begin_outbound(ticket.ticket_id, candidate, policy, evidence, assessment)
    assert permit is not None
    return ledger, permit


def _shallow_observation(**overrides: object):
    values = {"asks": (make_observation().asks[0],)}
    values.update(overrides)
    return make_observation(**values)


def test_leased_spot_submission_partial_fill_cancel_and_reopen_are_paper_owned(tmp_path: Path) -> None:
    """Only a real lease can reserve; observation events settle and reopen durable paper truth."""
    ledger, permit = _leased_permit(tmp_path / "ledger.sqlite")
    paper_path = tmp_path / "paper.sqlite"
    store = PaperStore(paper_path)
    gateway = PaperGateway(
        store,
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
        leased_submission_verifier=ledger,
    )
    gateway.advance_market(_shallow_observation())
    evidence = SubmissionCoordinator(ledger=ledger, gateway=gateway).submit(permit)
    assert evidence.evidence is not None
    assert evidence.evidence.state is OrderState.PARTIALLY_FILLED
    assert evidence.evidence.filled_quantity == Decimal("1")
    client_order_id = permit.client_order_id
    command_id = permit.command_id
    assert gateway.get_account_snapshot("paper-account", ProductType.SPOT).balances == (
        Balance("BTC", "1", "1", "0"),
        Balance("USDT", "899.799900", "789.579790", "110.220110"),
    )
    assert gateway.list_open_orders("paper-account", ProductType.SPOT)[0].filled_quantity == Decimal("1")

    request = gateway.cancel_order(client_order_id)
    assert request.evidence is not None
    assert request.evidence.state is OrderState.CANCEL_REQUESTED
    terminal = gateway.resolve_cancellation(client_order_id)
    assert terminal.evidence is not None
    assert terminal.evidence.state is OrderState.CANCELLED
    assert gateway.get_account_snapshot("paper-account", ProductType.SPOT).balances[-1] == Balance("USDT", "899.799900", "899.799900", "0")
    before_close = (
        gateway.lookup_order_by_client_id(client_order_id),
        gateway.list_fills(command_id),
        gateway.list_open_orders("paper-account", ProductType.SPOT),
        gateway.get_account_snapshot("paper-account", ProductType.SPOT),
    )
    ledger.close()
    store.close()

    reopened_store = PaperStore(paper_path)
    reopened = PaperGateway(reopened_store, policy=make_policy())
    assert reopened.lookup_order_by_client_id(client_order_id) == before_close[0]
    assert reopened.list_fills(command_id) == before_close[1]
    assert reopened.list_open_orders("paper-account", ProductType.SPOT) == before_close[2]
    assert reopened.get_account_snapshot("paper-account", ProductType.SPOT) == before_close[3]
    reopened_store.close()


def test_later_observation_can_fill_only_the_residual_order_quantity(tmp_path: Path) -> None:
    """A higher observation version advances the persisted remainder without re-filling prior depth."""
    ledger, permit = _leased_permit(tmp_path / "ledger.sqlite")
    store = PaperStore(tmp_path / "paper.sqlite")
    gateway = PaperGateway(
        store, policy=make_policy(), initial_balances={"USDT": "1000", "BTC": "0"}, leased_submission_verifier=ledger
    )
    gateway.advance_market(_shallow_observation())
    SubmissionCoordinator(ledger=ledger, gateway=gateway).submit(permit)

    change = gateway.advance_market(
        _shallow_observation(
            observation_id="btc-book-002",
            version=2,
            asks=(make_observation().asks[1],),
        )
    )
    assert change[0].evidence is not None
    assert change[0].evidence.state is OrderState.FILLED
    assert [fill.quantity for fill in gateway.list_fills(permit.command_id)] == [Decimal("1"), Decimal("1")]
    snapshot = gateway.get_account_snapshot("paper-account", ProductType.SPOT)
    assert snapshot.balances[-1] == Balance("USDT", "798.597799", "798.597799", "0")
    ledger.close()
    store.close()


def test_later_observation_wins_over_prior_cancellation_request_without_releasing_settled_fill(tmp_path: Path) -> None:
    """Terminal outcome follows persisted paper-event order, not cancellation intent timing."""
    ledger, permit = _leased_permit(tmp_path / "ledger.sqlite")
    store = PaperStore(tmp_path / "paper.sqlite")
    gateway = PaperGateway(
        store, policy=make_policy(), initial_balances={"USDT": "1000", "BTC": "0"}, leased_submission_verifier=ledger
    )
    gateway.advance_market(_shallow_observation())
    SubmissionCoordinator(ledger=ledger, gateway=gateway).submit(permit)

    request = gateway.cancel_order(permit.client_order_id)
    assert request.evidence is not None
    assert request.evidence.state is OrderState.CANCEL_REQUESTED
    fill_change = gateway.advance_market(
        _shallow_observation(
            observation_id="btc-book-003",
            version=2,
            asks=(make_observation().asks[1],),
        )
    )
    assert fill_change[0].evidence is not None
    assert fill_change[0].evidence.state is OrderState.FILLED
    terminal = gateway.resolve_cancellation(permit.client_order_id)
    assert terminal.evidence is not None
    assert terminal.evidence.state is OrderState.FILLED
    assert gateway.get_account_snapshot("paper-account", ProductType.SPOT).balances[-1] == Balance(
        "USDT", "798.597799", "798.597799", "0"
    )
    assert [event.sequence for event in store.list_events()][-3:] == [3, 4, 5]
    ledger.close()
    store.close()


def test_paper_direct_controls_observe_each_committed_result_once(tmp_path: Path) -> None:
    """Paper controls notify only after truth commits and never resubmit a leased order."""
    ledger, permit = _leased_permit(tmp_path / "ledger.sqlite")
    store = PaperStore(tmp_path / "paper.sqlite")
    observer = _RecordingOperationObserver()
    gateway = PaperGateway(
        store,
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
        operation_observer=observer,
        leased_submission_verifier=ledger,
    )
    try:
        gateway.advance_market(_shallow_observation())
        submitted = SubmissionCoordinator(ledger=ledger, gateway=gateway).submit(permit)
        assert submitted.evidence is not None
        assert observer.results == []
        changes = gateway.advance_market(
            _shallow_observation(
                observation_id="btc-book-004",
                version=2,
                asks=(make_observation().asks[1],),
            )
        )
        assert tuple(result.reference for result in observer.results) == tuple(
            result.reference for result in changes
        )
        batch = gateway.read_operation(changes[0].reference)
        assert batch.evidence == changes[0].evidence
        assert batch.fills == gateway.list_fills(permit.command_id)
        historical_batch = gateway.read_operation(submitted.reference)
        assert historical_batch.reference == submitted.reference
        with pytest.raises(GatewayUnavailableError):
            gateway.read_operation(
                GatewayOperationReference(
                    operation_id=f"paper:999:{permit.client_order_id}",
                    client_order_id=permit.client_order_id,
                )
            )
        assert gateway._submission_invocations == 1
    finally:
        ledger.close()
        store.close()


def test_terminal_paper_cancellation_observes_committed_result_once(tmp_path: Path) -> None:
    """A nonterminal request stays silent until Paper commits terminal cancellation truth."""
    ledger, permit = _leased_permit(tmp_path / "ledger.sqlite")
    store = PaperStore(tmp_path / "paper.sqlite")
    observer = _RecordingOperationObserver()
    gateway = PaperGateway(
        store,
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
        operation_observer=observer,
        leased_submission_verifier=ledger,
    )
    try:
        gateway.advance_market(_shallow_observation())
        SubmissionCoordinator(ledger=ledger, gateway=gateway).submit(permit)
        gateway.cancel_order(permit.client_order_id)
        assert observer.results == []
        terminal = gateway.resolve_cancellation(permit.client_order_id)
        assert observer.results == [terminal]
        assert terminal.evidence is not None
        assert terminal.evidence.state is OrderState.CANCELLED
        assert gateway._submission_invocations == 1
    finally:
        ledger.close()
        store.close()


def test_paper_observer_failure_keeps_committed_terminal_truth(tmp_path: Path) -> None:
    """A failed post-commit direct observer cannot re-enter the protected submission path."""
    ledger, permit = _leased_permit(tmp_path / "ledger.sqlite")
    store = PaperStore(tmp_path / "paper.sqlite")
    gateway = PaperGateway(
        store,
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
        operation_observer=_RecordingOperationObserver(fail=True),
        leased_submission_verifier=ledger,
    )
    try:
        gateway.advance_market(_shallow_observation())
        SubmissionCoordinator(ledger=ledger, gateway=gateway).submit(permit)
        gateway.cancel_order(permit.client_order_id)
        with pytest.raises(RuntimeError, match="injected paper observer failure"):
            gateway.resolve_cancellation(permit.client_order_id)
        resolved = gateway.lookup_order_by_client_id(permit.client_order_id)
        assert resolved is not None and resolved.evidence is not None
        assert resolved.evidence.state is OrderState.CANCELLED
        assert gateway._submission_invocations == 1
    finally:
        ledger.close()
        store.close()
