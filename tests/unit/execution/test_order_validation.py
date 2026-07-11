"""Unit coverage for the internal Decimal instrument-rule calculation."""
from __future__ import annotations

from decimal import Decimal

import pytest

from pa_agent.trading.application.validation import _validate_command_against_instrument_rules
from pa_agent.trading.domain.errors import InstrumentRuleValidationError
from pa_agent.trading.domain.models import InstrumentRules, OrderType
from tests.fixtures.execution_factories import make_spot_command


RULES = InstrumentRules(
    symbol="BTCUSDT",
    price_tick=Decimal("0.05"),
    quantity_step=Decimal("0.001"),
    minimum_quantity=Decimal("0.010"),
    minimum_notional=Decimal("100"),
)


def test_internal_rule_helper_accepts_an_exact_limit_command_without_mutation() -> None:
    """Exact Decimal tick, step, and minimum boundaries pass unchanged."""
    command = make_spot_command(price=Decimal("100.05"), quantity=Decimal("1.000"))

    _validate_command_against_instrument_rules(command, RULES)

    assert command.price == Decimal("100.05")
    assert command.quantity == Decimal("1.000")


@pytest.mark.parametrize(
    ("price", "quantity"),
    (
        (Decimal("100.01"), Decimal("1.000")),
        (Decimal("100.05"), Decimal("1.0005")),
        (Decimal("100.05"), Decimal("0.009")),
        (Decimal("100.05"), Decimal("0.999")),
    ),
)
def test_internal_rule_helper_rejects_decimal_rule_violations(
    price: Decimal, quantity: Decimal
) -> None:
    """Every numeric rule boundary rejects with the same typed failure."""
    command = make_spot_command(price=price, quantity=quantity)

    with pytest.raises(InstrumentRuleValidationError):
        _validate_command_against_instrument_rules(command, RULES)


def test_internal_rule_helper_rejects_symbol_mismatch_before_numeric_acceptance() -> None:
    """Rules for another symbol cannot validate an otherwise exact command."""
    command = make_spot_command(price=Decimal("100.05"), quantity=Decimal("1.000"))
    mismatched_rules = InstrumentRules(
        symbol="ETHUSDT",
        price_tick=Decimal("0.05"),
        quantity_step=Decimal("0.001"),
        minimum_quantity=Decimal("0.010"),
        minimum_notional=Decimal("100"),
    )

    with pytest.raises(InstrumentRuleValidationError):
        _validate_command_against_instrument_rules(command, mismatched_rules)


def test_internal_rule_helper_rejects_market_order_without_a_canonical_price() -> None:
    """Market commands cannot prove their notional minimum from rules alone."""
    command = make_spot_command(order_type=OrderType.MARKET, price=None, quantity=Decimal("1"))

    with pytest.raises(InstrumentRuleValidationError):
        _validate_command_against_instrument_rules(command, RULES)
