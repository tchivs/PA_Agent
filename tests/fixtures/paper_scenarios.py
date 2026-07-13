"""Reproducible Decimal-only paper-market scenario factories."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pa_agent.trading.domain.models import (
    ExecutionCommand,
    OrderType,
    ProductType,
    Side,
    SpotOrderContext,
)
from pa_agent.trading.domain.paper import DepthLevel, MarketObservation, PaperEconomicPolicy

FIXED_OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def make_policy(**overrides: object) -> PaperEconomicPolicy:
    """Build an immutable Spot policy with explicit economic rule versions."""
    values: dict[str, object] = {
        "product": ProductType.SPOT,
        "policy_version": "paper-spot-v1",
        "fee_rate": Decimal("0.001"),
        "fee_rule_version": "fee-v1",
        "slippage_rate": Decimal("0.001"),
        "slippage_rule_version": "slippage-v1",
    }
    values.update(overrides)
    return PaperEconomicPolicy(**values)  # type: ignore[arg-type]


def make_observation(**overrides: object) -> MarketObservation:
    """Build one explicit, fixed-time market fact; time is evidence only."""
    values: dict[str, object] = {
        "observation_id": "btc-book-001",
        "account_id": "paper-account",
        "product": ProductType.SPOT,
        "symbol": "BTCUSDT",
        "version": 1,
        "observed_at": FIXED_OBSERVED_AT,
        "asks": (
            DepthLevel(price=Decimal("100"), quantity=Decimal("1")),
            DepthLevel(price=Decimal("101"), quantity=Decimal("2")),
        ),
        "bids": (
            DepthLevel(price=Decimal("99"), quantity=Decimal("1")),
            DepthLevel(price=Decimal("98"), quantity=Decimal("2")),
        ),
    }
    values.update(overrides)
    return MarketObservation(**values)  # type: ignore[arg-type]


def make_command(**overrides: object) -> ExecutionCommand:
    """Build an immutable paper Spot command without any submission authority."""
    values: dict[str, object] = {
        "command_id": "paper-command-001",
        "logical_command_key": "paper-logical-001",
        "client_order_id": "paper-client-001",
        "mode": "paper",
        "account_id": "paper-account",
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("1"),
        "price": None,
        "context": SpotOrderContext(),
    }
    values.update(overrides)
    from pa_agent.trading.domain.models import Mode

    if values["mode"] == "paper":
        values["mode"] = Mode.PAPER
    return ExecutionCommand(**values)  # type: ignore[arg-type]
