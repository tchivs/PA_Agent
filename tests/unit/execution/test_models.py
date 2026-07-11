"""Execution-domain model unit tests."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pa_agent.trading.domain.errors import (
    DecimalValueError,
    LifecycleTransitionError,
    ProductContextError,
)
from pa_agent.trading.domain.lifecycle import assert_transition, is_terminal_state
from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    Fill,
    GatewayCapabilities,
    GatewayEvidence,
    InstrumentRules,
    IsolatedMarginOrderContext,
    LifecycleEvent,
    OrderProjection,
    OrderState,
    Position,
    ProductType,
    QuoteObservation,
    RuleObservation,
    SpotOrderContext,
    TimeObservation,
    UsdtPerpetualOrderContext,
)
from tests.fixtures.execution_factories import make_spot_command


def test_decimal_ingress_accepts_decimal_and_text_but_rejects_unsafe_values() -> None:
    """Canonical execution values reject floats and non-finite numeric inputs."""
    decimal_command = make_spot_command(quantity=Decimal("0.125"), price=Decimal("42.50"))
    text_command = make_spot_command(quantity="0.125", price="42.50")

    assert decimal_command.quantity == Decimal("0.125")
    assert text_command.price == Decimal("42.50")

    for value in (0.125, "NaN", Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(DecimalValueError):
            make_spot_command(quantity=value)


def test_canonical_values_are_frozen_and_keep_decimal_fields() -> None:
    """Every public canonical record is immutable and Decimal-backed."""
    command = make_spot_command()
    evidence = GatewayEvidence(
        evidence_id="evidence-001",
        client_order_id=command.client_order_id,
        state=OrderState.OPEN,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        filled_quantity="0.010",
        average_fill_price="42000.50",
    )
    values = (
        command,
        OrderProjection(command_id=command.command_id, state=OrderState.PROPOSED),
        Fill(
            fill_id="fill-001",
            command_id=command.command_id,
            quantity="0.010",
            price="42000.50",
            fee="0.42",
            fee_asset="USDT",
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        Balance(asset="USDT", total="1000.00", available="900.00", reserved="100.00"),
        Position(
            symbol="BTCUSDT",
            quantity="0.010",
            entry_price="42000.50",
            mark_price="42001.50",
            unrealized_pnl="0.01",
            margin="10.00",
        ),
        InstrumentRules(symbol="BTCUSDT", price_tick="0.01", quantity_step="0.001"),
        GatewayCapabilities(products=frozenset(ProductType), supports_order_lookup=True),
        AccountObservation(account_id="paper-account", product=ProductType.SPOT, observed_at=datetime(2026, 1, 1, tzinfo=UTC)),
        QuoteObservation(symbol="BTCUSDT", bid="42000.00", ask="42001.00", observed_at=datetime(2026, 1, 1, tzinfo=UTC)),
        TimeObservation(server_time=datetime(2026, 1, 1, tzinfo=UTC), observed_at=datetime(2026, 1, 1, tzinfo=UTC)),
        RuleObservation(rules=InstrumentRules(symbol="BTCUSDT", price_tick="0.01", quantity_step="0.001"), observed_at=datetime(2026, 1, 1, tzinfo=UTC)),
        evidence,
    )

    assert command.quantity == Decimal("0.125")
    assert evidence.average_fill_price == Decimal("42000.50")
    for value in values:
        with pytest.raises(FrozenInstanceError):
            value.symbol = "ETHUSDT"


def test_product_contexts_reject_impossible_combinations() -> None:
    """Only perpetual contexts carry product-gated leverage."""
    spot = SpotOrderContext()
    margin = IsolatedMarginOrderContext(isolated_symbol="BTCUSDT", borrow_asset="USDT")
    perpetual = UsdtPerpetualOrderContext(leverage="3", margin_mode="isolated", position_mode="one_way")

    assert spot.product is ProductType.SPOT
    assert margin.product is ProductType.ISOLATED_MARGIN
    assert perpetual.product is ProductType.USDT_PERPETUAL
    assert perpetual.leverage == Decimal("3")
    assert not hasattr(spot, "leverage")

    with pytest.raises(ProductContextError):
        IsolatedMarginOrderContext(isolated_symbol="BTCUSDT", auto_repay=True)
    with pytest.raises(ProductContextError):
        UsdtPerpetualOrderContext(leverage="3", margin_mode="cross", position_mode="one_way")
    with pytest.raises(ProductContextError):
        UsdtPerpetualOrderContext(leverage="0", margin_mode="isolated", position_mode="hedge")

def test_lifecycle_accepts_definitive_evidence_and_rejects_local_terminal_claims() -> None:
    """Only normalized gateway evidence may establish a terminal projection."""
    acknowledged = GatewayEvidence(
        evidence_id="ack-001",
        client_order_id="client-order-001",
        state=OrderState.ACKNOWLEDGED,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    filled = GatewayEvidence(
        evidence_id="fill-001",
        client_order_id="client-order-001",
        state=OrderState.FILLED,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        filled_quantity="0.125",
        average_fill_price="42000.50",
    )

    state = assert_transition(OrderState.PROPOSED, LifecycleEvent.SUBMIT_REQUESTED)
    state = assert_transition(state, LifecycleEvent.ACKNOWLEDGEMENT_OBSERVED, evidence=acknowledged)
    state = assert_transition(state, LifecycleEvent.FILL_OBSERVED, evidence=filled)

    assert state is OrderState.FILLED
    assert is_terminal_state(state)
    for event in (
        LifecycleEvent.LOCAL_TIMEOUT,
        LifecycleEvent.LOCAL_CANCELLATION,
        LifecycleEvent.STREAM_GAP,
        LifecycleEvent.MALFORMED_ACKNOWLEDGEMENT,
    ):
        assert assert_transition(OrderState.SUBMITTING, event) is OrderState.SUBMISSION_UNKNOWN
    with pytest.raises(LifecycleTransitionError):
        assert_transition(OrderState.OPEN, LifecycleEvent.FILL_OBSERVED)
