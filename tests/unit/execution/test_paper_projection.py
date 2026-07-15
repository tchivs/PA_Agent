"""Contract tests for immutable, one-way Paper audit projection batches."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pa_agent.trading.application.paper_projection import (
    PaperEvidenceProjector,
    PaperProjectionBatch,
    PaperProjectionBridge,
    PaperProjectionFill,
)
from pa_agent.trading.domain.models import Fill, GatewayEvidence, OrderState
from pa_agent.trading.gateways.paper.gateway import PaperOperationBatch
from pa_agent.trading.gateways.paper.store import PaperProductSnapshot
from pa_agent.trading.ports.gateway import GatewayOperationReference, GatewayOperationResult


NOW = datetime(2026, 7, 13, tzinfo=UTC)
REFERENCE = GatewayOperationReference("paper-order:client-1", "client-1")


def _operation() -> PaperOperationBatch:
    evidence = GatewayEvidence(
        evidence_id="paper-order:7:client-1",
        client_order_id="client-1",
        state=OrderState.FILLED,
        observed_at=NOW,
        exchange_order_id="client-1",
        filled_quantity=Decimal("1"),
        average_fill_price=Decimal("100"),
    )
    fill = Fill("fill-1", "command-1", "1", "100", "0.1", "USDT", NOW)
    snapshot = PaperProductSnapshot(
        account_id="paper-account",
        product="spot",
        scope="BTCUSDT",
        schema_version="paper-spot-snapshot-v1",
        payload={"balances": {"USDT": "899.9"}},
        paper_event_sequence=7,
    )
    return PaperOperationBatch(REFERENCE, evidence, (fill,), (snapshot,))


def test_batch_is_frozen_normalized_and_projection_has_no_outbound_authority() -> None:
    """A bridge can only consume committed Paper facts; it never receives submit authority."""
    batch = PaperProjectionBatch.from_operation(_operation())

    assert batch.reference == REFERENCE
    assert batch.evidence == (_operation().evidence,)
    assert batch.fills == (
        PaperProjectionFill(
            paper_fill_id="fill-1",
            fill=_operation().fills[0],
            provenance_json=None,
            paper_event_sequence=7,
        ),
    )
    assert batch.snapshots[0].scope == "BTCUSDT"
    with pytest.raises(FrozenInstanceError):
        batch.reference = GatewayOperationReference("other", "other")  # type: ignore[misc]

    assert not any(
        "submit" in attribute or "permit" in attribute or "lease" in attribute or "command" in attribute
        for attribute in vars(PaperEvidenceProjector)
    )
    assert not any("submit" in attribute for attribute in vars(PaperProjectionBridge))


class _Reader:
    def read_operation(self, reference: GatewayOperationReference) -> PaperOperationBatch:
        assert reference == REFERENCE
        return _operation()


class _RecordingProjector:
    def __init__(self) -> None:
        self.batches: list[PaperProjectionBatch] = []

    def apply(self, batch: PaperProjectionBatch) -> None:
        self.batches.append(batch)


def test_bridge_resolves_only_the_durable_reference_then_applies_one_batch() -> None:
    """The generic observer carries no Paper store, permit, lease, or command capability."""
    projector = _RecordingProjector()
    bridge = PaperProjectionBridge(reader=_Reader(), projector=projector)

    bridge.observe_operation(GatewayOperationResult(_operation().evidence, REFERENCE))

    assert projector.batches == [PaperProjectionBatch.from_operation(_operation())]
