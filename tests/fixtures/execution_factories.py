"""Deterministic execution-domain factories."""
from __future__ import annotations

from decimal import Decimal

from pa_agent.trading.domain.models import (
    ExecutionCommand,
    Mode,
    OrderType,
    Side,
    SpotOrderContext,
)


def make_spot_command(**overrides: object) -> ExecutionCommand:
    """Build a valid immutable spot command with deterministic identifiers."""
    values: dict[str, object] = {
        "command_id": "command-001",
        "logical_command_key": "logical-command-001",
        "client_order_id": "client-order-001",
        "mode": Mode.PAPER,
        "account_id": "paper-account",
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("0.125"),
        "price": Decimal("42000.50"),
        "context": SpotOrderContext(),
    }
    values.update(overrides)
    return ExecutionCommand(**values)  # type: ignore[arg-type]
