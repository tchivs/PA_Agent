"""One-way, immutable audit projection of independently durable Paper truth."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

from pa_agent.trading.domain.models import Fill, GatewayEvidence, canonicalize
from pa_agent.trading.gateways.paper.gateway import PaperOperationBatch
from pa_agent.trading.gateways.paper.store import PaperProductSnapshot
from pa_agent.trading.ports.gateway import (
    GatewayOperationObserver,
    GatewayOperationReference,
    GatewayOperationResult,
)


@dataclass(frozen=True, slots=True)
class PaperProjectionFill:
    """One exact Paper fill plus its source sequence and immutable provenance payload."""

    paper_fill_id: str
    fill: Fill
    provenance_json: str | None
    paper_event_sequence: int

    def __post_init__(self) -> None:
        if not self.paper_fill_id or self.fill.fill_id != self.paper_fill_id:
            raise ValueError("projection fill identity must match canonical fill identity")
        if type(self.paper_event_sequence) is not int or self.paper_event_sequence <= 0:
            raise ValueError("projection fills require a positive Paper event sequence")
        if self.provenance_json is not None:
            value = json.loads(self.provenance_json)
            if type(value) is not dict:
                raise ValueError("Paper fill provenance must be a canonical JSON object")
            canonical = _canonical_json(value)
            if canonical != self.provenance_json:
                raise ValueError("Paper fill provenance must retain canonical JSON exactly")


@dataclass(frozen=True, slots=True)
class PaperProjectionBatch:
    """Frozen, read-only facts reconstructed solely from committed Paper operation truth."""

    reference: GatewayOperationReference
    evidence: tuple[GatewayEvidence, ...]
    fills: tuple[PaperProjectionFill, ...]
    snapshots: tuple[PaperProductSnapshot, ...]
    source_sequence: int

    def __post_init__(self) -> None:
        if type(self.reference) is not GatewayOperationReference:
            raise TypeError("projection batches require a durable gateway reference")
        if not self.evidence or any(type(item) is not GatewayEvidence for item in self.evidence):
            raise TypeError("projection batches require normalized gateway evidence")
        if tuple(sorted(self.fills, key=lambda item: (item.paper_event_sequence, item.paper_fill_id))) != self.fills:
            raise ValueError("projection fills must be in ascending Paper event order")
        if not self.snapshots or any(snapshot.paper_event_sequence is None for snapshot in self.snapshots):
            raise ValueError("projection batches require sequence-keyed Paper snapshots")
        keys = {
            (snapshot.account_id, snapshot.product, snapshot.scope, snapshot.paper_event_sequence)
            for snapshot in self.snapshots
        }
        if len(keys) != len(self.snapshots):
            raise ValueError("projection batches cannot repeat a snapshot scope and sequence")
        if type(self.source_sequence) is not int or self.source_sequence <= 0:
            raise ValueError("projection batches require a positive source sequence")
        if any(fill.paper_event_sequence > self.source_sequence for fill in self.fills):
            raise ValueError("projection fill sequence cannot exceed its batch source sequence")
        if any(snapshot.paper_event_sequence > self.source_sequence for snapshot in self.snapshots):
            raise ValueError("projection snapshot sequence cannot exceed its batch source sequence")

    @classmethod
    def from_operation(cls, operation: PaperOperationBatch) -> PaperProjectionBatch:
        """Copy a committed Paper read result without retaining its gateway or store."""
        if type(operation) is not PaperOperationBatch:
            raise TypeError("projection batches are reconstructed only from Paper operation reads")
        if operation.evidence.client_order_id != operation.reference.client_order_id:
            raise ValueError("Paper operation evidence must match its durable reference")
        snapshots = tuple(operation.snapshots)
        sequences = tuple(snapshot.paper_event_sequence for snapshot in snapshots)
        if any(sequence is None for sequence in sequences):
            raise ValueError("Paper operation snapshots must be committed before projection")
        source_sequence = max(sequence for sequence in sequences if sequence is not None)
        paper_fills = {item.paper_fill_id: item for item in operation.paper_fills}
        fills = tuple(
            PaperProjectionFill(
                paper_fill_id=fill.fill_id,
                fill=fill,
                provenance_json=(paper_fills[fill.fill_id].provenance_json if fill.fill_id in paper_fills else None),
                paper_event_sequence=(
                    paper_fills[fill.fill_id].paper_event_sequence
                    if fill.fill_id in paper_fills
                    else source_sequence
                ),
            )
            for fill in operation.fills
        )
        return cls(
            reference=operation.reference,
            evidence=(operation.evidence,),
            fills=tuple(sorted(fills, key=lambda item: (item.paper_event_sequence, item.paper_fill_id))),
            snapshots=snapshots,
            source_sequence=source_sequence,
        )


class PaperOperationReader(Protocol):
    """Narrow read-only Paper reference resolver used by the projection bridge."""

    def read_operation(self, reference: GatewayOperationReference) -> PaperOperationBatch:
        """Return already committed Paper facts for exactly one durable reference."""


class PaperProjectionPort(Protocol):
    """Narrow central audit append port with no Paper or outbound capability."""

    def apply_paper_projection(self, batch: PaperProjectionBatch) -> None:
        """Atomically append one idempotent Paper audit batch."""


class PaperEvidenceProjector:
    """Persist immutable Paper batches centrally; it has no Paper mutation or submit capability."""

    def __init__(self, *, ledger: PaperProjectionPort) -> None:
        self._ledger = ledger

    def apply(self, batch: PaperProjectionBatch) -> None:
        """Append audit facts only after validating the frozen batch value."""
        if type(batch) is not PaperProjectionBatch:
            raise TypeError("Paper projection accepts only immutable Paper projection batches")
        self._ledger.apply_paper_projection(batch)


class PaperProjectionBridge(GatewayOperationObserver):
    """Paper-specific implementation of the generic post-operation observer."""

    def __init__(self, *, reader: PaperOperationReader, projector: PaperEvidenceProjector) -> None:
        self._reader = reader
        self._projector = projector

    def observe_operation(self, result: GatewayOperationResult) -> None:
        """Resolve one durable reference and deliver exactly that immutable batch once."""
        if type(result) is not GatewayOperationResult:
            raise TypeError("Paper projection bridge accepts only gateway operation results")
        self._projector.apply(PaperProjectionBatch.from_operation(self._reader.read_operation(result.reference)))


def _canonical_json(value: object) -> str:
    """Serialize canonical Paper provenance without recomputing or mutating economics."""
    return json.dumps(canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
