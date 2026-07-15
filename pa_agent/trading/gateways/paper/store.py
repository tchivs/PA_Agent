"""Transactional, independently durable repository for paper-trading truth."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType
from typing import Callable, Mapping

from pa_agent.trading.domain.approval import ExecutionTarget
from pa_agent.trading.domain.models import (
    Balance,
    ExecutionCommand,
    Mode,
    OrderType,
    Position,
    ProductType,
    Side,
    decimal_from_canonical,
    decimal_to_canonical,
    product_context_from_canonical_payload,
)
from pa_agent.trading.gateways.paper.accounting_margin import PaperMarginAccounting
from pa_agent.trading.gateways.paper.accounting_perpetual import PaperPerpetualAccounting
from pa_agent.trading.gateways.paper.accounting_spot import PaperSpotAccounting
from pa_agent.trading.domain.paper import (
    DepthLevel,
    MarketObservation,
    PaperFillCandidate,
    PaperLiquidationCandidate,
)
from pa_agent.trading.domain.risk import (
    IsolatedMarginProductEvidence,
    UsdtPerpetualProductEvidence,
)
from pa_agent.trading.gateways.paper.schema import run_paper_migrations
from pa_agent.trading.persistence.sqlite_connection import open_sqlite_connection, transaction


_TERMINAL_STATES = frozenset({"FILLED", "CANCELLED", "REJECTED"})


class ObservationDisposition(StrEnum):
    """Durable outcomes for one explicit market observation."""

    ACCEPTED = "accepted"
    IDEMPOTENT = "idempotent"
    REJECTED_OUT_OF_ORDER = "rejected_out_of_order"
    REJECTED_CONFLICT = "rejected_conflict"
    REJECTED_TERMINAL = "rejected_terminal"


class CancellationDisposition(StrEnum):
    """Durable outcomes for cancellation request and cancellation evidence facts."""

    REQUESTED = "requested"
    CANCELLED = "cancelled"
    REJECTED_TERMINAL = "rejected_terminal"


@dataclass(frozen=True)
class PaperObservationResult:
    disposition: ObservationDisposition
    paper_event_sequence: int | None


@dataclass(frozen=True)
class PaperCancellationResult:
    disposition: CancellationDisposition
    paper_event_sequence: int | None


@dataclass(frozen=True)
class PaperOrder:
    client_order_id: str
    command_id: str
    account_id: str
    product: str
    symbol: str
    lifecycle_state: str
    filled_quantity: Decimal
    paper_event_sequence: int | None


@dataclass(frozen=True)
class PaperFill:
    paper_fill_id: str
    command_id: str
    quantity: Decimal
    provenance_json: str
    paper_event_sequence: int


@dataclass(frozen=True)
class PaperWorkspaceFill:
    """Display-safe immutable fill fact without durable provenance payload leakage."""

    paper_fill_id: str
    command_id: str
    quantity: Decimal
    paper_event_sequence: int

    def __post_init__(self) -> None:
        if not self.paper_fill_id or not self.command_id or self.paper_event_sequence <= 0:
            raise ValueError("workspace fills require durable identities and sequence")
        if self.quantity <= 0:
            raise ValueError("workspace fills require positive quantity")


@dataclass(frozen=True)
class PaperLiquidationFill:
    """Durable forced-close provenance separate from the originating order fill."""

    paper_fill_id: str
    account_id: str
    symbol: str
    origin_command_id: str
    quantity: Decimal
    provenance: Mapping[str, object]
    paper_event_sequence: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True)
class PaperEvent:
    sequence: int
    event_type: str
    client_order_id: str | None
    command_id: str | None
    payload_json: str


@dataclass(frozen=True)
class PaperIncident:
    kind: str
    detail_json: str


@dataclass(frozen=True)
class PaperProductSnapshot:
    """Opaque, versioned product projector output committed with one paper event."""

    account_id: str
    product: str
    scope: str
    schema_version: str
    payload: Mapping[str, object]
    paper_event_sequence: int | None = None

    def __post_init__(self) -> None:
        if not all((self.account_id, self.product, self.scope, self.schema_version)):
            raise ValueError("paper snapshot scope and schema version are required")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        _canonical_json(dict(self.payload))


@dataclass(frozen=True)
class PaperWorkspaceProductFacts:
    """Version-checked, immutable durable facts for one Paper account product."""

    account_id: str
    product: ProductType
    balances: tuple[Balance, ...]
    positions: tuple[Position, ...]
    open_orders: tuple[PaperOrder, ...]
    fills: tuple[PaperWorkspaceFill, ...]
    source_sequence: int | None
    last_successful_reconciled_at: datetime | None
    source: str = "paper"

    def __post_init__(self) -> None:
        if not self.account_id or type(self.product) is not ProductType:
            raise ValueError("workspace facts require an exact account and product")
        if self.source != "paper":
            raise ValueError("workspace facts must retain their durable Paper source")
        if self.source_sequence is not None and (
            type(self.source_sequence) is not int or self.source_sequence <= 0
        ):
            raise ValueError("workspace facts require a positive durable source sequence")
        if self.last_successful_reconciled_at is not None and self.last_successful_reconciled_at.tzinfo is None:
            raise ValueError("workspace facts require timezone-aware reconciliation time")
        if any(type(value) is not Balance for value in self.balances):
            raise TypeError("workspace balances must be canonical values")
        if any(type(value) is not Position for value in self.positions):
            raise TypeError("workspace positions must be canonical values")
        if any(value.account_id != self.account_id or value.product != self.product.value for value in self.open_orders):
            raise ValueError("workspace orders must remain product scoped")
        if any(type(value) is not PaperWorkspaceFill for value in self.fills):
            raise TypeError("workspace fills must be display-safe durable Paper values")

class PaperStore:
    """Paper-owned SQLite authority with no central-ledger reads or writes."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).resolve(strict=False)
        self._connection = open_sqlite_connection(self.database_path)
        try:
            run_paper_migrations(self._connection)
        except Exception:
            self._connection.close()
            raise
        self._connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self._connection.close()

    def create_order(self, command: ExecutionCommand) -> PaperOrder:
        """Persist an open paper order before any observation can project a fill."""
        command_json = _canonical_json(command.to_canonical_dict())
        product = command.context.product.value
        with transaction(self._connection):
            self._connection.execute(
                """
                INSERT INTO paper_orders(
                    client_order_id, command_id, account_id, product, symbol, command_json,
                    quantity, lifecycle_state, filled_quantity, paper_event_sequence, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', '0', NULL, ?)
                """,
                (
                    command.client_order_id,
                    command.command_id,
                    command.account_id,
                    product,
                    command.symbol,
                    command_json,
                    decimal_to_canonical(command.quantity),
                    _utc_now_text(),
                ),
            )
        order = self.fetch_order(command.client_order_id)
        assert order is not None
        return order

    def ensure_snapshot(self, snapshot: PaperProductSnapshot) -> PaperProductSnapshot:
        """Initialize one paper account scope once without consulting any central projection."""
        with transaction(self._connection):
            existing = self.load_snapshot(
                account_id=snapshot.account_id, product=snapshot.product, scope=snapshot.scope
            )
            if existing is not None:
                return existing
            sequence = self._allocate_sequence()
            self._append_event(
                sequence=sequence,
                event_type="account_initialized",
                client_order_id=None,
                command_id=None,
                payload_json=_canonical_json(dict(snapshot.payload)),
            )
            return self._persist_snapshot(snapshot, sequence)

    def create_order_with_snapshot(
        self,
        command: ExecutionCommand,
        snapshot: PaperProductSnapshot,
        *,
        candidate_factory: Callable[[int], tuple[PaperFillCandidate, ...]] | None = None,
        snapshot_factory: Callable[[int, tuple[PaperFillCandidate, ...]], PaperProductSnapshot] | None = None,
        margin_evidence_factory: Callable[[int, tuple[PaperFillCandidate, ...]], IsolatedMarginProductEvidence] | None = None,
    ) -> PaperOrder:
        """Atomically persist a new open order and its already-reserved product truth."""
        if (snapshot.account_id, snapshot.product, snapshot.scope) != (
            command.account_id,
            command.context.product.value,
            command.symbol,
        ):
            raise ValueError("paper order snapshot scope must match command")
        command_json = _canonical_json(command.to_canonical_dict())
        with transaction(self._connection):
            sequence = self._allocate_sequence()
            self._connection.execute(
                """
                INSERT INTO paper_orders(
                    client_order_id, command_id, account_id, product, symbol, command_json,
                    quantity, lifecycle_state, filled_quantity, paper_event_sequence, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', '0', ?, ?)
                """,
                (
                    command.client_order_id,
                    command.command_id,
                    command.account_id,
                    command.context.product.value,
                    command.symbol,
                    command_json,
                    decimal_to_canonical(command.quantity),
                    sequence,
                    _utc_now_text(),
                ),
            )
            self._append_event(
                sequence=sequence,
                event_type="order_opened",
                client_order_id=command.client_order_id,
                command_id=command.command_id,
                payload_json=command_json,
            )
            candidates = () if candidate_factory is None else candidate_factory(sequence)
            self._assert_candidates_mutable(candidates)
            for candidate in candidates:
                if candidate.paper_event_sequence != sequence:
                    raise ValueError("paper fill candidate sequence must equal the durable event sequence")
                self._persist_fill(candidate, sequence)
            if snapshot_factory is not None:
                snapshot = snapshot_factory(sequence, candidates)
            self._persist_snapshot(snapshot, sequence)
            if margin_evidence_factory is not None:
                self._persist_isolated_margin_product_evidence(
                    margin_evidence_factory(sequence, candidates), sequence
                )
        order = self.fetch_order(command.client_order_id)
        assert order is not None
        return order

    def list_open_commands(self, *, account_id: str, product: ProductType, symbol: str) -> tuple[ExecutionCommand, ...]:
        """Reconstruct open commands from paper-owned durable payloads for explicit matching only."""
        rows = self._connection.execute(
            """
            SELECT command_json FROM paper_orders
            WHERE account_id = ? AND product = ? AND symbol = ?
              AND lifecycle_state NOT IN ('FILLED', 'CANCELLED', 'REJECTED')
            ORDER BY client_order_id
            """,
            (account_id, product.value, symbol),
        ).fetchall()
        return tuple(_command_from_canonical_json(row["command_json"]) for row in rows)

    def load_latest_observation(
        self, *, account_id: str, product: ProductType, symbol: str
    ) -> MarketObservation | None:
        """Return the latest accepted explicit book; there is no local-time market fallback."""
        row = self._connection.execute(
            """
            SELECT payload_json FROM paper_market_books
            WHERE account_id = ? AND product = ? AND symbol = ?
            ORDER BY observation_version DESC LIMIT 1
            """,
            (account_id, product.value, symbol),
        ).fetchone()
        return None if row is None else _observation_from_canonical_json(row["payload_json"])

    def apply_observation(
        self,
        *,
        observation: MarketObservation,
        candidates: tuple[PaperFillCandidate, ...] = (),
        snapshot: PaperProductSnapshot | None = None,
        candidate_factory: Callable[[int], tuple[PaperFillCandidate, ...]] | None = None,
        snapshot_factory: Callable[[int, tuple[PaperFillCandidate, ...]], PaperProductSnapshot] | None = None,
        margin_evidence_factory: Callable[[int, tuple[PaperFillCandidate, ...]], IsolatedMarginProductEvidence] | None = None,
        perpetual_evidence_factory: Callable[[int, tuple[PaperFillCandidate, ...]], UsdtPerpetualProductEvidence] | None = None,
        liquidation_factory: Callable[[int, tuple[PaperFillCandidate, ...]], PaperLiquidationCandidate | None] | None = None,
        allow_terminal_observation: bool = False,
    ) -> PaperObservationResult:
        """Atomically accept one observation, matching result, and product snapshot."""
        if snapshot is not None:
            self._assert_snapshot_scope(observation, snapshot)
        observation_payload = _canonical_json(observation.to_canonical_dict())
        scope = (observation.account_id, observation.product.value, observation.symbol)

        with transaction(self._connection):
            cursor = self._connection.execute(
                """
                SELECT observation_id, observation_version, observation_digest
                FROM paper_observation_cursors
                WHERE account_id = ? AND product = ? AND symbol = ?
                """,
                scope,
            ).fetchone()
            if cursor is not None:
                disposition = self._classify_cursor(cursor, observation)
                if disposition is ObservationDisposition.IDEMPOTENT:
                    return PaperObservationResult(disposition=disposition, paper_event_sequence=None)
                if disposition is not ObservationDisposition.ACCEPTED:
                    self._record_incident(
                        kind=("out_of_order" if disposition is ObservationDisposition.REJECTED_OUT_OF_ORDER else "conflict"),
                        scope=scope,
                        detail={"observation_id": observation.observation_id, "version": observation.version},
                    )
                    return PaperObservationResult(disposition=disposition, paper_event_sequence=None)

            scoped_states = self._connection.execute(
                """
                SELECT lifecycle_state FROM paper_orders
                WHERE account_id = ? AND product = ? AND symbol = ?
                """,
                scope,
            ).fetchall()
            if (
                scoped_states
                and all(row["lifecycle_state"] in _TERMINAL_STATES for row in scoped_states)
                and not allow_terminal_observation
            ):
                return PaperObservationResult(
                    disposition=ObservationDisposition.REJECTED_TERMINAL, paper_event_sequence=None
                )
            sequence = self._allocate_sequence()
            if candidate_factory is not None:
                candidates = candidate_factory(sequence)
            self._assert_candidates_mutable(candidates)
            if snapshot_factory is not None:
                snapshot = snapshot_factory(sequence, candidates)
            if snapshot is None:
                raise ValueError("paper observation requires a product snapshot")
            self._assert_snapshot_scope(observation, snapshot)
            liquidation = None if liquidation_factory is None else liquidation_factory(sequence, candidates)
            if liquidation is not None and (
                liquidation.account_id != observation.account_id
                or liquidation.symbol != observation.symbol
                or observation.product is not ProductType.USDT_PERPETUAL
            ):
                raise ValueError("paper liquidation candidate scope is invalid")
            self._append_event(
                sequence=sequence,
                event_type="observation_accepted",
                client_order_id=None,
                command_id=None,
                payload_json=observation_payload,
            )
            self._connection.execute(
                """
                INSERT INTO paper_observation_cursors(
                    account_id, product, symbol, observation_id, observation_version,
                    observation_digest, paper_event_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, product, symbol) DO UPDATE SET
                    observation_id = excluded.observation_id,
                    observation_version = excluded.observation_version,
                    observation_digest = excluded.observation_digest,
                    paper_event_sequence = excluded.paper_event_sequence
                """,
                (*scope, observation.observation_id, observation.version, observation.digest, sequence),
            )
            self._connection.execute(
                """
                INSERT INTO paper_market_books(
                    account_id, product, symbol, observation_version, observation_id,
                    observation_digest, payload_json, paper_event_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*scope, observation.version, observation.observation_id, observation.digest, observation_payload, sequence),
            )
            for candidate in candidates:
                if candidate.paper_event_sequence != sequence:
                    raise ValueError("paper fill candidate sequence must equal the durable event sequence")
                self._persist_fill(candidate, sequence)
            projection_sequence = sequence
            if liquidation is not None:
                projection_sequence = self._allocate_sequence()
                self._append_event(
                    sequence=projection_sequence,
                    event_type="perpetual_liquidation",
                    client_order_id=None,
                    command_id=liquidation.origin_command_id,
                    payload_json=_canonical_json(dict(liquidation.provenance)),
                )
                self._persist_liquidation_fill(liquidation, projection_sequence)
            self._persist_snapshot(snapshot, projection_sequence)
            if margin_evidence_factory is not None:
                self._persist_isolated_margin_product_evidence(
                    margin_evidence_factory(sequence, candidates), projection_sequence
                )
            if perpetual_evidence_factory is not None:
                self._persist_usdt_perpetual_product_evidence(
                    perpetual_evidence_factory(sequence, candidates), projection_sequence
                )
        return PaperObservationResult(ObservationDisposition.ACCEPTED, sequence)

    def request_cancellation(
        self, client_order_id: str, *, cancellation_id: str
    ) -> PaperCancellationResult:
        """Append cancellation intent without fabricating terminal cancellation evidence."""
        with transaction(self._connection):
            order = self._order_row(client_order_id)
            if order["lifecycle_state"] in _TERMINAL_STATES:
                return PaperCancellationResult(CancellationDisposition.REJECTED_TERMINAL, None)
            existing = self._connection.execute(
                "SELECT requested_sequence FROM paper_cancellation_requests WHERE cancellation_id = ?",
                (cancellation_id,),
            ).fetchone()
            if existing is not None:
                return PaperCancellationResult(CancellationDisposition.REQUESTED, existing["requested_sequence"])
            sequence = self._allocate_sequence()
            payload = _canonical_json({"cancellation_id": cancellation_id})
            self._append_event(
                sequence=sequence,
                event_type="cancellation_requested",
                client_order_id=client_order_id,
                command_id=order["command_id"],
                payload_json=payload,
            )
            self._connection.execute(
                """
                INSERT INTO paper_cancellation_requests(cancellation_id, client_order_id, requested_sequence, status)
                VALUES (?, ?, ?, 'REQUESTED')
                """,
                (cancellation_id, client_order_id, sequence),
            )
        return PaperCancellationResult(CancellationDisposition.REQUESTED, sequence)

    def persist_cancellation_evidence(
        self, client_order_id: str, *, cancellation_id: str, snapshot: PaperProductSnapshot | None = None
    ) -> PaperCancellationResult:
        """Persist definitive cancellation evidence only after a durable request exists."""
        with transaction(self._connection):
            order = self._order_row(client_order_id)
            if order["lifecycle_state"] in _TERMINAL_STATES:
                return PaperCancellationResult(CancellationDisposition.REJECTED_TERMINAL, None)
            request = self._connection.execute(
                """
                SELECT status FROM paper_cancellation_requests
                WHERE cancellation_id = ? AND client_order_id = ?
                """,
                (cancellation_id, client_order_id),
            ).fetchone()
            if request is None:
                raise ValueError("cancellation evidence requires a prior cancellation request")
            sequence = self._allocate_sequence()
            self._append_event(
                sequence=sequence,
                event_type="cancellation_observed",
                client_order_id=client_order_id,
                command_id=order["command_id"],
                payload_json=_canonical_json({"cancellation_id": cancellation_id}),
            )
            self._connection.execute(
                """
                UPDATE paper_orders
                SET lifecycle_state = 'CANCELLED', paper_event_sequence = ?
                WHERE client_order_id = ?
                """,
                (sequence, client_order_id),
            )
            if snapshot is not None:
                if (snapshot.account_id, snapshot.product, snapshot.scope) != (
                    order["account_id"], order["product"], order["symbol"]
                ):
                    raise ValueError("paper cancellation snapshot scope must match order")
                self._persist_snapshot(snapshot, sequence)
            self._connection.execute(
                """
                UPDATE paper_cancellation_requests
                SET status = 'CANCELLED', evidence_sequence = ?
                WHERE cancellation_id = ?
                """,
                (sequence, cancellation_id),
            )
        return PaperCancellationResult(CancellationDisposition.CANCELLED, sequence)

    def _persist_snapshot(self, snapshot: PaperProductSnapshot, sequence: int) -> PaperProductSnapshot:
        """Store one product projection under the event that established it."""
        snapshot_sequence = PaperProductSnapshot(
            account_id=snapshot.account_id,
            product=snapshot.product,
            scope=snapshot.scope,
            schema_version=snapshot.schema_version,
            payload=snapshot.payload,
            paper_event_sequence=sequence,
        )
        self._connection.execute(
            """
            INSERT INTO paper_product_snapshots(
                account_id, product, scope, schema_version, payload_json, paper_event_sequence
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, product, scope) DO UPDATE SET
                schema_version = excluded.schema_version,
                payload_json = excluded.payload_json,
                paper_event_sequence = excluded.paper_event_sequence
            """,
            (
                snapshot_sequence.account_id,
                snapshot_sequence.product,
                snapshot_sequence.scope,
                snapshot_sequence.schema_version,
                _canonical_json(dict(snapshot_sequence.payload)),
                sequence,
            ),
        )
        return snapshot_sequence

    def fetch_order(self, client_order_id: str) -> PaperOrder | None:
        row = self._connection.execute(
            """
            SELECT client_order_id, command_id, account_id, product, symbol, lifecycle_state,
                   filled_quantity, paper_event_sequence
            FROM paper_orders WHERE client_order_id = ?
            """,
            (client_order_id,),
        ).fetchone()
        return None if row is None else _paper_order_from_row(row)

    def fetch_order_by_command_id(self, command_id: str) -> PaperOrder | None:
        """Resolve a durable originating order for read-only liquidation evidence delivery."""
        row = self._connection.execute(
            """
            SELECT client_order_id, command_id, account_id, product, symbol, lifecycle_state,
                   filled_quantity, paper_event_sequence
            FROM paper_orders WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone()
        return None if row is None else _paper_order_from_row(row)

    def list_fills(self, command_id: str) -> tuple[PaperFill, ...]:
        rows = self._connection.execute(
            """
            SELECT paper_fill_id, command_id, quantity, provenance_json, paper_event_sequence
            FROM paper_fills WHERE command_id = ? ORDER BY paper_event_sequence, paper_fill_id
            """,
            (command_id,),
        ).fetchall()
        return tuple(
            PaperFill(
                paper_fill_id=row["paper_fill_id"],
                command_id=row["command_id"],
                quantity=decimal_from_canonical(row["quantity"]),
                provenance_json=row["provenance_json"],
                paper_event_sequence=row["paper_event_sequence"],
            )
            for row in rows
        )

    def list_liquidation_fills(self, *, account_id: str, symbol: str) -> tuple[PaperLiquidationFill, ...]:
        """Return durable USDT-perpetual forced closes in their committed event order."""
        rows = self._connection.execute(
            """
            SELECT paper_fill_id, account_id, symbol, origin_command_id, quantity, provenance_json,
                   paper_event_sequence
            FROM paper_liquidation_fills
            WHERE account_id = ? AND product = ? AND symbol = ?
            ORDER BY paper_event_sequence, paper_fill_id
            """,
            (account_id, ProductType.USDT_PERPETUAL.value, symbol),
        ).fetchall()
        return tuple(
            PaperLiquidationFill(
                paper_fill_id=row["paper_fill_id"],
                account_id=row["account_id"],
                symbol=row["symbol"],
                origin_command_id=row["origin_command_id"],
                quantity=decimal_from_canonical(row["quantity"]),
                provenance=json.loads(row["provenance_json"]),
                paper_event_sequence=row["paper_event_sequence"],
            )
            for row in rows
        )

    def list_open_orders(self, *, account_id: str, product: str) -> tuple[PaperOrder, ...]:
        rows = self._connection.execute(
            """
            SELECT client_order_id, command_id, account_id, product, symbol, lifecycle_state,
                   filled_quantity, paper_event_sequence
            FROM paper_orders
            WHERE account_id = ? AND product = ? AND lifecycle_state NOT IN ('FILLED', 'CANCELLED', 'REJECTED')
            ORDER BY client_order_id
            """,
            (account_id, product),
        ).fetchall()
        return tuple(_paper_order_from_row(row) for row in rows)

    def load_snapshot(self, *, account_id: str, product: str, scope: str) -> PaperProductSnapshot | None:
        row = self._connection.execute(
            """
            SELECT schema_version, payload_json, paper_event_sequence
            FROM paper_product_snapshots
            WHERE account_id = ? AND product = ? AND scope = ?
            """,
            (account_id, product, scope),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        if type(payload) is not dict:
            raise ValueError("stored paper snapshot payload is not an object")
        return PaperProductSnapshot(
            account_id=account_id,
            product=product,
            scope=scope,
            schema_version=row["schema_version"],
            payload=payload,
            paper_event_sequence=row["paper_event_sequence"],
        )
    def read_workspace_product_facts(
        self, *, account_id: str, product: ProductType
    ) -> PaperWorkspaceProductFacts:
        """Rebuild one product's canonical display facts from committed Paper state only."""
        if not account_id or type(product) is not ProductType:
            raise ValueError("workspace product reads require an exact account and product")
        snapshots = self._list_product_snapshots(account_id=account_id, product=product)
        fact_snapshots = snapshots
        if product is ProductType.SPOT and snapshots:
            fact_snapshots = (max(snapshots, key=lambda snapshot: snapshot.paper_event_sequence or 0),)
        balances: list[Balance] = []
        positions: list[Position] = []
        sequences: list[int] = []
        for snapshot in fact_snapshots:
            snapshot_balances, snapshot_positions = _workspace_snapshot_facts(snapshot, product)
            balances.extend(snapshot_balances)
            positions.extend(snapshot_positions)
            assert snapshot.paper_event_sequence is not None
            sequences.append(snapshot.paper_event_sequence)
        open_orders = self.list_open_orders(account_id=account_id, product=product.value)
        fills = self._list_product_fills(account_id=account_id, product=product.value)
        sequences.extend(
            sequence
            for sequence in (
                *(order.paper_event_sequence for order in open_orders),
                *(fill.paper_event_sequence for fill in fills),
            )
            if sequence is not None
        )
        source_sequence = max(sequences, default=None)
        return PaperWorkspaceProductFacts(
            account_id=account_id,
            product=product,
            balances=tuple(balances),
            positions=tuple(positions),
            open_orders=open_orders,
            fills=fills,
            source_sequence=source_sequence,
            last_successful_reconciled_at=(
                None if source_sequence is None else self._event_recorded_at(source_sequence)
            ),
        )

    def _list_product_snapshots(
        self, *, account_id: str, product: ProductType
    ) -> tuple[PaperProductSnapshot, ...]:
        rows = self._connection.execute(
            """
            SELECT scope, schema_version, payload_json, paper_event_sequence
            FROM paper_product_snapshots
            WHERE account_id = ? AND product = ?
            ORDER BY scope
            """,
            (account_id, product.value),
        ).fetchall()
        snapshots: list[PaperProductSnapshot] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            if type(payload) is not dict or type(row["paper_event_sequence"]) is not int:
                raise ValueError("stored paper workspace snapshot is invalid")
            snapshots.append(
                PaperProductSnapshot(
                    account_id=account_id,
                    product=product.value,
                    scope=row["scope"],
                    schema_version=row["schema_version"],
                    payload=payload,
                    paper_event_sequence=row["paper_event_sequence"],
                )
            )
        return tuple(snapshots)

    def _list_product_fills(
        self, *, account_id: str, product: str
    ) -> tuple[PaperWorkspaceFill, ...]:
        rows = self._connection.execute(
            """
            SELECT fills.paper_fill_id, fills.command_id, fills.quantity, fills.provenance_json,
                   fills.paper_event_sequence
            FROM paper_fills AS fills
            JOIN paper_orders AS orders ON orders.command_id = fills.command_id
            WHERE orders.account_id = ? AND orders.product = ?
            ORDER BY fills.paper_event_sequence, fills.paper_fill_id
            """,
            (account_id, product),
        ).fetchall()
        return tuple(
            PaperWorkspaceFill(
                paper_fill_id=row["paper_fill_id"],
                command_id=row["command_id"],
                quantity=decimal_from_canonical(row["quantity"]),
                paper_event_sequence=row["paper_event_sequence"],
            )
            for row in rows
        )

    def _event_recorded_at(self, sequence: int) -> datetime:
        row = self._connection.execute(
            "SELECT recorded_at_utc FROM paper_events WHERE sequence = ?", (sequence,)
        ).fetchone()
        if row is None or type(row["recorded_at_utc"]) is not str:
            raise ValueError("workspace fact sequence has no durable event")
        try:
            recorded_at = datetime.fromisoformat(row["recorded_at_utc"])
        except ValueError as exc:
            raise ValueError("workspace fact event timestamp is invalid") from exc
        if recorded_at.tzinfo is None:
            raise ValueError("workspace fact event timestamp must be timezone-aware")
        return recorded_at

    def commit_isolated_margin_product_evidence(
        self, evidence: IsolatedMarginProductEvidence
    ) -> None:
        """Commit one immutable exact-pair margin fact without creating an order."""
        if type(evidence) is not IsolatedMarginProductEvidence:
            raise TypeError("paper margin evidence must be canonical")
        self._commit_product_evidence(
            target=evidence.target,
            scope=evidence.isolated_symbol,
            evidence_type="isolated_margin_v1",
            observation_version=evidence.observation_version,
            observed_at=evidence.observed_at,
            digest=evidence.digest,
            payload=_isolated_margin_payload(evidence),
        )

    def commit_usdt_perpetual_product_evidence(
        self, evidence: UsdtPerpetualProductEvidence
    ) -> None:
        """Commit one immutable exact-symbol perpetual fact without creating an order."""
        if type(evidence) is not UsdtPerpetualProductEvidence:
            raise TypeError("paper perpetual evidence must be canonical")
        self._commit_product_evidence(
            target=evidence.target,
            scope=evidence.symbol,
            evidence_type="usdt_perpetual_v1",
            observation_version=evidence.observation_version,
            observed_at=evidence.observed_at,
            digest=evidence.digest,
            payload=_usdt_perpetual_payload(evidence),
        )

    def load_isolated_margin_product_evidence(
        self, target: ExecutionTarget, isolated_symbol: str
    ) -> IsolatedMarginProductEvidence | None:
        """Reconstruct only the latest committed exact-pair margin evidence."""
        row = self._load_product_evidence(target, isolated_symbol, "isolated_margin_v1")
        if row is None:
            return None
        evidence = _isolated_margin_from_payload(target, _load_evidence_payload(row))
        if (
            evidence.isolated_symbol != isolated_symbol
            or evidence.observation_version != row["observation_version"]
            or evidence.observed_at.isoformat() != row["observed_at_utc"]
            or evidence.digest != row["evidence_digest"]
        ):
            raise ValueError("stored isolated-margin evidence is contradictory")
        return evidence

    def load_usdt_perpetual_product_evidence(
        self, target: ExecutionTarget, symbol: str
    ) -> UsdtPerpetualProductEvidence | None:
        """Reconstruct only the latest committed exact-symbol perpetual evidence."""
        row = self._load_product_evidence(target, symbol, "usdt_perpetual_v1")
        if row is None:
            return None
        evidence = _usdt_perpetual_from_payload(target, _load_evidence_payload(row))
        if (
            evidence.symbol != symbol
            or evidence.observation_version != row["observation_version"]
            or evidence.observed_at.isoformat() != row["observed_at_utc"]
            or evidence.digest != row["evidence_digest"]
        ):
            raise ValueError("stored perpetual evidence is contradictory")
        return evidence

    def _persist_isolated_margin_product_evidence(
        self, evidence: IsolatedMarginProductEvidence, sequence: int
    ) -> None:
        """Write a margin evidence row under an already-open Paper event transaction."""
        if type(evidence) is not IsolatedMarginProductEvidence or sequence <= 0:
            raise TypeError("paper margin evidence requires canonical facts and an event sequence")
        identity = (
            evidence.target.target_id,
            evidence.target.account_id,
            evidence.target.product.value,
            evidence.isolated_symbol,
            "isolated_margin_v1",
        )
        latest = self._connection.execute(
            """
            SELECT observation_version, evidence_digest
            FROM paper_product_evidence
            WHERE target_id = ? AND account_id = ? AND product = ? AND scope = ? AND evidence_type = ?
            ORDER BY observation_version DESC LIMIT 1
            """,
            identity,
        ).fetchone()
        if latest is not None:
            if evidence.observation_version < latest["observation_version"]:
                raise ValueError("paper product evidence is stale")
            if evidence.observation_version == latest["observation_version"]:
                if evidence.digest == latest["evidence_digest"]:
                    return
                raise ValueError("paper product evidence version conflicts")
        self._connection.execute(
            """
            INSERT INTO paper_product_evidence(
                target_id, account_id, product, scope, evidence_type, observation_version,
                observed_at_utc, evidence_digest, payload_json, paper_event_sequence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                *identity,
                evidence.observation_version,
                evidence.observed_at.isoformat(),
                evidence.digest,
                _canonical_json(_isolated_margin_payload(evidence)),
                sequence,
            ),
        )

    def _persist_usdt_perpetual_product_evidence(
        self, evidence: UsdtPerpetualProductEvidence, sequence: int
    ) -> None:
        """Write a perpetual fact under the same Paper event transaction as its snapshot."""
        if type(evidence) is not UsdtPerpetualProductEvidence or sequence <= 0:
            raise TypeError("paper perpetual evidence requires canonical facts and an event sequence")
        identity = (
            evidence.target.target_id,
            evidence.target.account_id,
            evidence.target.product.value,
            evidence.symbol,
            "usdt_perpetual_v1",
        )
        latest = self._connection.execute(
            """
            SELECT observation_version, evidence_digest
            FROM paper_product_evidence
            WHERE target_id = ? AND account_id = ? AND product = ? AND scope = ? AND evidence_type = ?
            ORDER BY observation_version DESC LIMIT 1
            """,
            identity,
        ).fetchone()
        if latest is not None:
            if evidence.observation_version < latest["observation_version"]:
                raise ValueError("paper product evidence is stale")
            if evidence.observation_version == latest["observation_version"]:
                if evidence.digest == latest["evidence_digest"]:
                    return
                raise ValueError("paper product evidence version conflicts")
        self._connection.execute(
            """
            INSERT INTO paper_product_evidence(
                target_id, account_id, product, scope, evidence_type, observation_version,
                observed_at_utc, evidence_digest, payload_json, paper_event_sequence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                *identity,
                evidence.observation_version,
                evidence.observed_at.isoformat(),
                evidence.digest,
                _canonical_json(_usdt_perpetual_payload(evidence)),
                sequence,
            ),
        )

    def _commit_product_evidence(
        self,
        *,
        target: ExecutionTarget,
        scope: str,
        evidence_type: str,
        observation_version: int,
        observed_at: datetime,
        digest: str,
        payload: dict[str, object],
    ) -> None:
        if type(target) is not ExecutionTarget or not scope:
            raise ValueError("paper evidence requires exact target and scope")
        identity = (target.target_id, target.account_id, target.product.value, scope, evidence_type)
        with transaction(self._connection):
            latest = self._connection.execute(
                """
                SELECT observation_version, evidence_digest
                FROM paper_product_evidence
                WHERE target_id = ? AND account_id = ? AND product = ? AND scope = ? AND evidence_type = ?
                ORDER BY observation_version DESC LIMIT 1
                """,
                identity,
            ).fetchone()
            if latest is not None:
                if observation_version < latest["observation_version"]:
                    raise ValueError("paper product evidence is stale")
                if observation_version == latest["observation_version"]:
                    if digest == latest["evidence_digest"]:
                        return
                    raise ValueError("paper product evidence version conflicts")
            sequence = self._allocate_sequence()
            self._append_event(
                sequence=sequence,
                event_type=f"{evidence_type}_committed",
                client_order_id=None,
                command_id=None,
                payload_json=_canonical_json(payload),
            )
            self._connection.execute(
                """
                INSERT INTO paper_product_evidence(
                    target_id, account_id, product, scope, evidence_type, observation_version,
                    observed_at_utc, evidence_digest, payload_json, paper_event_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*identity, observation_version, observed_at.isoformat(), digest, _canonical_json(payload), sequence),
            )

    def _load_product_evidence(
        self, target: ExecutionTarget, scope: str, evidence_type: str
    ) -> sqlite3.Row | None:
        if type(target) is not ExecutionTarget or not scope:
            raise ValueError("paper evidence requires exact target and scope")
        return self._connection.execute(
            """
            SELECT observation_version, observed_at_utc, evidence_digest, payload_json
            FROM paper_product_evidence
            WHERE target_id = ? AND account_id = ? AND product = ? AND scope = ? AND evidence_type = ?
            ORDER BY observation_version DESC LIMIT 1
            """,
            (target.target_id, target.account_id, target.product.value, scope, evidence_type),
        ).fetchone()

    def list_events(self) -> tuple[PaperEvent, ...]:
        rows = self._connection.execute(
            """
            SELECT sequence, event_type, client_order_id, command_id, payload_json
            FROM paper_events ORDER BY sequence
            """
        ).fetchall()
        return tuple(
            PaperEvent(
                sequence=row["sequence"],
                event_type=row["event_type"],
                client_order_id=row["client_order_id"],
                command_id=row["command_id"],
                payload_json=row["payload_json"],
            )
            for row in rows
        )

    def list_incidents(self) -> tuple[PaperIncident, ...]:
        rows = self._connection.execute(
            "SELECT kind, detail_json FROM paper_incidents ORDER BY incident_id"
        ).fetchall()
        return tuple(PaperIncident(kind=row["kind"], detail_json=row["detail_json"]) for row in rows)

    def _assert_snapshot_scope(self, observation: MarketObservation, snapshot: PaperProductSnapshot) -> None:
        if (snapshot.account_id, snapshot.product, snapshot.scope) != (
            observation.account_id,
            observation.product.value,
            observation.symbol,
        ):
            raise ValueError("paper snapshot scope must match its observation")

    def _classify_cursor(self, cursor: sqlite3.Row, observation: MarketObservation) -> ObservationDisposition:
        version = cursor["observation_version"]
        if observation.version > version:
            return ObservationDisposition.ACCEPTED
        if observation.version < version:
            return ObservationDisposition.REJECTED_OUT_OF_ORDER
        if (
            observation.observation_id == cursor["observation_id"]
            and observation.digest == cursor["observation_digest"]
        ):
            return ObservationDisposition.IDEMPOTENT
        return ObservationDisposition.REJECTED_CONFLICT

    def _assert_candidates_mutable(self, candidates: tuple[PaperFillCandidate, ...]) -> None:
        for candidate in candidates:
            row = self._connection.execute(
                "SELECT lifecycle_state FROM paper_orders WHERE command_id = ?", (candidate.command_id,)
            ).fetchone()
            if row is None:
                raise ValueError("paper fill candidate has no durable order")
            if row["lifecycle_state"] in _TERMINAL_STATES:
                raise ValueError("terminal paper order cannot accept a fill candidate")

    def _persist_fill(self, candidate: PaperFillCandidate, sequence: int) -> None:
        order = self._connection.execute(
            "SELECT quantity, filled_quantity FROM paper_orders WHERE command_id = ?", (candidate.command_id,)
        ).fetchone()
        assert order is not None
        prior = decimal_from_canonical(order["filled_quantity"])
        total = prior + candidate.quantity
        requested = decimal_from_canonical(order["quantity"])
        if total > requested:
            raise ValueError("paper fill candidates exceed durable order quantity")
        lifecycle_state = "FILLED" if total == requested else "PARTIALLY_FILLED"
        self._connection.execute(
            """
            INSERT INTO paper_fills(paper_fill_id, command_id, quantity, provenance_json, paper_event_sequence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                candidate.paper_fill_id,
                candidate.command_id,
                decimal_to_canonical(candidate.quantity),
                _canonical_json(candidate.provenance.to_canonical_dict()),
                sequence,
            ),
        )
        self._connection.execute(
            """
            UPDATE paper_orders
            SET lifecycle_state = ?, filled_quantity = ?, paper_event_sequence = ?
            WHERE command_id = ?
            """,
            (lifecycle_state, decimal_to_canonical(total), sequence, candidate.command_id),
        )

    def _persist_liquidation_fill(self, candidate: PaperLiquidationCandidate, sequence: int) -> None:
        """Persist exact forced-close provenance only after its liquidation event exists."""
        if sequence <= 0:
            raise ValueError("paper liquidation requires a durable event sequence")
        self._connection.execute(
            """
            INSERT INTO paper_liquidation_fills(
                paper_fill_id, account_id, product, symbol, origin_command_id, quantity,
                provenance_json, paper_event_sequence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.paper_fill_id,
                candidate.account_id,
                ProductType.USDT_PERPETUAL.value,
                candidate.symbol,
                candidate.origin_command_id,
                decimal_to_canonical(candidate.quantity),
                _canonical_json(dict(candidate.provenance)),
                sequence,
            ),
        )

    def _order_row(self, client_order_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            """
            SELECT client_order_id, command_id, account_id, product, symbol, lifecycle_state
            FROM paper_orders WHERE client_order_id = ?
            """,
            (client_order_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown paper client order ID {client_order_id}")
        return row

    def _allocate_sequence(self) -> int:
        row = self._connection.execute(
            "SELECT value FROM paper_metadata WHERE key = 'next_event_sequence'"
        ).fetchone()
        if row is None:
            raise RuntimeError("paper sequence metadata is missing")
        sequence = int(row["value"]) + 1
        self._connection.execute(
            "UPDATE paper_metadata SET value = ? WHERE key = 'next_event_sequence'",
            (str(sequence),),
        )
        return sequence

    def _append_event(
        self,
        *,
        sequence: int,
        event_type: str,
        client_order_id: str | None,
        command_id: str | None,
        payload_json: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO paper_events(sequence, event_type, client_order_id, command_id, payload_json, recorded_at_utc)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sequence, event_type, client_order_id, command_id, payload_json, _utc_now_text()),
        )

    def _record_incident(self, *, kind: str, scope: tuple[str, str, str], detail: dict[str, object]) -> None:
        self._connection.execute(
            """
            INSERT INTO paper_incidents(kind, account_id, product, symbol, detail_json, recorded_at_utc)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (kind, *scope, _canonical_json(detail), _utc_now_text()),
        )


def _isolated_margin_payload(evidence: IsolatedMarginProductEvidence) -> dict[str, object]:
    return {
        "isolated_symbol": evidence.isolated_symbol,
        "collateral": decimal_to_canonical(evidence.collateral),
        "available_collateral": decimal_to_canonical(evidence.available_collateral),
        "debt_principal": decimal_to_canonical(evidence.debt_principal),
        "accrued_interest": decimal_to_canonical(evidence.accrued_interest),
        "margin_health": decimal_to_canonical(evidence.margin_health),
        "borrow_available": decimal_to_canonical(evidence.borrow_available),
        "repayment_required": evidence.repayment_required,
        "observed_at": evidence.observed_at.isoformat(),
        "observation_version": evidence.observation_version,
    }


def _usdt_perpetual_payload(evidence: UsdtPerpetualProductEvidence) -> dict[str, object]:
    return {
        "symbol": evidence.symbol,
        "isolated_margin_confirmed": evidence.isolated_margin_confirmed,
        "one_way_position_confirmed": evidence.one_way_position_confirmed,
        "maximum_leverage": decimal_to_canonical(evidence.maximum_leverage),
        "available_margin": decimal_to_canonical(evidence.available_margin),
        "initial_margin": decimal_to_canonical(evidence.initial_margin),
        "maintenance_margin": decimal_to_canonical(evidence.maintenance_margin),
        "mark_price": decimal_to_canonical(evidence.mark_price),
        "position_quantity": decimal_to_canonical(evidence.position_quantity),
        "observed_at": evidence.observed_at.isoformat(),
        "observation_version": evidence.observation_version,
    }


def _load_evidence_payload(row: sqlite3.Row) -> dict[str, object]:
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored paper product evidence payload is invalid") from exc
    if type(payload) is not dict:
        raise ValueError("stored paper product evidence payload is not an object")
    return payload


def _isolated_margin_from_payload(
    target: ExecutionTarget, payload: dict[str, object]
) -> IsolatedMarginProductEvidence:
    _require_payload_fields(
        payload,
        frozenset(
            {
                "isolated_symbol", "collateral", "available_collateral", "debt_principal",
                "accrued_interest", "margin_health", "borrow_available", "repayment_required",
                "observed_at", "observation_version",
            }
        ),
    )
    return IsolatedMarginProductEvidence(
        target=target,
        isolated_symbol=_payload_string(payload, "isolated_symbol"),
        collateral=_payload_decimal(payload, "collateral"),
        available_collateral=_payload_decimal(payload, "available_collateral"),
        debt_principal=_payload_decimal(payload, "debt_principal"),
        accrued_interest=_payload_decimal(payload, "accrued_interest"),
        margin_health=_payload_decimal(payload, "margin_health"),
        borrow_available=_payload_decimal(payload, "borrow_available"),
        repayment_required=_payload_bool(payload, "repayment_required"),
        observed_at=_payload_datetime(payload, "observed_at"),
        observation_version=_payload_version(payload),
    )


def _usdt_perpetual_from_payload(
    target: ExecutionTarget, payload: dict[str, object]
) -> UsdtPerpetualProductEvidence:
    _require_payload_fields(
        payload,
        frozenset(
            {
                "symbol", "isolated_margin_confirmed", "one_way_position_confirmed",
                "maximum_leverage", "available_margin", "initial_margin", "maintenance_margin",
                "mark_price", "position_quantity", "observed_at", "observation_version",
            }
        ),
    )
    return UsdtPerpetualProductEvidence(
        target=target,
        symbol=_payload_string(payload, "symbol"),
        isolated_margin_confirmed=_payload_bool(payload, "isolated_margin_confirmed"),
        one_way_position_confirmed=_payload_bool(payload, "one_way_position_confirmed"),
        maximum_leverage=_payload_decimal(payload, "maximum_leverage"),
        available_margin=_payload_decimal(payload, "available_margin"),
        initial_margin=_payload_decimal(payload, "initial_margin"),
        maintenance_margin=_payload_decimal(payload, "maintenance_margin"),
        mark_price=_payload_decimal(payload, "mark_price"),
        position_quantity=_payload_decimal(payload, "position_quantity"),
        observed_at=_payload_datetime(payload, "observed_at"),
        observation_version=_payload_version(payload),
    )


def _require_payload_fields(payload: dict[str, object], fields: frozenset[str]) -> None:
    if frozenset(payload) != fields:
        raise ValueError("stored paper product evidence fields are invalid")


def _workspace_snapshot_facts(
    snapshot: PaperProductSnapshot, product: ProductType
) -> tuple[tuple[Balance, ...], tuple[Position, ...]]:
    """Translate a versioned durable snapshot into display-safe canonical values."""
    if snapshot.product != product.value or snapshot.paper_event_sequence is None:
        raise ValueError("workspace snapshot product or durable sequence is invalid")
    if product is ProductType.SPOT:
        if snapshot.schema_version != "paper-spot-snapshot-v1":
            raise ValueError("unsupported Paper Spot workspace snapshot version")
        accounting = PaperSpotAccounting.from_snapshot_payload(snapshot.payload)
        return (
            tuple(
                Balance(asset=asset, total=value.total, available=value.available, reserved=value.reserved)
                for asset, value in sorted(accounting._balances.items())  # noqa: SLF001 - validated immutable accounting
            ),
            (),
        )
    if product is ProductType.ISOLATED_MARGIN:
        if snapshot.schema_version != "paper-isolated-margin-snapshot-v1":
            raise ValueError("unsupported Paper isolated-margin workspace snapshot version")
        accounting = PaperMarginAccounting.from_snapshot_payload(snapshot.payload)
        if accounting.isolated_symbol != snapshot.scope:
            raise ValueError("Paper isolated-margin workspace snapshot scope is contradictory")
        return (
            (
                Balance(
                    asset=accounting.borrow_asset,
                    total=accounting.collateral,
                    available=accounting.available_collateral,
                    reserved=accounting.collateral - accounting.available_collateral,
                ),
            ),
            (),
        )
    if snapshot.schema_version != "paper-usdt-perpetual-snapshot-v1":
        raise ValueError("unsupported Paper USDT-perpetual workspace snapshot version")
    accounting = PaperPerpetualAccounting.from_snapshot_payload(snapshot.payload)
    if accounting.symbol != snapshot.scope:
        raise ValueError("Paper USDT-perpetual workspace snapshot scope is contradictory")
    positions = ()
    if accounting.quantity != 0:
        positions = (
            Position(
                symbol=accounting.symbol,
                quantity=accounting.quantity,
                entry_price=accounting.entry_price,
                mark_price=accounting.entry_price,
                unrealized_pnl=accounting.unrealized_pnl,
                margin=accounting.isolated_margin,
            ),
        )
    return (
        (
            Balance(
                asset="USDT",
                total=accounting.available_usdt + accounting.isolated_margin,
                available=accounting.available_usdt,
                reserved=accounting.isolated_margin,
            ),
        ),
        positions,
    )


def _payload_string(payload: dict[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str) or not value:
        raise ValueError("stored paper product evidence string is invalid")
    return value


def _payload_decimal(payload: dict[str, object], name: str) -> Decimal:
    raw = _payload_string(payload, name)
    value = decimal_from_canonical(raw)
    if decimal_to_canonical(value) != raw:
        raise ValueError("stored paper product evidence Decimal is noncanonical")
    return value


def _payload_bool(payload: dict[str, object], name: str) -> bool:
    value = payload[name]
    if type(value) is not bool:
        raise ValueError("stored paper product evidence boolean is invalid")
    return value


def _payload_datetime(payload: dict[str, object], name: str) -> datetime:
    raw = _payload_string(payload, name)
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("stored paper product evidence timestamp is invalid") from exc


def _payload_version(payload: dict[str, object]) -> int:
    value = payload["observation_version"]
    if type(value) is not int or value <= 0:
        raise ValueError("stored paper product evidence version is invalid")
    return value


def _paper_order_from_row(row: sqlite3.Row) -> PaperOrder:
    return PaperOrder(
        client_order_id=row["client_order_id"],
        command_id=row["command_id"],
        account_id=row["account_id"],
        product=row["product"],
        symbol=row["symbol"],
        lifecycle_state=row["lifecycle_state"],
        filled_quantity=decimal_from_canonical(row["filled_quantity"]),
        paper_event_sequence=row["paper_event_sequence"],
    )


def _canonical_json(value: object) -> str:
    """Encode durable payloads deterministically and reject binary float inputs."""
    _reject_floats(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _reject_floats(value: object) -> None:
    if isinstance(value, float):
        raise ValueError("paper SQLite payloads cannot contain binary floats")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_floats(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _reject_floats(item)


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


def _command_from_canonical_json(payload: str) -> ExecutionCommand:
    """Reconstruct only the canonical command saved by the PaperStore itself."""
    try:
        raw = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored paper command payload is invalid") from exc
    if type(raw) is not dict or type(raw.get("context")) is not dict:
        raise ValueError("stored paper command payload has no canonical context")
    try:
        return ExecutionCommand(
            command_id=_payload_string(raw, "command_id"),
            logical_command_key=_payload_string(raw, "logical_command_key"),
            client_order_id=_payload_string(raw, "client_order_id"),
            mode=Mode(_payload_string(raw, "mode")),
            account_id=_payload_string(raw, "account_id"),
            symbol=_payload_string(raw, "symbol"),
            side=Side(_payload_string(raw, "side")),
            order_type=OrderType(_payload_string(raw, "order_type")),
            quantity=_payload_decimal(raw, "quantity"),
            price=None if raw.get("price") is None else _payload_decimal(raw, "price"),
            context=product_context_from_canonical_payload(_canonical_json(raw["context"])),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("stored paper command payload is contradictory") from exc


def _observation_from_canonical_json(payload: str) -> MarketObservation:
    """Rebuild a stored explicit market fact without inventing a clock or quote."""
    try:
        raw = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored paper observation payload is invalid") from exc
    if type(raw) is not dict:
        raise ValueError("stored paper observation payload is invalid")
    try:
        return MarketObservation(
            observation_id=_payload_string(raw, "observation_id"),
            account_id=_payload_string(raw, "account_id"),
            product=ProductType(_payload_string(raw, "product")),
            symbol=_payload_string(raw, "symbol"),
            version=_observation_version(raw),
            observed_at=_payload_datetime(raw, "observed_at"),
            asks=_depth_levels(raw, "asks"),
            bids=_depth_levels(raw, "bids"),
            mark_price=None if raw.get("mark_price") is None else _payload_decimal(raw, "mark_price"),
            funding_rate=(Decimal("0") if "funding_rate" not in raw else _payload_decimal(raw, "funding_rate")),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("stored paper observation payload is contradictory") from exc



def _observation_version(payload: dict[str, object]) -> int:
    value = payload.get("version")
    if type(value) is not int or value <= 0:
        raise ValueError("stored paper observation version is invalid")
    return value
def _depth_levels(payload: dict[str, object], name: str) -> tuple[DepthLevel, ...]:
    raw_levels = payload.get(name)
    if type(raw_levels) is not list:
        raise ValueError("stored paper observation depth is invalid")
    levels: list[DepthLevel] = []
    for raw in raw_levels:
        if type(raw) is not dict:
            raise ValueError("stored paper observation depth is invalid")
        levels.append(DepthLevel(price=_payload_decimal(raw, "price"), quantity=_payload_decimal(raw, "quantity")))
    return tuple(levels)
