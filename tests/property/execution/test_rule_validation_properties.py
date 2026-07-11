"""Property coverage for the internal Decimal instrument-rule calculation."""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pa_agent.trading.application.validation import _validate_command_against_instrument_rules
from pa_agent.trading.domain.errors import InstrumentRuleValidationError
from pa_agent.trading.domain.models import InstrumentRules, decimal_from_canonical
from tests.fixtures.execution_factories import make_spot_command

POSITIVE_SCALED_DECIMALS = st.integers(min_value=1, max_value=10_000).map(
    lambda value: decimal_from_canonical(Decimal(value) / Decimal("1000"))
)
POSITIVE_MULTIPLES = st.integers(min_value=1, max_value=1_000)


@given(
    price_tick=POSITIVE_SCALED_DECIMALS,
    quantity_step=POSITIVE_SCALED_DECIMALS,
    price_multiple=POSITIVE_MULTIPLES,
    quantity_multiple=POSITIVE_MULTIPLES,
)
@pytest.mark.property
def test_exact_decimal_rule_multiples_are_accepted(
    price_tick: Decimal,
    quantity_step: Decimal,
    price_multiple: int,
    quantity_multiple: int,
) -> None:
    """Positive exact Decimal multiples satisfy the pure helper's increment checks."""
    price = price_tick * price_multiple
    quantity = quantity_step * quantity_multiple
    command = make_spot_command(price=price, quantity=quantity)
    rules = InstrumentRules(
        symbol=command.symbol,
        price_tick=price_tick,
        quantity_step=quantity_step,
    )

    _validate_command_against_instrument_rules(command, rules)


@given(
    price_tick=POSITIVE_SCALED_DECIMALS,
    quantity_step=POSITIVE_SCALED_DECIMALS,
    price_multiple=POSITIVE_MULTIPLES,
    quantity_multiple=POSITIVE_MULTIPLES,
)
@pytest.mark.property
def test_fractional_decimal_rule_displacements_are_rejected(
    price_tick: Decimal,
    quantity_step: Decimal,
    price_multiple: int,
    quantity_multiple: int,
) -> None:
    """A non-zero fractional tick or step cannot pass Decimal increment validation."""
    rules = InstrumentRules(
        symbol="BTCUSDT",
        price_tick=price_tick,
        quantity_step=quantity_step,
    )
    off_tick_command = make_spot_command(
        price=price_tick * price_multiple + price_tick / Decimal("2"),
        quantity=quantity_step * quantity_multiple,
    )
    off_step_command = make_spot_command(
        price=price_tick * price_multiple,
        quantity=quantity_step * quantity_multiple + quantity_step / Decimal("2"),
    )

    with pytest.raises(InstrumentRuleValidationError):
        _validate_command_against_instrument_rules(off_tick_command, rules)
    with pytest.raises(InstrumentRuleValidationError):
        _validate_command_against_instrument_rules(off_step_command, rules)
