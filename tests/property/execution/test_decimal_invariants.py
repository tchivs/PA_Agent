"""Property tests for Decimal canonicalization."""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pa_agent.trading.domain.models import decimal_from_canonical, decimal_to_canonical
from tests.fixtures.execution_factories import make_spot_command

FINITE_DECIMALS = st.decimals(allow_nan=False, allow_infinity=False, places=6)


@given(FINITE_DECIMALS)
def test_finite_decimals_round_trip_through_canonical_domain_serialization(value: Decimal) -> None:
    """Canonical Decimal text is stable through parsing and command serialization."""
    text = decimal_to_canonical(value)
    command_value = value.copy_abs() if value else Decimal("1")
    command_text = decimal_to_canonical(command_value)
    command = make_spot_command(quantity=command_text)

    assert decimal_to_canonical(decimal_from_canonical(text)) == text
    assert command.to_canonical_dict()["quantity"] == command_text


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_binary_floats_never_enter_canonical_commands(value: float) -> None:
    """A binary float remains an invalid execution-domain input at every magnitude."""
    with pytest.raises(TypeError):
        make_spot_command(quantity=value)


