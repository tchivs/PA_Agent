"""Transactional SQLite implementation of the durable execution-ledger port."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pa_agent.trading.domain.errors import LifecycleTransitionError, ReconciliationEvidenceError
from pa_agent.trading.domain.lifecycle import assert_transition
from pa_agent.trading.domain.models import (
    ExecutionCommand,
    Fill,
    GatewayEvidence,
    LifecycleEvent,
    OrderState,
    canonicalize,
    decimal_to_canonical,
)
from pa_agent.trading.persistence.migrations import run_migrations
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerStorageError,
    open_sqlite_connection,
    transaction,
)
from pa_agent.trading.ports.clock import UtcClock
from pa_agent.trading.ports.ledger import (
    ExecutionLedger,
    ReconciliationJob,
    ReconciliationResult,
    SubmissionAdmission,
)


class SQLiteExecutionLedger(ExecutionLedger):
    """Durably admit exactly one unresolved command submission per logical key.

    This repository persists the command, lifecycle event, projection,
    reconciliation job, and submission claim in one SQLite transaction before a
    future gateway can cause a remote side effect. It owns no gateway transport.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        clock: UtcClock | None = None,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._connection: sqlite3.Connection | None = open_sqlite_connection(database_path)
        self._clock = clock
        self._failure_injector = failure_injector
        try:
            run_migrations(self._connection)
        except Exception:
            self._connection.close()
            raise

    def close(self) -> None:
        """Close the thread-confined SQLite connection deterministically."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def utc_now(self) -> datetime:
        """Return the injected or system UTC time used for durable timestamps."""
        if self._clock is not None:
            return self._clock.utc_now()
        return datetime.now(UTC)

    def create_or_load_and_claim_submission(self, command: ExecutionCommand) -> SubmissionAdmission:
        """Atomically create the first command records or reload a non-admissible repeat."""
        connection = self._require_connection()
        with transaction(connection):
            existing = self._load_admission(command.logical_command_key)
            if existing is not None:
                return existing

            command_json = _canonical_json(command.to_canonical_dict())
            now = _timestamp_text(self.utc_now())
            submitting = assert_transition(OrderState.PROPOSED, LifecycleEvent.SUBMIT_REQUESTED)
            job_id = _new_id("reconciliation")
            claim_token = _new_id("claim-token")
            claim_id = _new_id("claim")

            connection.execute(
                """
                INSERT INTO order_commands(
                    command_id, logical_command_key, client_order_id, command_json,
                    mode, product, account_id, symbol, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command.command_id,
                    command.logical_command_key,
                    command.client_order_id,
                    command_json,
                    command.mode.value,
                    command.context.product.value,
                    command.account_id,
                    command.symbol,
                    now,
                ),
            )
            self._append_event(
                command_id=command.command_id,
                previous_state=OrderState.PROPOSED,
                new_state=submitting,
                event=LifecycleEvent.SUBMIT_REQUESTED,
                occurred_at=now,
                detail={"source": "local"},
            )
            connection.execute(
                """
                INSERT INTO orders(
                    command_id, exchange_order_id, lifecycle_state, filled_quantity, filled_notional,
                    evidence_cursor
                ) VALUES (?, NULL, ?, ?, ?, NULL)
                """,
                (command.command_id, submitting.value, "0", "0"),
            )
            connection.execute(
                """
                INSERT INTO reconciliation_jobs(
                    job_id, command_id, reason, status, attempt_count, next_action_at_utc
                ) VALUES (?, ?, ?, ?, 0, ?)
                """,
                (job_id, command.command_id, "submission_pending", "queued", now),
            )
            self._inject_failure("before_claim")
            connection.execute(
                """
                INSERT INTO submission_claims(claim_id, command_id, claim_token, admitted_at_utc, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (claim_id, command.command_id, claim_token, now, "admitted"),
            )
            return SubmissionAdmission(
                command_id=command.command_id,
                client_order_id=command.client_order_id,
                reconciliation_job_id=job_id,
                lifecycle_state=submitting,
                is_admissible=True,
                claim_token=claim_token,
            )
    def assert_submission_claim_is_live(self, admission: SubmissionAdmission) -> None:
        """Fail closed when a durable admission claim is absent, stale, or consumed."""
        if not admission.is_admissible or admission.claim_token is None:
            raise LedgerStorageError("submission admission has no active claim")
        row = self._require_connection().execute(
            """
            SELECT orders.lifecycle_state, claims.claim_token, claims.status
            FROM orders
            JOIN submission_claims AS claims ON claims.command_id = orders.command_id
            WHERE orders.command_id = ?
            """,
            (admission.command_id,),
        ).fetchone()
        if (
            row is None
            or row[0] != OrderState.SUBMITTING.value
            or row[1] != admission.claim_token
            or row[2] != "admitted"
        ):
            raise LedgerStorageError("submission claim is no longer live")

    def mark_submission_ambiguous(
        self,
        admission: SubmissionAdmission,
        *,
        event: LifecycleEvent = LifecycleEvent.LOCAL_TIMEOUT,
    ) -> None:
        """Persist a local interruption without allocating replacement identities."""
        if event not in {
            LifecycleEvent.LOCAL_TIMEOUT,
            LifecycleEvent.LOCAL_CANCELLATION,
            LifecycleEvent.STREAM_GAP,
            LifecycleEvent.MALFORMED_ACKNOWLEDGEMENT,
        }:
            raise ValueError("submission ambiguity requires a local interruption event")
        connection = self._require_connection()
        with transaction(connection):
            row = connection.execute(
                """
                SELECT commands.client_order_id, orders.lifecycle_state, jobs.job_id,
                       claims.claim_token, claims.status
                FROM order_commands AS commands
                JOIN orders ON orders.command_id = commands.command_id
                JOIN reconciliation_jobs AS jobs ON jobs.command_id = commands.command_id
                JOIN submission_claims AS claims ON claims.command_id = commands.command_id
                WHERE commands.command_id = ?
                """,
                (admission.command_id,),
            ).fetchone()
            if row is None or row[0] != admission.client_order_id or row[2] != admission.reconciliation_job_id:
                raise LedgerStorageError("submission admission does not match durable ledger identities")
            if not admission.is_admissible or admission.claim_token is None or row[3] != admission.claim_token:
                raise LedgerStorageError("submission admission does not match a durable claim")
            previous_state = OrderState(row[1])
            if previous_state is OrderState.SUBMISSION_UNKNOWN:
                if row[4] not in {"admitted", "consumed"}:
                    raise LedgerStorageError("ambiguous submission has an invalid durable claim status")
                connection.execute(
                    """
                    UPDATE submission_claims SET status = ?
                    WHERE command_id = ? AND claim_token = ? AND status = ?
                    """,
                    ("consumed", admission.command_id, admission.claim_token, "admitted"),
                )
                return
            if row[4] != "admitted":
                raise LedgerStorageError("submission claim is no longer live")
            next_state = assert_transition(previous_state, event)
            now = _timestamp_text(self.utc_now())
            self._append_event(
                command_id=admission.command_id,
                previous_state=previous_state,
                new_state=next_state,
                event=event,
                occurred_at=now,
                detail={"source": "local", "reason": event.value},
            )
            connection.execute(
                "UPDATE orders SET lifecycle_state = ? WHERE command_id = ?",
                (next_state.value, admission.command_id),
            )
            connection.execute(
                """
                UPDATE reconciliation_jobs
                SET reason = ?, status = ?, next_action_at_utc = ?
                WHERE job_id = ?
                """,
                (event.value, "queued", now, admission.reconciliation_job_id),
            )
            consumed = connection.execute(
                """
                UPDATE submission_claims SET status = ?
                WHERE command_id = ? AND claim_token = ? AND status = ?
                """,
                ("consumed", admission.command_id, admission.claim_token, "admitted"),
            )
            if consumed.rowcount != 1:
                raise LedgerStorageError("submission claim could not be consumed")

    def list_unresolved_reconciliation_jobs(self) -> tuple[ReconciliationJob, ...]:
        """Load queued non-terminal work using the first persisted identities."""
        rows = self._require_connection().execute(
            """
            SELECT commands.command_id, commands.client_order_id, jobs.job_id, orders.lifecycle_state
            FROM reconciliation_jobs AS jobs
            JOIN order_commands AS commands ON commands.command_id = jobs.command_id
            JOIN orders ON orders.command_id = commands.command_id
            WHERE jobs.status = ?
              AND orders.lifecycle_state NOT IN (?, ?, ?)
            ORDER BY jobs.next_action_at_utc, jobs.job_id
            """,
            (
                "queued",
                OrderState.FILLED.value,
                OrderState.CANCELLED.value,
                OrderState.REJECTED.value,
            ),
        ).fetchall()
        try:
            return tuple(
                ReconciliationJob(
                    command_id=row[0],
                    client_order_id=row[1],
                    reconciliation_job_id=row[2],
                    lifecycle_state=OrderState(row[3]),
                )
                for row in rows
            )
        except ValueError as exc:
            raise LedgerStorageError("stored recovery job lifecycle state is invalid") from exc

    def apply_reconciliation_evidence(
        self, job: ReconciliationJob, evidence: GatewayEvidence
    ) -> ReconciliationResult:
        """Append legal canonical evidence while retaining conflicts as incidents."""
        connection = self._require_connection()
        with transaction(connection):
            row = connection.execute(
                """
                SELECT commands.client_order_id, jobs.job_id, orders.lifecycle_state, orders.evidence_cursor,
                       orders.exchange_order_id
                FROM order_commands AS commands
                JOIN reconciliation_jobs AS jobs ON jobs.command_id = commands.command_id
                JOIN orders ON orders.command_id = commands.command_id
                WHERE commands.command_id = ?
                """,
                (job.command_id,),
            ).fetchone()
            if row is None or row[0] != job.client_order_id or row[1] != job.reconciliation_job_id:
                raise LedgerStorageError("reconciliation job does not match durable ledger identities")
            current_state = OrderState(row[2])
            if evidence.client_order_id != job.client_order_id:
                self._record_incident(
                    command_id=job.command_id,
                    kind="contradictory_client_order_evidence",
                    detail={"expected_client_order_id": job.client_order_id, "evidence": canonicalize(evidence)},
                )
                return ReconciliationResult(current_state, evidence_applied=False)
            if (
                row[4] is not None
                and evidence.exchange_order_id is not None
                and row[4] != evidence.exchange_order_id
            ):
                self._record_incident(
                    command_id=job.command_id,
                    kind="contradictory_exchange_order_evidence",
                    detail={
                        "persisted_exchange_order_id": row[4],
                        "observed_exchange_order_id": evidence.exchange_order_id,
                        "evidence": canonicalize(evidence),
                    },
                )
                return ReconciliationResult(current_state, evidence_applied=False)
            if row[3] == evidence.evidence_id:
                return ReconciliationResult(current_state, evidence_applied=True)
            try:
                event = _lifecycle_event_for_evidence(evidence)
                next_state = assert_transition(current_state, event, evidence=evidence)
            except (LifecycleTransitionError, ReconciliationEvidenceError):
                self._record_incident(
                    command_id=job.command_id,
                    kind="out_of_order_reconciliation_evidence",
                    detail={"evidence": canonicalize(evidence), "current_state": current_state.value},
                )
                return ReconciliationResult(current_state, evidence_applied=False)
            self._append_event(
                command_id=job.command_id,
                previous_state=current_state,
                new_state=next_state,
                event=event,
                occurred_at=_timestamp_text(evidence.observed_at),
                detail={"source": "reconciliation", "evidence": canonicalize(evidence)},
                evidence=evidence,
            )
            connection.execute(
                """
                UPDATE orders
                SET exchange_order_id = COALESCE(?, exchange_order_id),
                    lifecycle_state = ?, evidence_cursor = ?
                WHERE command_id = ?
                """,
                (evidence.exchange_order_id, next_state.value, evidence.evidence_id, job.command_id),
            )
            terminal = next_state in {
                OrderState.FILLED,
                OrderState.CANCELLED,
                OrderState.REJECTED,
            }
            connection.execute(
                """
                UPDATE reconciliation_jobs
                SET reason = ?, status = ?, attempt_count = attempt_count + 1, next_action_at_utc = ?
                WHERE job_id = ?
                """,
                (
                    "terminal_evidence" if terminal else "reconciliation_required",
                    "completed" if terminal else "queued",
                    _timestamp_text(self.utc_now()),
                    job.reconciliation_job_id,
                ),
            )
            return ReconciliationResult(next_state, evidence_applied=True)

    def record_fill_evidence(self, fill: Fill) -> bool:
        """Persist idempotent fill evidence or record a conflicting-evidence incident.

        Returns ``True`` when the fill is new or exactly repeats prior evidence;
        returns ``False`` when an existing fill ID has contradictory canonical
        values. Contradictions never overwrite the original fill history.
        """
        connection = self._require_connection()
        values = (
            decimal_to_canonical(fill.quantity),
            decimal_to_canonical(fill.price),
            decimal_to_canonical(fill.fee),
            fill.fee_asset,
            _timestamp_text(fill.observed_at),
        )
        with transaction(connection):
            existing = connection.execute(
                """
                SELECT command_id, quantity, price, fee, fee_asset, observed_at_utc
                FROM fills WHERE fill_id = ?
                """,
                (fill.fill_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO fills(
                        fill_id, command_id, venue_fill_id, quantity, price, fee, fee_asset, observed_at_utc
                    ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
                    """,
                    (fill.fill_id, fill.command_id, *values),
                )
                return True
            if tuple(existing) == (fill.command_id, *values):
                return True
            self._record_incident(
                command_id=fill.command_id,
                kind="contradictory_fill_evidence",
                detail={"fill_id": fill.fill_id, "observed": canonicalize(fill)},
            )
            return False

    def record_account_observation(
        self,
        *,
        account_id: str,
        product: str,
        source: str,
        payload: Mapping[str, Any],
    ) -> str:
        """Persist a sanitized canonical observation for later reconciliation queries."""
        if not all((account_id, product, source)):
            raise ValueError("account observation requires account, product, and source")
        payload_json = _canonical_json(canonicalize(dict(payload)))
        observation_id = _new_id("observation")
        with transaction(self._require_connection()):
            self._require_connection().execute(
                """
                INSERT INTO account_observations(
                    observation_id, account_id, product, observed_at_utc, source, payload_json, payload_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    account_id,
                    product,
                    _timestamp_text(self.utc_now()),
                    source,
                    payload_json,
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                ),
            )
        return observation_id

    def _load_admission(self, logical_command_key: str) -> SubmissionAdmission | None:
        """Load persisted identities for a repeat without allocating any new authority."""
        row = self._require_connection().execute(
            """
            SELECT commands.command_id, commands.client_order_id, jobs.job_id, orders.lifecycle_state
            FROM order_commands AS commands
            JOIN orders ON orders.command_id = commands.command_id
            JOIN reconciliation_jobs AS jobs ON jobs.command_id = commands.command_id
            WHERE commands.logical_command_key = ?
            """,
            (logical_command_key,),
        ).fetchone()
        if row is None:
            return None
        try:
            state = OrderState(row[3])
        except ValueError as exc:
            raise LedgerStorageError("stored order lifecycle state is invalid") from exc
        if state in {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}:
            raise LedgerStorageError("stored command is terminal and cannot receive admission")
        return SubmissionAdmission(
            command_id=row[0],
            client_order_id=row[1],
            reconciliation_job_id=row[2],
            lifecycle_state=state,
            is_admissible=False,
            claim_token=None,
        )

    def _append_event(
        self,
        *,
        command_id: str,
        previous_state: OrderState,
        new_state: OrderState,
        event: LifecycleEvent,
        occurred_at: str,
        detail: Mapping[str, Any],
        evidence: GatewayEvidence | None = None,
    ) -> None:
        """Append one sequence-checked lifecycle event inside the active transaction."""
        expected = assert_transition(previous_state, event, evidence=evidence)
        if expected is not new_state:
            raise LedgerStorageError("event projection does not match lifecycle transition")
        sequence = self._require_connection().execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM order_events WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0]
        self._require_connection().execute(
            """
            INSERT INTO order_events(
                event_id, command_id, sequence, previous_state, new_state, event_type, observed_at_utc, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("event"),
                command_id,
                sequence,
                previous_state.value,
                new_state.value,
                event.value,
                occurred_at,
                _canonical_json(dict(detail)),
            ),
        )

    def _record_incident(self, *, command_id: str, kind: str, detail: Mapping[str, Any]) -> None:
        """Append a sanitized reconciliation incident without rewriting evidence history."""
        self._require_connection().execute(
            """
            INSERT INTO reconciliation_incidents(
                incident_id, command_id, kind, detail_json, observed_at_utc
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                _new_id("incident"),
                command_id,
                kind,
                _canonical_json(canonicalize(dict(detail))),
                _timestamp_text(self.utc_now()),
            ),
        )

    def _inject_failure(self, stage: str) -> None:
        """Invoke deterministic integration fault injection inside the active transaction."""
        if self._failure_injector is not None:
            self._failure_injector(stage)

    def _require_connection(self) -> sqlite3.Connection:
        """Return the open connection or reject post-close ledger use."""
        if self._connection is None:
            raise LedgerStorageError("execution ledger is closed")
        return self._connection



def _lifecycle_event_for_evidence(evidence: GatewayEvidence) -> LifecycleEvent:
    """Map a normalized external state to the sole corresponding lifecycle event."""
    events = {
        OrderState.ACKNOWLEDGED: LifecycleEvent.ACKNOWLEDGEMENT_OBSERVED,
        OrderState.OPEN: LifecycleEvent.OPEN_OBSERVED,
        OrderState.PARTIALLY_FILLED: LifecycleEvent.PARTIAL_FILL_OBSERVED,
        OrderState.FILLED: LifecycleEvent.FILL_OBSERVED,
        OrderState.REJECTED: LifecycleEvent.REJECTION_OBSERVED,
        OrderState.CANCELLED: LifecycleEvent.CANCELLATION_OBSERVED,
    }
    try:
        return events[evidence.state]
    except KeyError as exc:
        raise ReconciliationEvidenceError(
            f"evidence state {evidence.state.value} is not a remote lifecycle observation"
        ) from exc
def _canonical_json(value: Any) -> str:
    """Serialize canonical values deterministically for durable comparison and auditing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _new_id(prefix: str) -> str:
    """Generate an opaque durable local identity without venue semantics."""
    return f"{prefix}-{uuid4().hex}"


def _timestamp_text(value: datetime) -> str:
    """Require explicit timezone-aware timestamps before durable persistence."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ledger timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()
