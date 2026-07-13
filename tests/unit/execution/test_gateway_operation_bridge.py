"""RED specifications for the exchange-neutral post-operation bridge."""
from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import FrozenInstanceError, fields

import pytest

from pa_agent.trading.domain.models import GatewayEvidence, OrderState
from pa_agent.trading.ports.gateway import (
    GatewayOperationObserver,
    GatewayOperationReference,
    GatewayOperationResult,
)


def test_operation_result_is_frozen_and_reference_only() -> None:
    """A generic post-operation result carries evidence and no execution capability."""
    reference = GatewayOperationReference(
        operation_id="paper-order:17:client-42",
        client_order_id="client-42",
    )
    result = GatewayOperationResult(
        evidence=GatewayEvidence(
            evidence_id="paper-order:17:client-42",
            client_order_id="client-42",
            state=OrderState.OPEN,
            observed_at=datetime(2026, 7, 13, tzinfo=UTC),
        ),
        reference=reference,
    )

    assert tuple(field.name for field in fields(GatewayOperationReference)) == (
        "operation_id",
        "client_order_id",
    )
    assert tuple(field.name for field in fields(GatewayOperationResult)) == (
        "evidence",
        "reference",
    )
    with pytest.raises(FrozenInstanceError):
        result.reference = reference  # type: ignore[misc]


def test_operation_observer_has_one_result_only_callback() -> None:
    """Observers receive opaque immutable results, never outbound authority."""
    assert tuple(GatewayOperationObserver.__abstractmethods__) == ("observe_operation",)
