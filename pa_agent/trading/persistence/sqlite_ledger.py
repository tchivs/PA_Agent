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

from pa_agent.trading.domain.lifecycle import assert_transition
from pa_agent.trading.domain.models import (
    ExecutionCommand,
    Fill,
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
from pa_agent.trading.ports.ledger import ExecutionLedger, SubmissionAdmission


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

    def mark_submission_ambiguous(self, admission: SubmissionAdmission) -> None:
        """Persist an unresolved lifecycle transition without allocating replacement identities."""
        connection = self._require_connection()
        with transaction(connection):
            row = connection.execute(
                """
                SELECT commands.client_order_id, orders.lifecycle_state, jobs.job_id
                FROM order_commands AS commands
                JOIN orders ON orders.command_id = commands.command_id
                JOIN reconciliation_jobs AS jobs ON jobs.command_id = commands.command_id
                WHERE commands.command_id = ?
                """,
                (admission.command_id,),
            ).fetchone()
            if row is None or row[0] != admission.client_order_id or row[2] != admission.reconciliation_job_id:
                raise LedgerStorageError("submission admission does not match durable ledger identities")
            previous_state = OrderState(row[1])
            if previous_state is OrderState.SUBMISSION_UNKNOWN:
                return
            next_state = assert_transition(previous_state, LifecycleEvent.LOCAL_TIMEOUT)
            now = _timestamp_text(self.utc_now())
            self._append_event(
                command_id=admission.command_id,
                previous_state=previous_state,
                new_state=next_state,
                event=LifecycleEvent.LOCAL_TIMEOUT,
                occurred_at=now,
                detail={"source": "local", "reason": "submission_ambiguous"},
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
                ("submission_ambiguous", "queued", now, admission.reconciliation_job_id),
            )

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
                SELECT quantity, price, fee, fee_asset, observed_at_utc
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
            if tuple(existing) == values:
                return True
            connection.execute(
                """
                INSERT INTO reconciliation_incidents(
                    incident_id, command_id, kind, detail_json, observed_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _new_id("incident"),
                    fill.command_id,
                    "contradictory_fill_evidence",
                    _canonical_json({"fill_id": fill.fill_id, "observed": canonicalize(fill)}),
                    _timestamp_text(self.utc_now()),
                ),
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
        if state not in {OrderState.SUBMITTING, OrderState.SUBMISSION_UNKNOWN}:
            raise LedgerStorageError("stored command is not unresolved and cannot receive admission")
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
    ) -> None:
        """Append one sequence-checked lifecycle event inside the active transaction."""
        expected = assert_transition(previous_state, event)
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

    def _inject_failure(self, stage: str) -> None:
        """Invoke deterministic integration fault injection inside the active transaction."""
        if self._failure_injector is not None:
            self._failure_injector(stage)

    def _require_connection(self) -> sqlite3.Connection:
        """Return the open connection or reject post-close ledger use."""
        if self._connection is None:
            raise LedgerStorageError("execution ledger is closed")
        return self._connection


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
