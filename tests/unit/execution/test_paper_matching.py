"""Behavioral contracts for pure deterministic paper depth matching."""
from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from pa_agent.trading.domain.errors import CanonicalInputError, DecimalValueError, TradingDomainError
from pa_agent.trading.domain.models import OrderType, ProductType, Side
from pa_agent.trading.domain.paper import DepthLevel, MarketObservation, ObservationDisposition
from pa_agent.trading.gateways.paper.matching import match_order, sort_fill_candidates
from tests.fixtures.paper_scenarios import make_command, make_observation, make_policy


def test_market_buy_consumes_asks_lowest_first_with_exact_decimal_provenance() -> None:
    """A crossing buy consumes each explicit ask in canonical ascending price order."""
    result = match_order(
        command=make_command(quantity=Decimal("2.5")),
        observation=make_observation(),
        policy=make_policy(),
        paper_event_sequence=7,
    )

    assert result.disposition is ObservationDisposition.ACCEPTED
    assert result.remaining_quantity == Decimal("0")
    assert [(candidate.quantity, candidate.provenance.raw_book_price) for candidate in result.candidates] == [
        (Decimal("1"), Decimal("100")),
        (Decimal("1.5"), Decimal("101")),
    ]
    assert [candidate.provenance.final_execution_price for candidate in result.candidates] == [
        Decimal("100.100"),
        Decimal("101.101"),
    ]


def test_market_sell_consumes_bids_highest_first_and_retains_insufficient_remainder() -> None:
    """A sell walks bids downward and an exhausted book leaves a durable-ready remainder."""
    result = match_order(
        command=make_command(side=Side.SELL, quantity=Decimal("4")),
        observation=make_observation(),
        policy=make_policy(),
        paper_event_sequence=8,
    )

    assert [(candidate.quantity, candidate.provenance.raw_book_price) for candidate in result.candidates] == [
        (Decimal("1"), Decimal("99")),
        (Decimal("2"), Decimal("98")),
    ]
    assert result.filled_quantity == Decimal("3")
    assert result.remaining_quantity == Decimal("1")


def test_limit_orders_only_consume_crossing_depth() -> None:
    """Non-crossing limits remain open while a crossing limit consumes available depth only."""
    non_crossing = match_order(
        command=make_command(order_type=OrderType.LIMIT, price=Decimal("99"), quantity=Decimal("1")),
        observation=make_observation(),
        policy=make_policy(),
        paper_event_sequence=9,
    )
    crossing = match_order(
        command=make_command(order_type=OrderType.LIMIT, price=Decimal("100"), quantity=Decimal("2")),
        observation=make_observation(),
        policy=make_policy(),
        paper_event_sequence=10,
    )

    assert non_crossing.candidates == ()
    assert non_crossing.remaining_quantity == Decimal("1")
    assert [(candidate.quantity, candidate.provenance.raw_book_price) for candidate in crossing.candidates] == [
        (Decimal("1"), Decimal("100")),
    ]
    assert crossing.remaining_quantity == Decimal("1")


def test_equal_price_candidates_sort_by_observation_version_then_event_sequence() -> None:
    """Price ties never rely on local process order, wall time, or dictionary iteration."""
    version_one = match_order(
        command=make_command(),
        observation=make_observation(version=1),
        policy=make_policy(),
        paper_event_sequence=9,
    ).candidates[0]
    version_two = match_order(
        command=make_command(),
        observation=make_observation(observation_id="btc-book-002", version=2),
        policy=make_policy(),
        paper_event_sequence=1,
    ).candidates[0]
    later_event = replace(version_one, paper_event_sequence=12)

    assert sort_fill_candidates((later_event, version_two, version_one)) == (
        version_one,
        later_event,
        version_two,
    )


def test_duplicate_and_out_of_order_observations_produce_no_fill_candidates() -> None:
    """Observation identity/version/digest guards classify replay without advancing matching."""
    accepted = make_observation(version=2)
    duplicate = make_observation(version=2)
    lower = make_observation(observation_id="btc-book-000", version=1)
    conflicting = make_observation(
        version=2,
        asks=(DepthLevel(price=Decimal("100"), quantity=Decimal("2")),),
    )

    idempotent = match_order(
        command=make_command(),
        observation=duplicate,
        policy=make_policy(),
        paper_event_sequence=2,
        previous_observation=accepted,
    )
    out_of_order = match_order(
        command=make_command(),
        observation=lower,
        policy=make_policy(),
        paper_event_sequence=3,
        previous_observation=accepted,
    )
    conflict = match_order(
        command=make_command(),
        observation=conflicting,
        policy=make_policy(),
        paper_event_sequence=4,
        previous_observation=accepted,
    )

    assert idempotent.disposition is ObservationDisposition.IDEMPOTENT
    assert out_of_order.disposition is ObservationDisposition.REJECTED_OUT_OF_ORDER
    assert conflict.disposition is ObservationDisposition.REJECTED_CONFLICT
    assert all(not result.candidates for result in (idempotent, out_of_order, conflict))


def test_fill_provenance_serializes_every_decimal_input_and_policy_version() -> None:
    """A future accounting projector can reproduce each fill without consulting current policy."""
    candidate = match_order(
        command=make_command(quantity=Decimal("1")),
        observation=make_observation(),
        policy=make_policy(),
        paper_event_sequence=11,
    ).candidates[0]

    assert candidate.to_canonical_dict() == {
        "paper_fill_id": candidate.paper_fill_id,
        "command_id": "paper-command-001",
        "quantity": "1",
        "paper_event_sequence": 11,
        "provenance": {
            "observation_id": "btc-book-001",
            "observation_version": 1,
            "observation_digest": make_observation().digest,
            "raw_book_price": "100",
            "slippage_rate": "0.001",
            "slippage_rule_version": "slippage-v1",
            "slippage_adjusted_price": "100.100",
            "final_execution_price": "100.100",
            "fee_rate": "0.001",
            "fee_rule_version": "fee-v1",
            "fee_basis": "100.100",
            "fee": "0.100100",
            "product_policy_version": "paper-spot-v1",
        },
    }


def test_paper_values_are_frozen_and_policies_reject_float_rates() -> None:
    """Economic facts remain immutable and reject binary inputs before matching."""
    candidate = match_order(
        command=make_command(),
        observation=make_observation(),
        policy=make_policy(),
        paper_event_sequence=12,
    ).candidates[0]

    with pytest.raises(FrozenInstanceError):
        candidate.quantity = Decimal("2")  # type: ignore[misc]
    with pytest.raises(DecimalValueError):
        make_policy(fee_rate=0.001)


@pytest.mark.parametrize(
    ("factory", "error"),
    (
        (lambda: DepthLevel(price=100.0, quantity=Decimal("1")), DecimalValueError),
        (lambda: DepthLevel(price=Decimal("NaN"), quantity=Decimal("1")), DecimalValueError),
        (lambda: DepthLevel(price=Decimal("100"), quantity=Decimal("-1")), CanonicalInputError),
        (lambda: make_observation(observation_id=""), CanonicalInputError),
        (
            lambda: make_observation(
                asks=(
                    DepthLevel(price=Decimal("101"), quantity=Decimal("1")),
                    DepthLevel(price=Decimal("100"), quantity=Decimal("1")),
                )
            ),
            CanonicalInputError,
        ),
    ),
)
def test_observation_contract_rejects_noncanonical_market_data(
    factory: object, error: type[TradingDomainError]
) -> None:
    """Malformed external depth cannot reach the pure matching kernel."""
    with pytest.raises(error):
        factory()  # type: ignore[operator]


def test_matcher_has_no_clock_or_polling_callback_authority() -> None:
    """Only a supplied immutable observation can advance paper matching."""
    parameter_names = set(inspect.signature(match_order).parameters)

    assert not {"clock", "now", "poll", "polling_callback", "scheduler"} & parameter_names
    assert ProductType.SPOT is make_policy().product
