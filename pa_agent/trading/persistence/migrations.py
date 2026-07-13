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


def _create_kill_switch_schema(connection: sqlite3.Connection) -> None:
    """Create singleton safety state plus append-only cancellation request work."""
    for statement in _KILL_SWITCH_SCHEMA_STATEMENTS:
        connection.execute(statement)


_KILL_SWITCH_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE kill_switch_state (
        singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
        status TEXT NOT NULL,
        reason TEXT,
        actor_label TEXT,
        policy_summary TEXT,
        evidence_summary TEXT,
        changed_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE kill_switch_events (
        event_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        reason TEXT,
        actor_label TEXT NOT NULL,
        occurred_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE cancellation_work (
        work_id TEXT PRIMARY KEY,
        command_id TEXT NOT NULL UNIQUE REFERENCES order_commands(command_id),
        client_order_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        request_outcome TEXT,
        remote_resolution TEXT,
        created_at_utc TEXT NOT NULL,
        processed_at_utc TEXT
    )
    """,
    "CREATE INDEX cancellation_work_status_idx ON cancellation_work(status, created_at_utc)",
)


def _create_outbound_dispatch_schema(connection: sqlite3.Connection) -> None:
    """Create the one-way proof state consumed before the sole gateway call."""
    for statement in _OUTBOUND_DISPATCH_SCHEMA_STATEMENTS:
        connection.execute(statement)


_OUTBOUND_DISPATCH_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE outbound_dispatch_attempts (
        command_id TEXT PRIMARY KEY REFERENCES order_commands(command_id),
        client_order_id TEXT NOT NULL UNIQUE,
        reconciliation_job_id TEXT NOT NULL UNIQUE REFERENCES reconciliation_jobs(job_id),
        outbound_attempt_proof TEXT NOT NULL UNIQUE,
        created_at_utc TEXT NOT NULL,
        expires_at_utc TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending', 'leased', 'expired')),
        leased_at_utc TEXT
    )
    """,
    "CREATE INDEX outbound_dispatch_attempts_lease_idx "
    "ON outbound_dispatch_attempts(command_id, client_order_id, reconciliation_job_id, status)",
    "CREATE INDEX outbound_dispatch_attempts_expiry_idx "
    "ON outbound_dispatch_attempts(status, expires_at_utc)",
)


def _create_recovery_assessment_schema(connection: sqlite3.Connection) -> None:
    """Persist immutable recovery scopes and their restricted clearance facts."""
    for statement in _RECOVERY_ASSESSMENT_SCHEMA_STATEMENTS:
        connection.execute(statement)


_RECOVERY_ASSESSMENT_SCHEMA_STATEMENTS = (
    "ALTER TABLE kill_switch_events ADD COLUMN recovery_assessment_ids_json TEXT",
    """
    CREATE TABLE recovery_scopes (
        persistent_scope_id TEXT PRIMARY KEY,
        target_json TEXT NOT NULL,
        target_digest TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        scope_digest TEXT NOT NULL,
        active INTEGER NOT NULL CHECK(active IN (0, 1)),
        created_at_utc TEXT NOT NULL
    )
    """,
    "CREATE INDEX recovery_scopes_current_idx ON recovery_scopes(active, persistent_scope_id)",
    """
    CREATE TABLE recovery_assessments (
        recovery_assessment_id TEXT PRIMARY KEY,
        persistent_scope_id TEXT NOT NULL REFERENCES recovery_scopes(persistent_scope_id),
        scope_digest TEXT NOT NULL,
        target_digest TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        evidence_digest TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        accepted INTEGER NOT NULL CHECK(accepted IN (0, 1)),
        reason_codes_json TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL,
        recorded_at_utc TEXT NOT NULL
    )
    """,
    "CREATE INDEX recovery_assessments_scope_idx "
    "ON recovery_assessments(persistent_scope_id, recovery_assessment_id)",
)


def _add_zero_scope_clearance_audit_columns(connection: sqlite3.Connection) -> None:
    """Add nullable ID-free proof facts without rewriting prior safety events."""
    connection.execute("ALTER TABLE kill_switch_events ADD COLUMN zero_scope_clearance_proof_json TEXT")
    connection.execute("ALTER TABLE kill_switch_events ADD COLUMN zero_scope_clearance_summary TEXT")


def _create_zero_scope_recovery_transition_schema(connection: sqlite3.Connection) -> None:
    """Persist one expiring, one-time binding between zero-scope recovery actions."""
    for statement in _ZERO_SCOPE_RECOVERY_TRANSITION_SCHEMA_STATEMENTS:
        connection.execute(statement)


_ZERO_SCOPE_RECOVERY_TRANSITION_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE zero_scope_recovery_transitions (
        transition_id TEXT PRIMARY KEY,
        begin_event_id TEXT NOT NULL UNIQUE REFERENCES kill_switch_events(event_id),
        begin_proof_digest TEXT NOT NULL,
        transition_challenge TEXT NOT NULL UNIQUE,
        began_at_utc TEXT NOT NULL,
        challenge_expires_at_utc TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending', 'consumed')),
        consumed_at_utc TEXT,
        CHECK(
            (status = 'pending' AND consumed_at_utc IS NULL)
            OR (status = 'consumed' AND consumed_at_utc IS NOT NULL)
        )
    )
    """,
    "CREATE UNIQUE INDEX zero_scope_recovery_transitions_one_pending_idx "
    "ON zero_scope_recovery_transitions(status) WHERE status = 'pending'",
    "CREATE INDEX zero_scope_recovery_transitions_pending_expiry_idx "
    "ON zero_scope_recovery_transitions(status, challenge_expires_at_utc)",
)


def _add_product_context_contract_columns(connection: sqlite3.Connection) -> None:
    """Append nullable context material without rewriting Phase 2 Spot history."""
    for table in ("proposal_candidates", "approval_tickets", "order_commands"):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN product_context_json TEXT")
        connection.execute(f"ALTER TABLE {table} ADD COLUMN product_context_digest TEXT")


def _add_product_policy_binding_columns(connection: sqlite3.Connection) -> None:
    """Append durable policy identities without changing historical Phase 2 rows."""
    for table in (
        "proposal_candidates",
        "proposal_risk_assessments",
        "approval_tickets",
        "approval_ticket_events",
        "order_commands",
        "outbound_dispatch_attempts",
    ):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN policy_id TEXT")
        connection.execute(f"ALTER TABLE {table} ADD COLUMN policy_version_bound TEXT")
        connection.execute(f"ALTER TABLE {table} ADD COLUMN policy_digest_bound TEXT")


MIGRATIONS = (
    Migration(1, _create_initial_schema),
    Migration(2, _create_proposal_audit_schema),
    Migration(3, _create_approval_ticket_schema),
    Migration(4, _create_kill_switch_schema),
    Migration(5, _create_outbound_dispatch_schema),
    Migration(6, _create_recovery_assessment_schema),
    Migration(7, _add_zero_scope_clearance_audit_columns),
    Migration(8, _create_zero_scope_recovery_transition_schema),
    Migration(9, _add_product_context_contract_columns),
    Migration(10, _add_product_policy_binding_columns),
)
