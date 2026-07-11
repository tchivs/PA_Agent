"""Fresh-metadata orchestration and pure Decimal instrument-rule validation."""
from __future__ import annotations

from pa_agent.trading.domain.errors import InstrumentRuleValidationError
from pa_agent.trading.domain.models import ExecutionCommand, InstrumentRules, OrderType


def _validate_command_against_instrument_rules(
    command: ExecutionCommand, rules: InstrumentRules
) -> None:
    """Reject a command that cannot satisfy immutable current instrument rules."""
    if command.symbol != rules.symbol:
        raise InstrumentRuleValidationError("instrument rules do not match command symbol")
    if command.order_type is OrderType.MARKET:
        raise InstrumentRuleValidationError("market orders cannot establish minimum notional")

    price = command.price
    if price is None or price <= 0 or price % rules.price_tick != 0:
        raise InstrumentRuleValidationError("limit price must be an exact positive tick multiple")
    if command.quantity % rules.quantity_step != 0:
        raise InstrumentRuleValidationError("quantity must be an exact step multiple")
    if command.quantity < rules.minimum_quantity:
        raise InstrumentRuleValidationError("quantity is below the minimum")
    if command.quantity * price < rules.minimum_notional:
        raise InstrumentRuleValidationError("notional is below the minimum")

