"""Versioned schema migrations for the local execution ledger."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3

from pa_agent.trading.persistence.sqlite_connection import transaction


@dataclass(frozen=True)
class Migration:
    """One ordered, transactional execution-ledger schema migration."""

    version: int
    apply: Callable[[sqlite3.Connection], None]


def run_migrations(
    connection: sqlite3.Connection, *, migrations: Iterable[Migration] | None = None
) -> None:
    """Apply every pending migration, recording each version only after its DDL commits."""
    selected_migrations = tuple(MIGRATIONS if migrations is None else migrations)
    _validate_migration_order(selected_migrations)
    with transaction(connection):
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at_utc TEXT NOT NULL
            )
            """
        )

    applied = {
        row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
    }
    for migration in selected_migrations:
        if migration.version in applied:
            continue
        with transaction(connection):
            migration.apply(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at_utc) VALUES (?, ?)",
                (migration.version, _utc_now_text()),
            )


def _validate_migration_order(migrations: tuple[Migration, ...]) -> None:
    """Reject duplicate or unordered migration sets before changing the database."""
    versions = tuple(migration.version for migration in migrations)
    if any(version < 1 for version in versions) or versions != tuple(sorted(set(versions))):
        raise ValueError("ledger migrations must have unique, ascending positive versions")


def _create_initial_schema(connection: sqlite3.Connection) -> None:
    """Create the transactional command, evidence, projection, and recovery tables."""
    connection.executescript(
        """
        CREATE TABLE order_commands (
            command_id TEXT PRIMARY KEY,
            logical_command_key TEXT NOT NULL UNIQUE,
            client_order_id TEXT NOT NULL UNIQUE,
            command_json TEXT NOT NULL,
            mode TEXT NOT NULL,
            product TEXT NOT NULL,
            account_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE order_events (
            event_id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL REFERENCES order_commands(command_id),
            sequence INTEGER NOT NULL,
            previous_state TEXT NOT NULL,
            new_state TEXT NOT NULL,
            event_type TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            UNIQUE(command_id, sequence)
        );

        CREATE TABLE orders (
            command_id TEXT PRIMARY KEY REFERENCES order_commands(command_id),
            exchange_order_id TEXT UNIQUE,
            lifecycle_state TEXT NOT NULL,
            filled_quantity TEXT NOT NULL,
            filled_notional TEXT NOT NULL,
            evidence_cursor TEXT
        );

        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL REFERENCES order_commands(command_id),
            venue_fill_id TEXT UNIQUE,
            quantity TEXT NOT NULL,
            price TEXT NOT NULL,
            fee TEXT NOT NULL,
            fee_asset TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL
        );

        CREATE TABLE reconciliation_jobs (
            job_id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL UNIQUE REFERENCES order_commands(command_id),
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_action_at_utc TEXT NOT NULL
        );

        CREATE TABLE submission_claims (
            claim_id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL UNIQUE REFERENCES order_commands(command_id),
            claim_token TEXT NOT NULL UNIQUE,
            admitted_at_utc TEXT NOT NULL,
            status TEXT NOT NULL
        );

        CREATE TABLE account_observations (
            observation_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            product TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            source TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_digest TEXT NOT NULL
        );

        CREATE TABLE reconciliation_incidents (
            incident_id TEXT PRIMARY KEY,
            command_id TEXT NOT NULL REFERENCES order_commands(command_id),
            kind TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL
        );
        """
    )


def _utc_now_text() -> str:
    """Return one explicit UTC timestamp representation for schema metadata."""
    return datetime.now(timezone.utc).isoformat()


MIGRATIONS = (Migration(1, _create_initial_schema),)
