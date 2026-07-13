"""Spot Decimal accounting invariants independent of central execution ledger truth."""
from __future__ import annotations

from decimal import Decimal

import pytest

from pa_agent.trading.domain.models import OrderType, Side
from pa_agent.trading.gateways.paper.accounting_spot import PaperSpotAccounting
from pa_agent.trading.gateways.paper.gateway import PaperGateway
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.gateways.paper.matching import match_order
from tests.fixtures.paper_scenarios import make_command, make_observation, make_policy


def test_buy_reserves_quote_and_settles_only_accepted_partial_fill() -> None:
    """Opening a buy moves only its Decimal maximum into reserve until a fill settles."""
    command = make_command(order_type=OrderType.LIMIT, price=Decimal("110"), quantity=Decimal("2"))
    policy = make_policy()
    observation = make_observation(asks=(make_observation().asks[0],))
    accounting = PaperSpotAccounting.from_initial_balances({"USDT": "1000", "BTC": "0"})

    opened = accounting.open(command, policy=policy, observation=observation)
    assert opened.balance("USDT").total == Decimal("1000")
    assert opened.balance("USDT").reserved == Decimal("220.440220")
    assert opened.balance("USDT").available == Decimal("779.559780")

    candidates = match_order(
        command=command,
        observation=observation,
        policy=policy,
        paper_event_sequence=1,
    ).candidates
    partial = opened.settle(command, candidates)

    assert partial.balance("BTC").total == Decimal("1")
    assert partial.balance("BTC").available == Decimal("1")
    assert partial.balance("USDT").total == Decimal("899.799900")
    assert partial.balance("USDT").reserved == Decimal("110.220110")
    assert partial.balance("USDT").available + partial.balance("USDT").reserved == partial.balance("USDT").total


def test_sell_reserves_base_and_cancel_releases_only_unfilled_remainder() -> None:
    """A cancellation cannot restore the base portion already transferred by an accepted fill."""
    command = make_command(side=Side.SELL, quantity=Decimal("2"))
    policy = make_policy()
    observation = make_observation(bids=(make_observation().bids[0],))
    accounting = PaperSpotAccounting.from_initial_balances({"USDT": "0", "BTC": "2"})

    opened = accounting.open(command, policy=policy, observation=observation)
    partial = opened.settle(
        command,
        match_order(
            command=command,
            observation=observation,
            policy=policy,
            paper_event_sequence=1,
        ).candidates,
    )
    cancelled = partial.release(command, remaining_quantity=Decimal("1"))

    assert partial.balance("BTC").total == Decimal("1")
    assert partial.balance("BTC").reserved == Decimal("1")
    assert cancelled.balance("BTC").total == Decimal("1")
    assert cancelled.balance("BTC").available == Decimal("1")
    assert cancelled.balance("BTC").reserved == Decimal("0")
    assert cancelled.balance("USDT").total == Decimal("98.802099")


def test_insufficient_available_assets_reject_before_any_reservation() -> None:
    """A reservation rejects rather than creating a negative available balance."""
    command = make_command(order_type=OrderType.LIMIT, price=Decimal("110"), quantity=Decimal("2"))
    accounting = PaperSpotAccounting.from_initial_balances({"USDT": "1", "BTC": "0"})

    with pytest.raises(ValueError, match="insufficient available"):
        accounting.open(command, policy=make_policy(), observation=make_observation())

    assert accounting.balance("USDT").available == Decimal("1")
    assert accounting.balance("USDT").reserved == Decimal("0")


def test_gateway_rejects_direct_command_submission(tmp_path) -> None:
    """The Paper gateway's only submission surface remains the leased outbound value."""
    gateway = PaperGateway(
        PaperStore(tmp_path / "paper.sqlite"),
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
    )

    with pytest.raises(TypeError, match="OutboundSubmission"):
        gateway.submit_order(make_command())
