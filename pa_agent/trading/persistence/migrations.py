"""Versioned schema migrations for the local execution ledger."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

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

    for migration in selected_migrations:
        with transaction(connection):
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (migration.version,)
            ).fetchone()
            if applied is not None:
                continue
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
    for statement in _INITIAL_SCHEMA_STATEMENTS:
        connection.execute(statement)


_INITIAL_SCHEMA_STATEMENTS = (
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
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE orders (
        command_id TEXT PRIMARY KEY REFERENCES order_commands(command_id),
        exchange_order_id TEXT UNIQUE,
        lifecycle_state TEXT NOT NULL,
        filled_quantity TEXT NOT NULL,
        filled_notional TEXT NOT NULL,
        evidence_cursor TEXT
    )
    """,
    """
    CREATE TABLE fills (
        fill_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL REFERENCES order_commands(command_id),
        venue_fill_id TEXT UNIQUE,
        quantity TEXT NOT NULL,
        price TEXT NOT NULL,
        fee TEXT NOT NULL,
        fee_asset TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE reconciliation_jobs (
        job_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL UNIQUE REFERENCES order_commands(command_id),
        reason TEXT NOT NULL,
        status TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        next_action_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE submission_claims (
        claim_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL UNIQUE REFERENCES order_commands(command_id),
        claim_token TEXT NOT NULL UNIQUE,
        admitted_at_utc TEXT NOT NULL,
        status TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE account_observations (
        observation_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        product TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL,
        source TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        payload_digest TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE reconciliation_incidents (
        incident_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL REFERENCES order_commands(command_id),
        kind TEXT NOT NULL,
        detail_json TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL
    )
    """,
)


def _utc_now_text() -> str:
    """Return one explicit UTC timestamp representation for schema metadata."""
    return datetime.now(UTC).isoformat()


def _create_proposal_audit_schema(connection: sqlite3.Connection) -> None:
    """Create append-only pre-ticket proposal, evidence, and assessment storage."""
    for statement in _PROPOSAL_AUDIT_SCHEMA_STATEMENTS:
        connection.execute(statement)


_PROPOSAL_AUDIT_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE proposal_sources (
        snapshot_digest TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        completed_at_utc TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        decision_digest TEXT NOT NULL,
        target_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE proposal_candidates (
        intent_digest TEXT PRIMARY KEY,
        snapshot_digest TEXT NOT NULL REFERENCES proposal_sources(snapshot_digest),
        candidate_json TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE proposal_evidence (
        evidence_digest TEXT PRIMARY KEY,
        intent_digest TEXT NOT NULL REFERENCES proposal_candidates(intent_digest),
        evidence_json TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE proposal_risk_assessments (
        assessment_id TEXT PRIMARY KEY,
        intent_digest TEXT NOT NULL REFERENCES proposal_candidates(intent_digest),
        accepted INTEGER NOT NULL,
        policy_version TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        evidence_digest TEXT NOT NULL,
        reason_codes_json TEXT NOT NULL,
        fee_amount TEXT,
        assessment_json TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE proposal_audit_facts (
        fact_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_digest TEXT NOT NULL,
        source_snapshot_digest TEXT NOT NULL REFERENCES proposal_sources(snapshot_digest),
        intent_digest TEXT REFERENCES proposal_candidates(intent_digest),
        policy_digest TEXT,
        evidence_digest TEXT,
        reason_code TEXT,
        fee_amount TEXT,
        observed_at_utc TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL,
        summary_json TEXT NOT NULL
    )
    """,
    "CREATE INDEX proposal_candidates_snapshot_idx ON proposal_candidates(snapshot_digest)",
    "CREATE INDEX proposal_evidence_intent_idx ON proposal_evidence(intent_digest)",
    "CREATE INDEX proposal_risk_assessments_intent_idx ON proposal_risk_assessments(intent_digest)",
    "CREATE INDEX proposal_audit_facts_source_idx ON proposal_audit_facts(source_id, recorded_at_utc)",
    "CREATE INDEX proposal_audit_facts_intent_idx ON proposal_audit_facts(intent_digest, recorded_at_utc)",
)


def _create_approval_ticket_schema(connection: sqlite3.Connection) -> None:
    """Create durable review tickets and their append-only terminal event history."""
    for statement in _APPROVAL_TICKET_SCHEMA_STATEMENTS:
        connection.execute(statement)


_APPROVAL_TICKET_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE approval_tickets (
        ticket_id TEXT PRIMARY KEY,
        intent_digest TEXT NOT NULL REFERENCES proposal_candidates(intent_digest),
        policy_digest TEXT NOT NULL,
        evidence_digest TEXT NOT NULL REFERENCES proposal_evidence(evidence_digest),
        policy_version TEXT NOT NULL,
        binding_json TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,
        expires_at_utc TEXT NOT NULL,
        terminal_event TEXT,
        terminal_reason TEXT,
        terminal_at_utc TEXT,
        UNIQUE(intent_digest, policy_digest, evidence_digest)
    )
    """,
    """
    CREATE TABLE approval_ticket_events (
        event_id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL REFERENCES approval_tickets(ticket_id),
        event_type TEXT NOT NULL,
        reason TEXT NOT NULL,
        actor_label TEXT NOT NULL,
        binding_json TEXT NOT NULL,
        occurred_at_utc TEXT NOT NULL
    )
    """,
    "CREATE INDEX approval_ticket_events_ticket_idx ON approval_ticket_events(ticket_id, occurred_at_utc)",
)


MIGRATIONS = (
    Migration(1, _create_initial_schema),
    Migration(2, _create_proposal_audit_schema),
    Migration(3, _create_approval_ticket_schema),
)
