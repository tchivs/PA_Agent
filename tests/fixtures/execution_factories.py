"""Deterministic execution-domain factories."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pa_agent.trading.domain.models import (
    AccountObservation,
    Balance,
    ExecutionCommand,
    Mode,
    OrderType,
    Position,
    ProductType,
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


def make_account_observation(**overrides: object) -> AccountObservation:
    """Build a typed immutable spot account observation for contract tests."""
    values: dict[str, object] = {
        "account_id": "paper-account",
        "product": ProductType.SPOT,
        "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "balances": (
            Balance(asset="USDT", total="1000", available="900", reserved="100"),
        ),
        "positions": (
            Position(
                symbol="BTCUSDT",
                quantity="0.125",
                entry_price="42000",
                mark_price="42001",
                unrealized_pnl="0.125",
                margin="0",
            ),
        ),
    }
    values.update(overrides)
    return AccountObservation(**values)  # type: ignore[arg-type]
