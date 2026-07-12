"""Approval-ticket domain contracts without submission authority."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pa_agent.trading.domain.approval import (
    ApprovalTicket,
    ApprovalTicketStatus,
    TicketBinding,
    TicketTerminalEvent,
    build_ticket_review,
)
from pa_agent.trading.domain.risk import FeeEstimate, select_phase2_policy
from tests.fixtures.execution_factories import (
    make_candidate_execution_intent,
    make_execution_target,
)

NOW = datetime(2026, 7, 12, 11, 0, tzinfo=UTC)


def _binding() -> TicketBinding:
    candidate = make_candidate_execution_intent(price="8000", quantity="0.125")
    target = make_execution_target()
    policy = select_phase2_policy(target)
    fee = FeeEstimate(
        target=target,
        symbol="BTCUSDT",
        quote_identifier="BTCUSDT",
        expected_quote_price=Decimal("8000"),
        fee_currency="USDT",
        rate=Decimal("0.001"),
        rate_version="fees-v1",
        amount=Decimal("1.000"),
    )
    return TicketBinding.from_persisted_facts(
        candidate=candidate,
        policy=policy,
        evidence_digest="evidence-digest",
        quote_observed_at=NOW,
        fee_estimate=fee,
        risk_reason_codes=(),
        risk_metrics=(("slippage", Decimal("0.50")),),
    )


def test_pending_ticket_has_fixed_phase2_policy_ttl_and_complete_review() -> None:
    """A reviewable pending ticket freezes all D-09 facts for precisely sixty seconds."""
    binding = _binding()
    ticket = ApprovalTicket.create(ticket_id="ticket-001", binding=binding, created_at=NOW)

    assert ticket.status is ApprovalTicketStatus.PENDING
    assert ticket.policy_version == "phase2-v1"
    assert ticket.expires_at == NOW + timedelta(seconds=60)
    assert ticket.review == build_ticket_review(binding)
    assert ticket.review.venue == "paper-spot-primary"
    assert ticket.review.environment == "paper"
    assert ticket.review.account_id == "paper-account"
    assert ticket.review.product == "spot"
    assert ticket.review.symbol == "BTCUSDT"
    assert ticket.review.amount == Decimal("0.125")
    assert ticket.review.expected_price == Decimal("8000")
    assert ticket.review.estimated_fee == Decimal("1.000")
    assert ticket.review.fee_currency == "USDT"
    assert ticket.review.fee_rate_version == "fees-v1"
    assert ticket.review.quote_identifier == "BTCUSDT"
    assert ticket.review.leverage_context == "none"
    assert ticket.review.borrow_context == "none"
    assert ticket.review.position_context == "spot"
    assert ticket.review.source_provenance["source_id"] == "analysis-001"
    assert ticket.review.risk_result.accepted is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda binding: replace(binding, source_digest="changed-source"),
        lambda binding: replace(binding, command_digest="changed-command"),
        lambda binding: replace(binding, target_digest="changed-target"),
        lambda binding: replace(binding, policy_digest="changed-policy"),
        lambda binding: replace(binding, evidence_digest="changed-evidence"),
        lambda binding: replace(binding, quote_digest="changed-quote"),
        lambda binding: replace(binding, fee_rate_digest="changed-fee-rate"),
        lambda binding: replace(binding, data_age_digest="changed-data-age"),
    ],
)
def test_every_persisted_binding_mutation_requires_ticket_invalidation(mutation) -> None:
    """D-10 treats every immutable proposal binding as invalidation-relevant."""
    binding = _binding()
    ticket = ApprovalTicket.create(ticket_id="ticket-001", binding=binding, created_at=NOW)

    assert ticket.requires_invalidation(mutation(binding)) is True


@pytest.mark.parametrize(
    ("event", "status"),
    [
        (TicketTerminalEvent.OPERATOR_REJECTED, ApprovalTicketStatus.REJECTED),
        (TicketTerminalEvent.EXPIRED, ApprovalTicketStatus.EXPIRED),
        (TicketTerminalEvent.BINDING_INVALIDATED, ApprovalTicketStatus.INVALIDATED),
    ],
)
def test_ticket_terminal_events_are_distinct_and_append_only(
    event: TicketTerminalEvent, status: ApprovalTicketStatus
) -> None:
    """D-12 terminal events are separately named, durable lifecycle facts."""
    ticket = ApprovalTicket.create(ticket_id="ticket-001", binding=_binding(), created_at=NOW)
    terminal = ticket.terminate(event=event, reason="operator-or-runtime-reason", occurred_at=NOW)

    assert terminal.status is status
    assert terminal.terminal_event is event
    assert terminal.terminal_reason == "operator-or-runtime-reason"
    with pytest.raises(ValueError, match="pending"):
        terminal.terminate(event=event, reason="second-transition", occurred_at=NOW)
