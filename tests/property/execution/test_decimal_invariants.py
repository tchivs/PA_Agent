"""Property tests for Decimal canonicalization and lifecycle safety."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st

from pa_agent.trading.domain.errors import LifecycleTransitionError
from pa_agent.trading.domain.lifecycle import assert_transition
from pa_agent.trading.domain.models import (
    GatewayEvidence,
    LifecycleEvent,
    OrderState,
    decimal_from_canonical,
    decimal_to_canonical,
)
from tests.fixtures.execution_factories import make_spot_command

FINITE_DECIMALS = st.decimals(allow_nan=False, allow_infinity=False, places=6)


@given(FINITE_DECIMALS)
def test_finite_decimals_round_trip_through_canonical_domain_serialization(value: Decimal) -> None:
    """Canonical Decimal text is stable through parsing and command serialization."""
    text = decimal_to_canonical(value)
    command = make_spot_command(quantity=text)

    assert decimal_to_canonical(decimal_from_canonical(text)) == text
    assert command.to_canonical_dict()["quantity"] == text


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_binary_floats_never_enter_canonical_commands(value: float) -> None:
    """A binary float remains an invalid execution-domain input at every magnitude."""
    with pytest.raises(TypeError):
        make_spot_command(quantity=value)


@given(st.sampled_from([OrderState.PROPOSED, OrderState.SUBMITTING, OrderState.OPEN]))
def test_terminal_events_require_matching_normalized_evidence(state: OrderState) -> None:
    """Malformed or absent evidence cannot turn an order into a terminal projection."""
    with pytest.raises(LifecycleTransitionError):
        assert_transition(state, LifecycleEvent.FILL_OBSERVED)

    evidence = GatewayEvidence(
        evidence_id="fill-evidence",
        client_order_id="client-order-001",
        state=OrderState.FILLED,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        filled_quantity="1",
        average_fill_price="1",
    )
    if state is OrderState.OPEN:
        assert assert_transition(state, LifecycleEvent.FILL_OBSERVED, evidence=evidence) is OrderState.FILLED
