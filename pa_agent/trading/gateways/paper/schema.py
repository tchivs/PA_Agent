"""Private versioned SQLite schema for durable paper-trading truth."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from pa_agent.trading.persistence.sqlite_connection import transaction


@dataclass(frozen=True)
class PaperMigration:
    """One ordered, transactional migration owned solely by the paper store."""

    version: int
    apply: Callable[[sqlite3.Connection], None]


def run_paper_migrations(
    connection: sqlite3.Connection, *, migrations: Iterable[PaperMigration] | None = None
) -> None:
    """Apply the paper store's own migration registry without touching ledger schema."""
    selected = tuple(PAPER_MIGRATIONS if migrations is None else migrations)
    versions = tuple(migration.version for migration in selected)
    if any(version < 1 for version in versions) or versions != tuple(sorted(set(versions))):
        raise ValueError("paper migrations must have unique, ascending positive versions")

    with transaction(connection):
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at_utc TEXT NOT NULL
            )
            """
        )

    for migration in selected:
        with transaction(connection):
            applied = connection.execute(
                "SELECT 1 FROM paper_schema_migrations WHERE version = ?", (migration.version,)
            ).fetchone()
            if applied is not None:
                continue
            migration.apply(connection)
            connection.execute(
                "INSERT INTO paper_schema_migrations(version, applied_at_utc) VALUES (?, ?)",
                (migration.version, _utc_now_text()),
            )


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


def _create_initial_paper_schema(connection: sqlite3.Connection) -> None:
    for statement in _INITIAL_SCHEMA_STATEMENTS:
        connection.execute(statement)


_INITIAL_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE paper_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    INSERT OR IGNORE INTO paper_metadata(key, value) VALUES ('next_event_sequence', '0')
    """,
    """
    CREATE TABLE paper_orders (
        client_order_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL UNIQUE,
        account_id TEXT NOT NULL,
        product TEXT NOT NULL,
        symbol TEXT NOT NULL,
        command_json TEXT NOT NULL,
        quantity TEXT NOT NULL,
        lifecycle_state TEXT NOT NULL,
        filled_quantity TEXT NOT NULL,
        paper_event_sequence INTEGER,
        created_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE paper_events (
        sequence INTEGER PRIMARY KEY,
        event_type TEXT NOT NULL,
        client_order_id TEXT REFERENCES paper_orders(client_order_id),
        command_id TEXT REFERENCES paper_orders(command_id),
        payload_json TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE paper_observation_cursors (
        account_id TEXT NOT NULL,
        product TEXT NOT NULL,
        symbol TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        observation_version INTEGER NOT NULL,
        observation_digest TEXT NOT NULL,
        paper_event_sequence INTEGER NOT NULL REFERENCES paper_events(sequence),
        PRIMARY KEY(account_id, product, symbol)
    )
    """,
    """
    CREATE TABLE paper_market_books (
        account_id TEXT NOT NULL,
        product TEXT NOT NULL,
        symbol TEXT NOT NULL,
        observation_version INTEGER NOT NULL,
        observation_id TEXT NOT NULL,
        observation_digest TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        paper_event_sequence INTEGER NOT NULL REFERENCES paper_events(sequence),
        PRIMARY KEY(account_id, product, symbol, observation_version)
    )
    """,
    """
    CREATE TABLE paper_fills (
        paper_fill_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL REFERENCES paper_orders(command_id),
        quantity TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        paper_event_sequence INTEGER NOT NULL REFERENCES paper_events(sequence)
    )
    """,
    """
    CREATE TABLE paper_product_snapshots (
        account_id TEXT NOT NULL,
        product TEXT NOT NULL,
        scope TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        paper_event_sequence INTEGER NOT NULL REFERENCES paper_events(sequence),
        PRIMARY KEY(account_id, product, scope)
    )
    """,
    """
    CREATE TABLE paper_cancellation_requests (
        cancellation_id TEXT PRIMARY KEY,
        client_order_id TEXT NOT NULL REFERENCES paper_orders(client_order_id),
        requested_sequence INTEGER NOT NULL REFERENCES paper_events(sequence),
        evidence_sequence INTEGER REFERENCES paper_events(sequence),
        status TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE paper_incidents (
        incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        account_id TEXT NOT NULL,
        product TEXT NOT NULL,
        symbol TEXT NOT NULL,
        detail_json TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL
    )
    """,
    "CREATE INDEX paper_orders_scope_open_idx ON paper_orders(account_id, product, symbol, lifecycle_state)",
    "CREATE INDEX paper_fills_command_idx ON paper_fills(command_id, paper_event_sequence)",
    "CREATE INDEX paper_events_command_idx ON paper_events(command_id, sequence)",
)


def _create_product_evidence_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE paper_product_evidence (
            target_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            product TEXT NOT NULL,
            scope TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            observation_version INTEGER NOT NULL,
            observed_at_utc TEXT NOT NULL,
            evidence_digest TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            paper_event_sequence INTEGER NOT NULL REFERENCES paper_events(sequence),
            PRIMARY KEY(target_id, account_id, product, scope, evidence_type, observation_version)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX paper_product_evidence_latest_idx
        ON paper_product_evidence(target_id, account_id, product, scope, evidence_type, observation_version DESC)
        """
    )


PAPER_MIGRATIONS = (
    PaperMigration(version=1, apply=_create_initial_paper_schema),
    PaperMigration(version=2, apply=_create_product_evidence_schema),
)
